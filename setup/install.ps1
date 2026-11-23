# QualiZeal AI-DLC Studio: add the marketplace and install both plugins in Claude Code (Windows PowerShell).
# Safe to run again. The repository is public: the machine only needs to reach github.com.
param([string]$Repo = "qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse")
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
  Write-Host "Claude Code is not installed on this machine. Install it, then run this again."
  exit 1
}
claude plugin marketplace add $Repo
if ($LASTEXITCODE -ne 0) { Write-Host "The marketplace may already be added; continuing." }
foreach ($p in @("qz-aidlc@qualizeal", "qz-console@qualizeal")) {
  claude plugin install $p
  if ($LASTEXITCODE -ne 0) {
    Write-Host "$p did not install. Check that you are signed in to GitHub on this machine, then run this again."
    exit 1
  }
}
Write-Host "Installed. Open Claude Code in any folder and run /qz-aidlc:qz-setup to finish (plan, usage reading, projects folder)."
