# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TVS Activity Desk: a Django web app for school activity records (59 role-scoped
forms, encrypted payloads, audit trail, CSV/XLSX export, encrypted backups).
A legacy Windows 7–10 offline Tkinter desktop edition lives alongside it in the
same repo and shares the form definitions and crypto primitives.

## Commands

```bash
# web dev (Python 3.12; .venv-web is the checked-out venv)
source .venv-web/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver          # http://127.0.0.1:8000, setup token "local-setup"

# full test suite (what CI runs)
python manage.py test desk tests

# one test class / one test
python manage.py test desk.tests.WebWorkflowTests
python manage.py test desk.tests.WebWorkflowTests.test_login_lockout_after_five_failures

# the pure-unittest portion needs no Django
python -m unittest discover -s tests

# checks CI runs before tests
python manage.py makemigrations --check --dry-run
python manage.py check --deploy
python manage.py collectstatic --noinput

# disaster recovery (auto-detects Firebase when DJANGO_DEBUG=false)
python manage.py restore_tvs_backup /path/to/file.tvsbackup [--replace]

# generate the six Vercel env vars from a Firebase service-account key
python tools/prepare_vercel_env.py /path/to/firebase-service-account.json

# legacy desktop edition (32-bit Python 3.8 on Windows)
py -3.8-32 -m pip install -r requirements-desktop.txt
py -3.8-32 app.py
windows\build_windows.bat           # builds TVS-Activity-Desk-Setup.exe
```

## Architecture

### Two data backends behind one interface

The single most important structural fact: **views never touch the ORM or
Firestore directly.** Everything goes through `get_store()` in
[desk/store.py](desk/store.py), an `lru_cache`d factory returning one of:

- `DjangoStore` — Django ORM over SQLite. Used for local dev and **all tests**.
- `FirestoreStore` — Firebase Admin SDK. Used in production (Vercel is
  stateless, so there is no SQL database there).

Selection is `settings.TVS_USE_FIREBASE`: true when
`FIREBASE_SERVICE_ACCOUNT_JSON` is set and (`DEBUG` is false **or**
`TVS_USE_FIREBASE=true` is forced). CI sets a dummy Firebase JSON but runs tests
with `DJANGO_DEBUG=true`, so tests stay on SQLite.

The two stores return **different object types** with a deliberately identical
surface:

| Concern | DjangoStore | FirestoreStore |
|---|---|---|
| user | `django.contrib.auth.models.User` + `Profile` | `UserData` + `ProfileData` ([desk/domain.py](desk/domain.py)) |
| record | `ActivityRecord` model | `RecordData` dataclass |
| audit | `AuditLog` model | `AuditData` dataclass |

`desk/domain.py` dataclasses re-implement just enough of the Django API
(`.pk`, `.is_authenticated`, `.check_password()`, `.desk_profile`,
`.get_role_display()`, `.set_data()`/`.get_data()`) that view and template code
is backend-agnostic. **When adding a store method, implement it on both classes
and keep the returned shape identical**, including the id being a `str` on both
sides — view code compares with `str(record.owner_id) == str(user.id)` for
exactly this reason.

### Authentication is custom, not `django.contrib.auth`'s

`django.contrib.auth` middleware is *not* installed. Instead
[desk/middleware.py](desk/middleware.py) has:

- `VercelPreviewGuardMiddleware` — 404s every preview deployment unless
  `TVS_ALLOW_VERCEL_PREVIEW=true`, so preview URLs can't reach live school data.
- `ActivityDeskAuthenticationMiddleware` — resolves `request.user` from
  `session["tvs_user_id"]` via the store, and flushes the session when the
  stored `session_version` no longer matches the profile's. Bumping
  `session_version` is how deactivating a user revokes their already-issued
  signed-cookie session. `_auth_user_id` is honoured as a legacy path.
- `ActivityDeskSecurityMiddleware` — forces `must_change_password` users to
  `/account/password/`, and sets CSP/Permissions-Policy on every response.

Sessions are `signed_cookies` (no server-side session store on Vercel), so
session contents are signed but readable; never put secrets in them.

Django's `@login_required` works because `request.user` quacks correctly.
Role checks use `role_of(user)` and `@admin_required` in
[desk/views.py](desk/views.py).

### Encryption

