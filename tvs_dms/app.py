from __future__ import annotations

import tkinter as tk
import traceback
from tkinter import messagebox

from .config import APP_NAME, database_path
from .database import Database
from .ui import ActivityDeskApp


def main() -> None:
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

