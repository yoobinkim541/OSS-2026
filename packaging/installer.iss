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
AppPublisherURL=https://github.com/yoobinkim541/OSS-2026-Mirobot-Photo-Sketch
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
Name: "rvizenv"; Description: "RViz 3D 환경도 설치 (WSL2 + ROS 2, 약 400MB 다운로드)"; GroupDescription: "선택 기능:"; Flags: unchecked

[Files]
Source: "..\dist\MirobotSketch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "{#MyAppUserModelID}"
Name: "{group}\{#MyAppName} 명령 프롬프트"; Filename: "{cmd}"; Parameters: "/k ""cd /d ""{app}"" && mirobot.exe"""; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; AppUserModelID: "{#MyAppUserModelID}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent; Tasks: not rvizenv
; "RViz 3D 환경도 설치"를 골랐으면 앱을 열면서 설치 도우미 창도 엶 (다운로드·가져오기는 앱이 함)
Filename: "{app}\{#MyAppExe}"; Parameters: "--setup-rviz"; Description: "{cm:LaunchProgram,{#MyAppName}} + RViz 3D 환경 설치"; Flags: nowait postinstall skipifsilent; Tasks: rvizenv

[Code]
{ 앱을 지울 때 설치 도우미가 만든 WSL 배포판도 지울지 묻습니다. 조용히 지우는 경우(/SUPPRESSMSGBOXES)는 "아니요".
  다른 WSL 배포판은 건드리지 않습니다. }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if Exec(ExpandConstant('{sys}\wsl.exe'), '-d MirobotSketch-ROS --exec true', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
    begin
      if SuppressibleMsgBox('RViz 3D 환경(WSL 배포판 MirobotSketch-ROS)도 지울까요?' + #13#10 +
                            '다른 WSL 배포판은 그대로 둡니다.', mbConfirmation, MB_YESNO, IDNO) = IDYES then
        Exec(ExpandConstant('{sys}\wsl.exe'), '--unregister MirobotSketch-ROS', '', SW_HIDE,
             ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
