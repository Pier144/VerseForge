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

[Code]
function ProcessRunning(Image: String): Boolean;
var
  Code: Integer;
begin
  // tasklist lists the process when it runs, find returns 0 when it sees it
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq ' + Image + '" /NH | find /I "' + Image + '" >nul',
                 '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function InitializeSetup(): Boolean;
var
  Code, I: Integer;
begin
  Result := True;
  if WizardSilent then
  begin
    // in-app update: VerseForge quits right after starting this installer. Its Qt window does not answer the
    // Restart Manager, so wait for it here and, if it is still open after 15 s, close it.
    I := 0;
    while ProcessRunning('{#AppExe}') and (I < 30) do
    begin
      Sleep(500);
      I := I + 1;
    end;
    if ProcessRunning('{#AppExe}') then
      Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#AppExe} /F /T', '', SW_HIDE, ewWaitUntilTerminated, Code);
    // its browser engine helpers end with it
    I := 0;
    while ProcessRunning('QtWebEngineProcess.exe') and (I < 10) do
    begin
      Sleep(500);
      I := I + 1;
    end;
  end;
end;
