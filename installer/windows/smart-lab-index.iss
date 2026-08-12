#ifndef AppVersion
  #error AppVersion must be supplied by the build script
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by the build script
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by the build script
#endif
#ifndef OutputBaseFilename
  #error OutputBaseFilename must be supplied by the build script
#endif
#ifndef IconFile
  #error IconFile must be supplied by the build script
#endif

[Setup]
AppId={{A3B6E3AE-82EA-4F6A-B941-7E3289C62B8F}
AppName=Smart Lab Index
AppVersion={#AppVersion}
AppVerName=Smart Lab Index {#AppVersion}
AppPublisher=Wessel ter Laak
AppPublisherURL=https://wesseltl.github.io/pdf-mcp/
AppSupportURL=https://github.com/wesseltl/pdf-mcp/issues
AppUpdatesURL=https://github.com/wesseltl/pdf-mcp/releases
AppCopyright=Copyright (c) Wessel ter Laak
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Wessel ter Laak
VersionInfoDescription=Smart Lab Index installer
VersionInfoProductName=Smart Lab Index
DefaultDirName={localappdata}\Programs\Smart Lab Index
DefaultGroupName=Smart Lab Index
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\smart-lab-index.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=smart-lab-index.exe
RestartApplications=no
SetupLogging=yes
ShowLanguageDialog=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Smart Lab Index"; Filename: "{app}\smart-lab-index.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Smart Lab Index"; Filename: "{app}\smart-lab-index.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\smart-lab-index.exe"; Description: "Open Smart Lab Index"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
