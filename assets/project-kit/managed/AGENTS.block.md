<!-- devflow:managed:start -->
## VibeCode Control process

Read `.agent-flow/config.json`, `.agent-flow/workflow.json`, `.agent-flow/skills.lock.json`, this file, and the repository's current product, architecture, policy, roadmap, and workflow documents before acting.

Rule precedence: latest explicit PM decision; current repository sources of truth; project VibeCode Control configuration; VibeCode Control defaults. Never treat an agent proposal as an approved product decision.

For delivery work:

- Use one ready Issue, one branch, and one PR.
- Default to one active implementation PR. Use parallel streams only when project configuration explicitly allows them; serialize migrations, shared central files, production data, and trust-gate work.
- Keep scope and priorities unchanged unless the PM approves a product change.
- Classify task risk and map each acceptance criterion to a check and evidence.
- For behavior changes, prove `RED`, then reach `GREEN`, then refactor.
- Do not weaken tests, lint, security rules, coverage thresholds, CI, or other guardrails.
- Bind review, checks, and approval evidence to the current head SHA; a new commit invalidates stale evidence.
- Merge only the exact verified SHA with every required check green and blocking thread resolved.
- If architecture, component responsibilities, dependencies, data flow, storage, integrations, or deployment change, update `docs/ARCHITECTURE.md` and related ADR/runbook documentation in the same PR.
- Record `BLOCKED` with evidence for technical blockers. Use `HUMAN_NEEDED` only for a product decision, material compromise, unavailable access, irreversible risk, or real human approval.
- After two correction cycles without material progress, stop and present a concise stop-check to the PM.

Before a background node runs, execute the VibeCode Control skill preflight and explicitly load every skill assigned to that node. Never fetch or update skills from the network during an ordinary background run.
<!-- devflow:managed:end -->
