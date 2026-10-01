; Inno Setup script for the single-file installer. Build with
; packaging/build_release.py, not directly: it passes AppVersion, SourceDir and
; OutputDir from r7convert.__version__.
;
; Installs per user (no admin rights, so it works on locked-down lab machines)
; into %LOCALAPPDATA%\Programs. It wraps the same PyInstaller folder build as the
; zip, so nothing unpacks to a temp folder at launch.

#define AppName "Canon R7 EXR Converter"
#define ExeName AppName + " v" + AppVersion + ".exe"

[Setup]
AppId={{ABD4404C-0D49-493C-9D61-72B81E15E4EF}
AppName={#AppName} - FVFX
AppVersion={#AppVersion}
AppVerName={#AppName} v{#AppVersion}
AppPublisher=FVFX
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#AppName} v{#AppVersion} Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#ExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; The exe name carries the version: remove the previous one on upgrade.
Type: files; Name: "{app}\{#AppName} v*.exe"
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{group}\{#AppName} Manual"; Filename: "{app}\Manual.pdf"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#ExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; In-app updates run silently with /UPDATE=1: reopen the app afterwards.
Filename: "{app}\{#ExeName}"; Flags: nowait; Check: IsUpdate

[Code]
function IsUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;
