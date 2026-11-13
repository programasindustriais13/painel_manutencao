$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $ProjectRoot
$LogDirectory = Join-Path $ProjectRoot 'logs'
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$TaskLog = Join-Path $LogDirectory ('whatsapp_bladder_' + (Get-Date -Format 'yyyy-MM-dd') + '.log')
try {
    $PythonExec = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
    $Output = & $PythonExec manage.py enviar_resumo_estoque_bladder 2>&1
    $ResultCode = $LASTEXITCODE
    Add-Content -LiteralPath $TaskLog -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + ($Output -join [Environment]::NewLine))
    exit $ResultCode
} catch {
    Add-Content -LiteralPath $TaskLog -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ERRO: ' + $_.Exception.Message)
    exit 1
}
