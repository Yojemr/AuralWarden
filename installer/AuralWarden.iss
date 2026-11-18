#ifndef AppVersion
  #error AppVersion must be supplied by build-installer.ps1
#endif
#ifndef PackageRoot
  #error PackageRoot must be supplied by build-installer.ps1
#endif
#ifndef OutputRoot
  #error OutputRoot must be supplied by build-installer.ps1
#endif

[Setup]
AppId={{4C3ED85A-5B7A-4C53-82FB-32A6153B0621}
AppName=AuralWarden
AppVersion={#AppVersion}
AppPublisher=Yojemr
AppPublisherURL=https://github.com/Yojemr/AuralWarden
DefaultDirName={localappdata}\Programs\AuralWarden
DefaultGroupName=AuralWarden
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputRoot}
OutputBaseFilename=AuralWarden-{#AppVersion}-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern dark polar
SetupIconFile=..\src\auralwarden\ui\assets\app-icon.ico
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\AuralWarden.exe
AppMutex=Local\Yojemr.AuralWarden.Installed
CloseApplications=no
RestartApplications=no
SetupLogging=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
CreateUninstallRegKey=not IsQAMode
UsePreviousAppDir=not IsQAMode

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "{#PackageRoot}\*"; DestDir: "{app}"; Excludes: "portable.flag,data\*,data-location.json"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\AuralWarden"; Filename: "{app}\AuralWarden.exe"; Check: not IsQAMode
Name: "{userdesktop}\AuralWarden"; Filename: "{app}\AuralWarden.exe"; Tasks: desktopicon; Check: not IsQAMode

[Run]
Filename: "{app}\AuralWarden.exe"; Description: "Abrir AuralWarden"; Flags: nowait postinstall skipifsilent; Check: not IsQAMode

[Code]
function IsQAMode: Boolean;
begin
  Result := ExpandConstant('{param:QAISOLATED|0}') = '1';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if not UninstallSilent then
      MsgBox('Se conservan los modelos, configuración, clips y transcripciones en la carpeta de datos. La desinstalación no borra tus archivos personales.', mbInformation, MB_OK);
end;
