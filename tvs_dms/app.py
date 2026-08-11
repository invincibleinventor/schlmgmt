from __future__ import annotations

import sys
import tempfile
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import messagebox

from .config import APP_NAME, database_path
from .database import Database
from .ui import ActivityDeskApp


def package_check() -> None:
    """Small non-GUI check used by the Windows release builder."""
    from .security import decrypt_bytes, encrypt_bytes

    key = b"T" * 32
    nonce, ciphertext, tag = encrypt_bytes(b"package-ok", key)
    if decrypt_bytes(nonce, ciphertext, tag, key) != b"package-ok":
        raise RuntimeError("Encryption self-check failed.")
    with tempfile.TemporaryDirectory(prefix="tvs-package-check-") as temporary:
        database = Database(Path(temporary) / "check.db")
        database.close()


def main() -> None:
    if "--package-check" in sys.argv:
        package_check()
        return
    root = tk.Tk()
    root.withdraw()
    database = None
    try:
        database = Database(database_path())
        ActivityDeskApp(root, database)
    except Exception as exc:
        details = traceback.format_exc()
        print(details)
        try:
            error_path = database_path().parent / "startup-error.log"
            error_path.write_text(details, encoding="utf-8")
        except Exception:
            pass
        messagebox.showerror(APP_NAME, "The application could not start.\n\n%s" % exc)
        if database is not None:
            database.close()
        root.destroy()
        return
    root.update_idletasks()
    root.deiconify()
    root.lift()
    root.mainloop()
