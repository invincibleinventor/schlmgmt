from __future__ import annotations

import base64
import binascii
import json
import threading
import uuid
from datetime import timedelta
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.contrib.auth.hashers import identify_hasher, make_password
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from tvs_dms.forms import ROLE_LABELS

from .domain import AuditData, ProfileData, RecordData, UserData
from .models import ActivityRecord, AuditLog, FieldVisibility, ModuleControl, Profile, SiteSettings

_FIREBASE_APP_LOCK = threading.Lock()


class AlreadyInitialized(Exception):
    pass


class DuplicateUsername(Exception):
    pass


def _get_or_initialize_firebase_app(firebase_admin, credentials, service_account: dict[str, Any]):
    """Return one named Firebase app even when cold-start requests race."""
    app_name = f"tvs-activity-desk-{service_account['project_id']}"
    with _FIREBASE_APP_LOCK:
        try:
            return firebase_admin.get_app(app_name)
        except ValueError:
            return firebase_admin.initialize_app(
                credentials.Certificate(service_account),
                name=app_name,
            )


def validate_restore_payload(payload: dict[str, Any]) -> None:
    """Validate a backup completely before a destructive replace begins."""
    school_name = payload.get("school_name")
    users = payload.get("users")
    records = payload.get("records", [])
    controls = payload.get("module_controls", [])
    if not isinstance(school_name, str) or not school_name.strip():
        raise ValueError("school_name is missing")
    if not isinstance(users, list) or not users:
        raise ValueError("backup must contain at least one user")
    if not isinstance(records, list) or not isinstance(controls, list):
        raise TypeError("records and module_controls must be lists")

    usernames: set[str] = set()
    for item in users:
        if not isinstance(item, dict):
            raise TypeError("user entry is invalid")
        username = item.get("username")
        display_name = item.get("display_name")
        role = item.get("role")
        password_hash = item.get("password_hash")
        if not isinstance(username, str) or not username.strip():
            raise ValueError("user entry has no username")
        username_key = username.strip().casefold()
        if username_key in usernames:
            raise ValueError(f"duplicate username in backup: {username}")
        usernames.add(username_key)
        if not isinstance(display_name, str) or not display_name.strip():
            raise ValueError(f"user {username} has no display name")
        if role not in ROLE_LABELS:
            raise ValueError(f"user {username} has an unknown role")
        if not isinstance(password_hash, str):
            raise TypeError(f"user {username} has no password hash")
        try:
            identify_hasher(password_hash)
        except ValueError as exc:
            raise ValueError(f"user {username} has an unsupported password hash") from exc

    for item in controls:
        if not isinstance(item, dict) or not isinstance(item.get("module_key"), str):
            raise TypeError("module control entry is invalid")
        if not isinstance(item.get("enabled"), bool):
            raise TypeError("module control enabled value must be true or false")

    for item in records:
        if not isinstance(item, dict):
            raise TypeError("record entry is invalid")
        try:
            uuid.UUID(str(item["id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("record id is invalid") from exc
        owner = item.get("owner")
        if not isinstance(owner, str) or owner.strip().casefold() not in usernames:
            raise ValueError(f"backup record refers to missing user: {owner}")
        if item.get("role") not in ROLE_LABELS or item.get("status") not in {"draft", "submitted"}:
            raise ValueError(f"record {item['id']} has an invalid role or status")
        event_date = item.get("event_date")
        if event_date and (not isinstance(event_date, str) or parse_date(event_date) is None):
            raise ValueError(f"record {item['id']} has an invalid event date")
        created_at = item.get("created_at")
        updated_at = item.get("updated_at")
        if (
            not isinstance(created_at, str)
            or not isinstance(updated_at, str)
            or parse_datetime(created_at) is None
            or parse_datetime(updated_at) is None
        ):
            raise ValueError(f"record {item['id']} has an invalid timestamp")
        for field, expected_length in (("nonce", 12), ("tag", 16)):
            try:
                decoded = base64.b64decode(item[field], validate=True)
            except (binascii.Error, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"record {item['id']} has invalid encrypted data") from exc
            if len(decoded) != expected_length:
                raise ValueError(f"record {item['id']} has invalid encrypted data")
        try:
            ciphertext = base64.b64decode(item["ciphertext"], validate=True)
        except (binascii.Error, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"record {item['id']} has invalid encrypted data") from exc
        if not ciphertext:
            raise ValueError(f"record {item['id']} has invalid encrypted data")


class DjangoStore:
    """Django ORM adapter retained for local development and legacy tests."""

    def initialized(self) -> bool:
        return User.objects.exists()

    def school_name(self) -> str:
        return SiteSettings.school_name_value()

    def username_exists(self, username: str) -> bool:
        return User.objects.filter(username__iexact=username.strip()).exists()

    def get_user(self, user_id: str | int) -> User | None:
        try:
            return User.objects.select_related("desk_profile").get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            return None

    def get_user_by_username(self, username: str) -> User | None:
        return User.objects.filter(username__iexact=username.strip()).select_related("desk_profile").first()

    def list_users(self) -> list[User]:
        return list(User.objects.select_related("desk_profile").order_by("desk_profile__display_name"))

    def create_initial_admin(
        self,
        *,
        school_name: str,
        username: str,
        password: str,
        display_name: str,
    ) -> User:
        try:
            with transaction.atomic():
                if self.initialized():
                    raise AlreadyInitialized
                user = User.objects.create_user(username=username, password=password)
                Profile.objects.create(
                    user=user,
                    display_name=display_name,
                    role="administrator",
                    must_change_password=False,
                )
                SiteSettings.objects.create(school_name=school_name)
                self.audit(user, "system_setup", "cloud_database")
                return user
        except IntegrityError as exc:
            raise AlreadyInitialized from exc

    def create_user(self, *, username: str, password: str, display_name: str, role: str) -> User:
        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username, password=password)
                Profile.objects.create(user=user, display_name=display_name, role=role)
                return user
        except IntegrityError as exc:
            raise DuplicateUsername from exc

    def register_login_failure(self, user: User) -> None:
        profile = user.desk_profile
        profile.failed_attempts += 1
        if profile.failed_attempts >= 5:
            profile.failed_attempts = 0
            profile.locked_until = timezone.now() + timedelta(minutes=5)
        profile.save(update_fields=("failed_attempts", "locked_until", "updated_at"))

    def clear_login_failures(self, user: User) -> None:
        profile = user.desk_profile
        profile.failed_attempts = 0
        profile.locked_until = None
        profile.save(update_fields=("failed_attempts", "locked_until", "updated_at"))

    def update_password(self, user: User, password: str, *, must_change: bool) -> None:
        user.set_password(password)
        user.save(update_fields=("password",))
        profile = user.desk_profile
        profile.must_change_password = must_change
        profile.failed_attempts = 0
        profile.locked_until = None
        profile.session_version += 1
        profile.save(
            update_fields=(
                "must_change_password",
                "failed_attempts",
                "locked_until",
                "session_version",
                "updated_at",
            )
        )

    def set_user_active(self, user: User, active: bool) -> None:
        user.is_active = active
        user.save(update_fields=("is_active",))
        user.desk_profile.session_version += 1
        user.desk_profile.save(update_fields=("session_version", "updated_at"))

    def module_states(self) -> dict[str, bool]:
        return {row.module_key: row.enabled for row in ModuleControl.objects.all()}

    def set_module_enabled(self, module_key: str, enabled: bool) -> None:
        control, _ = ModuleControl.objects.get_or_create(module_key=module_key)
        control.enabled = enabled
        control.save()

    def hidden_fields(self) -> dict[tuple[str, str], set[str]]:
        result: dict[tuple[str, str], set[str]] = {}
        for row in FieldVisibility.objects.all():
            result.setdefault((row.module_key, row.role), set()).add(row.field_key)
        return result

    def set_field_hidden(self, module_key: str, role: str, field_key: str, hidden: bool) -> None:
        if hidden:
            FieldVisibility.objects.get_or_create(
                module_key=module_key, role=role, field_key=field_key
            )
        else:
            FieldVisibility.objects.filter(
                module_key=module_key, role=role, field_key=field_key
            ).delete()

    def list_records(self) -> list[ActivityRecord]:
        return list(ActivityRecord.objects.select_related("owner", "owner__desk_profile").order_by("-updated_at"))

    def get_record(self, record_id: str) -> ActivityRecord | None:
        try:
            return ActivityRecord.objects.select_related("owner", "owner__desk_profile").get(pk=record_id)
        except (ActivityRecord.DoesNotExist, ValueError):
            return None

    def save_record(
        self,
        *,
        record: ActivityRecord | None,
        module_key: str,
        module_name: str,
        role: str,
        owner: User,
        status: str,
        event_date,
        payload: dict[str, Any],
    ) -> ActivityRecord:
        with transaction.atomic():
            if record is None:
                record = ActivityRecord(module_key=module_key, module_name=module_name, role=role, owner=owner)
            record.status = status
            record.event_date = event_date
            record.set_data(payload)
            record.save()
        return record

    def audit(self, user: User | None, action: str, target: str = "") -> None:
        AuditLog.objects.create(user=user, action=action, target=target[:255])

    def list_audit(self) -> list[AuditLog]:
        return list(AuditLog.objects.select_related("user", "user__desk_profile").order_by("-id"))

    def health(self) -> None:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def restore(self, payload: dict[str, Any], *, replace: bool) -> tuple[int, int]:
        validate_restore_payload(payload)
        if self.initialized() and not replace:
            raise AlreadyInitialized
        with transaction.atomic():
            if replace:
                AuditLog.objects.all().delete()
                ActivityRecord.objects.all().delete()
                ModuleControl.objects.all().delete()
                SiteSettings.objects.all().delete()
                User.objects.all().delete()

            users: dict[str, User] = {}
            for item in payload.get("users", []):
                user = User.objects.create(
                    username=item["username"],
                    password=item["password_hash"],
                    is_active=bool(item.get("active", True)),
                )
                Profile.objects.create(
                    user=user,
                    display_name=item["display_name"],
                    role=item["role"],
                    must_change_password=bool(item.get("must_change_password", True)),
                )
                users[user.username.strip().casefold()] = user

            SiteSettings.objects.create(school_name=payload["school_name"])
            ModuleControl.objects.bulk_create(
                [
                    ModuleControl(module_key=item["module_key"], enabled=item["enabled"])
                    for item in payload.get("module_controls", [])
                ]
            )
            for item in payload.get("records", []):
                owner = users.get(item["owner"].strip().casefold())
                if owner is None:
                    raise ValueError(f"Backup record refers to missing user: {item['owner']}")
                record = ActivityRecord.objects.create(
                    id=item["id"],
                    module_key=item["module_key"],
                    module_name=item["module_name"],
                    role=item["role"],
                    owner=owner,
                    status=item["status"],
                    event_date=parse_date(item["event_date"]) if item.get("event_date") else None,
                    payload_nonce=base64.b64decode(item["nonce"]),
                    payload_ciphertext=base64.b64decode(item["ciphertext"]),
                    payload_tag=base64.b64decode(item["tag"]),
                )
                ActivityRecord.objects.filter(pk=record.pk).update(
                    created_at=parse_datetime(item["created_at"]),
                    updated_at=parse_datetime(item["updated_at"]),
                )
            self.audit(None, "backup_restored", "encrypted_backup")
        return len(payload.get("records", [])), len(users)


class FirestoreStore:
    """Firestore adapter used by Vercel and other stateless deployments."""

    def __init__(self) -> None:
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError as exc:
            raise ImproperlyConfigured("firebase-admin is required for Firestore deployments.") from exc

        raw = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        try:
            service_account = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ImproperlyConfigured("FIREBASE_SERVICE_ACCOUNT_JSON must contain valid JSON.") from exc
        if service_account.get("type") != "service_account" or not service_account.get("project_id"):
            raise ImproperlyConfigured("FIREBASE_SERVICE_ACCOUNT_JSON is not a Firebase service account key.")
        app = _get_or_initialize_firebase_app(firebase_admin, credentials, service_account)
        self.db = firestore.client(app=app)
        self.firestore = firestore
        self._school_name: str | None = None

    @staticmethod
    def _username_key(username: str) -> str:
        return username.strip().casefold()

    def _user_from_snapshot(self, snapshot) -> UserData | None:
        if snapshot is None or not snapshot.exists:
            return None
        data = snapshot.to_dict()
        return UserData(
            id=snapshot.id,
            username=data["username"],
            password=data["password_hash"],
            is_active=bool(data.get("active", True)),
            desk_profile=ProfileData(
                display_name=data["display_name"],
                role=data["role"],
                must_change_password=bool(data.get("must_change_password", True)),
                failed_attempts=int(data.get("failed_attempts", 0)),
                locked_until=data.get("locked_until"),
                session_version=int(data.get("session_version", 1)),
            ),
        )

    def initialized(self) -> bool:
        return self.db.collection("config").document("site").get().exists

    def school_name(self) -> str:
        if self._school_name is None:
            snapshot = self.db.collection("config").document("site").get()
            self._school_name = snapshot.to_dict().get("school_name") if snapshot.exists else None
        return self._school_name or "School Activity Management"

    def username_exists(self, username: str) -> bool:
        return self.db.collection("usernames").document(self._username_key(username)).get().exists

    def get_user(self, user_id: str | int) -> UserData | None:
        return self._user_from_snapshot(self.db.collection("users").document(str(user_id)).get())

    def get_user_by_username(self, username: str) -> UserData | None:
        mapping = self.db.collection("usernames").document(self._username_key(username)).get()
        if not mapping.exists:
            return None
        return self.get_user(mapping.to_dict()["uid"])

    def list_users(self) -> list[UserData]:
        users = [self._user_from_snapshot(snapshot) for snapshot in self.db.collection("users").stream()]
        return sorted((user for user in users if user), key=lambda user: user.desk_profile.display_name.casefold())

    def _create_user_transaction(
        self,
        *,
        username: str,
        password: str,
        display_name: str,
        role: str,
        must_change_password: bool,
        school_name: str | None = None,
    ) -> UserData:
        uid = str(uuid.uuid4())
        now = timezone.now()
        user_ref = self.db.collection("users").document(uid)
        username_ref = self.db.collection("usernames").document(self._username_key(username))
        site_ref = self.db.collection("config").document("site")
        audit_ref = self.db.collection("audit_logs").document(str(uuid.uuid4()))
        db_transaction = self.db.transaction()

        @self.firestore.transactional
        def create(transaction):
            site = site_ref.get(transaction=transaction) if school_name is not None else None
            username_row = username_ref.get(transaction=transaction)
            if site is not None and site.exists:
                raise AlreadyInitialized
            if username_row.exists:
                raise DuplicateUsername
            user_data = {
                "username": username.strip(),
                "username_key": self._username_key(username),
                "password_hash": make_password(password, hasher="argon2"),
                "active": True,
                "display_name": display_name.strip(),
                "role": role,
                "must_change_password": must_change_password,
                "failed_attempts": 0,
                "locked_until": None,
                "session_version": 1,
                "created_at": now,
                "updated_at": now,
            }
            transaction.set(user_ref, user_data)
            transaction.set(username_ref, {"uid": uid})
            if school_name is not None:
                transaction.set(site_ref, {"school_name": school_name.strip(), "created_at": now, "updated_at": now})
                transaction.set(
                    audit_ref,
                    {
                        "user_uid": uid,
                        "username": username.strip(),
                        "display_name": display_name.strip(),
                        "action": "system_setup",
                        "target": "firebase_firestore",
                        "created_at": now,
                    },
                )
            return user_data

        data = create(db_transaction)
        if school_name is not None:
            self._school_name = school_name.strip()
        return self._user_from_snapshot(_Snapshot(uid, data))

    def create_initial_admin(
        self,
        *,
        school_name: str,
        username: str,
        password: str,
        display_name: str,
    ) -> UserData:
        return self._create_user_transaction(
            school_name=school_name,
            username=username,
            password=password,
            display_name=display_name,
            role="administrator",
            must_change_password=False,
        )

    def create_user(self, *, username: str, password: str, display_name: str, role: str) -> UserData:
        return self._create_user_transaction(
            username=username,
            password=password,
            display_name=display_name,
            role=role,
            must_change_password=True,
        )

    def register_login_failure(self, user: UserData) -> None:
        user_ref = self.db.collection("users").document(user.id)
        db_transaction = self.db.transaction()

        @self.firestore.transactional
        def record_failure(transaction):
            snapshot = user_ref.get(transaction=transaction)
            data = snapshot.to_dict() if snapshot.exists else {}
            attempts = int(data.get("failed_attempts", 0)) + 1
            locked_until = data.get("locked_until")
            if attempts >= 5:
                attempts = 0
                locked_until = timezone.now() + timedelta(minutes=5)
            transaction.update(
                user_ref,
                {
                    "failed_attempts": attempts,
                    "locked_until": locked_until,
                    "updated_at": timezone.now(),
                },
            )
            return attempts, locked_until

        user.desk_profile.failed_attempts, user.desk_profile.locked_until = record_failure(db_transaction)

    def clear_login_failures(self, user: UserData) -> None:
        user.desk_profile.failed_attempts = 0
        user.desk_profile.locked_until = None
        self.db.collection("users").document(user.id).update(
            {"failed_attempts": 0, "locked_until": None, "updated_at": timezone.now()}
        )

    def update_password(self, user: UserData, password: str, *, must_change: bool) -> None:
        user.set_password(password)
        profile = user.desk_profile
        profile.must_change_password = must_change
        profile.failed_attempts = 0
        profile.locked_until = None
        profile.session_version += 1
        self.db.collection("users").document(user.id).update(
            {
                "password_hash": user.password,
                "must_change_password": must_change,
                "failed_attempts": 0,
                "locked_until": None,
                "session_version": self.firestore.Increment(1),
                "updated_at": timezone.now(),
            }
        )

    def set_user_active(self, user: UserData, active: bool) -> None:
        user.is_active = active
        user.desk_profile.session_version += 1
        self.db.collection("users").document(user.id).update(
            {
                "active": active,
                "session_version": self.firestore.Increment(1),
                "updated_at": timezone.now(),
            }
        )

    def module_states(self) -> dict[str, bool]:
        return {
            snapshot.id: bool(snapshot.to_dict().get("enabled", True))
            for snapshot in self.db.collection("module_controls").stream()
        }

    def set_module_enabled(self, module_key: str, enabled: bool) -> None:
        self.db.collection("module_controls").document(module_key).set(
            {"enabled": enabled, "updated_at": timezone.now()}
        )

    def hidden_fields(self) -> dict[tuple[str, str], set[str]]:
        result: dict[tuple[str, str], set[str]] = {}
        for snapshot in self.db.collection("field_visibility").stream():
            data = snapshot.to_dict() or {}
            module_key = data.get("module_key")
            role = data.get("role")
            field_key = data.get("field_key")
            if module_key and role and field_key:
                result.setdefault((module_key, role), set()).add(field_key)
        return result

    def set_field_hidden(self, module_key: str, role: str, field_key: str, hidden: bool) -> None:
        document = self.db.collection("field_visibility").document(
            f"{module_key}__{role}__{field_key}"
        )
        if hidden:
            document.set(
                {
                    "module_key": module_key,
                    "role": role,
                    "field_key": field_key,
                    "updated_at": timezone.now(),
                }
            )
        else:
            document.delete()

    def _record_from_snapshot(self, snapshot, users: dict[str, UserData] | None = None) -> RecordData | None:
        if snapshot is None or not snapshot.exists:
            return None
        data = snapshot.to_dict()
        owner_uid = data["owner_uid"]
        owner = users.get(owner_uid) if users is not None else None
        owner = owner or self.get_user(owner_uid)
        if owner is None:
            return None
        return RecordData(
            id=snapshot.id,
            module_key=data["module_key"],
            module_name=data["module_name"],
            role=data["role"],
            owner=owner,
            status=data["status"],
            event_date=parse_date(data.get("event_date", "")) if data.get("event_date") else None,
            payload_nonce=base64.b64decode(data["nonce"]),
            payload_ciphertext=base64.b64decode(data["ciphertext"]),
            payload_tag=base64.b64decode(data["tag"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def list_records(self) -> list[RecordData]:
        users = {user.id: user for user in self.list_users()}
        records = [
            self._record_from_snapshot(snapshot, users)
            for snapshot in self.db.collection("activity_records").stream()
        ]
        return sorted((record for record in records if record), key=lambda record: record.updated_at, reverse=True)

    def get_record(self, record_id: str) -> RecordData | None:
        return self._record_from_snapshot(self.db.collection("activity_records").document(str(record_id)).get())

    def save_record(
        self,
        *,
        record: RecordData | None,
        module_key: str,
        module_name: str,
        role: str,
        owner: UserData,
        status: str,
        event_date,
        payload: dict[str, Any],
    ) -> RecordData:
        now = timezone.now()
        if record is None:
            record = RecordData(
                id=str(uuid.uuid4()),
                module_key=module_key,
                module_name=module_name,
                role=role,
                owner=owner,
                status=status,
                event_date=event_date,
                payload_nonce=b"",
                payload_ciphertext=b"",
                payload_tag=b"",
                created_at=now,
                updated_at=now,
            )
        record.status = status
        record.event_date = event_date
        record.updated_at = now
        record.set_data(payload)
        self.db.collection("activity_records").document(record.id).set(
            {
                "module_key": record.module_key,
                "module_name": record.module_name,
                "role": record.role,
                "owner_uid": str(record.owner.id),
                "owner_username": record.owner.username,
                "owner_name": record.owner.desk_profile.display_name,
                "status": record.status,
                "event_date": record.event_date.isoformat() if record.event_date else "",
                "nonce": base64.b64encode(record.payload_nonce).decode("ascii"),
                "ciphertext": base64.b64encode(record.payload_ciphertext).decode("ascii"),
                "tag": base64.b64encode(record.payload_tag).decode("ascii"),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )
        return record

    def audit(self, user: UserData | None, action: str, target: str = "") -> None:
        self.db.collection("audit_logs").document(str(uuid.uuid4())).set(
            {
                "user_uid": user.id if user else "",
                "username": user.username if user else "",
                "display_name": user.desk_profile.display_name if user else "",
                "action": action,
                "target": target[:255],
                "created_at": timezone.now(),
            }
        )

    def list_audit(self) -> list[AuditData]:
        users = {user.id: user for user in self.list_users()}
        entries = []
        for snapshot in self.db.collection("audit_logs").stream():
            data = snapshot.to_dict()
            entries.append(
                AuditData(
                    id=snapshot.id,
                    user=users.get(data.get("user_uid", "")),
                    action=data["action"],
                    target=data.get("target", ""),
                    created_at=data["created_at"],
                )
            )
        return sorted(entries, key=lambda entry: entry.created_at, reverse=True)

    def health(self) -> None:
        self.db.collection("config").document("site").get()

    def _delete_collection(self, name: str) -> None:
        collection = self.db.collection(name)
        while True:
            snapshots = list(collection.limit(400).stream())
            if not snapshots:
                return
            batch = self.db.batch()
            for snapshot in snapshots:
                batch.delete(snapshot.reference)
            batch.commit()

    def restore(self, payload: dict[str, Any], *, replace: bool) -> tuple[int, int]:
        validate_restore_payload(payload)
        if self.initialized() and not replace:
            raise AlreadyInitialized
        if replace:
            for collection in ("audit_logs", "activity_records", "module_controls", "usernames", "users", "config"):
                self._delete_collection(collection)

        users: dict[str, UserData] = {}
        for item in payload.get("users", []):
            uid = str(uuid.uuid4())
            now = timezone.now()
            data = {
                "username": item["username"],
                "username_key": self._username_key(item["username"]),
                "password_hash": item["password_hash"],
                "active": bool(item.get("active", True)),
                "display_name": item["display_name"],
                "role": item["role"],
                "must_change_password": bool(item.get("must_change_password", True)),
                "failed_attempts": 0,
                "locked_until": None,
                "session_version": 1,
                "created_at": now,
                "updated_at": now,
            }
            self.db.collection("users").document(uid).set(data)
            self.db.collection("usernames").document(data["username_key"]).set({"uid": uid})
            users[item["username"].strip().casefold()] = self._user_from_snapshot(_Snapshot(uid, data))

        now = timezone.now()
        self.db.collection("config").document("site").set(
            {"school_name": payload["school_name"], "created_at": now, "updated_at": now}
        )
        self._school_name = payload["school_name"]
        for item in payload.get("module_controls", []):
            self.set_module_enabled(item["module_key"], bool(item["enabled"]))
        for item in payload.get("records", []):
            owner = users.get(item["owner"].strip().casefold())
            if owner is None:
                raise ValueError(f"Backup record refers to missing user: {item['owner']}")
            self.db.collection("activity_records").document(item["id"]).set(
                {
                    "module_key": item["module_key"],
                    "module_name": item["module_name"],
                    "role": item["role"],
                    "owner_uid": owner.id,
                    "owner_username": owner.username,
                    "owner_name": owner.desk_profile.display_name,
                    "status": item["status"],
                    "event_date": item.get("event_date", ""),
                    "nonce": item["nonce"],
                    "ciphertext": item["ciphertext"],
                    "tag": item["tag"],
                    "created_at": parse_datetime(item["created_at"]) or now,
                    "updated_at": parse_datetime(item["updated_at"]) or now,
                }
            )
        self.audit(None, "backup_restored", "encrypted_backup")
        return len(payload.get("records", [])), len(users)


class _Snapshot:
    """Small adapter used when Firestore data was created in the same request."""

    exists = True

    def __init__(self, document_id: str, data: dict[str, Any]) -> None:
        self.id = document_id
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return self._data


@lru_cache(maxsize=1)
def get_store():
    if getattr(settings, "TVS_USE_FIREBASE", False):
        return FirestoreStore()
    return DjangoStore()
