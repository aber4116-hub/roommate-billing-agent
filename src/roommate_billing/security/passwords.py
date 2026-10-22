"""密码哈希与令牌工具。"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import get_settings

_hasher = PasswordHasher()
# 对不存在的邮箱也执行一次真实校验，降低时序枚举。
DUMMY_PASSWORD_HASH = _hasher.hash("dummy-password-for-timing-only")


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 128:
        raise ValueError("密码长度必须为 12–128 个字符")
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # 不存在密码的账户也执行一次校验，保持时序接近。
        with contextlib.suppress(VerificationError, VerifyMismatchError, InvalidHashError):
            _hasher.verify(DUMMY_PASSWORD_HASH, password)
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, VerifyMismatchError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_hex(value: str, *, secret: str | None = None) -> str:
    key = (secret or get_settings().app_secret_key).encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def secure_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
