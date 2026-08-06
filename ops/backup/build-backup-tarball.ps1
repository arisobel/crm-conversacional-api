[CmdletBinding()]
param()

# Empacota apenas esta pasta para deploy no CapRover. O captain-definition
# precisa estar na RAIZ do tarball, por isso o --directory aponta para cá.
$ErrorActionPreference = "Stop"

$backupRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$distPath = Join-Path (Split-Path -Parent (Split-Path -Parent $backupRoot)) "dist"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$archivePath = Join-Path $distPath "crm-backup-$timestamp.tar"

$tarPath = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path -LiteralPath $tarPath)) {
    throw "O tar.exe nativo do Windows não foi encontrado em $tarPath."
}

if (-not (Test-Path -LiteralPath $distPath)) {
    New-Item -ItemType Directory -Path $distPath | Out-Null
}

& $tarPath --create --file=$archivePath --format=pax --directory=$backupRoot `
    "captain-definition" "Dockerfile" "backup.sh" "restore.sh" "entrypoint.sh"
if ($LASTEXITCODE -ne 0) {
    throw "tar.exe falhou ao criar o pacote de backup."
}

Write-Host "Pacote criado: $archivePath"
