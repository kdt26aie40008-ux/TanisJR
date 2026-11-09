<#
.SYNOPSIS
  デスクトップとスタートメニューに「AnotherMe」のショートカットを作る。
  ダブルクリックすると、必要ならサーバーと Ollama を起動して、アプリの画面を開く（scripts\open.ps1）。
#>
$Root = Split-Path -Parent $PSScriptRoot
$Open = Join-Path $PSScriptRoot 'open.ps1'
$Icon = Join-Path $Root 'assets\icons\anotherme.ico'
$Shell = New-Object -ComObject WScript.Shell

$places = @(
    [Environment]::GetFolderPath('Desktop'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) '')
)
foreach ($dir in $places) {
    $lnk = $Shell.CreateShortcut((Join-Path $dir 'AnotherMe.lnk'))
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $lnk.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Open`""
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = 'AnotherMe（もう一人の私）を開く'
    $lnk.WindowStyle = 7
    $lnk.Save()
    Write-Host "作成しました: $(Join-Path $dir 'AnotherMe.lnk')"
}
