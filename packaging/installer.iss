; Mirobot Sketch Windows 설치 프로그램 (Inno Setup 6)
;
;   1) pyinstaller packaging/mirobot_sketch.spec --noconfirm   -> dist\MirobotSketch;   2) iscc /DMyAppVersion=0.1.1 packaging\installer.iss        -> dist\installer\MirobotSketch-Setup-0.1.1.exe
;
; 관리자 권한 없이 사용자 폴더에 설치하고, 시작 메뉴(항상)·바탕화면(선택) 바로가기와
; 제거 프로그램을 만듭니다. AppId는 버전이 바뀌어도 그대로 둬야 업그레이드 설치가 됩니다.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "Mirobot Sketch"
#define MyAppExe "MirobotSketch.exe"
#define MyAppUserModelID "YoobinKim.MirobotSketch"

[Setup]
AppId={{5A2ED07C-4D0E-4431-900E-C2BA12717045}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Yoobin Kim
AppPublisherURL=https://github.com/yoobinkim541/OSS-2026
AppSupportURL=https://github.com/yoobinkim541/OSS-2026-Mirobot-Photo-Sketch/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile=..\mirobot_sketch\data\app_icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
OutputDir=..\dist\installer
OutputBaseFilename=MirobotSketch-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\MirobotSketch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{group}\{#MyAppName} 명령 프롬프트"; Filename: "{cmd}"; Parameters: "/k ""cd /d ""{app}"" && mirobot.exe"""; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "{#MyAppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
