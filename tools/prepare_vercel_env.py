#!/usr/bin/env python3
"""Print a ready-to-paste Vercel environment block without writing secrets to disk."""

from __future__ import annotations

import base64
import json
import secrets
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python tools/prepare_vercel_env.py /path/to/firebase-service-account.json", file=sys.stderr)
        return 2

    path = Path(sys.argv[1]).expanduser()
    try:
        service_account = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read a valid Firebase JSON key: {exc}", file=sys.stderr)
        return 1

    required = {"type", "project_id", "private_key", "client_email"}
    if service_account.get("type") != "service_account" or not required.issubset(service_account):
        print("That file is not a complete Firebase service-account key.", file=sys.stderr)
        return 1

    print(f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}")
    print(f"TVS_DATA_KEY={base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()}")
    print(f"TVS_SETUP_TOKEN={secrets.token_urlsafe(32)}")
    print("DJANGO_DEBUG=false")
    print("DJANGO_TIME_ZONE=Asia/Kolkata")
    print(f"FIREBASE_SERVICE_ACCOUNT_JSON={json.dumps(service_account, separators=(',', ':'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
