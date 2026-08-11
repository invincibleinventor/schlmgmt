# TVS Activity Desk

TVS Activity Desk is a single-computer, offline-first desktop application for school activity records. It replaces the defunct mobile DMS shown in the supplied screenshots while retaining its role-based forms, draft/submission workflow, user administration and reporting.

## What is included

- 58 role-specific forms: Class Teacher (5), Catalyst Member (14), Office (7), and Academic Supervisor (32)
- first-run master-password setup
- local role-based accounts with temporary lockout after repeated failures
- PBKDF2-HMAC-SHA256 password protection (600,000 iterations)
- AES-256-GCM authenticated encryption for every form payload
- drafts, submitted records, editing, search, and audit history
- CSV and styled XLSX export with spreadsheet-formula injection protection
- encrypted-data backups (`.tvsbackup`)
- a Windows installer definition and pinned legacy-compatible build toolchain

The application never requires an internet connection. Its database is stored under the signed-in Windows user's Local AppData folder, not beside the executable.

## Run from source

```text
python -m pip install -r requirements.txt
python app.py
```

On macOS 27, do not use Apple's bundled `/usr/bin/python3`; its obsolete Tk 8.5 runtime may display an unpainted window. Launch with:

```text
./run_macos.command
```

The first launch opens the secure workspace setup. Enter the school name and create the master password. The initial administrator username is `admin`. The password is intentionally unrecoverable; keep it in the school's approved password manager.

## Windows 7 installer build

Build on a Windows machine matching the target architecture:

1. Install **Python 3.8.10** (the final Python release supporting Windows 7) and enable the Python launcher.
2. Install Inno Setup 6.
3. Run `windows\build_windows.bat`.
4. Distribute `dist\installer\TVS-Activity-Desk-Setup.exe`.

The installer is per-user and does not require administrator privileges. It supports Windows 7 SP1 and later. On first launch after installation, the in-app setup wizard requires the master password to be created before any data can be entered.

Do not build the Windows 7 package using Python 3.9+ or a newer PyInstaller than the pinned version without separately validating it on Windows 7. For both 32-bit and 64-bit deployments, run the build once with each matching Python 3.8.10 architecture and label the installers accordingly.

## Operating notes

- Administrators can create accounts, assign one of the four operational roles, reset passwords, deactivate accounts, enable/disable individual forms, view all records, view the audit log, export reports and create backups.
- Operational users see only their assigned forms and their own records.
- Drafts may be incomplete. Submission enforces the form's required fields and validates dates/numbers.
- CSV files use UTF-8 with BOM for reliable Excel opening. XLSX is the preferred report format.
- Backups contain encrypted payloads and password-protected key material. Copy backups to a physically separate, access-controlled drive.
- Uninstalling the program deliberately retains the local database in `%LOCALAPPDATA%\TVSActivityDesk` to prevent accidental data loss.

## Tests

```text
python -m unittest discover -v
```

The tests cover encryption integrity, authentication, key re-wrapping during password resets, access control, all requested form counts, database backups, and both export formats.

