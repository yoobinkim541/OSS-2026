<#
저장소 코드용 바로가기 만들기 (개발 PC)
  - 바탕화면과 시작 메뉴에 "Mirobot Sketch" 바로가기를 만듭니다.
  - pythonw.exe로 CV\gui_sketch.py를 실행하므로 콘솔 창이 뜨지 않고,
    저장소 코드를 고치면 바로가기로 실행할 때 바로 반영됩니다.
  - 설치형 배포(다른 PC)는 Releases의 MirobotSketch-Setup.exe를 쓰세요.

사용법 (저장소 폴더에서):
  powershell -ExecutionPolicy Bypass -File packaging\create_shortcuts.ps1
  powershell -ExecutionPolicy Bypass -File packaging\create_shortcuts.ps1 -Remove
#>
param([switch]$Remove)

$repo = Split-Path -Parent $PSScriptRoot
$name = "Mirobot Sketch.lnk"
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) $name),
    (Join-Path ([Environment]::GetFolderPath('Programs')) $name)
)

if ($Remove) {
    foreach ($t in $targets) { if (Test-Path $t) { Remove-Item $t; "삭제: $t" } }
    return
}

$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { throw "pythonw.exe를 찾을 수 없습니다. 파이썬 설치와 PATH를 확인하세요." }

$shell = New-Object -ComObject WScript.Shell
foreach ($t in $targets) {
    $lnk = $shell.CreateShortcut($t)
    $lnk.TargetPath = $pythonw
    $lnk.Arguments = "`"$repo\CV\gui_sketch.py`""
    $lnk.WorkingDirectory = $repo
    $lnk.IconLocation = "$repo\assets\app_icon.ico,0"
    $lnk.Description = "사진을 로봇 팔이 그릴 수 있는 선으로 (Mirobot Sketch)"
    $lnk.Save()
    "생성: $t"
}
