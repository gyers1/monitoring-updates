param(
    [string]$Version = "",
    [string]$AssetName = "MonitoringDashboard.zip",
    [switch]$PrepareOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "[STEP] $Message"
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message"
}

function Remove-Directory([string]$Path) {
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Ensure-Directory([string]$Path) {
    [System.IO.Directory]::CreateDirectory($Path) | Out-Null
}

function Read-VersionFromJson([string]$Path) {
    $json = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    return [string]$json.version
}

function Set-DotEnvValue([string]$Path, [string]$Key, [string]$Value) {
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ($text -match "(?m)^\s*$([regex]::Escape($Key))\s*=") {
        $text = [regex]::Replace($text, "(?m)^\s*$([regex]::Escape($Key))\s*=.*$", "$Key=$Value")
    }
    else {
        $text = $text.TrimEnd("`r", "`n") + [Environment]::NewLine + "$Key=$Value" + [Environment]::NewLine
    }
    [System.IO.File]::WriteAllText($Path, $text, [System.Text.UTF8Encoding]::new($false))
}

function Sync-VersionFiles([string]$SourceDir, [string]$VersionValue) {
    $envPath = Join-Path $SourceDir '.env'
    $versionJsonPath = Join-Path $SourceDir 'version.json'

    Set-DotEnvValue -Path $envPath -Key 'APP_VERSION' -Value $VersionValue

    $versionJson = [ordered]@{ version = $VersionValue } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($versionJsonPath, $versionJson, [System.Text.UTF8Encoding]::new($false))
}

function Get-DotEnvValue([string]$Path, [string]$Key) {
    $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    $match = [regex]::Match($text, "(?m)^\s*$([regex]::Escape($Key))\s*=\s*(.*)$")
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return ''
}

function Get-RepoFromUpdateUrl([string]$Url) {
    if ($Url -match 'github\.com/([^/]+/[^/]+)/releases/') {
        return $Matches[1]
    }
    return ''
}

function Copy-Entry([string]$SourcePath, [string]$DestinationPath) {
    if (Test-Path -LiteralPath $SourcePath -PathType Container) {
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Recurse -Force
    }
    else {
        Copy-Item -LiteralPath $SourcePath -Destination $DestinationPath -Force
    }
}

function Ensure-BuildEnvironment([string]$SourceDir) {
    $venvDir = Join-Path $SourceDir 'venv_webview'
    $pythonExe = Join-Path $venvDir 'Scripts\python.exe'
    $pyinstallerExe = Join-Path $venvDir 'Scripts\pyinstaller.exe'
    $pyarmorExe = Join-Path $venvDir 'Scripts\pyarmor.exe'
    $requirementsPath = Join-Path $SourceDir 'requirements.txt'
    $requirementsHash = (Get-FileHash -LiteralPath $requirementsPath -Algorithm SHA256).Hash
    $requirementsStamp = Join-Path $venvDir '.requirements_hash'

    if (-not (Test-Path -LiteralPath $pythonExe)) {
        Write-Step 'Creating venv_webview with Python 3.12'
        & py -3.12 -c "import sys" *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'Python 3.12 is required for source and build environments.'
        }
        & py -3.12 -m venv $venvDir
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to create venv_webview.'
        }
    }

    $pyVersion = (& $pythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')").Trim()
    if ($pyVersion -ne '3.12') {
        throw "venv_webview must use Python 3.12, but found $pyVersion."
    }

    & $pythonExe -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Step 'Restoring pip inside venv_webview'
        & $pythonExe -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to restore pip inside venv_webview.'
        }
    }

    $installedHash = ''
    if (Test-Path -LiteralPath $requirementsStamp) {
        $installedHash = (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
    }
    if ($installedHash -ne $requirementsHash) {
        Write-Step 'Installing runtime dependencies'
        & $pythonExe -m pip install -r $requirementsPath
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to install runtime dependencies.'
        }
        [System.IO.File]::WriteAllText($requirementsStamp, $requirementsHash, [System.Text.UTF8Encoding]::new($false))
    }

    $toolModules = [ordered]@{
        pyinstaller = 'PyInstaller'
        pyarmor = 'pyarmor'
    }
    foreach ($tool in $toolModules.Keys) {
        $moduleName = $toolModules[$tool]
        & $pythonExe -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('$moduleName') else 1)" > $null 2> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Step "Installing build tool: $tool"
            & $pythonExe -m pip install $tool
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to install build tool: $tool"
            }
        }
    }

    if (-not (Test-Path -LiteralPath $pyinstallerExe)) {
        throw 'pyinstaller.exe was not found after setup.'
    }
    if (-not (Test-Path -LiteralPath $pyarmorExe)) {
        throw 'pyarmor.exe was not found after setup.'
    }

    return [PSCustomObject]@{
        Python = $pythonExe
        PyInstaller = $pyinstallerExe
        PyArmor = $pyarmorExe
    }
}

