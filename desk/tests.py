from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from tvs_dms.forms import MODULES

from .models import ActivityRecord, AuditLog, ModuleControl, Profile, SiteSettings
from .store import _get_or_initialize_firebase_app, get_store


@override_settings(
    TVS_SETUP_TOKEN="deployment-token",
    TVS_DATA_KEY="VFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFQ=",
)
class WebWorkflowTests(TestCase):
    setup_values: ClassVar[dict[str, str]] = {
        "school_name": "Test School",
        "display_name": "System Administrator",
        "username": "admin",
        "password": "CorrectHorse77Battery!",
        "confirm_password": "CorrectHorse77Battery!",
        "setup_token": "deployment-token",
    }

    def create_user(self, username: str, role: str, password: str = "TeacherPass123!") -> User:
        user = User.objects.create_user(username=username, password=password)
        Profile.objects.create(
            user=user,
            display_name=username.replace("_", " ").title(),
            role=role,
            must_change_password=False,
        )
        return user

    def test_concurrent_firebase_initialization_creates_one_named_app(self):
        class FakeFirebaseAdmin:
            apps: ClassVar[dict[str, object]] = {}
            initialize_count = 0

            @classmethod
            def get_app(cls, name):
                if name not in cls.apps:
                    raise ValueError("missing")
                return cls.apps[name]

            @classmethod
            def initialize_app(cls, credential, *, name):
                cls.initialize_count += 1
                cls.apps[name] = credential
                return credential

        class FakeCredentials:
            @staticmethod
            def Certificate(service_account):
                return service_account

        service_account = {"project_id": "test-project"}
        with ThreadPoolExecutor(max_workers=8) as executor:
            apps = list(
                executor.map(
                    lambda _: _get_or_initialize_firebase_app(
                        FakeFirebaseAdmin,
                        FakeCredentials,
                        service_account,
                    ),
                    range(16),
                )
            )
        self.assertEqual(1, FakeFirebaseAdmin.initialize_count)
        self.assertTrue(all(app is service_account for app in apps))

    def test_first_run_requires_deployment_token_and_creates_argon2_admin(self):
        self.assertRedirects(self.client.get("/"), reverse("setup"))
        bad = dict(self.setup_values, setup_token="wrong")
        response = self.client.post(reverse("setup"), bad)
        self.assertContains(response, "deployment setup token is incorrect", status_code=200)
        self.assertFalse(User.objects.exists())

        response = self.client.post(reverse("setup"), self.setup_values, follow=True)
        self.assertContains(response, "Dashboard")
        self.assertContains(response, "Assembly Console")
        admin = User.objects.get(username="admin")
        self.assertEqual("argon2", identify_hasher(admin.password).algorithm)
        self.assertEqual("administrator", admin.desk_profile.role)
        self.assertEqual("Test School", SiteSettings.school_name_value())
        self.assertRedirects(self.client.get(reverse("setup")), reverse("dashboard"))

    def test_login_lockout_after_five_failures(self):
        user = self.create_user("teacher", "class_teacher")
        for _ in range(5):
            self.client.post(reverse("login"), {"username": user.username, "password": "wrong"})
        user.desk_profile.refresh_from_db()
        self.assertIsNotNone(user.desk_profile.locked_until)
        response = self.client.post(reverse("login"), {"username": user.username, "password": "TeacherPass123!"})
        self.assertContains(response, "temporarily locked")

    def test_deactivating_user_revokes_their_signed_session(self):
        teacher = self.create_user("teacher", "class_teacher")
        admin = self.create_user("admin", "administrator")
        self.client.post(reverse("login"), {"username": teacher.username, "password": "TeacherPass123!"})
        self.assertEqual(200, self.client.get(reverse("dashboard")).status_code)

        admin_client = Client()
        admin_client.force_login(admin)
        admin_client.post(reverse("toggle_user", args=(teacher.id,)))

        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('dashboard')}")

    def test_role_workflow_encrypts_payload_and_enforces_ownership(self):
        teacher = self.create_user("teacher_one", "class_teacher")
        other = self.create_user("teacher_two", "class_teacher")
        self.client.force_login(teacher)
        response = self.client.post(
            reverse("record_new", args=("no_bag_day",)),
            {
                "event_date": "2026-08-16",
                "event": "Vidya Day",
                "activities": "Sports and reading",
                "outcome": "Students participated",
                "action": "submit",
            },
        )
        self.assertRedirects(response, reverse("records"))
        record = ActivityRecord.objects.get()
        self.assertEqual(ActivityRecord.SUBMITTED, record.status)
        self.assertNotIn(b"Vidya Day", bytes(record.payload_ciphertext))
        self.assertEqual("Vidya Day", record.get_data()["event"])

        self.client.force_login(other)
        response = self.client.get(reverse("record_edit", args=(record.id, record.module_key)))
        self.assertEqual(403, response.status_code)
        self.assertNotContains(self.client.get(reverse("records")), "Vidya Day")

    def test_draft_can_be_incomplete_but_submission_validates_required_fields(self):
        teacher = self.create_user("teacher", "class_teacher")
        self.client.force_login(teacher)
        url = reverse("record_new", args=("sanskrit",))
        draft = self.client.post(url, {"topic": "Grammar", "action": "draft"})
        self.assertRedirects(draft, reverse("records"))
        self.assertEqual(ActivityRecord.DRAFT, ActivityRecord.objects.get().status)
        invalid = self.client.post(url, {"topic": "Grammar", "action": "submit"})
        self.assertContains(invalid, "This field is required.")
        self.assertEqual(1, ActivityRecord.objects.count())

    def test_disabled_form_blocks_teacher_but_not_administrator(self):
        teacher = self.create_user("teacher", "class_teacher")
        ModuleControl.objects.create(module_key="no_bag_day", enabled=False)
        self.client.force_login(teacher)
        response = self.client.get(reverse("record_new", args=("no_bag_day",)), follow=True)
        self.assertContains(response, "disabled by an administrator")

        admin = self.create_user("admin", "administrator")
        self.client.force_login(admin)
        self.assertEqual(200, self.client.get(reverse("record_new", args=("no_bag_day",))).status_code)

    def test_exports_are_role_scoped_and_formula_safe(self):
        teacher = self.create_user("teacher", "class_teacher")
        other = self.create_user("other", "class_teacher")
        for owner, event in ((teacher, "=DANGEROUS"), (other, "Private event")):
            record = ActivityRecord(
                module_key="no_bag_day",
                module_name="No Bag Day",
                role="class_teacher",
                owner=owner,
                status="submitted",
            )
            record.set_data({"event": event})
            record.save()
        self.client.force_login(teacher)
        response = self.client.get(reverse("export_records", args=("csv",)))
        text = response.content.decode("utf-8-sig")
        self.assertIn("'=DANGEROUS", text)
        self.assertNotIn("Private event", text)

    def test_admin_can_manage_users_forms_audit_and_backup_restore(self):
        admin = self.create_user("admin", "administrator", "AdminPassword123!")
        SiteSettings.objects.create(school_name="Backup School")
        self.client.force_login(admin)
        response = self.client.post(
            reverse("users"),
            {
                "username": "office_user",
                "display_name": "Office User",
                "role": "office",
                "password": "OfficePassword123!",
                "confirm_password": "OfficePassword123!",
            },
        )
        self.assertRedirects(response, reverse("users"))
        office = User.objects.get(username="office_user")
        self.assertEqual("office", office.desk_profile.role)
        self.assertTrue(office.desk_profile.must_change_password)
        self.client.post(reverse("form_controls"), {"module_key": "first_aid", "enabled": "false"})
        self.assertFalse(ModuleControl.objects.get(module_key="first_aid").enabled)

        record = ActivityRecord(module_key="first_aid", module_name="First Aid", role="office", owner=office, status="draft")
        record.set_data({"incident": "Minor injury"})
        record.save()
        backup_response = self.client.post(reverse("backup_download"))
        self.assertEqual("application/octet-stream", backup_response["Content-Type"])
        with tempfile.TemporaryDirectory() as temporary:
            backup_path = Path(temporary) / "backup.tvsbackup"
            backup_path.write_bytes(backup_response.content)
            call_command("restore_tvs_backup", str(backup_path), replace=True, verbosity=0)
        self.assertEqual("Backup School", SiteSettings.school_name_value())
        self.assertEqual("Minor injury", ActivityRecord.objects.get().get_data()["incident"])
        self.assertTrue(User.objects.get(username="office_user").check_password("OfficePassword123!"))
        self.assertTrue(AuditLog.objects.filter(action="backup_restored").exists())

    def test_invalid_replace_backup_is_rejected_before_existing_data_is_deleted(self):
        existing = self.create_user("existing_admin", "administrator")
        invalid_payload = {
            "school_name": "Broken Backup",
            "users": [
                {
                    "username": "restored_admin",
                    "display_name": "Restored Admin",
                    "role": "administrator",
                    "password_hash": "not-a-password-hash",
                }
            ],
            "module_controls": [],
            "records": [],
        }
        with self.assertRaisesRegex(ValueError, "unsupported password hash"):
            get_store().restore(invalid_payload, replace=True)
        self.assertTrue(User.objects.filter(pk=existing.pk).exists())

    def test_health_and_all_requested_modules(self):
        self.assertEqual(58, len(MODULES))
        response = self.client.get(reverse("health"))
        self.assertJSONEqual(response.content, {"ok": True, "service": "tvs-activity-desk"})
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertIn("camera=()", response["Permissions-Policy"])

    def test_vercel_preview_is_closed_by_default(self):
        with patch.dict("os.environ", {"VERCEL_ENV": "preview"}):
            response = self.client.get(reverse("health"))
        self.assertEqual(404, response.status_code)
        self.assertContains(response, "Preview deployment disabled", status_code=404)

    def test_state_changing_views_enforce_csrf(self):
        admin = self.create_user("admin", "administrator")
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(admin)
        response = csrf_client.post(reverse("form_controls"), {"module_key": "first_aid", "enabled": "false"})
        self.assertEqual(403, response.status_code)
        self.assertFalse(ModuleControl.objects.filter(module_key="first_aid").exists())

    def test_all_administrator_pages_render_and_xlsx_downloads(self):
        admin = self.create_user("admin", "administrator")
        SiteSettings.objects.create(school_name="Render Test School")
        target = self.create_user("target", "office")
        self.client.force_login(admin)
        for url in (
            reverse("dashboard"),
            reverse("records"),
            reverse("reports"),
            reverse("users"),
            reverse("reset_password", args=(target.id,)),
            reverse("form_controls"),
            reverse("audit_log"),
            reverse("backup"),
            reverse("change_password"),
        ):
            with self.subTest(url=url):
                self.assertEqual(200, self.client.get(url).status_code)
        xlsx = self.client.get(reverse("export_records", args=("xlsx",)))
        self.assertEqual(200, xlsx.status_code)
        self.assertTrue(xlsx.content.startswith(b"PK"))

    def test_temporary_password_must_be_changed(self):
        admin = self.create_user("admin", "administrator")
        self.client.force_login(admin)
        self.client.post(
            reverse("users"),
            {
                "username": "new_teacher",
                "display_name": "New Teacher",
                "role": "class_teacher",
                "password": "TemporaryPass123!",
                "confirm_password": "TemporaryPass123!",
            },
        )
        self.client.logout()
        self.client.post(reverse("login"), {"username": "new_teacher", "password": "TemporaryPass123!"})
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("change_password"))
        response = self.client.post(
            reverse("change_password"),
            {
                "old_password": "TemporaryPass123!",
                "new_password1": "PrivateReplacement456!",
                "new_password2": "PrivateReplacement456!",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(User.objects.get(username="new_teacher").desk_profile.must_change_password)
