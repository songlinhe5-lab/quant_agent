"""
加密解密模块单元测试（AES-256-GCM）

覆盖：
- get_encryption_key() 密钥获取
- encrypt_sensitive_data() 加密
- decrypt_sensitive_data() 解密
- generate_new_master_key() 密钥生成
- 异常路径：篡改密文、错误密钥、InvalidTag
"""

import base64
import os
import warnings

import pytest

from backend.core.encryption import (
    decrypt_sensitive_data,
    encrypt_sensitive_data,
    generate_new_master_key,
    get_encryption_key,
)


class TestGetEncryptionKey:
    """get_encryption_key() 密钥获取"""

    def test_returns_32_bytes(self):
        key = get_encryption_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_missing_key_returns_zeros_with_warning(self):
        """未配置 ENCRYPTION_MASTER_KEY 时返回零密钥并发出警告"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            enc_module.settings.encryption_master_key = None
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                key = get_encryption_key()
                assert key == b"\x00" * 32
                assert any("ENCRYPTION_MASTER_KEY" in str(warning.message) for warning in w)
        finally:
            enc_module.settings.encryption_master_key = original

    def test_hex_key_decoding(self):
        """64 字符十六进制密钥正确解码为 32 字节"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            hex_key = "aa" * 32  # 64 字符 = 32 字节
            enc_module.settings.encryption_master_key = hex_key
            key = get_encryption_key()
            assert len(key) == 32
            assert key == bytes.fromhex(hex_key)
        finally:
            enc_module.settings.encryption_master_key = original

    def test_base64_key_decoding(self):
        """Base64 编码密钥正确解码"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            raw_key = os.urandom(32)
            b64_key = base64.b64encode(raw_key).decode("utf-8")
            enc_module.settings.encryption_master_key = b64_key
            key = get_encryption_key()
            assert key == raw_key
        finally:
            enc_module.settings.encryption_master_key = original

    def test_invalid_hex_falls_back_to_plain_string(self):
        """64 字符非 hex 密钥被视为原始字符串并截断为 32 字节"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            # "zz" * 32 是 64 字符，但不是有效的 hex
            enc_module.settings.encryption_master_key = "zz" * 32
            key = get_encryption_key()
            # 进入 except 分支，将 "zzzz..." 视为原始字符串
            expected = ("zz" * 32).encode("utf-8")[:32]
            assert key == expected
        finally:
            enc_module.settings.encryption_master_key = original

    def test_non_ascii_key_falls_back_to_plain_string(self):
        """包含非 ASCII 字符的密钥被视为原始字符串"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            # 包含中文的密钥会导致 base64 解码失败，进入 except 分支
            enc_module.settings.encryption_master_key = "这是一个很长的密钥用于测试" * 2
            key = get_encryption_key()
            # 进入 except 分支，将密钥视为原始字符串并截断为 32 字节
            assert len(key) == 32
        finally:
            enc_module.settings.encryption_master_key = original

    def test_plain_string_key_shorter_than_32_bytes_raises(self):
        """原始字符串短于 32 字节时抛出 ValueError"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            # 先设置一个会进入 except 分支的 key（包含非 ASCII 字符）
            enc_module.settings.encryption_master_key = "短"
            with pytest.raises(ValueError, match="长度必须 >= 32 字节"):
                get_encryption_key()
        finally:
            enc_module.settings.encryption_master_key = original


class TestEncryptSensitiveData:
    """encrypt_sensitive_data() 加密"""

    def test_encrypt_string_returns_base64(self):
        plaintext = "my-secret-api-key"
        ciphertext = encrypt_sensitive_data(plaintext)
        assert isinstance(ciphertext, str)
        # 应该是有效的 Base64
        decoded = base64.b64decode(ciphertext)
        # 格式：nonce(12) + ciphertext + tag(16)
        assert len(decoded) >= 28

    def test_encrypt_bytes(self):
        plaintext = b"binary-data-\x00\x01\x02"
        ciphertext = encrypt_sensitive_data(plaintext)
        assert isinstance(ciphertext, str)
        decoded = base64.b64decode(ciphertext)
        assert len(decoded) >= 28

    def test_encrypt_none_returns_none(self):
        assert encrypt_sensitive_data(None) is None

    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "hello-world-测试中文"
        ciphertext = encrypt_sensitive_data(plaintext)
        decrypted = decrypt_sensitive_data(ciphertext)
        assert decrypted == plaintext

    def test_different_nonce_each_time(self):
        """每次加密应使用不同 nonce（随机）"""
        plaintext = "same-data"
        c1 = encrypt_sensitive_data(plaintext)
        c2 = encrypt_sensitive_data(plaintext)
        # 密文应不同（因为 nonce 不同）
        assert c1 != c2


class TestDecryptSensitiveData:
    """decrypt_sensitive_data() 解密"""

    def test_decrypt_none_returns_none(self):
        assert decrypt_sensitive_data(None) is None

    def test_decrypt_valid_ciphertext(self):
        plaintext = "test-secret-123"
        ciphertext = encrypt_sensitive_data(plaintext)
        assert decrypt_sensitive_data(ciphertext) == plaintext

    def test_decrypt_tampered_ciphertext_raises(self):
        """篡改密文应触发 InvalidTag 异常"""
        plaintext = "test-secret"
        ciphertext = encrypt_sensitive_data(plaintext)
        # 篡改密文（修改中间部分）
        raw = bytearray(base64.b64decode(ciphertext))
        raw[20] ^= 0xFF  # 翻转一位
        tampered = base64.b64encode(bytes(raw)).decode("utf-8")
        with pytest.raises(ValueError, match="认证失败|密文认证失败"):
            decrypt_sensitive_data(tampered)

    def test_decrypt_wrong_key_raises(self):
        """使用错误密钥解密应失败"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            enc_module.settings.encryption_master_key = base64.b64encode(os.urandom(32)).decode()
            plaintext = "secret-data"
            ciphertext = encrypt_sensitive_data(plaintext)

            # 切换密钥
            enc_module.settings.encryption_master_key = base64.b64encode(os.urandom(32)).decode()
            with pytest.raises(ValueError, match="认证失败|密文认证失败"):
                decrypt_sensitive_data(ciphertext)
        finally:
            enc_module.settings.encryption_master_key = original

    def test_decrypt_invalid_base64_raises(self):
        with pytest.raises(Exception):
            decrypt_sensitive_data("not-valid-base64!!!")

    def test_decrypt_too_short_ciphertext_raises(self):
        """密文太短（无法拆分 nonce + ciphertext + tag）"""
        short_b64 = base64.b64encode(b"\x00" * 10).decode("utf-8")
        with pytest.raises((ValueError, IndexError)):
            decrypt_sensitive_data(short_b64)


class TestGenerateNewMasterKey:
    """generate_new_master_key() 密钥生成"""

    def test_returns_hex_string(self):
        key_hex = generate_new_master_key()
        assert isinstance(key_hex, str)
        assert len(key_hex) == 64  # 32 字节 = 64 十六进制字符

    def test_generated_key_is_random(self):
        k1 = generate_new_master_key()
        k2 = generate_new_master_key()
        assert k1 != k2

    def test_generated_key_valid_for_encryption(self):
        """生成的密钥可用于加解密"""
        from backend.core import encryption as enc_module

        original = enc_module.settings.encryption_master_key
        try:
            enc_module.settings.encryption_master_key = generate_new_master_key()
            plaintext = "test-with-new-key"
            ciphertext = encrypt_sensitive_data(plaintext)
            assert decrypt_sensitive_data(ciphertext) == plaintext
        finally:
            enc_module.settings.encryption_master_key = original
