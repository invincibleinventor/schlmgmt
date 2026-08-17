from __future__ import annotations

import base64
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from desk.crypto import data_key, key_fingerprint
from desk.store import AlreadyInitialized, get_store
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
        try:
            record_count, user_count = get_store().restore(payload, replace=options["replace"])
        except AlreadyInitialized as exc:
            raise CommandError(
                "Database is not empty. Use --replace only after confirming a destructive restore."
            ) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise CommandError(f"Backup data is invalid: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Restored {record_count} records and {user_count} users."))
