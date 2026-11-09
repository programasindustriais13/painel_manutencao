# ==============================================================================
# PIPELINE DE DEPLOY AUTOMATIZADO APÓS GIT PULL — PNEUS FREEDOM
# Redirecionamento transparente para o script mestre de produção unificado
# ==============================================================================
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$DryRun,
    [switch]$SkipCaldeiraWarmup
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TargetScript = Join-Path $ScriptDir "deploy_production.ps1"

& $TargetScript @PSBoundParameters
exit $LASTEXITCODE
