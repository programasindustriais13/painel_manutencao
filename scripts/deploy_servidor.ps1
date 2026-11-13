# ==============================================================================
# Entrada do instalador por duplo clique: Git validado antes do deploy mestre.
# ==============================================================================
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$DryRun,
    [switch]$SkipCaldeiraWarmup
)

$ErrorActionPreference = 'Stop'
try {
    $ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
    Set-Location -LiteralPath $ProjectRoot
    $TargetScript = Join-Path $PSScriptRoot 'deploy_production.ps1'
    if (-not (Test-Path -LiteralPath $TargetScript)) {
        throw 'Script mestre scripts\deploy_production.ps1 nao encontrado.'
    }

    if ($CheckOnly -or $DryRun) {
        Write-Host '[INFO] Modo de verificacao/simulacao: git pull nao sera executado.' -ForegroundColor Cyan
    } else {
        Get-Command git -CommandType Application -ErrorAction Stop | Out-Null
        $Branch = & git branch --show-current
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel identificar o repositorio Git.' }
        if ($Branch -ne 'main') { throw 'O deploy exige a branch main. Nenhuma branch foi alterada automaticamente.' }

        $Changes = & git status --porcelain --untracked-files=no
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel verificar as alteracoes locais do Git.' }
        if ($Changes) {
            $Changes | ForEach-Object { Write-Host $_ -ForegroundColor Yellow }
            throw 'Existem alteracoes locais em arquivos versionados. Preserve e resolva essas alteracoes antes do deploy.'
        }

        Write-Host 'Sincronizando com GitHub: git pull --ff-only origin main...' -ForegroundColor Cyan
        & git pull --ff-only origin main
        $PullResult = $LASTEXITCODE
        if ($PullResult -ne 0) {
            Write-Host '[ERRO] Git pull falhou. O deploy nao sera executado.' -ForegroundColor Red
            exit $PullResult
        }
    }

    & $TargetScript @PSBoundParameters
    exit $LASTEXITCODE
} catch {
    Write-Host ('[ERRO] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
