# Readiness audit

Scores: 0 absent, 1 partial, 2 in place. Ready at 70% overall with no blocker at zero. Blockers: SEC-1 credentials
in the repository, SEC-3 side-effect tools without approval, SEC-4 unsandboxed code execution, REL-1 no loop limit,
EVAL-1 no gold set.

The scan matches patterns. A match shows the mechanism exists in the code, not that it is correct or covers every
path. When reviewing: open each evidence line; downgrade a 2 that is only a comment or dead code; say which findings
you verified by reading.

Scoring the MANUAL items (give file and line, or what you opened and saw):

| Item | 2 means | 0 means |
|---|---|---|
| SEC-5 untrusted content apart from instructions | retrieved text, tool results and user files are delimited or screened at every entry point and cannot set tool targets | user or retrieved text is concatenated into the system prompt, or chooses a recipient, id or path |
| SEC-7 MCP servers and plugins | every server is pinned to a version or fixed URL and listed with an owner | unpinned `npx -y`, `@latest`, or servers nobody can name |
| SEC-8 personal data | the data the agent sees is listed; logs and traces mask it | raw personal data in logs or traces |
| SEC-9 keys outside the agent | the agent process holds no long-lived key: a gateway or proxy adds it, or a short-lived token is issued per run | an API key sits in the agent's environment or config |
| SEC-10 outbound allow-list | every host the agent may call is listed, ideally enforced at an egress proxy; metadata addresses are blocked | the agent can fetch any URL a page or ticket gives it |
| SEC-11 identity per agent | each agent has its own service account or workload identity; logs show which agent acted | agents share one key or one account |
| OBS-2 trace content | one real trace shows run id, tool calls with status, tokens and the decision, and no secrets | no trace could be produced, or it holds secrets |
| OBS-3 drift alerts | an alert with a threshold and a named receiver exists for errors, cost or quality | nobody is told |
| GOV-5 data path | each data item is classified and the provider terms it travels under are written down | unknown |

Map findings to OWASP when reporting: LLM01 prompt injection, LLM02 sensitive information disclosure, LLM03 supply
chain, LLM05 improper output handling, LLM06 excessive agency, LLM09 misinformation, LLM10 unbounded consumption;
ASI01 to ASI10 as listed in `patterns.md`.
