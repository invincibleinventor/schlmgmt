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

## Installing on Windows 7-10

Teachers receive one file: `TVS-Activity-Desk-Setup.exe`.

1. Double-click the setup file.
2. Click **Next**. Installation begins immediately with safe defaults.
3. Leave **Launch TVS Activity Desk** selected and click **Finish**.

The installer includes Python and every required library. It installs without an
administrator password, creates desktop and Start Menu shortcuts automatically,
and opens the first-time setup when finished. Windows 7 computers must have
Service Pack 1 and their normal Microsoft updates installed.

The designated school administrator should perform first-time setup and create
individual accounts for teachers. A plain-language Quick Start guide is installed
in the Start Menu.

## Building the Windows installer

Build on a Windows machine or VM:

1. Install **32-bit Python 3.8.10** and enable the Python launcher.
2. Install Inno Setup 6.
3. Double-click `windows\build_windows.bat`.
4. Distribute `dist\installer\TVS-Activity-Desk-Setup.exe`.

The builder runs tests, creates a professional icon, makes a self-contained 32-bit
application that runs on both 32-bit and 64-bit Windows, checks the packaged
database/encryption runtime, builds the installer, and creates a SHA-256 checksum.
See `windows\BUILDING.md` for the release checklist.

Do not build the legacy package with Python 3.9+ or unpinned packaging tools.
Validate every release on clean Windows 7 SP1 and Windows 10 computers.

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
