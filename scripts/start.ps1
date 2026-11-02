<#
.SYNOPSIS
  第二の自分AI を起動する（初回は依存関係の導入とビルドを自動で行う）。
.PARAMETER Rebuild
  フロントエンドを強制的に再ビルドする。
#>
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPython = Join-Path $Backend '.venv\Scripts\python.exe'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# --- Python 環境 ---
if (-not (Test-Path $VenvPython)) {
    Step 'Python 仮想環境を作成しています'
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python が見つかりません。https://www.python.org/ から Python 3.12 以降をインストールしてください。'
    }
    py -3 -m venv (Join-Path $Backend '.venv')
}
$Req = Join-Path $Backend 'requirements.txt'
$Stamp = Join-Path $Backend '.venv\.requirements.sha256'
$Hash = (Get-FileHash $Req -Algorithm SHA256).Hash
if (-not (Test-Path $Stamp) -or (Get-Content $Stamp) -ne $Hash) {
    Step 'Python パッケージをインストールしています'
    & $VenvPython -m pip install --disable-pip-version-check -q -r $Req
    if ($LASTEXITCODE -ne 0) { throw 'Python パッケージのインストールに失敗しました。' }
    Set-Content -Path $Stamp -Value $Hash -Encoding ascii
}

# --- フロントエンド ---
$Dist = Join-Path $Frontend 'dist\index.html'
if ($Rebuild -or -not (Test-Path $Dist)) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'Node.js が見つかりません。https://nodejs.org/ から LTS 版をインストールしてください。'
    }
    Push-Location $Frontend
    try {
        if (-not (Test-Path 'node_modules')) {
            Step 'npm パッケージをインストールしています'
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm パッケージのインストールに失敗しました。' }
        }
        Step '画面をビルドしています'
        npm run build
        if ($LASTEXITCODE -ne 0) { throw '画面のビルドに失敗しました。' }
    } finally { Pop-Location }
}

# --- Ollama 確認（起動していなくてもサーバーは起動し、画面で案内する） ---
try {
    Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3 | Out-Null
} catch {
    Write-Warning 'Ollama に接続できません。Ollama を起動してください（https://ollama.com/download）。'
}

$Port = if ($env:TWIN_PORT) { $env:TWIN_PORT } else { '8765' }
Step "起動します: http://127.0.0.1:$Port  （終了は Ctrl+C）"
Push-Location $Backend
try { & $VenvPython -m app.main } finally { Pop-Location }
