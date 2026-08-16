# TVS Activity Desk

TVS Activity Desk is a secure, responsive Django website for school activity
records. It keeps the original role-specific workflows while allowing teachers
to use it from any current browser without installing software.

## Included

- 58 forms across Class Teacher, Catalyst Member, Office and Academic Supervisor
- one-time, token-protected master administrator setup
- Argon2 password hashing and five-attempt account lockout
- server-side sessions, CSRF protection and role/record ownership enforcement
- AES-256-GCM encryption for every form payload
- drafts, submitted records, editing, search and form availability controls
- user creation, password resets, account activation and audit history
- formula-safe CSV and styled XLSX exports
- encrypted downloadable backups and a tested recovery command
- PostgreSQL production support and SQLite for local development
- responsive layouts for phones, tablets and desktop browsers

## Run the website locally

Python 3.10 or newer is required.

```bash
python -m venv .venv-web
source .venv-web/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000`. For local setup, the default deployment token is
`local-setup`. Local development uses SQLite and a development-only encryption
key. Do not use those defaults on a public server.

Run the complete test suite with:

```bash
python manage.py test desk tests
```

## Deploy to the cloud

Use [DEPLOY.md](DEPLOY.md). It gives a field-by-field Koyeb setup using a free web
service and managed PostgreSQL database, explains every required secret, covers
first-run setup, updates, custom domains, backups, recovery and common failures.

The production service starts through `Procfile`, automatically collects static
files, applies database migrations and launches Gunicorn. `/health/` is the
provider health-check endpoint.

Koyeb's free limits can change. Confirm both the web and database instance show
`$0` in the control panel before deployment.

## Security operations

- Keep `DJANGO_SECRET_KEY`, `TVS_DATA_KEY`, `TVS_SETUP_TOKEN` and `DATABASE_URL`
  only in Koyeb Secrets and the school's password manager.
- Never change `TVS_DATA_KEY` after records exist. Losing it makes encrypted
  records and backups unrecoverable.
- Give every staff member an individual account. Never share the administrator
  login.
- Download an encrypted backup at least weekly and store it outside Koyeb.
- Use only HTTPS in production. The production configuration enforces HTTPS,
  secure cookies, HSTS, frame denial and content-type protection.

## Legacy desktop edition

The Windows 7–10 offline desktop edition remains available for installations
that cannot use the cloud. Its dependencies are in `requirements-desktop.txt`,
and its installer is built by `windows\build_windows.bat`.

```text
py -3.8-32 -m pip install -r requirements-desktop.txt
py -3.8-32 app.py
```

See `windows\BUILDING.md` for the legacy installer release process. The web and
desktop editions use the same 58 form definitions, encryption primitives and
spreadsheet-safety rules, but they keep separate databases.
