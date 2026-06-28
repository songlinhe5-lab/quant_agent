"""
敏感字段加密工具（AES-256-GCM）
提供透明的加密/解密功能，防止敏感数据明文落库
"""

import base64
import os
from typing import Union

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from backend.core.config import settings

# ==========================================
# AES-256-GCM 加密/解密工具函数
# ==========================================


def get_encryption_key() -> bytes:
    """
    从配置中获取加密主密钥（AES-256 需要 32 字节）

    ⚠️ 安全警告：
    1. ENCRYPTION_MASTER_KEY 必须配置在 .env 中，禁止硬编码
    2. 生产环境建议使用 KMS/Vault 管理主密钥，而非直接配置在 .env
    3. 密钥长度必须 >= 32 字节（AES-256 要求）
    """
    master_key = getattr(settings, "encryption_master_key", None)
    if not master_key:
        # 开发环境自动生成临时密钥（仅用于开发，生产必须配置）
        import warnings

        warnings.warn(
            "⚠️ ENCRYPTION_MASTER_KEY 未配置！使用临时密钥，重启后数据无法解密！",
            RuntimeWarning,
        )
        # 返回固定的开发密钥（仅用于开发环境）
        return b"\x00" * 32

    # 将十六进制或 Base64 编码的密钥解码为字节
    try:
        # 尝试十六进制解码
        if len(master_key) == 64:  # 32 字节的十六进制表示 = 64 字符
            return bytes.fromhex(master_key)
        # 尝试 Base64 解码
        return base64.b64decode(master_key)
    except Exception:
        # 如果是原始字符串，直接编码（不推荐，仅用于兼容）
        key_bytes = master_key.encode("utf-8")
        if len(key_bytes) < 32:
            raise ValueError("❌ ENCRYPTION_MASTER_KEY 长度必须 >= 32 字节（AES-256 要求）")  # noqa: E501
        return key_bytes[:32]


def encrypt_sensitive_data(plaintext: Union[str, bytes]) -> str:
    """
    使用 AES-256-GCM 加密敏感数据

    Args:
        plaintext: 明文数据（字符串或字节）

    Returns:
        加密后的密文（Base64 编码，格式：nonce:ciphertext:tag）
    """
    if plaintext is None:
        return None

    # 统一转换为字节
    if isinstance(plaintext, str):
        plaintext_bytes = plaintext.encode("utf-8")
    else:
        plaintext_bytes = plaintext

    # 生成随机 nonce（12 字节，GCM 推荐长度）
    nonce = os.urandom(12)

    # 创建 AES-GCM 加密器
    key = get_encryption_key()
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()

    # 执行加密
    ciphertext = encryptor.update(plaintext_bytes) + encryptor.finalize()

    # 获取认证标签（GCM 模式提供完整性校验）
    tag = encryptor.tag

    # 组合 nonce:ciphertext:tag 并 Base64 编码
    combined = nonce + ciphertext + tag
    return base64.b64encode(combined).decode("utf-8")


def decrypt_sensitive_data(ciphertext_b64: str) -> str:
    """
    使用 AES-256-GCM 解密敏感数据

    Args:
        ciphertext_b64: 加密后的密文（Base64 编码，格式：nonce:ciphertext:tag）

    Returns:
        解密后的明文（字符串）
    """
    if ciphertext_b64 is None:
        return None

    try:
        # Base64 解码
        combined = base64.b64decode(ciphertext_b64)

        # 拆分 nonce (12 bytes) + ciphertext + tag (16 bytes)
        nonce = combined[:12]
        tag = combined[-16:]
        ciphertext = combined[12:-16]

        # 创建 AES-GCM 解密器
        key = get_encryption_key()
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend())
        decryptor = cipher.decryptor()

        # 执行解密
        plaintext_bytes = decryptor.update(ciphertext) + decryptor.finalize()

        # 返回字符串
        return plaintext_bytes.decode("utf-8")

    except InvalidTag:
        raise ValueError("❌ 密文认证失败（可能密钥错误或数据被篡改）")
    except Exception as e:
        raise ValueError(f"❌ 解密失败：{str(e)}")


# ==========================================
# SQLAlchemy 透明加密 Mixin（可选，用于未来扩展）
# ==========================================


class EncryptedFieldMixin:
    """
    透明加密字段 Mixin（示例）

    使用方法：
    1. 在模型中定义字段时，使用 String 类型存储密文
    2. 提供@property 和 setter 实现透明加密/解密

    示例：
        class User(Base, EncryptedFieldMixin):
            __tablename__ = "users"
            # ... 其他字段 ...

            # 加密字段（存储密文）
            _encrypted_api_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)

            @property
            def api_key(self) -> Optional[str]:
                if not self._encrypted_api_key:
                    return None
                return decrypt_sensitive_data(self._encrypted_api_key)

            @api_key.setter
            def api_key(self, value: Optional[str]) -> None:
                if not value:
                    self._encrypted_api_key = None
                else:
                    self._encrypted_api_key = encrypt_sensitive_data(value)
    """  # noqa: E501

    pass


# ==========================================
# 工具函数：生成新的主密钥（用于初始化）
# ==========================================


def generate_new_master_key() -> str:
    """
    生成新的 AES-256 主密钥（十六进制字符串格式）

    使用方法：
    1. 调用此函数生成新密钥
    2. 将输出的十六进制字符串配置到 .env 的 ENCRYPTION_MASTER_KEY
    3. 重启服务使新密钥生效
    """
    new_key = os.urandom(32)
    return new_key.hex()


if __name__ == "__main__":
    # 测试代码
    print("🔐 生成新的 AES-256 主密钥...")
    new_key = generate_new_master_key()
    print("请将以下密钥配置到 .env 的 ENCRYPTION_MASTER_KEY：")
    print(f"{new_key}")
    print()

    # 测试加密/解密
    print("🧪 测试加密/解密...")
    test_data = "my-secret-api-key-123456"
    encrypted = encrypt_sensitive_data(test_data)
    print(f"明文：{test_data}")
    print(f"密文：{encrypted}")

    decrypted = decrypt_sensitive_data(encrypted)
    print(f"解密：{decrypted}")

    assert test_data == decrypted, "❌ 加密/解密测试失败！"
    print("✅ 加密/解密测试通过！")
