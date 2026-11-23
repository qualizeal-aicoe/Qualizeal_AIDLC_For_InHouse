# Setting up the QualiZeal AI-DLC Studio

On a laptop, from the cloned repository:

| System | Run | Checks only, installs nothing |
|---|---|---|
| Windows | `setup\bootstrap.cmd` | `setup\bootstrap.cmd -CheckOnly` |
| macOS or Linux | `sh setup/bootstrap.sh` | `sh setup/bootstrap.sh --check-only` |

The bootstrap installs what is missing into your user folder (Claude Code, uv, Python 3.12), adds the Studio to Claude
Code and runs the doctor, which should end with `Result: ready for a live session`. No administrator rights are
needed, and it is safe to run again after any fix. It writes `doctor-report.json` in the repository folder: send that
to the AI CoE (AI Center of Excellence) if a line still says FAIL.

| Also here | For |
|---|---|
| `install.ps1`, `install.sh` | IT installing many laptops: they add the marketplace and both plugins, nothing else |
| `/qz-aidlc:qz-setup org`, in Claude Code | The organisation's admin: managed settings and rollout steps |

The repository is public, so a laptop needs no GitHub account to read it. The full guide is
[docs/SETUP-GUIDE.md](../docs/SETUP-GUIDE.md).
