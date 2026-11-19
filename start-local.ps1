param(
    [switch]$UseLocalModel,
    [string]$ModelFile = $env:SAIG_LOCAL_MODEL_FILE,
    [string]$ServerExe = (Join-Path $env:LOCALAPPDATA 'Programs\llama.cpp\b10976-cuda12.4\llama-server.exe')
)
$ErrorActionPreference = 'Stop'
$logs = Join-Path $PSScriptRoot '.local'
New-Item -Path $logs -ItemType Directory -Force | Out-Null
function Test-Ready([string]$Address) {
    try { return (Invoke-WebRequest -UseBasicParsing $Address -TimeoutSec 2).StatusCode -eq 200 }
    catch { return $false }
}
function Wait-Ready([string]$Address, $Process, [int]$Seconds) {
    $until=(Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $until) {
        if (Test-Ready $Address) { return }
        if ($Process.HasExited) { throw "服务退出。请检查日志 $logs" }
        Start-Sleep -Seconds 1
    }
    throw "服务未在预期时间内就绪。请检查 $Address 和 $logs"
}
if ($UseLocalModel) {
    $env:SAIG_MODEL_URL = 'http://127.0.0.1:18942/v1'
    $env:SAIG_MODEL = 'saig-local'
}
if ($UseLocalModel -and -not (Test-Ready 'http://127.0.0.1:18942/health')) {
    if (-not $ModelFile -or -not (Test-Path -LiteralPath $ModelFile) -or -not (Test-Path -LiteralPath $ServerExe)) {
        throw '请指定 ModelFile 与 ServerExe，或配置 SAIG_MODEL_URL 和 SAIG_MODEL。'
    }
    $llm=Start-Process -FilePath $ServerExe -ArgumentList @('-m',('"{0}"' -f $ModelFile),'--alias','saig-local','--host','127.0.0.1','--port','18942','--ctx-size','12288','--parallel','1','--cache-ram','0','--ctx-checkpoints','0','--gpu-layers','auto','--flash-attn','on','--reasoning-budget','0') -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'model.out') -RedirectStandardError (Join-Path $logs 'model.err')
    Wait-Ready 'http://127.0.0.1:18942/health' $llm 100
}
if (-not (Test-Ready 'http://127.0.0.1:18943/health')) {
    $api=Start-Process -FilePath (Get-Command python).Source -WorkingDirectory $PSScriptRoot -ArgumentList @('serve.py','--port','18943') -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'api.out') -RedirectStandardError (Join-Path $logs 'api.err')
    Wait-Ready 'http://127.0.0.1:18943/health' $api 30
}
$health = Invoke-RestMethod 'http://127.0.0.1:18943/health'
Push-Location -LiteralPath $PSScriptRoot
try { $expected = & python -c "from model import Model; print(Model().name)" }
finally { Pop-Location }
if ($LASTEXITCODE -ne 0 -or $health.model -ne $expected) {
    throw 'Existing SAIG API uses a different model. Restart the SAIG API to apply configuration.'
}
$health
