"""隐写格式测试，不启动 AstrBot，也不进行网络请求。"""

import sys
import tempfile
from pathlib import Path

from PIL import Image

from vangonography_api import (
    DATA_DELIMITER,
    FILENAME_DELIMITER,
    FORMAT_HEADER,
    StegoError,
    StegoIntegrityError,
    StegoPasswordError,
    _embed_data,
    cli_main,
    encrypt_data,
    extract_file_from_image,
    hide_file_into_image,
)


_failures = []


def check(condition, label):
    if condition:
        print(f"  通过  {label}")
    else:
        print(f"  失败  {label}")
        _failures.append(label)


def capture_error(expected_type, callback, label):
    try:
        callback()
    except expected_type as exc:
        print(f"  通过  {label}")
        return exc
    except Exception as exc:
        print(f"  失败  {label}（异常类型为 {type(exc).__name__}）")
        _failures.append(label)
        return exc
    print(f"  失败  {label}（没有抛出异常）")
    _failures.append(label)
    return None


def make_cover(path, size=(24, 24)):
    Image.new("RGB", size, (72, 128, 186)).save(path, "PNG")


def test_v2_roundtrip():
    print("v2 无加密往返：")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cover = root / "cover.png"
        source = root / "source.bin"
        stego = root / "stego.png"
        output_dir = root / "output"
        make_cover(cover)
        content = bytes(range(256)) * 5
        source.write_bytes(content)

        hide_file_into_image(
            cover,
            source,
            "../../原始图片.png",
            stego,
        )
        extracted = extract_file_from_image(stego, output_dir)

        check(stego.is_file(), "生成 PNG 隐写文件")
        check(extracted.name == "原始图片.png", "提取文件名去除目录部分")
        check(extracted.read_bytes() == content, "提取内容逐字节一致")
        with Image.open(cover) as original, Image.open(stego) as encoded:
            check(
                encoded.width * encoded.height > original.width * original.height,
                "载体容量不足时自动扩容",
            )


def test_encrypted_roundtrip():
    print("v2 加密与密码错误：")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cover = root / "cover.png"
        source = root / "source.png"
        stego = root / "encrypted.png"
        make_cover(cover, (64, 64))
        source.write_bytes(b"encrypted-image-content")
        hide_file_into_image(
            cover,
            source,
            source.name,
            stego,
            encrypt=True,
            password="Correct-Password",
        )

        missing = capture_error(
            StegoPasswordError,
            lambda: extract_file_from_image(stego, root / "missing"),
            "加密图未提供密码时明确拒绝",
        )
        wrong = capture_error(
            StegoPasswordError,
            lambda: extract_file_from_image(
                stego,
                root / "wrong",
                password="Wrong-Password",
            ),
            "错误密码与载体损坏分开报告",
        )
        extracted = extract_file_from_image(
            stego,
            root / "correct",
            password="Correct-Password",
        )

        check("请提供密码" in str(missing), "缺少密码提示可读")
        check("密码错误" in str(wrong), "错误密码提示可读")
        check(
            extracted.read_bytes() == source.read_bytes(),
            "正确密码完整恢复内容",
        )


def test_integrity_and_compression():
    print("完整性校验与平台压缩：")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cover = root / "cover.png"
        source = root / "source.bin"
        stego = root / "stego.png"
        damaged = root / "damaged.png"
        jpeg = root / "compressed.jpg"
        recompressed = root / "recompressed.png"
        make_cover(cover, (96, 96))
        source.write_bytes(b"integrity-check" * 40)
        hide_file_into_image(cover, source, source.name, stego)

        with Image.open(stego) as opened:
            image = opened.convert("RGB")
        bit_index = FORMAT_HEADER.size * 8 + 7
        pixel_index, channel_index = divmod(bit_index, 3)
        x = pixel_index % image.width
        y = pixel_index // image.width
        channels = list(image.getpixel((x, y)))
        channels[channel_index] ^= 1
        image.putpixel((x, y), tuple(channels))
        image.save(damaged, "PNG")

        integrity_error = capture_error(
            StegoIntegrityError,
            lambda: extract_file_from_image(damaged, root / "damaged-output"),
            "单个位变化触发 SHA-256 校验失败",
        )
        check("校验失败" in str(integrity_error), "损坏原因明确指向完整性")

        with Image.open(stego) as opened:
            opened.convert("RGB").save(jpeg, "JPEG", quality=88)
        with Image.open(jpeg) as opened:
            opened.convert("RGB").save(recompressed, "PNG")
        compression_error = capture_error(
            StegoError,
            lambda: extract_file_from_image(
                recompressed,
                root / "compressed-output",
            ),
            "有损重编码后的图片不可误判为有效数据",
        )
        check(
            "压缩" in str(compression_error) or "隐写" in str(compression_error),
            "有损重编码返回可诊断提示",
        )


def test_legacy_compatibility():
    print("v1 旧格式兼容：")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cover = root / "cover.png"
        tiny_cover = root / "tiny-cover.png"
        tiny_legacy = root / "tiny-legacy.png"
        legacy = root / "legacy.png"
        legacy_encrypted = root / "legacy-encrypted.png"
        make_cover(cover, (80, 80))
        make_cover(tiny_cover, (1, 1))
        content = b"legacy-content" * 12
        inner = "旧版图片.png".encode("utf-8") + FILENAME_DELIMITER + content

        _embed_data(cover, inner + DATA_DELIMITER, legacy)
        extracted = extract_file_from_image(legacy, root / "plain-output")
        check(extracted.read_bytes() == content, "未加密旧格式可继续提取")

        encrypted = encrypt_data(inner, "Legacy-Password")
        _embed_data(cover, encrypted + DATA_DELIMITER, legacy_encrypted)
        extracted_encrypted = extract_file_from_image(
            legacy_encrypted,
            root / "encrypted-output",
            password="Legacy-Password",
        )
        check(extracted_encrypted.read_bytes() == content, "加密旧格式可继续提取")

        tiny_inner = b"a" + FILENAME_DELIMITER + b"x"
        _embed_data(tiny_cover, tiny_inner + DATA_DELIMITER, tiny_legacy)
        tiny_extracted = extract_file_from_image(tiny_legacy, root / "tiny-output")
        check(tiny_extracted.read_bytes() == b"x", "不足 v2 包头长度的旧格式仍可提取")


def test_cli_extract():
    print("离线命令行：")
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        cover = root / "cover.png"
        source = root / "source.dat"
        stego = root / "stego.png"
        output_dir = root / "cli-output"
        make_cover(cover, (48, 48))
        source.write_bytes(b"offline-extract")
        hide_file_into_image(cover, source, source.name, stego)

        code = cli_main(
            [
                "extract",
                str(stego),
                "--output-dir",
                str(output_dir),
            ]
        )
        check(code == 0, "命令行提取返回成功状态")
        check(
            (output_dir / source.name).read_bytes() == source.read_bytes(),
            "命令行在指定目录恢复文件",
        )


def main():
    print("=" * 56)
    print("NAI 隐写格式测试")
    print("=" * 56)
    for function in (
        test_v2_roundtrip,
        test_encrypted_roundtrip,
        test_integrity_and_compression,
        test_legacy_compatibility,
        test_cli_extract,
    ):
        function()
        print()
    print("=" * 56)
    if _failures:
        print(f"失败 {len(_failures)} 项：")
        for item in _failures:
            print(f"  - {item}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
