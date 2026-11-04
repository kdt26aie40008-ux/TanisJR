<#
.SYNOPSIS
  第二の自分AI を起動する（初回は依存関係の導入とビルドを自動で行う）。
.PARAMETER Rebuild
  フロントエンドを強制的に再ビルドする。
.PARAMETER SetupOnly
  依存関係の導入とビルドだけを行い、起動しない。
#>
param([switch]$Rebuild, [switch]$SetupOnly)

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
# git pull などで画面のソースや依存パッケージが変わったら、自動で入れ直し・ビルドし直す
function Get-SourceHash([string[]]$Paths) {
    $files = foreach ($p in $Paths) {
        if (Test-Path $p -PathType Container) { Get-ChildItem $p -Recurse -File } elseif (Test-Path $p) { Get-Item $p }
    }
    $lines = $files | Sort-Object FullName | ForEach-Object {
        $_.FullName.Substring($Frontend.Length) + ':' + (Get-FileHash $_.FullName -Algorithm SHA256).Hash
    }
    $bytes = [Text.Encoding]::UTF8.GetBytes(($lines -join "`n"))
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($bytes)).Replace('-', '') } finally { $sha.Dispose() }
}

$Lock = Join-Path $Frontend 'package-lock.json'
$Modules = Join-Path $Frontend 'node_modules'
$ModulesStamp = Join-Path $Modules '.package-lock.sha256'
$LockHash = (Get-FileHash $Lock -Algorithm SHA256).Hash
$NeedInstall = -not (Test-Path $ModulesStamp) -or (Get-Content $ModulesStamp) -ne $LockHash

$Dist = Join-Path $Frontend 'dist\index.html'
$BuildStamp = Join-Path $Frontend 'dist\.source.sha256'
$SourceHash = Get-SourceHash @(
    (Join-Path $Frontend 'src'), (Join-Path $Frontend 'public'), (Join-Path $Frontend 'index.html'),
    $Lock, (Join-Path $Frontend 'vite.config.ts'), (Join-Path $Frontend 'tsconfig.json')
)
$NeedBuild = $Rebuild -or $NeedInstall -or -not (Test-Path $Dist) -or -not (Test-Path $BuildStamp) -or (Get-Content $BuildStamp) -ne $SourceHash

if ($NeedBuild) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw 'Node.js が見つかりません。https://nodejs.org/ から LTS 版をインストールしてください。'
    }
    Push-Location $Frontend
    try {
        if ($NeedInstall) {
            Step 'npm パッケージをインストールしています'
            npm ci --no-audit --no-fund
            if ($LASTEXITCODE -ne 0) { throw 'npm パッケージのインストールに失敗しました。' }
            Set-Content -Path $ModulesStamp -Value $LockHash -Encoding ascii
        }
        Step '画面をビルドしています'
        npm run build
        if ($LASTEXITCODE -ne 0) { throw '画面のビルドに失敗しました。' }
        Set-Content -Path $BuildStamp -Value $SourceHash -Encoding ascii
    } finally { Pop-Location }
}

if ($SetupOnly) {
    Step '準備ができました（-SetupOnly のため起動しません）'
    return
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
