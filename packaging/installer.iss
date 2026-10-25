#define AppVersion "1.0.0"
[Setup]
AppId={{A7988A36-37D1-4A32-AC2D-52A7225C9438}
AppName=Work Assistant
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\WorkAssistant
DefaultGroupName=Work Assistant
PrivilegesRequired=lowest
OutputDir=..\installer-output
OutputBaseFilename=WorkAssistant-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\WorkAssistant.exe
[Files]
Source: "..\dist\WorkAssistant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Work Assistant"; Filename: "{app}\WorkAssistant.exe"
Name: "{autodesktop}\Work Assistant"; Filename: "{app}\WorkAssistant.exe"
[Run]
Filename: "{app}\WorkAssistant.exe"; Description: "Launch Work Assistant"; Flags: nowait postinstall skipifsilent
