#define MyAppName "TVS Activity Desk"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "TVS"
#define MyAppExeName "TVS Activity Desk.exe"

[Setup]
AppId={{F1B00A8C-68B8-4D34-A786-7A6F9E5EB2F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}.0
DefaultDirName={localappdata}\Programs\TVS Activity Desk
DefaultGroupName=TVS Activity Desk
DisableWelcomePage=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=TVS-Activity-Desk-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=6.1sp1
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
SetupIconFile=..\build\assets\tvs.ico
ArchitecturesAllowed=x86 x64
UsePreviousAppDir=yes
RestartIfNeededByRun=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\TVS Activity Desk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "TEACHER-QUICK-START.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\TVS Activity Desk"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\TVS Activity Desk - Quick Start"; Filename: "{app}\TEACHER-QUICK-START.txt"
Name: "{autodesktop}\TVS Activity Desk"; Filename: "{app}\{#MyAppExeName}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TVS Activity Desk"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
; Deliberately retain the encrypted database in Local AppData after uninstall.
Type: filesandordirs; Name: "{app}"

[Code]
procedure InitializeWizard;
begin
  WizardForm.WelcomeLabel1.Caption := 'Install TVS Activity Desk';
  WizardForm.WelcomeLabel2.Caption :=
    'This installs everything needed to use TVS Activity Desk.' + #13#10 + #13#10 +
    'No Python setup or internet connection is required.' + #13#10 + #13#10 +
    'Click Next to install.';
end;
