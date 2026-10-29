; Inno Setup script for the 3D Scan Post-Processor
; Build with build_installer.ps1 (runs PyInstaller first), or:
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\3DScanPostProcessor.iss

#define AppName "3D Scan Post-Processor"
#define AppVersion "1.0.0"
#define AppExe "3DScanPostProcessor.exe"

[Setup]
AppId={{6E2D7B54-3F0A-4C1B-9E55-2A7C1D8B9F31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=3D Scan Post-Processor
DefaultDirName={autopf}\3DScanPostProcessor
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\dist\installer
OutputBaseFilename=3DScanPostProcessor_Setup_{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\3DScanPostProcessor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\README"; Filename: "{app}\README.md"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
