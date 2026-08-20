"""NAI 隐写文件格式、加解密与离线命令行工具。"""

import argparse
import base64
import getpass
import hashlib
import hmac
import logging
import math
import os
import struct
import sys
from pathlib import Path
from typing import Iterator, Optional

from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

try:
    from astrbot.api import logger
except ImportError:
    logger = logging.getLogger(__name__)


FILENAME_DELIMITER = b"<-F-N->"
DATA_DELIMITER = b"<-V-G->"
FORMAT_MAGIC = b"NAISTEG2"
FORMAT_HEADER = struct.Struct(">8sBQ32s")
FILENAME_LENGTH = struct.Struct(">H")
FLAG_ENCRYPTED = 0x01
KNOWN_FLAGS = FLAG_ENCRYPTED
MAX_PAYLOAD_BYTES = 200 * 1024 * 1024


class StegoError(ValueError):
    """隐写处理的可预期错误。"""


class StegoFormatError(StegoError):
    """图片不含受支持的隐写格式。"""


class StegoIntegrityError(StegoError):
    """隐写数据长度或校验值不一致。"""


class StegoPasswordError(StegoError):
    """隐写密码缺失或不正确。"""


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_data(data: bytes, password: str) -> bytes:
    salt = os.urandom(16)
    return salt + Fernet(_derive_key(password, salt)).encrypt(data)


def decrypt_data(data: bytes, password: str) -> bytes:
    if len(data) <= 16:
        raise InvalidToken
    salt, ciphertext = data[:16], data[16:]
    return Fernet(_derive_key(password, salt)).decrypt(ciphertext)


