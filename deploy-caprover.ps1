[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$EnvironmentFile = (Join-Path $PSScriptRoot ".env"),
    [string]$TarFile,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

function Import-DeployEnvironment {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Arquivo de configuração não encontrado: $Path"
    }

    # Não executa o .env como PowerShell. Só aceita as quatro chaves que este
    # deploy precisa, para que editar uma variável no arquivo não vire execução
    # de código local por acidente.
    $allowed = @(
        "CAPROVER_URL",
        "CAPROVER_APP",
        "CAPROVER_APP_TOKEN",
        "CAPROVER_TAR_KEEP"
    )
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        if ($trimmed -notmatch "^(?<name>[A-Z0-9_]+)=(?<value>.*)$") {
            throw "Linha inválida em $Path. Use NOME=valor, sem comandos PowerShell."
        }
        $name = $Matches.name
        if ($name -notin $allowed) {
            throw "Variável não permitida em ${Path}: $name"
        }
        $value = $Matches.value.Trim()
        if ($value.Length -ge 2 -and (
            ($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))
        )) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        # Carregar configuração não é a operação de deploy. Forçar este
        # passo no -WhatIf também evita que o PowerShell imprima o token no
        # texto de simulação do Set-Item.
        Set-Item -LiteralPath "Env:$name" -Value $value -WhatIf:$false
    }
}

function Require-EnvironmentValue {
    param([Parameter(Mandatory)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Defina $Name em $EnvironmentFile antes de fazer o deploy."
    }
    return $value.Trim()
}

Import-DeployEnvironment -Path $EnvironmentFile

$caproverUrl = Require-EnvironmentValue -Name "CAPROVER_URL"
$caproverApp = Require-EnvironmentValue -Name "CAPROVER_APP"
$appToken = Require-EnvironmentValue -Name "CAPROVER_APP_TOKEN"

$uri = $null
if (-not [Uri]::TryCreate($caproverUrl, [UriKind]::Absolute, [ref]$uri) -or
    $uri.Scheme -ne "https") {
    throw "CAPROVER_URL deve ser uma URL HTTPS completa, por exemplo https://captain.exemplo.com"
}
if ($caproverApp -notmatch "^[a-z0-9][a-z0-9-]*$") {
    throw "CAPROVER_APP deve ser o nome do app no CapRover, em minúsculas e sem espaços."
}

# No Windows, `Get-Command caprover` pode devolver o par `caprover.cmd` e
# `caprover` sem extensão. Escolher o .cmd evita que a propriedade seja uma
# coleção de caminhos concatenados na invocação abaixo.
$cli = @(Get-Command caprover -CommandType Application -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ieq "caprover.cmd" } |
    Select-Object -First 1)
if ($cli.Count -eq 0) {
    $cli = @(Get-Command caprover -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1)
}
if ($null -eq $cli) {
    throw "CLI do CapRover não encontrado. Instale-o com: npm install -g caprover"
}

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
if ($TarFile) {
    if (-not (Test-Path -LiteralPath $TarFile -PathType Leaf)) {
        throw "Tarball informado não encontrado: $TarFile"
    }
    $archivePath = (Resolve-Path -LiteralPath $TarFile).Path
}
else {
    if ($SkipBuild) {
        throw "-SkipBuild exige também -TarFile."
    }
    $keep = 5
    $configuredKeep = [Environment]::GetEnvironmentVariable("CAPROVER_TAR_KEEP")
    if ($configuredKeep) {
        if (-not [int]::TryParse($configuredKeep, [ref]$keep) -or $keep -lt 1 -or $keep -gt 100) {
            throw "CAPROVER_TAR_KEEP deve ser um inteiro entre 1 e 100."
        }
    }
    $archivePath = $null
}

$target = "$caproverApp em $caproverUrl"
if (-not $PSCmdlet.ShouldProcess($target, "Criar pacote e publicar no CapRover")) {
    return
}

if ($null -eq $archivePath) {
    & (Join-Path $projectRoot "build.ps1") -Keep $keep
    if ($LASTEXITCODE -ne 0) {
        throw "build.ps1 falhou; o deploy foi cancelado."
    }
    $archives = @(Get-ChildItem -LiteralPath (Join-Path $projectRoot "dist") -File -Filter "*.tar" |
        Sort-Object LastWriteTimeUtc -Descending)
    if ($archives.Count -eq 0) {
        throw "build.ps1 terminou sem criar um tarball em dist/."
    }
    $archivePath = $archives[0].FullName
}

# O token fica apenas no ambiente do processo, de onde a CLI o lê. Não usamos
# --appToken para evitar deixá-lo visível na linha de comando ou nos logs.
# A CLI 2.4.3 concatena o diretório atual a --tarFile mesmo quando recebe um
# caminho absoluto do Windows. `Resolve-Path -Relative` funciona também no
# Windows PowerShell 5.1 (que não tem Path.GetRelativePath) e evita o
# `C:\projetoC:\projeto\dist\...` que ela não consegue abrir.
Push-Location -LiteralPath $projectRoot
try {
    $archiveForCli = Resolve-Path -LiteralPath $archivePath -Relative
}
finally {
    Pop-Location
}
$env:CAPROVER_APP_TOKEN = $appToken
$deployArguments = @(
    "deploy",
    "--caproverUrl", $caproverUrl,
    "--caproverApp", $caproverApp,
    "--tarFile", $archiveForCli
)

Write-Host "Publicando $($archivePath | Split-Path -Leaf) em $caproverApp..."
Push-Location -LiteralPath $projectRoot
try {
    & $cli[0].Path @deployArguments
    if ($LASTEXITCODE -ne 0) {
        throw "A CLI do CapRover retornou falha no deploy."
    }
}
finally {
    Pop-Location
}

Write-Host "Deploy enviado com sucesso. Acompanhe o build e a saúde do app no CapRover."
