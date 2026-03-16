param(
    [string]$Version = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    Write-Host "[STEP] $Message"
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message"
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

function Test-GitHubReleaseExists([string]$GhPath, [string]$Version, [string]$Repo) {
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $GhPath
    $startInfo.Arguments = ('release view "{0}" --repo "{1}"' -f $Version, $Repo)
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $process.Start() | Out-Null
    $null = $process.StandardOutput.ReadToEnd()
    $null = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    return ($process.ExitCode -eq 0)
}

$sourceDir = Split-Path -Parent $PSCommandPath
$newRoot = Split-Path $sourceDir -Parent
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = [string](Get-Content -LiteralPath (Join-Path $sourceDir 'version.json') -Raw | ConvertFrom-Json).version
}
$Version = $Version.Trim()
if ([string]::IsNullOrWhiteSpace($Version)) {
    throw 'Version could not be determined.'
}

$artifactDir = Join-Path $newRoot (Join-Path 'build\artifacts' $Version)
$manifestPath = Join-Path $artifactDir 'release_manifest.json'
$notesPath = Join-Path $artifactDir 'release_notes.md'
$shaPath = Join-Path $artifactDir 'MonitoringDashboard.sha256.txt'

if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw "release_manifest.json was not found for version $Version. Build the release first."
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$repo = [string]$manifest.github_repo
if ([string]::IsNullOrWhiteSpace($repo)) {
    $repo = Get-RepoFromUpdateUrl -Url (Get-DotEnvValue -Path (Join-Path $sourceDir '.env') -Key 'UPDATE_URL')
}
$assetName = [string]$manifest.asset_name
$zipPath = Join-Path $artifactDir $assetName

if ([string]::IsNullOrWhiteSpace($repo)) {
    throw 'github_repo is missing in release_manifest.json and could not be derived from .env.'
}
if (-not (Test-Path -LiteralPath $zipPath)) {
    throw "ZIP artifact was not found: $zipPath"
}
if (-not (Test-Path -LiteralPath $notesPath)) {
    throw "release_notes.md was not found: $notesPath"
}
if (-not (Test-Path -LiteralPath $shaPath)) {
    throw "MonitoringDashboard.sha256.txt was not found: $shaPath"
}

$gh = (Get-Command gh -ErrorAction Stop).Source

Write-Step 'Checking GitHub CLI authentication'
& $gh auth status
if ($LASTEXITCODE -ne 0) {
    throw 'GitHub CLI authentication failed. Run gh auth login first.'
}

if (Test-GitHubReleaseExists -GhPath $gh -Version $Version -Repo $repo) {
    throw "Release tag $Version already exists in $repo. Use a new version tag."
}

Write-Step "Publishing $Version to $repo"
& $gh release create $Version $zipPath $manifestPath $shaPath --repo $repo --title $Version --notes-file $notesPath --latest
if ($LASTEXITCODE -ne 0) {
    throw 'gh release create failed.'
}

Write-Ok "Published GitHub release $Version"
