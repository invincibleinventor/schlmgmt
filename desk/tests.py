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

    def test_admin_cannot_deactivate_their_own_account(self):
        admin = self.create_user("admin", "administrator")
        self.client.force_login(admin)
        self.client.post(reverse("toggle_user", args=(admin.id,)))
        admin.refresh_from_db()
        self.assertTrue(admin.is_active, "an admin who locks themselves out cannot be recovered in-app")

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
        self.assertEqual(59, len(MODULES))
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


DATA_KEY = "VFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFRUVFQ="


class AnalyticsCatalogueTests(TestCase):
    """Structural guarantees of the analyzer engine, independent of stored data."""

    def test_every_module_yields_at_least_fifty_analyses(self):
        from .analytics import catalogue_for

        thin = {
            key: len(catalogue_for(module))
            for key, module in MODULES.items()
            if len(catalogue_for(module)) < 50
        }
        self.assertEqual(thin, {}, f"modules below the 50-analysis floor: {thin}")

    def test_field_definitions_are_well_formed(self):
        """`f()` is positional, so a choices tuple can silently land in `required`."""
        for module_key, module in MODULES.items():
            for field in module.fields:
                self.assertIsInstance(
                    field.required, bool, f"{module_key}.{field.key} has a non-bool required flag"
                )
                if field.kind == "choice":
                    self.assertTrue(
                        field.choices, f"{module_key}.{field.key} is a choice field with no choices"
                    )

    def test_impact_deck_fields_exist_on_their_hubs(self):
        """Every field the IMPACT deck names is collectable somewhere."""
        required = {
            "dayboarding": ("attendance", "food_wastage", "rating_food", "rating_student_feedback",
                            "rating_staff_feedback", "rating_waiting_time", "challenges"),
            "exam_details": ("students_appeared", "absentees", "od_count", "portion_covered",
                             "qp_status", "invigilators", "challenges"),
            "stationary": ("opening_stock", "item", "received", "issued", "receipt_reference"),
            "field_trip": ("venue_planned", "participants", "challenges", "feedback"),
            "assembly_console": ("participants", "theme", "programme_flow", "feedback"),
        }
        for module_key, field_keys in required.items():
            present = {field.key for field in MODULES[module_key].fields}
            self.assertEqual(
                set(), set(field_keys) - present, f"{module_key} is missing deck fields"
            )

    def test_every_declared_spec_analysis_can_actually_fire(self):
        """A catalogue entry no builder emits would advertise an analysis that never appears."""
        from datetime import date, timedelta

        from .analytics.specs import _CATALOGUES, apply_spec
        from .analytics.types import Observation

        # Two exams share 15 Aug so the schedule-density analysis has a busy day.
        rows = {
            "dayboarding": lambda i, day: dict(
                attendance=100 - i * 7, expected_attendance=120, session=["Lunch", "Snack"][i % 2],
                food_wastage=["Minimal", "High", "Very high", "Moderate", "High"][i],
                wastage_notes=f"rice {i}", rating_food=["Good", "Poor", "Satisfactory", "Excellent", "Good"][i],
                rating_student_feedback=["Good", "Needs improvement", "Good", "Poor", "Excellent"][i],
                rating_staff_feedback="Good",
                rating_waiting_time=["Poor", "Poor", "Satisfactory", "Good", "Good"][i],
                waiting_minutes=8 + i * 3, staff=["Mr A", "Ms B"][i % 2], challenges="queue",
            ),
            "exam_details": lambda i, day: dict(
                exam=f"Term {i}", subject=["Maths", "Science", "English"][i % 3],
                subjects="Maths, Science", students_expected=100, students_appeared=90 - i,
                absentees="12,15", od_count=3 + i, portion_covered=[95, 60, 72, 88, 50][i],
                qp_status=["Ready", "Delayed", "In preparation", "Ready", "Not started"][i],
                paper_arrangement=["Complete", "Pending", "Partial", "Complete", "Pending"][i],
                invigilators=[3, 2, 5, 1, 4][i], standard=["X", "IX"][i % 2], challenges="clash",
            ),
            "field_trip": lambda i, day: dict(
                destination=["Zoo", "Museum", "Zoo", "Fort", "Museum"][i],
                venue_planned=["Zoo", "Planetarium", "Zoo", "Fort", "Museum"][i],
                participants=40 - i, students_expected=50, staff_count=[2, 1, 4, 3, 2][i],
                transport_mode=["School bus", "Hired coach", "School bus", "Walk", "Hired coach"][i],
                budget=5000 + i * 900, standard=["X", "IX"][i % 2],
                student_engagement=["Good", "Poor", "Excellent", "Satisfactory", "Good"][i],
                purpose="learning", feedback="good", challenges="traffic",
            ),
            "assembly_console": lambda i, day: dict(
                assembly_type=["Class", "House", "School", "Special", "Class"][i],
                theme=f"Theme {i % 3}", conducted_by=["Mr A", "Ms B", "Mr A", "Ms C", "Mr A"][i],
                participants=200 - i * 10, students_expected=240, programme_flow="song",
                flow_rating=["Good", "Poor", "Excellent", "Good", "Satisfactory"][i],
                student_performance=["Good", "Satisfactory", "Excellent", "Poor", "Good"][i],
                values_shared=["Honesty", "Respect", "Honesty", "Courage", "Respect"][i], feedback="ok",
            ),
            "stationary": lambda i, day: dict(
                # A4 paper appears three times so the falling-stock trend has
                # the minimum series length the analysis requires.
                item=["A4 paper", "Markers", "A4 paper", "A4 paper", "Markers"][i],
                department=["Science", "Admin", "Science", "Primary", "Admin"][i],
                opening_stock=500 - i * 80, received=[100, 0, 50, 20, 0][i],
                issued=[120, 40, 90, 30, 60][i], pending_items="reams" if i % 2 else "",
                pending_count=[10, 0, 5, 0, 8][i], unit_cost=[200, 50, 200, 10, 50][i],
                receipt_reference="R1" if i % 2 else "",
                stock_status=["Sufficient", "Reorder soon", "Critically low", "Out of stock", "Reorder soon"][i],
            ),
        }
        base = date(2026, 8, 1)
        for module_key, build in rows.items():
            observations = []
            for i in range(5):
                day = base + timedelta(days=i if i < 4 else 3)
                observations.append(Observation(
                    record_id=str(i), module_key=module_key, owner_id=str(i % 2),
                    owner_name=f"Filer {i % 2}", status="submitted", event_date=day,
                    created_at=day, values=build(i, day),
                ))
            fired = {insight.key for insight in apply_spec(MODULES[module_key], observations, date(2026, 8, 20))}
            declared = {row[0] for row in _CATALOGUES[module_key]}
            self.assertEqual(
                set(), declared - fired,
                f"{module_key} advertises analyses its builder never emits: {sorted(declared - fired)}",
            )

    def test_identity_fields_never_reach_the_decision_tier(self):
        """The deck is explicit: the principal gets insight, not roll numbers."""
        from .analytics.access import DECISION, is_identity_field
        from .analytics import catalogue_for

        for key, module in MODULES.items():
            for entry in catalogue_for(module):
                if entry.tier != DECISION:
                    continue
                leaked = [f for f in entry.fields_used if is_identity_field(f)]
                self.assertEqual([], leaked, f"{key}/{entry.key} exposes identity fields at DECISION")

    def test_analysis_keys_are_unique_within_a_module(self):
        from .analytics import catalogue_for

        for key, module in MODULES.items():
            entries = catalogue_for(module)
            self.assertEqual(
                len(entries), len({entry.key for entry in entries}), f"duplicate keys in {key}"
            )

    def test_every_role_maps_to_a_tier(self):
        from tvs_dms.forms import ROLE_LABELS

        from .analytics.access import ROLE_TIERS

        self.assertEqual(set(ROLE_TIERS), set(ROLE_LABELS))

    def test_tiers_inherit_upward_only(self):
        from .analytics import DECISION, ENTRY, SUPPORT, can_see

        self.assertTrue(can_see(DECISION, ENTRY))
        self.assertTrue(can_see(SUPPORT, ENTRY))
        self.assertTrue(can_see(ENTRY, ENTRY))
        self.assertFalse(can_see(ENTRY, SUPPORT))
        self.assertFalse(can_see(ENTRY, DECISION))
        self.assertFalse(can_see(SUPPORT, DECISION))

    def test_no_analysis_calls_out_to_a_model_or_network(self):
        """The feature is contractually deterministic; see METHODOLOGY.md section 8."""
        from pathlib import Path

        banned = ("requests", "urllib", "httpx", "openai", "anthropic", "socket", "http.client")
        analytics_dir = Path(__file__).resolve().parent / "analytics"
        for path in analytics_dir.glob("*.py"):
            source = path.read_text()
            for name in banned:
                self.assertNotIn(
                    f"import {name}", source, f"{path.name} must not reach the network"
                )


