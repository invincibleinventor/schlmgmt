from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.contrib.auth.hashers import check_password, make_password

from tvs_dms.forms import ROLE_LABELS

from .crypto import decrypt_payload, encrypt_payload


@dataclass
class ProfileData:
    display_name: str
    role: str
    must_change_password: bool = True
    failed_attempts: int = 0
    locked_until: datetime | None = None
    session_version: int = 1

    def get_role_display(self) -> str:
        return ROLE_LABELS.get(self.role, self.role.replace("_", " ").title())


@dataclass(eq=False)
class UserData:
    id: str
    username: str
    password: str
    is_active: bool
    desk_profile: ProfileData

    @property
    def pk(self) -> str:
        return self.id

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def check_password(self, raw_password: str) -> bool:
        return check_password(raw_password, self.password)

    def set_password(self, raw_password: str) -> None:
        self.password = make_password(raw_password, hasher="argon2")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, UserData) and self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class RecordData:
    id: str
    module_key: str
    module_name: str
    role: str
    owner: UserData
    status: str
    event_date: date | None
    payload_nonce: bytes
    payload_ciphertext: bytes
    payload_tag: bytes
    created_at: datetime
    updated_at: datetime

    DRAFT = "draft"
    SUBMITTED = "submitted"

    @property
    def owner_id(self) -> str:
        return self.owner.id

    def get_status_display(self) -> str:
        return "Submitted" if self.status == self.SUBMITTED else "Draft"

    def set_data(self, value: dict[str, Any]) -> None:
        nonce, ciphertext, tag = encrypt_payload(value, self.id)
        self.payload_nonce = nonce
        self.payload_ciphertext = ciphertext
        self.payload_tag = tag

    def get_data(self) -> dict[str, Any]:
        return decrypt_payload(
            self.payload_nonce,
            self.payload_ciphertext,
            self.payload_tag,
            self.id,
        )


@dataclass
class AuditData:
    id: str
    user: UserData | None
    action: str
    target: str
    created_at: datetime
