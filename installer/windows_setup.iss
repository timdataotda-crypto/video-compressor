; Inno Setup script — menghasilkan satu file DroneCompressor-Setup.exe
; Build: iscc installer\windows_setup.iss
; Prasyarat: folder dist\DroneCompressor\ sudah ada hasil PyInstaller

#define AppName "Drone Compressor"
#define AppVersion "0.2.2"
#define AppPublisher "Drone Compressor"
#define AppExeName "DroneCompressor.exe"

[Setup]
AppId={{8E3F1B42-5C7A-4D91-9B23-DC0A1F7E4A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\DroneCompressor
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=DroneCompressor-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Buat shortcut di Desktop"; GroupDescription: "Shortcut:"

[Files]
Source: "..\dist\DroneCompressor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Jalankan {#AppName}"; Flags: nowait postinstall skipifsilent
