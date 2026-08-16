from __future__ import annotations

import base64
import hashlib
import hmac
from functools import lru_cache

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from tvs_dms.security import decrypt_json, encrypt_json


@lru_cache(maxsize=1)
def data_key() -> bytes:
    encoded = getattr(settings, "TVS_DATA_KEY", "").strip()
    if encoded:
        try:
            key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured("TVS_DATA_KEY must be URL-safe base64.") from exc
        if len(key) != 32:
            raise ImproperlyConfigured("TVS_DATA_KEY must decode to exactly 32 bytes.")
        return key
    if not settings.DEBUG:
        raise ImproperlyConfigured("TVS_DATA_KEY is required in production.")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        b"tvs-activity-desk-development-data-key-v1",
        hashlib.sha256,
    ).digest()


def encrypt_payload(value: dict, record_id: str) -> tuple[bytes, bytes, bytes]:
    return encrypt_json(value, data_key(), record_id)


def decrypt_payload(nonce: bytes, ciphertext: bytes, tag: bytes, record_id: str) -> dict:
    return decrypt_json(nonce, ciphertext, tag, data_key(), record_id)


def key_fingerprint() -> str:
    return hashlib.sha256(data_key()).hexdigest()[:16]