def _embed_data(image_path: Path, data: bytes, output_path: Path) -> None:
    """按 RGB 通道最低位写入完整字节流，容量不足时等比放大载体。"""
    with Image.open(image_path) as source:
        image = source.convert("RGB")

    width, height = image.size
    required_pixels = math.ceil(len(data) * 8 / 3)
    current_pixels = width * height
    if required_pixels > current_pixels:
        scale = math.sqrt(required_pixels / current_pixels)
        width = max(width, math.ceil(width * scale))
        height = max(height, math.ceil(required_pixels / width))
        image = image.resize((width, height), Image.Resampling.LANCZOS)

    bit_index = 0
    total_bits = len(data) * 8
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            channels = list(pixels[x, y])
            for channel_index in range(3):
                if bit_index >= total_bits:
                    break
                source_byte = data[bit_index // 8]
                bit = (source_byte >> (7 - bit_index % 8)) & 1
                channels[channel_index] = (channels[channel_index] & ~1) | bit
                bit_index += 1
            pixels[x, y] = tuple(channels)
            if bit_index >= total_bits:
                break
        if bit_index >= total_bits:
            break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG")


def _iter_lsb_bytes(image_path: Path) -> Iterator[int]:
    """逐字节读取 RGB 最低位，避免为整张图构造庞大位字符串。"""
    with Image.open(image_path) as source:
        image = source.convert("RGB")

    current_byte = 0
    bit_count = 0
    for pixel in image.getdata():
        for channel in pixel:
            current_byte = (current_byte << 1) | (channel & 1)
            bit_count += 1
            if bit_count == 8:
                yield current_byte
                current_byte = 0
                bit_count = 0


def _take_bytes(iterator: Iterator[int], count: int, error_message: str) -> bytes:
    result = bytearray()
    try:
        for _ in range(count):
            result.append(next(iterator))
    except StopIteration as exc:
        raise StegoIntegrityError(error_message) from exc
    return bytes(result)


def _extract_legacy_data(initial: bytes, iterator: Iterator[int]) -> bytes:
    """读取 v1 分隔符格式，供升级前生成的隐写图继续使用。"""
    extracted = bytearray(initial)
    delimiter_index = extracted.find(DATA_DELIMITER)
    if delimiter_index >= 0:
        return bytes(extracted[:delimiter_index])

    for value in iterator:
        extracted.append(value)
        if len(extracted) > MAX_PAYLOAD_BYTES:
            raise StegoIntegrityError(
                "旧版隐写数据超过 200MB，图片可能已损坏或未包含有效结束标记。"
            )
        if extracted[-len(DATA_DELIMITER):] == DATA_DELIMITER:
            return bytes(extracted[:-len(DATA_DELIMITER)])

    raise StegoFormatError(
        "未找到隐写格式标识；图片可能未包含数据，或已被聊天平台压缩。"
    )


def _extract_payload(image_path: Path) -> tuple[bytes, bool, bool]:
    """返回隐藏载荷、是否加密、是否为旧版格式。"""
    iterator = _iter_lsb_bytes(image_path)
    try:
        initial_buffer = bytearray()
        for _ in range(FORMAT_HEADER.size):
            try:
                initial_buffer.append(next(iterator))
            except StopIteration:
                break
        initial = bytes(initial_buffer)
        if initial[: len(FORMAT_MAGIC)] != FORMAT_MAGIC:
            return _extract_legacy_data(initial, iterator), False, True
        if len(initial) < FORMAT_HEADER.size:
            raise StegoIntegrityError("图片容量不足，隐写头不完整。")

        magic, flags, payload_length, expected_digest = FORMAT_HEADER.unpack(initial)
        if magic != FORMAT_MAGIC or flags & ~KNOWN_FLAGS:
            raise StegoFormatError("隐写格式版本或标记不受支持。")
        if payload_length <= 0 or payload_length > MAX_PAYLOAD_BYTES:
            raise StegoIntegrityError(
                "隐写数据长度异常，图片可能已被压缩、裁剪或修改。"
            )

        payload = _take_bytes(
            iterator,
            payload_length,
            "隐写数据不完整，图片可能已被压缩、裁剪或修改。",
        )
        actual_digest = hashlib.sha256(payload).digest()
        if not hmac.compare_digest(actual_digest, expected_digest):
            raise StegoIntegrityError(
                "隐写数据校验失败，图片已被压缩、裁剪或修改。"
            )
        return payload, bool(flags & FLAG_ENCRYPTED), False
    finally:
        close = getattr(iterator, "close", None)
        if close:
            close()


def _build_inner_payload(file_name: str, file_content: bytes) -> bytes:
    filename = Path(str(file_name).replace("\\", "/")).name
    filename_bytes = filename.encode("utf-8")
    if not filename or filename in {".", ".."}:
        raise StegoFormatError("隐藏文件名无效。")
    if len(filename_bytes) > 65535:
        raise StegoFormatError("隐藏文件名过长。")
    return FILENAME_LENGTH.pack(len(filename_bytes)) + filename_bytes + file_content


def _parse_inner_payload(payload: bytes, legacy: bool) -> tuple[str, bytes]:
    try:
        if legacy:
            filename_bytes, file_content = payload.split(FILENAME_DELIMITER, 1)
        else:
            if len(payload) < FILENAME_LENGTH.size:
                raise StegoIntegrityError("隐写文件信息不完整。")
            filename_length = FILENAME_LENGTH.unpack(
                payload[: FILENAME_LENGTH.size]
            )[0]
            filename_end = FILENAME_LENGTH.size + filename_length
            if filename_length == 0 or filename_end > len(payload):
                raise StegoIntegrityError("隐写文件名长度异常。")
            filename_bytes = payload[FILENAME_LENGTH.size:filename_end]
            file_content = payload[filename_end:]
        unsafe_filename = filename_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StegoIntegrityError("隐写文件名编码已损坏。") from exc
    except ValueError as exc:
        if legacy:
            raise StegoFormatError(
                "无法解析旧版隐写内容；它可能需要密码，或图片已经损坏。"
            ) from exc
        raise

    filename = Path(unsafe_filename.replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise StegoIntegrityError("提取出的文件名无效。")
    return filename, file_content


def hide_file_into_image(
    cover_path: Path,
    file_path: Path,
    file_name: str,
    output_path: Path,
    encrypt: bool = False,
    password: Optional[str] = None,
) -> None:
    """将文件写入载体图，输出带完整性校验的 v2 PNG。"""
    try:
        source_path = Path(file_path)
        if source_path.stat().st_size > MAX_PAYLOAD_BYTES:
            raise StegoIntegrityError("待隐藏文件超过 200MB 上限。")
        inner_payload = _build_inner_payload(file_name, source_path.read_bytes())
        flags = 0
        payload = inner_payload
        if encrypt:
            if not password:
                raise StegoPasswordError("加密需要提供密码。")
            payload = encrypt_data(inner_payload, password)
            flags |= FLAG_ENCRYPTED
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise StegoIntegrityError("待隐藏文件超过 200MB 上限。")

        header = FORMAT_HEADER.pack(
            FORMAT_MAGIC,
            flags,
            len(payload),
            hashlib.sha256(payload).digest(),
        )
        _embed_data(Path(cover_path), header + payload, Path(output_path))
    except StegoError:
        raise
    except Exception as exc:
        logger.error(f"隐藏文件时出错：{exc}", exc_info=True)
        raise


def extract_file_from_image(
    image_path: Path,
    output_dir: Path,
    password: Optional[str] = None,
) -> Path:
    """从 v2 或旧版隐写图中提取文件。"""
    payload, encrypted, legacy = _extract_payload(Path(image_path))

    if legacy:
        if password:
            try:
                payload = decrypt_data(payload, password)
            except InvalidToken as exc:
                raise StegoPasswordError(
                    "旧版隐写图解密失败，密码错误或图片已损坏。"
                ) from exc
    elif encrypted:
        if not password:
            raise StegoPasswordError("该隐写图已加密，请提供密码。")
        try:
            payload = decrypt_data(payload, password)
        except InvalidToken as exc:
            raise StegoPasswordError("解密失败，密码错误。") from exc

    filename, file_content = _parse_inner_payload(payload, legacy)
    resolved_output_dir = Path(output_dir).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (resolved_output_dir / filename).resolve()
    if output_path.parent != resolved_output_dir:
        raise StegoIntegrityError("提取出的文件路径异常，已停止写入。")
    output_path.write_bytes(file_content)
    return output_path


def _cli_password(args: argparse.Namespace) -> Optional[str]:
    if getattr(args, "ask_password", False):
        return getpass.getpass("请输入隐写密码：")
    return getattr(args, "password", None)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="叶子的逼隐写图离线提取与生成工具"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="从原始隐写 PNG 提取文件")
    extract_parser.add_argument("image", type=Path, help="原始隐写 PNG 路径")
    extract_parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="输出目录，默认为当前目录",
    )
    extract_password = extract_parser.add_mutually_exclusive_group()
    extract_password.add_argument("-p", "--password", help="隐写密码")
    extract_password.add_argument(
        "--ask-password",
        action="store_true",
        help="在终端中隐藏输入密码",
    )

    hide_parser = subparsers.add_parser("hide", help="把文件隐藏进载体图")
    hide_parser.add_argument("cover", type=Path, help="载体图片路径")
    hide_parser.add_argument("file", type=Path, help="待隐藏文件路径")
    hide_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="输出 PNG 路径，默认写到载体图旁边",
    )
    hide_parser.add_argument("--name", help="提取时使用的文件名")
    hide_password = hide_parser.add_mutually_exclusive_group()
    hide_password.add_argument("-p", "--password", help="设置隐写密码")
    hide_password.add_argument(
        "--ask-password",
        action="store_true",
        help="在终端中隐藏输入密码",
    )
    return parser


def cli_main(argv: Optional[list[str]] = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    try:
        password = _cli_password(args)
        if args.command == "extract":
            result = extract_file_from_image(
                args.image,
                args.output_dir,
                password=password,
            )
            print(f"提取成功：{result}")
            return 0

        output_path = args.output or args.cover.with_name(
            f"{args.cover.stem}_stego.png"
        )
        hide_file_into_image(
            cover_path=args.cover,
            file_path=args.file,
            file_name=args.name or args.file.name,
            output_path=output_path,
            encrypt=bool(password),
            password=password,
        )
        print(f"隐写成功：{output_path}")
        return 0
    except (OSError, StegoError, InvalidToken) as exc:
        print(f"失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli_main())
