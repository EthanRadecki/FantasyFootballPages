# Bundle the local pipeline scripts for engine/_legacy/, with a secret scan.
#
# Run from your local pipeline folder (the one with app.py and the .conda env):
#   powershell -ExecutionPolicy Bypass -File bundle_legacy.ps1
#
# Produces legacy_scripts.zip next to this script's working folder. Nothing
# else is modified. The zip is NOT created if anything that looks like an ESPN
# cookie is found in the scripts.

$ErrorActionPreference = "Stop"
$root = (Get-Location).Path
$staging = Join-Path $root "_legacy_staging"
$zip = Join-Path $root "legacy_scripts.zip"

# Scratch and legacy-app files that do not carry forward.
$skip = @(
    "app.py", "generate_manager_visualizations.py",
    "check.py", "audit_picks.py", "get_heatmap_tips.py", "extract_manager_picks.py",
    "debug_cole_late.py", "debug_late_rounds.py", "debug_love.py", "debug_weighted_surplus.py",
    "bundle_legacy.ps1"
)

$scripts = Get-ChildItem -Path $root -File |
    Where-Object { $_.Extension -in ".py", ".R" -and $_.Name -notin $skip }

# 1. Secret scan.
#    Blocking: a long literal assigned to espn_s2 / swid.
#    Warning only: SWID-shaped GUIDs. ESPN member ids use the same shape and
#    are not secret, but your own SWID cookie would also match, so review them.
$blocking = $scripts | Select-String -Pattern @(
    '(?i)(espn_s2|swid)["'']?\s*[=:]\s*["''][^"'']{20,}',   # espn_s2 = "..." or "espn_s2": "..."
    '["'']AE[A-Za-z0-9%+/=]{100,}["'']'                        # a bare espn_s2 cookie value
)
if ($blocking) {
    Write-Host "STOP: possible ESPN credentials found. Move them to espn_auth.json first:" -ForegroundColor Red
    $blocking | ForEach-Object { Write-Host ("  {0}:{1}" -f $_.Filename, $_.LineNumber) }
    exit 1
}
$guids = $scripts | Select-String -Pattern '\{[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}'
if ($guids) {
    Write-Host "REVIEW: GUIDs found. Fine if they are member ids; not fine if one is your SWID cookie:" -ForegroundColor Yellow
    $guids | ForEach-Object { Write-Host ("  {0}:{1}: {2}" -f $_.Filename, $_.LineNumber, $_.Line.Trim()) }
}

# 2. Stage and zip.
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $staging "engine\_legacy") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $staging "docs") | Out-Null

$scripts | Copy-Item -Destination (Join-Path $staging "engine\_legacy")
if (Test-Path (Join-Path $root "METRICS_REFERENCE.md")) {
    Copy-Item (Join-Path $root "METRICS_REFERENCE.md") (Join-Path $staging "docs")
}

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip
Remove-Item $staging -Recurse -Force

Write-Host ("OK: {0} scripts bundled into {1}" -f $scripts.Count, $zip) -ForegroundColor Green
Write-Host "Skipped (not carried forward): $($skip -join ', ')"
