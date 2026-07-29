[CmdletBinding()]
param(
    [ValidateRange(1, 100)]
    [int]$Keep = 5
)

$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
$distPath = Join-Path $projectRoot "dist"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$archivePath = Join-Path $distPath "crm-conversacional-api-$timestamp.tar"
$temporaryPath = Join-Path ([System.IO.Path]::GetTempPath()) "crm-conversacional-api-$([guid]::NewGuid())"
$requiredPaths = @(
    ".dockerignore",
    ".gitattributes",
    "README.md",
    "Dockerfile",
    "alembic.ini",
    "alembic",
    "captain-definition",
    "db",
    "docker-entrypoint.sh",
    "pyproject.toml",
    "src",
    "uv.lock"
)

$tarPath = Join-Path $env:SystemRoot "System32\tar.exe"
if (-not (Test-Path -LiteralPath $tarPath)) {
    throw "O tar.exe nativo do Windows não foi encontrado em $tarPath."
}

if (-not (Test-Path -LiteralPath $distPath)) {
    New-Item -ItemType Directory -Path $distPath | Out-Null
}

try {
    New-Item -ItemType Directory -Path $temporaryPath | Out-Null

    foreach ($relativePath in $requiredPaths) {
        $sourcePath = Join-Path $projectRoot $relativePath
        if (-not (Test-Path -LiteralPath $sourcePath)) {
            throw "Arquivo necessário ao deploy não encontrado: $relativePath"
        }
        Copy-Item -LiteralPath $sourcePath -Destination $temporaryPath -Recurse
    }

    Get-ChildItem -LiteralPath $temporaryPath -Directory -Recurse -Filter "__pycache__" |
        Remove-Item -Recurse -Force
    Get-ChildItem -LiteralPath $temporaryPath -File -Recurse -Filter "*.pyc" |
        Remove-Item -Force

    & $tarPath --create --file=$archivePath --format=pax --directory=$temporaryPath .
    if ($LASTEXITCODE -ne 0) {
        throw "tar.exe falhou ao criar o pacote CapRover."
    }
}
finally {
    if (Test-Path -LiteralPath $temporaryPath) {
        Remove-Item -LiteralPath $temporaryPath -Recurse -Force
    }
}

$resolvedDistPath = (Resolve-Path -LiteralPath $distPath).Path.TrimEnd('\', '/')
$distPrefix = "$resolvedDistPath$([System.IO.Path]::DirectorySeparatorChar)"
$archives = @(Get-ChildItem -LiteralPath $distPath -File -Filter "*.tar" | Sort-Object LastWriteTime -Descending)

foreach ($oldArchive in ($archives | Select-Object -Skip $Keep)) {
    $resolvedArchivePath = [System.IO.Path]::GetFullPath($oldArchive.FullName)
    if (-not $resolvedArchivePath.StartsWith($distPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Recusada a remoção fora de dist: $resolvedArchivePath"
    }
    Remove-Item -LiteralPath $resolvedArchivePath -Force
}

Write-Host "Pacote criado: $archivePath"
Write-Host "Pacotes mantidos em dist: $([Math]::Min($archives.Count, $Keep))"