@override_settings(TVS_SETUP_TOKEN="deployment-token", TVS_DATA_KEY=DATA_KEY)
class AnalyticsReportTests(TestCase):
    module_key = "dayboarding"

    def setUp(self):
        import datetime

        get_store.cache_clear()
        self.store = get_store()
        self.store.create_initial_admin(
            username="admin",
            password="CorrectHorse77Battery!",
            display_name="Administrator",
            school_name="Test School",
        )
        admin = self.store.get_user_by_username("admin")
        self.store.update_password(admin, "CorrectHorse77Battery!", must_change=False)
        self.teacher = self.store.create_user(
            username="cat1",
            password="TeacherPass123!",
            display_name="Catalyst One",
            role="catalyst_member",
        )
        self.store.update_password(self.teacher, "TeacherPass123!", must_change=False)

        module = MODULES[self.module_key]
        base = datetime.date.today() - datetime.timedelta(days=20)
        for index in range(12):
            event_date = base + datetime.timedelta(days=index)
            self.store.save_record(
                record=None,
                module_key=module.key,
                module_name=module.name,
                role=module.role,
                owner=self.teacher,
                status="submitted",
                event_date=event_date,
                payload={
                    "event_date": event_date.isoformat(),
                    "level": "Primary",
                    "standard": ["III", "IV", "V"][index % 3],
                    "shift": "General",
                    "participants": 60 + index * 5,
                    "session": "Lunch" if index % 2 else "Snack",
                    "staff": "Mrs R",
                    "outcome": "Service ran smoothly with positive student feedback.",
                    "remarks": "Queue length remains a recurring challenge at peak.",
                },
            )

    def login(self, username: str, password: str) -> None:
        self.client.post(reverse("login"), {"username": username, "password": password})

    def test_report_page_renders_for_admin(self):
        self.login("admin", "CorrectHorse77Battery!")
        response = self.client.get(reverse("module_report", args=[self.module_key]))
        self.assertEqual(response.status_code, 200)
        self.assertGreater(response.context["report"].record_count, 0)
        self.assertTrue(response.context["report"].insights)

    def test_decision_tier_sees_more_than_entry_tier(self):
        from .analytics import build_report, select_observations, tier_of

        module = MODULES[self.module_key]
        records = self.store.list_records()
        admin_report = build_report(
            module,
            select_observations(
                records, module, viewer_id="0", tier=tier_of("administrator")
            ),
            role="administrator",
        )
        entry_report = build_report(
            module,
            select_observations(
                records, module, viewer_id=str(self.teacher.id), tier=tier_of("catalyst_member")
            ),
            role="catalyst_member",
        )
        self.assertGreater(len(admin_report.insights), len(entry_report.insights))
        self.assertTrue(admin_report.swot)
        self.assertFalse(entry_report.swot)

    def test_entry_tier_only_sees_own_records(self):
        from .analytics import select_observations, tier_of

        module = MODULES[self.module_key]
        observations = select_observations(
            self.store.list_records(), module, viewer_id="does-not-exist", tier=tier_of("office")
        )
        self.assertEqual(observations, [])

    def test_hiding_a_field_suppresses_its_analyses(self):
        from .analytics import build_report, select_observations, tier_of

        module = MODULES[self.module_key]
        observations = select_observations(
            self.store.list_records(), module, viewer_id="0", tier=tier_of("administrator")
        )
        before = build_report(module, observations, role="administrator")
        self.store.set_field_hidden(module.key, "administrator", "participants", True)
        after = build_report(module, observations, role="administrator")
        self.assertLess(len(after.insights), len(before.insights))
        self.assertFalse(
            any("participants" in insight.fields_used for insight in after.insights)
        )

    def test_hiding_a_field_redacts_the_raw_record_export(self):
        """Reports and the raw export must not disagree about what is hidden."""
        self.login("admin", "CorrectHorse77Battery!")
        url = reverse("export_records", args=["csv"])
        before = self.client.get(url, {"module": self.module_key}).content.decode()
        self.assertIn("Participants", before)

        self.store.set_field_hidden(self.module_key, "administrator", "participants", True)
        after = self.client.get(url, {"module": self.module_key}).content.decode()
        self.assertNotIn("Participants", after)
        # Only the hidden column goes; the rest of the row survives.
        self.assertIn("Session / activity", after)
        self.assertIn("Mrs R", after)

    def test_visibility_console_toggle_round_trips(self):
        self.login("admin", "CorrectHorse77Battery!")
        url = reverse("field_visibility")
        self.client.post(
            url,
            {
                "module_key": self.module_key,
                "role": "catalyst_member",
                "field_key": "participants",
                "hidden": "true",
            },
        )
        self.assertIn(
            "participants",
            self.store.hidden_fields().get((self.module_key, "catalyst_member"), set()),
        )
        self.client.post(
            url,
            {
                "module_key": self.module_key,
                "role": "catalyst_member",
                "field_key": "participants",
                "hidden": "false",
            },
        )
        self.assertNotIn(
            "participants",
            self.store.hidden_fields().get((self.module_key, "catalyst_member"), set()),
        )

    def test_visibility_console_rejects_unknown_field(self):
        self.login("admin", "CorrectHorse77Battery!")
        response = self.client.post(
            reverse("field_visibility"),
            {
                "module_key": self.module_key,
                "role": "catalyst_member",
                "field_key": "not_a_real_field",
                "hidden": "true",
            },
        )
        self.assertEqual(response.status_code, 404)

    def test_visibility_console_is_admin_only(self):
        self.login("cat1", "TeacherPass123!")
        self.assertEqual(self.client.get(reverse("field_visibility")).status_code, 403)

    def test_pdf_export_is_admin_only(self):
        self.login("cat1", "TeacherPass123!")
        response = self.client.get(
            reverse("export_report", args=[self.module_key, "pdf"])
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_pdf_export_is_a_valid_pdf(self):
        self.login("admin", "CorrectHorse77Battery!")
        response = self.client.get(
            reverse("export_report", args=[self.module_key, "pdf"])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", response.content)

    def test_spreadsheet_exports_work(self):
        self.login("admin", "CorrectHorse77Battery!")
        for file_type in ("xlsx", "csv"):
            response = self.client.get(
                reverse("export_report", args=[self.module_key, file_type])
            )
            self.assertEqual(response.status_code, 200, file_type)
            self.assertTrue(response.content)

    def test_unknown_export_type_is_404(self):
        self.login("admin", "CorrectHorse77Battery!")
        response = self.client.get(
            reverse("export_report", args=[self.module_key, "docx"])
        )
        self.assertEqual(response.status_code, 404)

    def test_report_for_a_module_outside_the_role_is_404(self):
        self.login("cat1", "TeacherPass123!")
        response = self.client.get(reverse("module_report", args=["exam_details"]))
        self.assertEqual(response.status_code, 404)

    def test_charts_are_inline_svg_with_no_inline_styles(self):
        """The CSP forbids inline styles and external scripts."""
        self.login("admin", "CorrectHorse77Battery!")
        body = self.client.get(
            reverse("module_report", args=[self.module_key])
        ).content.decode()
        self.assertIn("<svg", body)
        self.assertNotIn("style=", body)
        # Scripts are allowed from 'self' (base.html loads app.js); inline ones
        # are what the CSP blocks.
        self.assertNotIn("<script>", body)
        self.assertNotIn("javascript:", body)
