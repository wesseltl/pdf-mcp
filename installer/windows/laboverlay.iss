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
AppName=LabOverlay
AppVersion={#AppVersion}
AppVerName=LabOverlay {#AppVersion}
AppPublisher=Wessel ter Laak
AppPublisherURL=https://wesseltl.github.io/pdf-mcp/
AppSupportURL=https://github.com/wesseltl/pdf-mcp/issues
AppUpdatesURL=https://github.com/wesseltl/pdf-mcp/releases
AppCopyright=Copyright (c) Wessel ter Laak
VersionInfoVersion={#AppVersion}
VersionInfoCompany=Wessel ter Laak
VersionInfoDescription=LabOverlay installer
VersionInfoProductName=LabOverlay
DefaultDirName={localappdata}\Programs\LabOverlay
DefaultGroupName=LabOverlay
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBaseFilename}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\laboverlay.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=laboverlay.exe,smart-lab-index.exe
RestartApplications=no
SetupLogging=yes
ShowLanguageDialog=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\smart-lab-index.exe"

[Icons]
Name: "{group}\LabOverlay"; Filename: "{app}\laboverlay.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\LabOverlay"; Filename: "{app}\laboverlay.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\laboverlay.exe"; Description: "Open LabOverlay"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
