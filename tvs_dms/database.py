from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .security import (
    decrypt_json,
    encrypt_json,
    hash_password,
    unwrap_data_key,
    verify_password,
    wrap_data_key,
)
from .forms import MODULES, ROLE_LABELS


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


@dataclass
class Session:
    user_id: int
    username: str
    display_name: str
    role: str
    data_key: bytes


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA secure_delete=ON")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                wrap_nonce BLOB NOT NULL,
                wrapped_key BLOB NOT NULL,
                wrap_tag BLOB NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                module_key TEXT NOT NULL,
                module_name TEXT NOT NULL,
                role TEXT NOT NULL,
                owner_id INTEGER NOT NULL REFERENCES users(id),
                status TEXT NOT NULL CHECK(status IN ('draft','submitted')),
                event_date TEXT,
                payload_nonce BLOB NOT NULL,
                payload BLOB NOT NULL,
                payload_tag BLOB NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_module ON records(module_key);
            CREATE INDEX IF NOT EXISTS idx_records_owner ON records(owner_id);
            CREATE INDEX IF NOT EXISTS idx_records_event_date ON records(event_date);
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                action TEXT NOT NULL,
                target TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS module_controls (
                module_key TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def is_initialized(self) -> bool:
        row = self.conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return bool(row["count"])

    def school_name(self) -> str:
        row = self.conn.execute("SELECT value FROM settings WHERE key='school_name'").fetchone()
        return row["value"] if row else "School Activity Management"

    @staticmethod
    def validate_password(password: str) -> Optional[str]:
        if len(password) < 10:
            return "Use at least 10 characters."
        if not any(c.isupper() for c in password):
            return "Include at least one uppercase letter."
        if not any(c.islower() for c in password):
            return "Include at least one lowercase letter."
        if not any(c.isdigit() for c in password):
            return "Include at least one number."
        return None

    def create_master(self, school_name: str, display_name: str, password: str) -> Session:
        if self.is_initialized():
            raise ValueError("Setup has already been completed.")
        error = self.validate_password(password)
        if error:
            raise ValueError(error)
        if not school_name.strip() or not display_name.strip():
            raise ValueError("School name and administrator display name are required.")
        data_key = os.urandom(32)
        salt, digest = hash_password(password)
        nonce, wrapped, tag = wrap_data_key(data_key, password, salt)
        timestamp = now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """INSERT INTO users
                (username, display_name, role, password_salt, password_hash,
                 wrap_nonce, wrapped_key, wrap_tag, created_at, updated_at)
                VALUES (?, ?, 'administrator', ?, ?, ?, ?, ?, ?, ?)""",
                ("admin", display_name.strip(), salt, digest, nonce, wrapped, tag, timestamp, timestamp),
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO settings(key,value) VALUES('school_name',?)",
                (school_name.strip(),),
            )
            self.conn.execute(
                "INSERT INTO audit_log(user_id,action,target,created_at) VALUES(?,?,?,?)",
                (cursor.lastrowid, "system_setup", "local_database", timestamp),
            )
        return Session(cursor.lastrowid, "admin", display_name.strip(), "administrator", data_key)

    def authenticate(self, username: str, password: str) -> Session:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE", (username.strip(),)
        ).fetchone()
        generic = ValueError("Invalid username or password.")
        if not row or not row["active"]:
            raise generic
        if row["locked_until"]:
            locked_until = datetime.fromisoformat(row["locked_until"])
            if datetime.now() < locked_until:
                seconds = max(1, int((locked_until - datetime.now()).total_seconds()))
                raise ValueError("Account temporarily locked. Try again in %d seconds." % seconds)
        if not verify_password(password, row["password_salt"], row["password_hash"]):
            attempts = row["failed_attempts"] + 1
            locked_until = None
            if attempts >= 5:
                locked_until = (datetime.now() + timedelta(seconds=30)).replace(microsecond=0).isoformat()
                attempts = 0
            with self.conn:
                self.conn.execute(
                    "UPDATE users SET failed_attempts=?, locked_until=? WHERE id=?",
                    (attempts, locked_until, row["id"]),
                )
            raise generic
        data_key = unwrap_data_key(
            row["wrap_nonce"], row["wrapped_key"], row["wrap_tag"], password, row["password_salt"]
        )
        with self.conn:
            self.conn.execute(
                "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE id=?", (row["id"],)
            )
            self._audit(row["id"], "login", row["username"])
        return Session(row["id"], row["username"], row["display_name"], row["role"], data_key)

    def _audit(self, user_id: Optional[int], action: str, target: str = "") -> None:
        self.conn.execute(
            "INSERT INTO audit_log(user_id,action,target,created_at) VALUES(?,?,?,?)",
            (user_id, action, target, now_iso()),
        )

    def create_user(
        self, actor: Session, username: str, display_name: str, role: str, password: str
    ) -> int:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        username = username.strip()
        if not username or not display_name.strip():
            raise ValueError("Username and display name are required.")
        if role not in ROLE_LABELS:
            raise ValueError("Invalid role.")
        error = self.validate_password(password)
        if error:
            raise ValueError(error)
        salt, digest = hash_password(password)
        nonce, wrapped, tag = wrap_data_key(actor.data_key, password, salt)
        timestamp = now_iso()
        try:
            with self.conn:
                cursor = self.conn.execute(
                    """INSERT INTO users
                    (username,display_name,role,password_salt,password_hash,wrap_nonce,wrapped_key,wrap_tag,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (username, display_name.strip(), role, salt, digest, nonce, wrapped, tag, timestamp, timestamp),
                )
                self._audit(actor.user_id, "user_created", username)
            return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ValueError("That username already exists.") from exc

    def list_users(self, actor: Session) -> List[sqlite3.Row]:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        return list(self.conn.execute(
            "SELECT id,username,display_name,role,active,created_at FROM users ORDER BY display_name"
        ))

    def reset_password(self, actor: Session, user_id: int, new_password: str) -> None:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        error = self.validate_password(new_password)
        if error:
            raise ValueError(error)
        row = self.conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise ValueError("User not found.")
        salt, digest = hash_password(new_password)
        nonce, wrapped, tag = wrap_data_key(actor.data_key, new_password, salt)
        with self.conn:
            self.conn.execute(
                """UPDATE users SET password_salt=?,password_hash=?,wrap_nonce=?,wrapped_key=?,wrap_tag=?,
                failed_attempts=0,locked_until=NULL,updated_at=? WHERE id=?""",
                (salt, digest, nonce, wrapped, tag, now_iso(), user_id),
            )
            self._audit(actor.user_id, "password_reset", row["username"])

    def set_user_active(self, actor: Session, user_id: int, active: bool) -> None:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        if user_id == actor.user_id and not active:
            raise ValueError("You cannot deactivate your own account.")
        row = self.conn.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if not row:
            raise ValueError("User not found.")
        with self.conn:
            self.conn.execute(
                "UPDATE users SET active=?,updated_at=? WHERE id=?", (int(active), now_iso(), user_id)
            )
            self._audit(actor.user_id, "user_activated" if active else "user_deactivated", row["username"])

    def module_is_enabled(self, module_key: str) -> bool:
        row = self.conn.execute(
            "SELECT enabled FROM module_controls WHERE module_key=?", (module_key,)
        ).fetchone()
        return True if row is None else bool(row["enabled"])

    def set_module_enabled(self, actor: Session, module_key: str, enabled: bool) -> None:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        if module_key not in MODULES:
            raise ValueError("Unknown form.")
        with self.conn:
            self.conn.execute(
                """INSERT OR REPLACE INTO module_controls(module_key,enabled,updated_at)
                VALUES(?,?,?)""", (module_key, int(enabled), now_iso())
            )
            self._audit(actor.user_id, "form_enabled" if enabled else "form_disabled", module_key)

    def save_record(
        self,
        session: Session,
        module_key: str,
        module_name: str,
        module_role: str,
        status: str,
        payload: Dict[str, Any],
        record_id: Optional[str] = None,
    ) -> str:
        if status not in ("draft", "submitted"):
            raise ValueError("Invalid record status.")
        module = MODULES.get(module_key)
        if not module or module.name != module_name or module.role != module_role:
            raise ValueError("Unknown or mismatched form definition.")
        if session.role != "administrator" and session.role != module.role:
            raise PermissionError("This form is not assigned to your role.")
        if session.role != "administrator" and not self.module_is_enabled(module_key):
            raise PermissionError("This form has been disabled by an administrator.")
        timestamp = now_iso()
        if record_id:
            row = self.conn.execute("SELECT owner_id FROM records WHERE id=?", (record_id,)).fetchone()
            if not row:
                raise ValueError("Record not found.")
            if session.role != "administrator" and row["owner_id"] != session.user_id:
                raise PermissionError("You cannot edit another user's record.")
        else:
            record_id = str(uuid.uuid4())
        nonce, encrypted, tag = encrypt_json(payload, session.data_key, record_id)
        event_date = str(payload.get("event_date", ""))
        with self.conn:
            if self.conn.execute("SELECT 1 FROM records WHERE id=?", (record_id,)).fetchone():
                self.conn.execute(
                    """UPDATE records SET status=?,event_date=?,payload_nonce=?,payload=?,payload_tag=?,updated_at=?
                    WHERE id=?""",
                    (status, event_date, nonce, encrypted, tag, timestamp, record_id),
                )
                action = "record_updated"
            else:
                self.conn.execute(
                    """INSERT INTO records
                    (id,module_key,module_name,role,owner_id,status,event_date,payload_nonce,payload,payload_tag,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (record_id, module_key, module_name, module_role, session.user_id, status, event_date, nonce, encrypted, tag, timestamp, timestamp),
                )
                action = "record_created"
            self._audit(session.user_id, action, "%s:%s" % (module_key, record_id))
        return record_id

    def list_records(
        self,
        session: Session,
        module_key: str = "",
        status: str = "",
        search: str = "",
        include_all: bool = False,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if not (session.role == "administrator" and include_all):
            if session.role == "administrator":
                pass
            else:
                clauses.append("r.owner_id=?")
                params.append(session.user_id)
        if module_key:
            clauses.append("r.module_key=?")
            params.append(module_key)
        if status:
            clauses.append("r.status=?")
            params.append(status)
        if search:
            clauses.append("(r.module_name LIKE ? OR u.display_name LIKE ? OR r.event_date LIKE ?)")
            term = "%%%s%%" % search
            params.extend((term, term, term))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            """SELECT r.*,u.display_name AS owner_name,u.username AS owner_username
            FROM records r JOIN users u ON u.id=r.owner_id""" + where + " ORDER BY r.updated_at DESC",
            params,
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["data"] = decrypt_json(
                row["payload_nonce"], row["payload"], row["payload_tag"], session.data_key, row["id"]
            )
            result.append(item)
        return result

    def get_record(self, session: Session, record_id: str) -> Dict[str, Any]:
        row = self.conn.execute(
            """SELECT r.*,u.display_name AS owner_name FROM records r
            JOIN users u ON u.id=r.owner_id WHERE r.id=?""", (record_id,)
        ).fetchone()
        if not row:
            raise ValueError("Record not found.")
        if session.role != "administrator" and row["owner_id"] != session.user_id:
            raise PermissionError("You cannot open another user's record.")
        item = dict(row)
        item["data"] = decrypt_json(
            row["payload_nonce"], row["payload"], row["payload_tag"], session.data_key, row["id"]
        )
        return item

    def dashboard_counts(self, session: Session) -> Dict[str, int]:
        where = "" if session.role == "administrator" else " WHERE owner_id=?"
        params: Tuple[Any, ...] = () if session.role == "administrator" else (session.user_id,)
        rows = self.conn.execute(
            "SELECT status,COUNT(*) AS count FROM records" + where + " GROUP BY status", params
        ).fetchall()
        values = {"draft": 0, "submitted": 0}
        values.update({row["status"]: row["count"] for row in rows})
        values["total"] = values["draft"] + values["submitted"]
        return values

    def backup_to(self, actor: Session, destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(destination))
        try:
            self.conn.backup(target)
        finally:
            target.close()
        with self.conn:
            self._audit(actor.user_id, "backup_created", destination.name)
        return destination

    def recent_audit(self, actor: Session, limit: int = 100) -> List[sqlite3.Row]:
        if actor.role != "administrator":
            raise PermissionError("Administrator access is required.")
        return list(self.conn.execute(
            """SELECT a.created_at,COALESCE(u.display_name,'System') AS user_name,a.action,a.target
            FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?""",
            (limit,),
        ))
