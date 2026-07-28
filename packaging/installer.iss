; Inno Setup script for Desktop Pet.
; Build with:  iscc packaging\installer.iss   (after build.bat has produced the exe)
; Produces:    dist\DesktopPet-Setup.exe

#define AppName "Desktop Pet"
#define AppVersion "1.0.0"
#define AppPublisher "Desktop Pet contributors"
#define AppExeName "DesktopPet.exe"
#define AppURL "https://github.com/evergarden0101/desktop-pet"

[Setup]
AppId={{F2C9B7A2-7E4B-4E2A-9E3C-DE5107A11B01}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\DesktopPet
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin required).
PrivilegesRequiredOverridesAllowed=dialog commandline
OutputDir=..\dist
OutputBaseFilename=DesktopPet-Setup
SetupIconFile=app.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startupicon"; Description: "Start Desktop Pet automatically at &login"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
; The single-file PyInstaller output. If you build the one-folder variant
; instead, replace this with the whole dist\DesktopPet\ directory.
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\app.ico"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Desktop Pet now"; Flags: nowait postinstall skipifsilent