function Copy-SourceForStaging([string]$SourceDir, [string]$StageDir) {
    $items = @(
        'application',
        'config',
        'domain',
        'infrastructure',
        'presentation',
        'main.py',
        'webview_app.py',
        'MonitoringDashboard.spec',
        'TARGET.json',
        '.env',
        'version.json',
        'requirements.txt'
    )

    foreach ($item in $items) {
        $src = Join-Path $SourceDir $item
        if (-not (Test-Path -LiteralPath $src)) {
            throw "Required source item is missing: $item"
        }
        Copy-Entry -SourcePath $src -DestinationPath $StageDir
    }
}

function Invoke-SelectiveObfuscation([string]$StageDir, [string]$PyArmorExe) {
    $obfDir = Join-Path $StageDir '_obf'
    $targets = @('main.py', 'webview_app.py', 'application\crawl_service.py')
    Remove-Directory $obfDir

    Push-Location $StageDir
    try {
        Write-Step 'Obfuscating partial sensitive files with PyArmor'
        & $PyArmorExe gen -O $obfDir -r @targets
        if ($LASTEXITCODE -ne 0) {
            throw 'PyArmor obfuscation failed.'
        }
    }
    finally {
        Pop-Location
    }

    foreach ($target in $targets) {
        $stageTarget = Join-Path $StageDir $target
        $obfTarget = Join-Path $obfDir (Split-Path -Leaf $target)
        if (-not (Test-Path -LiteralPath $obfTarget)) {
            throw "PyArmor output is missing: $target"
        }
        $stageParent = Split-Path -Parent $stageTarget
        if (-not [string]::IsNullOrWhiteSpace($stageParent)) {
            Ensure-Directory $stageParent
        }
        Copy-Item -LiteralPath $obfTarget -Destination $stageTarget -Force
    }

    $runtimeDir = Join-Path $obfDir 'pyarmor_runtime_000000'
    if (-not (Test-Path -LiteralPath $runtimeDir)) {
        throw 'pyarmor_runtime_000000 was not generated.'
    }
    Copy-Entry -SourcePath $runtimeDir -DestinationPath $StageDir
}

function Build-Package([string]$StageDir, [string]$DistDir, [string]$WorkDir, [string]$PyInstallerExe) {
    Ensure-Directory $DistDir
    Ensure-Directory $WorkDir
    $specPath = Join-Path $StageDir 'MonitoringDashboard.spec'

    Write-Step 'Running PyInstaller'
    & $PyInstallerExe --noconfirm --clean --distpath $DistDir --workpath $WorkDir $specPath
    if ($LASTEXITCODE -ne 0) {
        throw 'PyInstaller build failed.'
    }

    $releaseDir = Join-Path $DistDir 'MonitoringDashboard'
    if (-not (Test-Path -LiteralPath $releaseDir)) {
        throw 'PyInstaller did not create MonitoringDashboard output.'
    }
    return $releaseDir
}

function Add-ReleaseAssets([string]$SourceDir, [string]$ReleaseDir) {
    $deployAssetsDir = Join-Path $SourceDir 'deploy_assets'
    $launcherTemplate = Join-Path $deployAssetsDir 'start_tray.bat'
    if (-not (Test-Path -LiteralPath $launcherTemplate)) {
        throw 'deploy_assets\start_tray.bat is missing.'
    }

    Copy-Item -LiteralPath $launcherTemplate -Destination (Join-Path $ReleaseDir 'start_tray.bat') -Force
    Copy-Item -LiteralPath (Join-Path $SourceDir '.env') -Destination (Join-Path $ReleaseDir '.env') -Force
    Copy-Item -LiteralPath (Join-Path $SourceDir 'version.json') -Destination (Join-Path $ReleaseDir 'version.json') -Force
}

