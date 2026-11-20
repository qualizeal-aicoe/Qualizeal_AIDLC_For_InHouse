# QualiZeal AI-DLC Studio: get this Windows laptop ready, then check it. Safe to run again; nothing needs administrator rights.
# From the cloned repository run:  setup\bootstrap.cmd
#   (the same as: powershell -NoProfile -ExecutionPolicy Bypass -File setup\bootstrap.ps1)
param(
  [string]$Repo = "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse",
  [switch]$CheckOnly
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Reload-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  if ($env:Path -notlike "*$env:USERPROFILE\.local\bin*") { $env:Path += ";$env:USERPROFILE\.local\bin" }
}
if ([Environment]::Is64BitOperatingSystem -and -not [Environment]::Is64BitProcess) {
  Write-Host "This is the 32-bit PowerShell. Open 'Windows PowerShell' (not x86) and run setup\bootstrap.cmd again." -ForegroundColor Red
  exit 1
}

Step "Git"
if (-not (Have git)) {
  Write-Host "Git is missing. Install it, open a new terminal, and run this again:" -ForegroundColor Red
  Write-Host "  winget install --id Git.Git -e"
  exit 1
}
git --version

Step "Claude Code"
if (-not (Have claude)) {
  if ($CheckOnly) { Write-Host "Claude Code is missing: irm https://claude.ai/install.ps1 | iex" -ForegroundColor Red; exit 1 }
  Write-Host "Installing Claude Code with Anthropic's installer (into your user folder) ..."
  try { Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression } catch { Write-Host "  The installer did not run ($_). Try: winget install --id Anthropic.ClaudeCode -e" -ForegroundColor Red; exit 1 }
  Reload-Path
}
claude --version

Step "uv, which runs the Studio's Python"
if (-not (Have uv)) {
  if ($CheckOnly) { Write-Host "uv is missing: irm https://astral.sh/uv/install.ps1 | iex" -ForegroundColor Red; exit 1 }
  try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression } catch { Write-Host "  The installer did not run ($_). Try: winget install --id astral-sh.uv -e" -ForegroundColor Red; exit 1 }
  Reload-Path
}
uv --version
uv python find ">=3.11,<3.14" *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "No Python 3.11 to 3.13 found; uv installs Python 3.12 for the Studio (about 30 MB) ..."
  uv python install 3.12
}

if (-not $CheckOnly) {
  Step "The Studio in Claude Code"
  # Claude Code updates the Studio in the background with git; HTTPS avoids a hang on old SSH keys.
  [Environment]::SetEnvironmentVariable("CLAUDE_CODE_PLUGIN_PREFER_HTTPS", "1", "User")
  $env:CLAUDE_CODE_PLUGIN_PREFER_HTTPS = "1"
  claude plugin marketplace add $Repo
  if ($LASTEXITCODE -ne 0) { Write-Host "  (already added, or not readable yet: the check below says which)" }
  foreach ($p in @("qz-aidlc@qualizeal", "qz-console@qualizeal")) { claude plugin install $p }
}

Step "The check"
$qz = Join-Path $root "plugins\qz-aidlc\scripts\qz.py"
$report = Join-Path $root "doctor-report.json"
$fix = @(); if (-not $CheckOnly) { $fix = @("--fix") }
uv run -q --no-project --python ">=3.11,<3.14" python -I -B -X utf8 $qz doctor --json $report --repo $Repo @fix
$code = $LASTEXITCODE
Write-Host ""
if ($code -eq 0) { Write-Host "Ready. Restart Claude Code, then send doctor-report.json to the session lead." -ForegroundColor Green }
else { Write-Host "Fix the FAIL lines above, then run setup\bootstrap.cmd again. Send doctor-report.json to the session lead if you are stuck." -ForegroundColor Yellow }
exit $code
