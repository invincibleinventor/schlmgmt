from __future__ import annotations

import base64
import json
from pathlib import Path

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime

from desk.crypto import data_key, key_fingerprint
from desk.models import ActivityRecord, AuditLog, ModuleControl, Profile, SiteSettings
from tvs_dms.security import SecurityError, decrypt_bytes


class Command(BaseCommand):
    help = "Restore an encrypted TVS cloud backup into an empty database."

    def add_arguments(self, parser):
        parser.add_argument("backup_file")
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Delete all existing Activity Desk data before restoring.",
        )

    def handle(self, *args, **options):
        path = Path(options["backup_file"])
        if not path.is_file():
            raise CommandError(f"Backup file not found: {path}")
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if envelope.get("format") != "tvs-cloud-envelope" or envelope.get("version") != 1:
                raise ValueError("unsupported backup envelope")
            raw = decrypt_bytes(
                base64.b64decode(envelope["nonce"]),
                base64.b64decode(envelope["ciphertext"]),
                base64.b64decode(envelope["tag"]),
                data_key(),
                b"tvs-cloud-backup-v1",
            )
            payload = json.loads(raw.decode("utf-8"))
        except (KeyError, ValueError, TypeError, json.JSONDecodeError, SecurityError) as exc:
            raise CommandError("Backup is invalid or TVS_DATA_KEY does not match.") from exc
        if payload.get("format") != "tvs-cloud-backup" or payload.get("version") != 1:
            raise CommandError("Unsupported TVS backup version.")
        if payload.get("key_fingerprint") != key_fingerprint():
            raise CommandError("TVS_DATA_KEY fingerprint does not match the backup.")
        if User.objects.exists() and not options["replace"]:
            raise CommandError("Database is not empty. Use --replace only after confirming a destructive restore.")

        with transaction.atomic():
            if options["replace"]:
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
                users[user.username] = user

            SiteSettings.objects.create(school_name=payload["school_name"])
            ModuleControl.objects.bulk_create(
                [ModuleControl(module_key=item["module_key"], enabled=item["enabled"]) for item in payload.get("module_controls", [])]
            )
            for item in payload.get("records", []):
                owner = users.get(item["owner"])
                if owner is None:
                    raise CommandError(f"Backup record refers to missing user: {item['owner']}")
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
            AuditLog.objects.create(action="backup_restored", target=path.name[:255])

        self.stdout.write(self.style.SUCCESS(f"Restored {len(payload.get('records', []))} records and {len(users)} users."))