function New-ZipFromDirectoryContents([string]$SourceDir, [string]$ZipPath) {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $ZipPath) {
        Remove-Item -LiteralPath $ZipPath -Force
    }

    $sourceResolved = (Resolve-Path -LiteralPath $SourceDir).Path
    $baseUri = [System.Uri]($sourceResolved.TrimEnd('\') + '\')
    $fs = [System.IO.File]::Open($ZipPath, [System.IO.FileMode]::CreateNew)
    try {
        $zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create, $false)
        try {
            Get-ChildItem -LiteralPath $SourceDir -Recurse -Force -File | ForEach-Object {
                $entryUri = [System.Uri]($_.FullName)
                $relative = [System.Uri]::UnescapeDataString($baseUri.MakeRelativeUri($entryUri).ToString())
                $relative = $relative.Replace('\', '/')
                $entry = $zip.CreateEntry($relative, [System.IO.Compression.CompressionLevel]::Optimal)
                $inStream = [System.IO.File]::OpenRead($_.FullName)
                $outStream = $entry.Open()
                try {
                    $inStream.CopyTo($outStream)
                }
                finally {
                    $outStream.Dispose()
                    $inStream.Dispose()
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    finally {
        $fs.Dispose()
    }
}

function Assert-NoPythonSourceLeak([string]$ReleaseDir) {
    $leaked = Get-ChildItem -LiteralPath $ReleaseDir -Recurse -File -Filter *.py |
        Where-Object {
            $_.FullName -notlike '*\pyarmor_runtime_000000\*'
        }
    if ($leaked) {
        $sample = ($leaked | Select-Object -First 20 | ForEach-Object { $_.FullName }) -join [Environment]::NewLine
        throw "Raw Python source leaked into release package.`n$sample"
    }
}

$sourceDir = Split-Path -Parent $PSCommandPath
$newRoot = Split-Path $sourceDir -Parent
$buildRoot = Join-Path $newRoot 'build'
$versionJsonPath = Join-Path $sourceDir 'version.json'

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Read-VersionFromJson -Path $versionJsonPath
}
$Version = $Version.Trim()
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw 'Version could not be determined. Pass -Version or set version.json.'
}

$stageDir = Join-Path $buildRoot (Join-Path 'staging' $Version)
$workDir = Join-Path $buildRoot (Join-Path 'work' $Version)
$distDir = Join-Path $buildRoot (Join-Path 'dist' $Version)
$artifactDir = Join-Path $buildRoot (Join-Path 'artifacts' $Version)

Write-Step "Preparing build environment for $Version"
$tools = Ensure-BuildEnvironment -SourceDir $sourceDir
if ($PrepareOnly) {
    Write-Ok 'Build environment is ready.'
    exit 0
}

Write-Step 'Syncing source version files'
Sync-VersionFiles -SourceDir $sourceDir -VersionValue $Version
Write-Ok "Version synced: $Version"

Remove-Directory $stageDir
Remove-Directory $workDir
Remove-Directory $distDir
Remove-Directory $artifactDir
Ensure-Directory $stageDir
Ensure-Directory $artifactDir

Write-Step 'Copying source files to staging'
Copy-SourceForStaging -SourceDir $sourceDir -StageDir $stageDir
Invoke-SelectiveObfuscation -StageDir $stageDir -PyArmorExe $tools.PyArmor

$releaseDir = Build-Package -StageDir $stageDir -DistDir $distDir -WorkDir $workDir -PyInstallerExe $tools.PyInstaller
Add-ReleaseAssets -SourceDir $sourceDir -ReleaseDir $releaseDir
Assert-NoPythonSourceLeak -ReleaseDir $releaseDir

$zipPath = Join-Path $artifactDir $AssetName
Write-Step 'Creating update ZIP artifact'
New-ZipFromDirectoryContents -SourceDir $releaseDir -ZipPath $zipPath
$zipSha256 = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
$shaPath = Join-Path $artifactDir 'MonitoringDashboard.sha256.txt'
$shaBody = "$zipSha256  $AssetName" + [Environment]::NewLine
[System.IO.File]::WriteAllText($shaPath, $shaBody, [System.Text.UTF8Encoding]::new($false))

$updateUrl = Get-DotEnvValue -Path (Join-Path $sourceDir '.env') -Key 'UPDATE_URL'
$repo = Get-RepoFromUpdateUrl -Url $updateUrl
$manifestPath = Join-Path $artifactDir 'release_manifest.json'
$manifest = [ordered]@{
    version = $Version
    built_at = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    github_repo = $repo
    asset_name = $AssetName
    zip_sha256 = $zipSha256
    update_url = $updateUrl
}
[System.IO.File]::WriteAllText($manifestPath, (($manifest | ConvertTo-Json -Depth 5)), [System.Text.UTF8Encoding]::new($false))

$notesPath = Join-Path $artifactDir 'release_notes.md'
$notes = @(
    "# MonitoringDashboard $Version",
    '',
    "- Asset: $AssetName",
    "- SHA256: $zipSha256",
    '- Public release metadata excludes internal packaging details.'
) -join [Environment]::NewLine
[System.IO.File]::WriteAllText($notesPath, $notes + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))

Write-Ok "Release folder: $releaseDir"
Write-Ok "ZIP artifact: $zipPath"
Write-Ok "SHA256: $zipSha256"
Write-Ok 'Build finished.'
