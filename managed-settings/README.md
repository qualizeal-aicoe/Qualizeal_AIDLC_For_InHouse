# Managed settings for QualiZeal AI-DLC

For the admin of a Claude Team or Enterprise organisation. Two ways to deliver `managed-settings.json`:

- **claude.ai admin console** (server-managed settings): reaches laptops and cloud sessions.
- **A file on each laptop** (MDM or a script): `C:\Program Files\ClaudeCode\managed-settings.json` on Windows,
  `/Library/Application Support/ClaudeCode/managed-settings.json` on macOS, `/etc/claude-code/managed-settings.json`
  on Linux and WSL. Cloud sessions do not read the file.

People cannot override these settings. They:

- register the QualiZeal marketplace (`qualizeal-aicoe/Qualizeal_AIDLC_For_InHouse`) and turn on `qz-aidlc` and `qz-console`;
- allow Sonnet, Opus and Haiku, with Sonnet as the default (`availableModels` with `enforceAvailableModels`), and leave
  Fable out (`deniedModels`): it is billed to usage credits on Pro and has its own weekly cap on Max and Ultra, so allow it
  only once someone owns that spend. The Studio's router and agents move heavy work to Opus and light work to Haiku;
- cap effort at high (`maxEffortLevel`, Claude Code 2.1.267 or later): people can still pick low or medium;
- turn off "bypass permissions" mode;
- pre-approve the read-only QualiZeal tools (Knowledge Fabric search, report card, routing, voice check);
- deny reading credentials, the pricing workbook and `.qz/internal/`, and editing the audit chain, run ledgers and sealed outputs.
  This is a second fence: the plugin's guard enforces the same rules from its hook.

To make a version for your organisation (another repository, the plan name for routing, Opus as the default, or Fable
allowed), run `/qz-aidlc:qz-setup org` in Claude Code: it writes this file and the admin's rollout steps.

Deliberately not set: `allowManagedHooksOnly`. It would also block the AWS AI-DLC engine's project hooks in
`.claude/settings.json`, which the Deliver lane needs. Turn it on only once those hooks are moved into managed settings.
Check the keys against the current Claude Code settings reference before rolling out; settings evolve.
