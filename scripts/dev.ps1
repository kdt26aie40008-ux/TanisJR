<#
.SYNOPSIS
  開発用: バックエンド (8765) と Vite 開発サーバー (5173, ホットリロード) を起動する。
  事前に start.ps1 を一度実行して依存関係を導入しておくこと。
#>
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$VenvPython = Join-Path $Backend '.venv\Scripts\python.exe'

$backendProc = Start-Process -FilePath $VenvPython -ArgumentList '-m', 'app.main' -WorkingDirectory $Backend -PassThru -NoNewWindow
try {
    Write-Host '==> 画面: http://127.0.0.1:5173' -ForegroundColor Cyan
    Push-Location (Join-Path $Root 'frontend')
    npm run dev
} finally {
    Pop-Location
    Stop-Process -Id $backendProc.Id -ErrorAction SilentlyContinue
}
