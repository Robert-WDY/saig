param([Parameter(Mandatory)][ipaddress]$Address, [int]$Port=18944)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $env:SAIG_INVITE=[guid]::NewGuid().ToString('N')
    $authority="$($Address.IPAddressToString):$Port"
    New-Item -ItemType Directory -Force -Path .local | Out-Null
    Write-Host "同一可信 Wi-Fi 下，在手机微信打开以下完整邀请链接。关闭此窗口即停止。"
    Write-Host "http://$authority/#invite=$env:SAIG_INVITE"
    & python serve.py --host $Address.IPAddressToString --port $Port --allowed-host $authority --db .local/phone.sqlite
} finally { Remove-Item Env:SAIG_INVITE -ErrorAction SilentlyContinue; Pop-Location }
