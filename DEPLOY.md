# Deploy TVS Activity Desk with Vercel and Firebase

This is the no-cost cloud path for the school website:

- Vercel runs the Django application and serves static files over HTTPS.
- Firebase Cloud Firestore stores accounts, form controls, encrypted records,
  and audit history.
- Teachers only open the website. They install nothing.

Firebase's Spark plan needs no payment method. Its current free Firestore quota
is 1 GiB stored data, 50,000 document reads per day, 20,000 writes per day, and
20,000 deletes per day. Vercel's Hobby plan is free but its terms limit it to
personal/non-commercial use; confirm that the school's use qualifies. Neither
free plan has a production SLA, so download the encrypted app backup weekly.

Official references: [Vercel's zero-configuration Django support](https://vercel.com/changelog/zero-configuration-django-support),
[Vercel Hobby plan](https://vercel.com/docs/plans/hobby),
[Firebase Spark plan](https://firebase.google.com/docs/projects/billing/firebase-pricing-plans),
[Firestore free quota](https://firebase.google.com/docs/firestore/quotas), and
[Firebase Admin SDK setup](https://firebase.google.com/docs/admin/setup).

## 1. Create the free Firebase database

1. Open [console.firebase.google.com](https://console.firebase.google.com) and
   choose **Create a project**.
2. Name it `tvs-activity-desk`. Google Analytics is not needed for this app and
   can remain disabled.
3. Keep the project on the **Spark / No-cost** plan. Do not link a billing
   account.
4. Open **Build → Firestore Database → Create database**.
5. Choose the standard/native Firestore database, select **Production mode**,
   and choose the closest available region. The database region cannot be
   changed later.
6. Open the Firestore **Rules** tab. Replace its contents with the checked-in
   [`firestore.rules`](firestore.rules) file and click **Publish**. These rules
   deny all browser access; only the Django server's service account can read or
   write data.

Do not enable Realtime Database, Firebase Hosting, Cloud Functions, or Firebase
Authentication. This application only needs Firestore.

## 2. Download one Firebase service-account key

1. In Firebase, open **Project settings → Service accounts**.
2. Select **Firebase Admin SDK → Generate new private key** and confirm.
3. Keep the downloaded JSON file private. It grants server access to the
   database. Never commit it, upload it to GitHub, email it, or paste it into
   chat.

The key is used only as an encrypted Vercel environment variable. If it is ever
exposed, delete that key in Google Cloud IAM immediately and generate a new one.

## 3. Generate the complete Vercel environment block

From this repository, run the helper with the downloaded JSON path:

```bash
python tools/prepare_vercel_env.py /path/to/firebase-service-account.json
```

On Windows, use `py` instead of `python` if needed. The helper validates the
Firebase key, creates three independent random secrets, and prints these six
ready-to-paste lines:

```text
DJANGO_SECRET_KEY=...
TVS_DATA_KEY=...
TVS_SETUP_TOKEN=...
DJANGO_DEBUG=false
DJANGO_TIME_ZONE=Asia/Kolkata
FIREBASE_SERVICE_ACCOUNT_JSON={...}
```

Save the complete output in the school's password manager before continuing.
`TVS_DATA_KEY` encrypts every form payload and downloaded backup. Losing or
changing it makes existing records unreadable, so keep a second offline copy
controlled by the school.

## 4. Import the GitHub repository into Vercel

1. Open [vercel.com/new](https://vercel.com/new), sign in with GitHub, and
   import the `schlmgmt` repository.
2. Leave **Root Directory** at the repository root. Vercel detects `manage.py`
   and configures Django automatically; do not add a build command, output
   directory, or start command.
3. Before clicking **Deploy**, expand **Environment Variables**.
4. Add each of the six names and values printed in step 3. Apply them to
   **Production**, **Preview**, and **Development** so every build can validate
   Django's production configuration.
5. Click **Deploy**.

Preview deployments deliberately return `404 Preview deployment disabled for
school data safety.` They inherit the secrets so builds succeed, but the guard
prevents preview URLs from using the live school database. Production remains
fully available.

The first build installs Python 3.12 dependencies and collects Django static
files. No SQL migration or persistent filesystem is needed. A successful
production URL ends in `.vercel.app`.

## 5. Verify the deployment and create the workspace

1. Open `https://your-project.vercel.app/health/`. It should return:

```json
{"ok": true, "service": "tvs-activity-desk"}
```

2. Open the production URL. An empty Firestore database redirects to `/setup/`.
3. Enter the school name and administrator details.
4. Use a unique master password with at least ten characters, uppercase,
   lowercase, and a number.
5. Enter the saved `TVS_SETUP_TOKEN` value.
6. Create the workspace. The setup page permanently closes after the first
   administrator is created.
7. Open **Users** and create a separate account for each staff member.

Do not share the master administrator account. Passwords are Argon2-hashed,
login attempts lock after five failures, disabled users' signed sessions are
revoked, and activity payloads are AES-256-GCM encrypted before Firestore sees
them.

## Updating the website

Push tested changes to `main`. Vercel builds and deploys them automatically.
After every release, check the production deployment log and `/health/`.

Do not enable preview access against the production Firebase project. If a
developer needs a working preview, create a separate Firebase project and use
its service-account key for Preview only before setting
`TVS_ALLOW_VERCEL_PREVIEW=true` in the Preview environment.

## Backups and recovery

Firestore's managed backup/restore features are not included in its free quota.
At least weekly, an administrator should open **Backup**, download the encrypted
`.tvsbackup` file, and copy it to a separate access-controlled drive. Keep
`TVS_DATA_KEY` separately.

To restore into an empty Firebase project, install the web requirements locally,
set the same six environment variables from the password manager, and run:

```bash
python manage.py restore_tvs_backup /path/to/file.tvsbackup
```

The restore command detects Firebase automatically when `DJANGO_DEBUG=false`.
It refuses to touch a non-empty database. `--replace` exists for disaster
recovery, but deletes the existing Activity Desk collections first. Download a
fresh backup and verify its key fingerprint before using it.

## Custom domain

Add the domain from the Vercel project's **Settings → Domains** page. Then add
these production environment variables and redeploy:

```text
DJANGO_ALLOWED_HOSTS=.vercel.app,activity.example.edu
DJANGO_CSRF_TRUSTED_ORIGINS=https://activity.example.edu
```

Replace `activity.example.edu` with the exact hostname. Do not include a path or
trailing slash. Vercel issues and renews HTTPS certificates automatically.

## Common failures

- **Vercel reports Ready but every URL is a platform 404:** inspect the build
  duration. If it finished almost instantly and did not install Python, open
  **Project Settings → Build and Deployment** and set **Framework Preset** to
  **Django**, then redeploy. From an authenticated CLI, the equivalent command
  is `vercel project update tvs-activity-desk --framework django`.
- **Build reports a missing variable:** confirm all six variables from step 3
  exist in Vercel and are enabled for the environment being built.
- **Firebase JSON is invalid:** rerun `tools/prepare_vercel_env.py` using the
  original downloaded JSON and replace the complete Vercel value. Do not remove
  quotes or backslash characters inside the JSON.
- **Permission denied from Firestore:** confirm the service-account key belongs
  to the same Firebase project as the Firestore database and has not been
  revoked.
- **Bad Request (400):** remove a stale `DJANGO_ALLOWED_HOSTS` override, or add
  the exact Vercel/custom hostname to it.
- **CSRF verification failed:** add the exact HTTPS origin, without a trailing
  slash, to `DJANGO_CSRF_TRUSTED_ORIGINS`.
- **Records cannot be decrypted:** restore the original `TVS_DATA_KEY`; never
  create a replacement key for an existing database.
- **Firebase quota exceeded:** Firestore stops the affected operation on Spark
  rather than charging a card. Check **Firestore → Usage** and wait for the
  quota reset, or move to an approved paid plan.
- **Preview URL shows a 404:** this is intentional. Use the production URL.

## Local development

Local development continues to use SQLite so no developer needs Firebase:

```bash
python -m venv .venv-web
source .venv-web/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

The local setup token is `local-setup`. Never deploy with local defaults. Run
the full test suite with `python manage.py test desk tests`.
