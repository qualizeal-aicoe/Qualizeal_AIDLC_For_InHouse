## QualiZeal names

The plugins, commands, agents, tool server, policy files, scripts, settings (`QZ_...`) and records folder (`.qz/`) all start with `qz`. Every guard rule id starts with `QZ-`, so a refusal reads `[qz-guard] ... (rule QZ-SH-ENV-CREDS)`.

{parts_table}

Agents QualiZeal wrote: {agents_list}.

The Deliver lane also uses the 14 agents of AWS AI-DLC. Their file names stay as AWS ships them, because the AI-DLC engine finds each agent by that name and a renamed file would not be found. What you see on screen is the QualiZeal name:

{roster_table}

The {n_tools} tools sit under the `qz` tool server, so a tool's full name is `mcp__plugin_qz-aidlc_qz__<tool>`. Two things do not carry the prefix on their own: the tool names, because the server name already does, and the four demo starters (`story-site`, `ops-dashboard`, `agent-console`, `arch-flow`), which are template folders inside the plugin.
