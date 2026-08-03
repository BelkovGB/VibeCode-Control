<!-- devflow:managed:start -->
## VibeCode Control process

Read `.agent-flow/config.json`, `.agent-flow/workflow.json`, `.agent-flow/skills.lock.json`, this file, and the repository's current product, architecture, policy, roadmap, and workflow documents before acting.

Rule precedence: latest explicit PM decision; current repository sources of truth; project VibeCode Control configuration; VibeCode Control defaults. Never treat an agent proposal as an approved product decision.

For delivery work:

- Use one ready Issue, one branch, and one PR.
- Size an Issue around one feature or decision. Group several small features only when they live in one place and the PR still reviews in a single pass, and add an incidental fix to the active Issue by updating its scope explicitly, never silently.
- Default to one active implementation PR. Use parallel streams only when project configuration explicitly allows them; serialize migrations, shared central files, production data, and trust-gate work.
- Keep scope and priorities unchanged unless the PM approves a product change.
- Classify task risk and map each acceptance criterion to a check and evidence.
- For behavior changes, prove `RED`, then reach `GREEN`, then refactor.
- Do not weaken tests, lint, security rules, coverage thresholds, CI, or other guardrails.
- Bind review, checks, and approval evidence to the current head SHA; a new commit invalidates stale evidence.
- Merge only the exact verified SHA with every required check green and blocking thread resolved.
- If architecture, component responsibilities, dependencies, data flow, storage, integrations, or deployment change, update `docs/ARCHITECTURE.md` and related ADR/runbook documentation in the same PR.
- Record `BLOCKED` with evidence for technical blockers. Use `HUMAN_NEEDED` only for a product decision, material compromise, unavailable access, irreversible risk, or real human approval.
- Work only where the configured directory roles allow it: `automation.workspaces` says which checkout holds the control plane, where Issue work happens and where throwaway state lives, and whether changes, dependency installation and test runs are permitted in each. Do not install dependencies or build inside the control checkout unless it is declared for that.
- Do not start the next task autonomously without a chain budget: `devflow pipeline check` reports the remainder and refuses when it is spent, the template ships `{"mode": "manual"}`, and a new budget means a new `decision_ref`.
- After two correction cycles without material progress, stop and present a concise stop-check to the PM. The cycle budget is enforced: `devflow operate --node <node> --issue <ref>` reports the remainder and blocks a spent cycle, `devflow run record` refuses an over-budget attempt, and extending it requires `--human-decision <ref>`.

For execution configuration:

- Read the effective configuration instead of guessing: `python3 .agent-flow/devflow.py --repo . config effective`.
- Every model and effort parameter carries a mode. `explicit` pins a value; `inherited` is resolved by the client at run time and must be observed and recorded; `unset` means the parameter is deliberately absent and must never be materialized; `not-applicable` belongs to a role that executes no model.
- Before moving a stage between clients, show the effective-configuration matrix, and after writing rebuild it from the actual files and compare it cell by cell. A mismatch is `BLOCKED`, never a fallback.
- Client execution configuration is not portable: agent identifiers, models, effort vocabularies, and permission profiles differ per client and require an explicit decision, not a copied default.

For review and checks:

- A successful job is not a passed check. A review node must publish the artifact its `evidence_contract` declares — review, comment, or findings — and the run record must name it as `<name>=<kind>:<reference>`.
- Verify the `conclusion` and the annotations and logs, not only that a job finished. A green `skipped`, `neutral`, or `cancelled` conclusion does not prove a check.
- If a PR changes the workflow that verifies it, determine whether the base or the head version actually executed before trusting the result. If the action requires the workflow to match the default branch, record a one-time exception and perform a full manual review.
- Do not repeat a run without changing the cause of the failure, and do not treat a re-run as a fix.
- After merge, do not dispatch a workflow against the closed PR when it needs `refs/pull/<N>/merge`; use an open test PR or the next working PR.

When posting multi-line Markdown through the GitHub CLI, pass it with `--body-file` or stdin instead of a multi-line `--body`, so line breaks survive the shell.

Before a background node runs, execute the VibeCode Control skill preflight and explicitly load every skill assigned to that node. Never fetch or update skills from the network during an ordinary background run.
<!-- devflow:managed:end -->