Two layers, both AES-256-GCM via `tvs_dms/security.py`:

- **Record payloads.** Every form submission is JSON-serialized and encrypted
  with the record's UUID as GCM associated data, then stored as
  nonce/ciphertext/tag. The key comes from `TVS_DATA_KEY`
  (URL-safe base64, must decode to exactly 32 bytes). In `DEBUG` with no key
  set, [desk/crypto.py](desk/crypto.py) derives a development-only key from
  `SECRET_KEY` via HMAC — never usable in production.
- **Backups.** Downloaded `.tvsbackup` files are encrypted with the same data
  key and carry a `key_fingerprint()`.

`TVS_DATA_KEY` is unrotatable: changing it makes existing records and backups
permanently unreadable. Anything touching key derivation or the associated-data
binding needs the same care.

The desktop edition instead derives its key from the user's password
(PBKDF2, 600k iterations) in `tvs_dms/security.py` — same primitives, different
key management.

### Form definitions

All 59 forms are declared once, as data, in
[tvs_dms/forms.py](tvs_dms/forms.py): `_MODULE_SPECS` maps role →
`(key, name, fields)` tuples, built with the `f()`, `activity_fields()`, and
`simple_activity()` helpers. Module counts are asserted in tests
(class_teacher 5, catalyst_member 14, office 8, academic_supervisor 32, 59
total) — adding or removing a form means updating
[tests/test_core.py](tests/test_core.py) and [desk/tests.py](desk/tests.py).

`f()` is positional (`key, label, kind, required, choices, hint`), so passing a
choices tuple where `required` belongs yields a required field with no options —
`test_field_definitions_are_well_formed` guards this.

Five of the modules (`dayboarding`, `exam_details`, `stationary`, `field_trip`,
`assembly_console`) implement the hubs specified in `DMS - IMPACT.pptx`; their
field lists come from the deck and are pinned by
`test_impact_deck_fields_exist_on_their_hubs`. See METHODOLOGY.md §6a before
changing them.

`desk/forms.py` translates a `Field` into a Django form field
(`_web_field`), with the key rule that **drafts skip required-field validation
while submissions enforce it**. The desktop edition renders the same specs
through Tkinter in `tvs_dms/ui.py`.

Administrators can disable individual modules (`ModuleControl` /
`module_states()`); disabled modules are hidden from teachers but stay usable by
administrators.

### Shared package `tvs_dms/`

Used by both editions. `forms.py` (module specs), `security.py` (crypto),
`exporter.py` (formula-safe CSV/XLSX — leading `=`, `+`, `-`, `@` are escaped;
keep that behaviour, it's tested). `app.py`, `ui.py`, `database.py`, `config.py`
are desktop-only (Tkinter + local SQLite in the OS app-data dir).

## Deployment notes

Vercel zero-config Django: it detects `manage.py` — do not add a build command,
output directory, or start command. If a deploy finishes instantly and 404s, the
framework preset was lost; re-set it to Django
(`vercel project update <project> --framework django`). Full runbook, including
every env var and its failure modes, is in [DEPLOY.md](DEPLOY.md).

Required production env vars: `DJANGO_SECRET_KEY`, `TVS_DATA_KEY`,
`TVS_SETUP_TOKEN`, `FIREBASE_SERVICE_ACCOUNT_JSON`, `DJANGO_DEBUG=false`,
`DJANGO_TIME_ZONE`. [tvs_web/settings.py](tvs_web/settings.py) raises
`ImproperlyConfigured` at import when any are missing with `DEBUG=false`, so a
misconfigured build fails loudly rather than serving insecurely.

Firestore rules ([firestore.rules](firestore.rules)) deny all client access —
only the server's service account reads or writes.

## Conventions

- `from __future__ import annotations` at the top of every module; modern
  builtin generics in annotations.
- The `desk` Django app is web-only; `tvs_dms` must stay importable without
  Django (`tests/test_core.py` and the desktop build depend on that).
- Migrations exist for the SQLite/dev path; `makemigrations --check` runs in CI,
  so model changes need a migration even though production uses Firestore.
- `/health/` pings the active store (`get_store().health()`) before returning
  its fixed JSON body, so a broken Firestore connection surfaces as a 500. It is
  exempt from the password-change redirect.
