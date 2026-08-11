import unittest
from pathlib import Path

from tvs_dms.app import package_check


ROOT = Path(__file__).resolve().parents[1]


class WindowsPackagingTests(unittest.TestCase):
    def test_non_gui_package_check(self):
        package_check()

    def test_installer_is_simple_and_legacy_compatible(self):
        script = (ROOT / "windows" / "TVSActivityDesk.iss").read_text(encoding="utf-8")
        self.assertIn("MinVersion=6.1sp1", script)
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("DisableDirPage=yes", script)
        self.assertIn("DisableReadyPage=yes", script)
        self.assertIn("TEACHER-QUICK-START.txt", script)
        self.assertIn("{autodesktop}\\TVS Activity Desk", script)
        self.assertNotIn("[Tasks]", script)

    def test_builder_produces_one_32_bit_cross_version_package(self):
        builder = (ROOT / "windows" / "build_windows.bat").read_text(encoding="utf-8")
        self.assertIn("py -3.8-32", builder)
        self.assertIn("--package-check", builder)
        self.assertIn("python -m unittest discover", builder)
        self.assertIn("TVS-Activity-Desk-Setup.exe", builder)

    def test_automated_windows_build_uploads_the_installer(self):
        workflow = (ROOT / ".github" / "workflows" / "windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn('architecture: "x86"', workflow)
        self.assertIn('python-version: "3.8.10"', workflow)
        self.assertIn("- main", workflow)
        self.assertIn("TVS-Activity-Desk-Setup.exe", workflow)
        self.assertIn("actions/upload-artifact@v4", workflow)


if __name__ == "__main__":
    unittest.main()
