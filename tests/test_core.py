import csv
import tempfile
import unittest
from pathlib import Path

from tvs_dms import security
from tvs_dms.database import Database
from tvs_dms.exporter import export_csv, export_xlsx
from tvs_dms.forms import MODULES, MODULES_BY_ROLE


class SecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_iterations = security.PBKDF2_ITERATIONS
        security.PBKDF2_ITERATIONS = 2_000

    @classmethod
    def tearDownClass(cls):
        security.PBKDF2_ITERATIONS = cls.original_iterations

    def test_password_and_encryption_round_trip(self):
        salt, verifier = security.hash_password("StrongPass123")
        self.assertTrue(security.verify_password("StrongPass123", salt, verifier))
        self.assertFalse(security.verify_password("WrongPass123", salt, verifier))
        data_key = b"k" * 32
        nonce, wrapped, tag = security.wrap_data_key(data_key, "StrongPass123", salt)
        self.assertEqual(data_key, security.unwrap_data_key(nonce, wrapped, tag, "StrongPass123", salt))
        self.assertNotEqual(verifier, security.derive_key("StrongPass123", salt))

    def test_authenticated_payload_rejects_tampering(self):
        key = b"z" * 32
        nonce, payload, tag = security.encrypt_json({"note": "private"}, key, "record-1")
        damaged = payload[:-1] + bytes([payload[-1] ^ 1])
        with self.assertRaises(security.SecurityError):
            security.decrypt_json(nonce, damaged, tag, key, "record-1")


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.old_iterations = security.PBKDF2_ITERATIONS
        security.PBKDF2_ITERATIONS = 2_000
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.db")
        self.admin = self.db.create_master("Test School", "Admin", "StrongPass123")

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()
        security.PBKDF2_ITERATIONS = self.old_iterations

    def test_all_requested_modules_exist(self):
        self.assertEqual(5, len(MODULES_BY_ROLE["class_teacher"]))
        self.assertEqual(14, len(MODULES_BY_ROLE["catalyst_member"]))
        self.assertEqual(8, len(MODULES_BY_ROLE["office"]))
        self.assertEqual(32, len(MODULES_BY_ROLE["academic_supervisor"]))
        self.assertEqual(59, len(MODULES))

    def test_user_login_record_and_reset(self):
        user_id = self.db.create_user(self.admin, "teacher1", "Teacher One", "class_teacher", "TeacherPass123")
        teacher = self.db.authenticate("TEACHER1", "TeacherPass123")
        record_id = self.db.save_record(
            teacher, "no_bag_day", "No Bag Day", "class_teacher", "draft",
            {"event_date": "16-07-2025", "event": "Vidya", "activities": "Sports"},
        )
        records = self.db.list_records(teacher)
        self.assertEqual(record_id, records[0]["id"])
        self.assertEqual("Vidya", records[0]["data"]["event"])
        self.db.reset_password(self.admin, user_id, "NewTeacher123")
        teacher_again = self.db.authenticate("teacher1", "NewTeacher123")
        self.assertEqual("Vidya", self.db.get_record(teacher_again, record_id)["data"]["event"])

    def test_role_owner_cannot_open_another_users_record(self):
        self.db.create_user(self.admin, "teacher1", "Teacher One", "class_teacher", "TeacherPass123")
        self.db.create_user(self.admin, "teacher2", "Teacher Two", "class_teacher", "TeacherPass456")
        first = self.db.authenticate("teacher1", "TeacherPass123")
        second = self.db.authenticate("teacher2", "TeacherPass456")
        record_id = self.db.save_record(first, "sanskrit", "Sanskrit", "class_teacher", "draft", {"topic": "Grammar"})
        with self.assertRaises(PermissionError):
            self.db.get_record(second, record_id)

    def test_role_cannot_use_another_roles_form_or_admin_api(self):
        self.db.create_user(self.admin, "teacher1", "Teacher One", "class_teacher", "TeacherPass123")
        teacher = self.db.authenticate("teacher1", "TeacherPass123")
        with self.assertRaises(PermissionError):
            self.db.save_record(teacher, "career_guidance", "Career Guidance", "catalyst_member", "draft", {})
        with self.assertRaises(PermissionError):
            self.db.create_user(teacher, "intruder", "Intruder", "office", "StrongPass123")
        with self.assertRaises(PermissionError):
            self.db.list_users(teacher)

    def test_backup_is_readable_database(self):
        target = Path(self.temp.name) / "backup.tvsbackup"
        self.db.backup_to(self.admin, target)
        copied = Database(target)
        try:
            self.assertTrue(copied.is_initialized())
            self.assertEqual("Test School", copied.school_name())
        finally:
            copied.close()

    def test_disabled_form_blocks_operational_entry(self):
        self.db.create_user(self.admin, "teacher1", "Teacher One", "class_teacher", "TeacherPass123")
        teacher = self.db.authenticate("teacher1", "TeacherPass123")
        self.db.set_module_enabled(self.admin, "no_bag_day", False)
        with self.assertRaises(PermissionError):
            self.db.save_record(teacher, "no_bag_day", "No Bag Day", "class_teacher", "draft", {})


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.records = [{
            "id": "abc", "module_key": "no_bag_day", "module_name": "No Bag Day",
            "role": "class_teacher", "status": "submitted", "owner_name": "Teacher",
            "created_at": "2025-07-16T10:00:00", "updated_at": "2025-07-16T10:00:00",
            "data": {"event_date": "16-07-2025", "event": "=DANGEROUS", "participants": 500},
        }]

    def tearDown(self):
        self.temp.cleanup()

    def test_csv_export_is_utf8_and_formula_safe(self):
        path = export_csv(self.records, Path(self.temp.name) / "out.csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertIn("Event", rows[0])
        self.assertIn("'=DANGEROUS", rows[1])

    def test_xlsx_export(self):
        try:
            path = export_xlsx(self.records, Path(self.temp.name) / "out.xlsx")
        except RuntimeError:
            self.skipTest("openpyxl is not installed in the development environment")
        self.assertTrue(path.exists())
        self.assertGreater(path.stat().st_size, 1000)


if __name__ == "__main__":
    unittest.main()

