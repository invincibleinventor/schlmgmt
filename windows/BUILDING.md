# Building the Windows 7-10 installer

The teacher-facing deliverable is one file: `TVS-Activity-Desk-Setup.exe`.
Teachers never install Python or any packages.

## Build machine

Use a Windows machine or VM with:

- Windows 7 SP1, 8.1, or 10 (building and testing on Windows 7 SP1 gives the strongest legacy assurance)
- 32-bit Python 3.8.10 with the Python launcher enabled
- Inno Setup 6
- internet access during the build only

Run `build_windows.bat` by double-clicking it. The script creates an isolated
32-bit environment, installs pinned build dependencies, builds the app, performs
a packaged encryption/database check, compiles the installer, and produces a
SHA-256 checksum.

The 32-bit application is intentional: the same installer runs on both 32-bit
and 64-bit editions of Windows 7, 8, and 10.

Before distribution, test the installer on a clean Windows 7 SP1 computer and a
Windows 10 computer. Windows 7 must include KB2533623 and the Universal C Runtime
from normal Microsoft updates. These are operating-system prerequisites for
Python 3.8 applications.

For the smoothest Windows warning experience, sign both the application and
installer with the school's trusted Authenticode certificate before distribution.

