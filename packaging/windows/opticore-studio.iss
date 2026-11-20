; Inno Setup script of the OptiCore Studio installer for Windows.
;
; Build after PyInstaller (packaging/opticore-studio.spec), from the repository root:
;   ISCC /DAppVersion=0.1.0 packaging\windows\opticore-studio.iss
; (add /DFast for a quick test build with light compression). The result is
; packaging\dist\OptiCore-Studio-<version>-Setup.exe.
;
; One click: the installer asks nothing. It installs for the current user without administrator rights
; (%LOCALAPPDATA%\Programs\OptiCore Studio), adds Start menu and desktop shortcuts, and offers to open the program
; when it is done. An update closes a running copy and replaces the previous files. Projects are stored in the
; browser, not in the program folder, so they survive updates and uninstallation.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "OptiCore Studio"
#define AppExe "OptiCore Studio.exe"

[Setup]
; the same id in every version: it identifies the installation for updates and uninstallation
AppId={{27F52DE4-756A-4653-BA9E-7585F78CEBC3}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Juuso Heiskanen
AppPublisherURL=https://github.com/Juusseli/opticore-studio
AppSupportURL=https://github.com/Juusseli/opticore-studio/issues
AppUpdatesURL=https://github.com/Juusseli/opticore-studio/releases
AppCopyright=Copyright (C) 2026 Juuso Heiskanen
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
ShowLanguageDialog=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist
OutputBaseFilename=OptiCore-Studio-{#AppVersion}-Setup
SetupIconFile=..\assets\opticore-studio.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
#ifdef Fast
Compression=lzma2/fast
#else
Compression=lzma2/max
SolidCompression=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "finnish"; MessagesFile: "compiler:Languages\Finnish.isl"

[InstallDelete]
; files of the previous version (an update must not mix libraries of two versions)
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the program's log and running-instance record (projects live in the browser and are kept)
Type: filesandordirs; Name: "{localappdata}\{#AppName}"
