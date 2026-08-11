from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "TVS Activity Desk"
APP_VERSION = "1.0.0"


def data_dir() -> Path:
    override = os.environ.get("TVS_DMS_DATA_DIR")
    if override:
        root = Path(override)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TVSActivityDesk"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "TVSActivityDesk"
    else:
        root = Path.home() / ".local" / "share" / "tvs-activity-desk"
    root.mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    return data_dir() / "activity-desk.db"


