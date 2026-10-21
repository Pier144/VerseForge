; Inno Setup script for VerseForge  ->  "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\VerseForge.iss
; Builds dist\VerseForge-<version>-Setup.exe from the PyInstaller folder dist\VerseForge.
#define AppName "VerseForge"
#define AppVersion "1.4.0"
#define AppExe "VerseForge.exe"

[Setup]
AppId={{7C2E1B9A-4F3D-4C8E-9A61-5E0B2D7F3A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=VerseForge (personal project)
AppComments=Search, view in 3D and export Star Citizen models. Unofficial fan project.
; per-user install: no administrator rights needed
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-Setup
SetupIconFile=..\assets\verseforge.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; in-app updates run this installer with /SILENT /CLOSEAPPLICATIONS: close a VerseForge that is still open,
; VerseForge is started again by the [Run] entry below (not by the Restart Manager)
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\VerseForge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; silent install = update started from inside VerseForge: reopen it when done
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
