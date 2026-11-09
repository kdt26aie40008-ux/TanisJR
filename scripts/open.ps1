<#
.SYNOPSIS
  AnotherMe を開く（デスクトップのショートカットから呼ばれる）。
  サーバーが止まっていれば、新しい版の準備（start.ps1 -SetupOnly）をしてから裏で起動し、
  Ollama が止まっていれば起動して、準備ができたらアプリの画面を開く。
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Port = if ($env:TWIN_PORT) { $env:TWIN_PORT } else { '8765' }
$Url = "http://127.0.0.1:$Port"

function Test-Up([string]$address) {
    try { Invoke-RestMethod -Uri $address -TimeoutSec 2 | Out-Null; return $true } catch { return $false }
}

function Show-Message([string]$text) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($text, 'AnotherMe') | Out-Null
}

# --- Ollama（AI 本体）が止まっていれば起動する ---
if (-not (Test-Up 'http://127.0.0.1:11434/api/version')) {
    $ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path $ollama) { Start-Process -FilePath $ollama -WindowStyle Hidden }
}

# --- サーバーが止まっていれば、準備してから裏で起動する ---
if (-not (Test-Up "$Url/api/health")) {
    try {
        # git pull などで変わった部品・画面をそろえる（変わっていなければすぐ終わる）
        & (Join-Path $PSScriptRoot 'start.ps1') -SetupOnly
    } catch {
        Show-Message "起動の準備に失敗しました。`n`n$($_.Exception.Message)`n`nstart.bat を実行すると、くわしい内容が表示されます。"
        exit 1
    }
    $python = Join-Path $Backend '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path $python)) { $python = Join-Path $Backend '.venv\Scripts\python.exe' }
    Start-Process -FilePath $python -ArgumentList '-m', 'app.main', '--background' -WorkingDirectory $Backend -WindowStyle Hidden
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Up "$Url/api/health") { $ready = $true; break }
    }
    if (-not $ready) {
        Show-Message "サーバーを起動できませんでした。`n`nstart.bat を実行すると、くわしい内容が表示されます。"
        exit 1
    }
}

# --- アプリの画面を開く（Edge のアプリ用ウィンドウ。なければいつものブラウザー） ---
$edge = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($edge) {
    Start-Process -FilePath $edge -ArgumentList "--app=$Url/#/chat"
} else {
    Start-Process "$Url/#/chat"
}
