#define MyAppName "TVS Activity Desk"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "TVS"
#define MyAppExeName "TVS Activity Desk.exe"

[Setup]
AppId={{F1B00A8C-68B8-4D34-A786-7A6F9E5EB2F4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\TVS Activity Desk
DefaultGroupName=TVS Activity Desk
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=TVS-Activity-Desk-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
MinVersion=6.1sp1
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x86 x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\TVS Activity Desk\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\TVS Activity Desk"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\TVS Activity Desk"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch TVS Activity Desk and set the master password"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately retain the encrypted database in Local AppData after uninstall.
Type: filesandordirs; Name: "{app}"


