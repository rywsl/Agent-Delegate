"""Password hashing, API keys and at-rest encryption of provider credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet

from .config import get_settings

API_KEY_PREFIX = "dlg_"
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt_hex), n=int(n), r=int(r), p=int(p), dklen=len(digest_hex) // 2
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext key, display prefix, sha256 hash)."""
    key = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return key, key[: len(API_KEY_PREFIX) + 6], hash_api_key(key)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    material = hashlib.sha256(b"delegate-at-rest:" + get_settings().secret_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)
