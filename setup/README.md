# Setting up the QualiZeal AI-DLC Studio

Pick the line that matches you. Each one ends in Claude with `/qz-aidlc:qz-setup`, which records your plan,
turns on the usage reading (with your yes) and creates the projects folder.

| You are | Do this |
|---|---|
| In an organisation whose admin syncs plugins | Nothing: the Studio appears in Claude. Run `/qz-aidlc:qz-setup`. |
| On your own plan (Pro, Max, Ultra), in the Claude app | Customize > Plugins > Add marketplace `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`, then install qz-aidlc and qz-console. |
| On a laptop with Claude Code | `/plugin` > Marketplaces > Add `qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`, then install both. For IT installing many laptops: `install.ps1` (Windows) or `install.sh` (macOS, Linux, WSL) in this folder do the same and are safe to run again. |
| The organisation's admin | In Claude Code run `/qz-aidlc:qz-setup org`: it writes the managed settings and the rollout steps. |

The repository is private, so a laptop install needs you signed in to GitHub on that machine.
The full guide is [docs/SETUP-GUIDE.md](../docs/SETUP-GUIDE.md).
