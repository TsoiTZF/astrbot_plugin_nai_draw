import base64
from typing import Optional
from pathlib import Path

from PIL import Image
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from astrbot.api import logger

FILENAME_DELIMITER = b"<-F-N->"
DATA_DELIMITER = b"<-V-G->"


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return base64.urlsafe_b64encode(kdf.derive(password.encode()))


def encrypt_data(data: bytes, password: str) -> bytes:
    import os
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    return salt + fernet.encrypt(data)


def decrypt_data(data: bytes, password: str) -> bytes:
    salt, ciphertext = data[:16], data[16:]
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    return fernet.decrypt(ciphertext)


# 优化: 统一使用 pathlib 进行路径操作
def _embed_data(image_path: Path, data: bytes, output_path: Path):
    image = Image.open(image_path).convert('RGB')
    width, height = image.size
    
    data_with_delimiter = data + DATA_DELIMITER
    bits_to_embed = ''.join(f'{byte:08b}' for byte in data_with_delimiter)
    
    required_pixels = -(-len(bits_to_embed) // 3)
    current_pixels = width * height

    if required_pixels > current_pixels:
        scale_factor = (required_pixels / current_pixels) ** 0.5
        new_width = int(width * scale_factor) + 1
        new_height = int(height * scale_factor) + 1
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        width, height = new_width, new_height

    bit_index = 0
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            
            if bit_index < len(bits_to_embed):
                r = (r & ~1) | int(bits_to_embed[bit_index])
                bit_index += 1
            if bit_index < len(bits_to_embed):
                g = (g & ~1) | int(bits_to_embed[bit_index])
                bit_index += 1
            if bit_index < len(bits_to_embed):
                b = (b & ~1) | int(bits_to_embed[bit_index])
                bit_index += 1
            
            pixels[x, y] = (r, g, b)
            if bit_index >= len(bits_to_embed):
                break
        if bit_index >= len(bits_to_embed):
            break
            
    image.save(output_path, 'PNG')


def _extract_data(image_path: Path) -> bytes:
    """从图片中提取隐藏数据，设有数据量上限防止恶意大图耗尽内存。"""
    image = Image.open(image_path).convert('RGB')
    width, height = image.size
    pixels = image.load()

    extracted_bytes = bytearray()
    bit_buffer = []
    delimiter_len = len(DATA_DELIMITER)
    # 安全上限：最多提取 200MB，防止无分隔符时遍历整张大图耗尽内存
    max_bytes = 200 * 1024 * 1024

    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            bit_buffer.extend([str(r & 1), str(g & 1), str(b & 1)])

            while len(bit_buffer) >= 8:
                byte_str = "".join(bit_buffer[:8])
                del bit_buffer[:8]
                extracted_bytes.append(int(byte_str, 2))

                if len(extracted_bytes) >= max_bytes:
                    raise ValueError("提取数据超过安全上限（200MB），图片可能已损坏或未包含有效分隔符。")

                if len(extracted_bytes) >= delimiter_len:
                    if extracted_bytes[-delimiter_len:] == DATA_DELIMITER:
                        return bytes(extracted_bytes[:-delimiter_len])

    raise ValueError("数据分隔符未找到，文件可能已损坏或格式不正确。")


# 优化: 统一使用 pathlib 进行路径操作
def hide_file_into_image(cover_path: Path, file_path: Path, file_name: str, output_path: Path,
                         encrypt: bool = False, password: Optional[str] = None):
    try:
        file_content = file_path.read_bytes()
        
        payload = file_name.encode('utf-8') + FILENAME_DELIMITER + file_content
        
        if encrypt:
            if not password:
                raise ValueError('加密需要提供密码')
            payload = encrypt_data(payload, password)
            
        _embed_data(cover_path, payload, output_path)
    except Exception as e:
        logger.error(f"隐藏文件时出错: {e}", exc_info=True)
        raise


# 优化: 统一使用 pathlib 进行路径操作
def extract_file_from_image(image_path: Path, output_dir: Path, password: Optional[str] = None) -> Path:
    extracted_data = _extract_data(image_path)
    
    if password:
        try:
            extracted_data = decrypt_data(extracted_data, password)
        except InvalidToken:
            raise ValueError("解密失败，密码错误或文件已损坏。")

    try:
        filename_bytes, file_content = extracted_data.split(FILENAME_DELIMITER, 1)

        unsafe_filename = filename_bytes.decode('utf-8')
        # 提取纯文件名，防止路径遍历攻击
        filename = Path(unsafe_filename).name

        if not filename or filename in ('.', '..'):
            raise ValueError("提取出的文件名无效或具有安全风险。")

    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError("无法解析文件名或内容，文件可能已损坏。") from e

    output_file_path = (output_dir / filename).resolve()
    # 二次校验：确保最终路径仍在 output_dir 内，防止路径遍历绕过
    if not str(output_file_path).startswith(str(output_dir.resolve())):
        raise ValueError("提取出的文件路径异常，已阻止写入。")
    output_file_path.write_bytes(file_content)
        
    return output_file_path
