# Deploy TVS Activity Desk on Koyeb

This is the production path for the web version. It uses one Koyeb web service
and one Koyeb PostgreSQL database. Teachers use a normal HTTPS website; they do
not install Python or any desktop software.

Koyeb's free offering changes over time. At the time this guide was updated,
accounts could create one free web service and one free PostgreSQL database.
Confirm that the instance selector says **Free / $0** before creating either
resource. A payment method may be requested for account verification. Never
select a `small`, `eco`, or larger paid instance unless the school approves it.

Official references: [Koyeb Django deployment](https://www.koyeb.com/docs/deploy/django),
[Git build and Procfile behavior](https://www.koyeb.com/docs/build-and-deploy/build-from-git),
[managed database limits](https://www.koyeb.com/docs/databases), and
[Koyeb Secrets](https://www.koyeb.com/docs/reference/secrets).

## 1. Put the repository on GitHub

Push the current `main` branch to a private GitHub repository. In Koyeb, sign in
with the GitHub account that can read that repository.

## 2. Generate three secrets

Run these commands on your own computer. Every command prints one different
secret. Save all three in the school's password manager.

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
python -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use the first value for `DJANGO_SECRET_KEY`, the second for `TVS_DATA_KEY`, and
the third for `TVS_SETUP_TOKEN`.

`TVS_DATA_KEY` encrypts every form payload and every downloaded backup. If it is
lost, those records cannot be decrypted. If it is changed after records exist,
the site will still start but existing records will not open. Keep an offline
copy controlled by the school.

## 3. Create the PostgreSQL database

1. In the Koyeb control panel, open **Databases** and choose **Create Database**.
2. Choose PostgreSQL and the **free** instance.
3. Choose the same region you will use for the web service.
4. Name it `tvs-activity-desk-db` and create it.
5. Open its connection details and copy the private/internal connection URL.
   It begins with `postgresql://`.
6. Open **Secrets** in Koyeb and create `TVS_DATABASE_URL` with that complete URL.

Do not paste the connection URL into GitHub, `.env`, screenshots, chat, or this
repository.

## 4. Create the Koyeb secrets

In **Secrets**, create these additional secrets from step 2:

| Koyeb secret name | Value |
| --- | --- |
| `TVS_DJANGO_SECRET` | first generated value |
| `TVS_DATA_KEY` | second generated value |
| `TVS_SETUP_TOKEN` | third generated value |

## 5. Create the web service

1. Choose **Create Web Service** and select **GitHub**.
2. Select this repository and the `main` branch.
3. Select the **Buildpack** builder.
4. Leave the build command and run command blank. Koyeb reads the checked-in
   `Procfile`, which collects static files, applies migrations, and starts
   Gunicorn.
5. Choose the **Free** web instance and the same region as PostgreSQL.
6. Set the exposed port to `8000` with protocol HTTP and route `/`.
7. Set the health check path to `/health/`.
8. Add the environment variables below using Koyeb's bulk editor:

```text
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS={{ KOYEB_PUBLIC_DOMAIN }}
DJANGO_CSRF_TRUSTED_ORIGINS=https://{{ KOYEB_PUBLIC_DOMAIN }}
DJANGO_SECRET_KEY={{ secret.TVS_DJANGO_SECRET }}
TVS_DATA_KEY={{ secret.TVS_DATA_KEY }}
TVS_SETUP_TOKEN={{ secret.TVS_SETUP_TOKEN }}
DATABASE_URL={{ secret.TVS_DATABASE_URL }}
DJANGO_TIME_ZONE=Asia/Kolkata
```

9. Click **Deploy**. The first build can take several minutes. A successful log
   ends with Gunicorn listening on port 8000. The health check returns:

```json
{"ok": true, "service": "tvs-activity-desk"}
```

## 6. Complete the one-time school setup

1. Open the `.koyeb.app` address shown for the service.
2. The site redirects to `/setup/` because the database is empty.
3. Enter the school name and administrator details.
4. Use a unique master password with at least ten characters, uppercase,
   lowercase and a number.
5. Enter the `TVS_SETUP_TOKEN` value from the password manager.
6. Create the workspace. The setup page permanently closes after the first
   account is created.
7. Open **Users** and create a separate account for each staff member.

Do not share the master administrator account with teachers.

## Updating the website

Push tested changes to the connected branch. Koyeb builds and deploys them
automatically. Database migrations run before each Gunicorn start. Check the
deployment log and `/health/` after every release.

## Backups and recovery

At least weekly, an administrator should open **Backup**, download the
`.tvsbackup` file, and copy it to a separate access-controlled drive. The file is
encrypted, but it still needs to be protected. Keep `TVS_DATA_KEY` separately.

To restore into a new, empty deployment:

1. Configure the new service with the exact same `TVS_DATA_KEY`.
2. Upload the backup temporarily through a Koyeb shell or another secure method.
3. Run `python manage.py restore_tvs_backup /path/to/file.tvsbackup`.
4. Delete the uploaded backup after the command succeeds.

The restore command refuses to touch a non-empty database. `--replace` exists
for disaster recovery, but it deletes all existing Activity Desk data first.
Download a fresh backup and verify its key fingerprint before using it.

## Custom domain

Add the domain in Koyeb, then update the web service variables:

```text
DJANGO_ALLOWED_HOSTS=activity.example.edu
DJANGO_CSRF_TRUSTED_ORIGINS=https://activity.example.edu
```

Koyeb manages HTTPS after DNS verification. Do not disable HTTPS redirect or
cookie security in production.

## Common failures

- **Build succeeds, service restarts:** inspect runtime logs. A missing secret is
  reported by name before Django starts.
- **Bad Request (400):** `DJANGO_ALLOWED_HOSTS` does not match the public domain.
- **CSRF verification failed:** add the exact HTTPS origin, without a trailing
  slash, to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **Records cannot be decrypted:** the deployed `TVS_DATA_KEY` differs from the
  key used when the records were created. Restore the original secret; do not
  create a new key.
- **Missing `DATABASE_URL`:** the service intentionally refuses to start instead
  of silently storing production data in an ephemeral SQLite file. Verify that
  the `TVS_DATABASE_URL` secret is attached exactly as shown above.
- **Database connection error:** verify that `DATABASE_URL` contains the full
  PostgreSQL URL and that both services are in the same region.
- **Slow first page:** free services may sleep when idle. Wait for the first
  request, then refresh once. Data remains in PostgreSQL.
- **Free allowance warning:** stop and confirm both instance types show `$0`
  before accepting any change. Free services have no production SLA.

## Local production check

Before deployment, run:

```bash
python -m venv .venv-web
source .venv-web/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py test
python manage.py check --deploy
python manage.py runserver
```

For local development without environment variables, Django uses a local SQLite
database and development-only keys. Never copy that database to production.
