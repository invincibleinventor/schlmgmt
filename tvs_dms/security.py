from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Any, Dict, Optional, Tuple

from Crypto.Cipher import AES

PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
KEY_BYTES = 32


class SecurityError(Exception):
    pass


def new_salt() -> bytes:
    return os.urandom(SALT_BYTES)


def derive_key(password: str, salt: bytes) -> bytes:
    if not password:
        raise SecurityError("Password cannot be empty.")
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=KEY_BYTES
    )


def _purpose_key(base_key: bytes, purpose: bytes) -> bytes:
    return hmac.new(base_key, purpose, hashlib.sha256).digest()


def hash_password(password: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    salt = salt or new_salt()
    base_key = derive_key(password, salt)
    return salt, _purpose_key(base_key, b"tvs-password-verifier-v1")


def verify_password(password: str, salt: bytes, expected: bytes) -> bool:
    try:
        base_key = derive_key(password, salt)
        actual = _purpose_key(base_key, b"tvs-password-verifier-v1")
    except SecurityError:
        return False
    return hmac.compare_digest(actual, expected)


def encrypt_bytes(plaintext: bytes, key: bytes, associated_data: bytes = b"") -> Tuple[bytes, bytes, bytes]:
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
    if associated_data:
        cipher.update(associated_data)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return nonce, ciphertext, tag


def decrypt_bytes(
    nonce: bytes, ciphertext: bytes, tag: bytes, key: bytes, associated_data: bytes = b""
) -> bytes:
    try:
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce, mac_len=16)
        if associated_data:
            cipher.update(associated_data)
        return cipher.decrypt_and_verify(ciphertext, tag)
    except (ValueError, KeyError) as exc:
        raise SecurityError("Encrypted data could not be verified.") from exc


def wrap_data_key(data_key: bytes, password: str, salt: bytes) -> Tuple[bytes, bytes, bytes]:
    wrapping_key = _purpose_key(derive_key(password, salt), b"tvs-data-wrap-key-v1")
    return encrypt_bytes(data_key, wrapping_key, b"tvs-user-data-key-v1")


def unwrap_data_key(
    nonce: bytes, wrapped_key: bytes, tag: bytes, password: str, salt: bytes
) -> bytes:
    wrapping_key = _purpose_key(derive_key(password, salt), b"tvs-data-wrap-key-v1")
    return decrypt_bytes(nonce, wrapped_key, tag, wrapping_key, b"tvs-user-data-key-v1")


def encrypt_json(value: Dict[str, Any], data_key: bytes, record_id: str) -> Tuple[bytes, bytes, bytes]:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return encrypt_bytes(raw, data_key, record_id.encode("utf-8"))


def decrypt_json(
    nonce: bytes, ciphertext: bytes, tag: bytes, data_key: bytes, record_id: str
) -> Dict[str, Any]:
    raw = decrypt_bytes(nonce, ciphertext, tag, data_key, record_id.encode("utf-8"))
    return json.loads(raw.decode("utf-8"))


def encode_token(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")

