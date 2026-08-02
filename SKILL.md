---
name: vibecode-control
description: Use VibeCode Control to initialize, adopt, inspect, configure, operate, audit, repair, or upgrade a software project for controlled AI-assisted development with Codex, Claude, Git, GitHub, CI, tests, reviews, state graphs, role/model/effort routing, background-agent skill delivery, and evidence-based quality gates. Use when starting a separate product project, bringing an existing or legacy repository under the process, changing agent roles or models, showing the workflow graph, checking setup stages and next steps, selecting skills per graph node, diagnosing automation failures, or running a periodic scheme and skill review.
---

# VibeCode Control

Treat VibeCode Control as a reusable control plane for one product repository. Keep every product in its own project and repository. Do not depend on a shared “Vibe Code” project during product development.

Keep the internal CLI and compatibility identifiers `devflow`, `.agent-flow`, and `devflow-node`. They are implementation names, not the public skill name.

Use the personal skill to inspect, advise, and install. Use the project-local `.agent-flow/devflow.py`, configuration, state graph, GitHub/CI, and repo-scoped skills to govern background execution.

## Start safely

1. Resolve the repository root.
2. Read applicable `AGENTS.md`, `CLAUDE.md`, `README`, product scope, roadmap, architecture, policy, workflow, and active Git/GitHub state before making judgments.
3. Preserve unrelated user changes and existing instructions.
4. Run the bundled CLI explicitly; do not assume `devflow` is on `PATH`:

   ```bash
   python3 <this-skill>/scripts/devflow.py --repo <repo> <command>
   ```

   On Windows, prefer `py` instead of `python3`.
5. Treat `inspect`, `setup check`, `graph`, `audit`, `doctor`, and dry-runs as read-only. An explicit `inspect --output` may only create a new JSON report under `.agent-flow/.local/reports/`; a saved plan may only create a new JSON file under `.agent-flow/.local/plans/`.
6. Before a mutation, inspect the typed plan and diff. Use `--diff-path` and `--full-diff` for any truncated guarded file. A saved plan may be applied only with the SHA-256 printed when that exact plan was saved. Apply only within the user’s requested init, adopt, upgrade, repair, or configuration scope. Verify the resulting run immediately.

## Choose the mode

- Use `inspect` first in every unfamiliar repository.
- Use `init` only for a new or effectively empty project.
- Use `adopt` for an existing or legacy project. Measure its baseline, identify gaps, and plan small migration PRs. Do not rewrite the whole project or impose ideal absolute thresholds immediately.
- Use `operate --node <id>` before one configured background node.
- Use `upgrade` to update VibeCode Control-managed files and project CLI through a diff.
- Use `doctor` for a fast offline health check.
- Use `scheme check` when the whole automation is failing, a model/effort/stack/architecture changed, retries repeat, a pinned skill changed, a review date is due, or the user asks to re-evaluate the scheme.

Read [setup-and-commands.md](references/setup-and-commands.md) when onboarding, explaining commands, or guiding the user stage by stage.

## Follow the installation workflow

Use this sequence:

```text
inspect → normalize → plan → dry-run → apply → verify → reconcile
```

After every setup stage, show:

- `status`: `PASS`, `PARTIAL`, `BLOCKED`, or `NOT_APPLICABLE`;
- verified evidence;
- gaps and their current criticality;
- one recommendation;
- the next setup stage and exact command;
- the specific PM decision only when one is genuinely required.

Keep the product lifecycle separate from the VibeCode Control setup lifecycle. Never convert a setup hint into an unapproved `GO`, scope, roadmap, budget, priority, or architecture decision.

## Keep the graph authoritative

Treat `.agent-flow/workflow.json` as the state-machine source of truth. Generate Mermaid or a table from it; do not hand-edit a duplicate diagram.

For every node, resolve and display:

- state and entry condition;
- action;
- logical role;
- actual agent, model, effort, and permission profile;
- expected evidence and checks;
- assigned skills or an explicit `zero-skill` decision.

For every edge, require a named condition, bounded retries, and an explicit failure destination. Validate reachability, terminal paths, unknown roles, unsafe conditions, stale merge evidence, and unbounded cycles.

Read [configuration-and-graph.md](references/configuration-and-graph.md) before changing the graph, schemas, roles, models, effort, permissions, or source precedence.

## Configure roles, models, and effort honestly

Separate logical roles from concrete agents. Use the project configuration to assign Codex, Claude, another approved executor, or a human to a role.

Use:

```bash
devflow role set <role> <agent>
devflow model set <role-or-node> <model> --effort <level>
devflow permissions set <role-or-node> <profile>
devflow config show --effective
```

Apply a changed model or effort only to future runs. Check its availability on the actual execution surface. If compatibility cannot be verified, report `PARTIAL` or `BLOCKED`; never select a silent fallback. When a model, effort, agent, permissions, stack, or node action changes, mark that node’s skill decision for revalidation.

## Decide skills per node

Require an explicit skill decision for every active node, but prefer `zero-skill` whenever the current model, project rules, VibeCode Control, scripts, CI, MCP, or objective checks already cover the work.

Evaluate the concrete execution profile:

```text
node + action + agent + model + effort + permissions + stack/version + risk
```

For each node:

1. Identify the competency and actual gap.
2. Check whether a project rule, deterministic script, CI gate, MCP/app, or the model is the correct solution instead of a skill.
3. Assess each candidate for added value, duplication, staleness, conflict, context cost, background compatibility, permissions, provenance, license, and safety.
4. Classify it as `REQUIRED`, `RECOMMENDED`, `OPTIONAL`, `NOT_NEEDED`, `REJECT`, or `EVALUATE` and state the evidence level.
5. Compare `zero-skill`, the pinned incumbent, and at most three challengers under the same model, effort, permissions, code, tools, and scenarios when a runner is available.
6. If no comparison ran, say `эмпирически не проверено`; do not claim that a candidate is better.
7. Present one consolidated node table and ask one confirmation/edit question. Do not ask dozens of repetitive questions.
8. Install or replace no third-party skill without explicit user approval after the exact-content audit and diff.

Limit discovery to:

- `https://www.skills.sh`;
- `https://github.com/openai/skills` and repositories or locations directly recommended by current official OpenAI/Codex sources;
- `https://github.com/anthropics/skills` and repositories or locations directly recommended by current official Anthropic/Claude sources;
- extra sources explicitly added by the user.

Do not use general GitHub search, blogs, awesome lists, or unrestricted web discovery. Treat skills.sh ranking and audits as signals, not proof.

Read [skill-governance.md](references/skill-governance.md) completely before searching, auditing, registering, assigning, syncing, evaluating, updating, replacing, or removing a skill.

## Deliver skills to background agents

Keep approved project skills copied—not symlinked—under both applicable locations:

```text
.agents/skills/<skill>/
.claude/skills/<skill>/
```

Pin the canonical repository to a full commit SHA, record a deterministic tree checksum, license, audit date, review date, targets, and node assignments in `.agent-flow/skills.lock.json`.

Accept a pin only from a clean tracked Git checkout whose `HEAD`, origin, tracked file set, and canonical source URL match. Protect the lock, vendor copies, workflow, prompts, and agent rules with repository review/CODEOWNERS; local fields are not a cryptographic replacement for an external approval gate.

Before each background node:

1. Run `skills verify --node <id>`.
2. Require the workflow prompt to name `devflow-node` and every assigned required skill explicitly.
3. Compare both `devflow-node` copies with the canonical project toolkit copy; do not accept equal coordinated drift.
4. Stop as `BLOCKED` on unresolved decisions, missing copies, checksum drift, incompatible targets, or unavailable executors.
5. Never fetch or update skills from the network during an ordinary run.

Guarantee delivery, explicit invocation, integrity, and objective outcome checks. Do not claim to prove that a model “mentally applied” a skill.

## Enforce evidence-based delivery

Use the delivery path from `.agent-flow/workflow.json`. Treat model reviews as secondary controls; objective tests and quality gates provide the primary evidence.

Require:

- a ready Issue with goal, boundaries, dependencies, risk class, acceptance criteria, relevant documents, checks, and architecture impact;
- one Issue → one branch → one PR;
- baseline measurement before tightening legacy thresholds;
- `RED → GREEN → REFACTOR` for behavior changes, with fresh RED evidence;
- characterization tests for legacy behavior when needed;
- unit, integration, contract, scenario/E2E, security, coverage, and targeted mutation checks according to risk;
- an acceptance-criterion → check → result → artifact map;
- evidence bound to the current head SHA;
- a successful delivery run record only when local Git HEAD matches, `operate` passes, and every workflow `expected_evidence` has a named artifact reference;
- no weakening of tests, lint, thresholds, CI, security policy, agent rules, or other guardrails;
- independent final review against Issue, scope, architecture, policies, and evidence;
- merge only of the exact verified SHA with required checks green and blocking threads resolved;
- only risk- or policy-required post-merge/deploy checks.

If architecture, component responsibility, dependency, data flow, storage, integration, or deployment changes, update `docs/ARCHITECTURE.md` and related ADR/runbook documentation in the same PR. Block merge until the canonical documentation describes the post-merge reality.

Read [process-and-quality.md](references/process-and-quality.md) when preparing Issues, executing work, reviewing, merging, managing backlog, diagnosing stalled work, or reporting limits.

## Audit external enforcement separately

Distinguish local files from actual GitHub and runner settings. A workflow file does not prove that a remote ruleset requires its check.

Use read-only local inspection first. Then, when appropriate access exists, verify remote rulesets, required checks, current PR head, review threads, CI, merge policy, and runner permissions through the available GitHub surface. Never report external settings as changed or verified without fresh evidence.

Keep review and release preflight `BLOCKED` until GitHub adapter access, the remote required-check set, and—on release nodes—the merge ruleset have been verified. Local configuration is not a substitute for GitHub enforcement.

Read [adapters-and-security.md](references/adapters-and-security.md) before configuring GitHub Actions, background Codex or Claude, branch protection, CI/CD, secrets, deploy, notifications, or remote automation.

## Run periodic scheme checks deliberately

Do not re-search and re-evaluate every skill on every run.

Use fast `doctor` for configuration, graph, setup, security, presence, and checksum checks. Use `scheme check` for:

- repeated node or gate failures;
- a changed model, effort, agent, stack, architecture, or workflow;
- a VibeCode Control or pinned-skill update;
- a due `review_after` date;
- an explicit user request to test or repair the scheme.

During a scheme check:

1. Inspect recent node evidence, retries, `BLOCKED`, `HUMAN_NEEDED`, and escaped defects.
2. Re-evaluate roles, graph edges, models, effort, permissions, gates, and delivery surfaces.
3. Re-test the incumbent against `zero-skill` where practical.
4. Search alternatives only through the allowlist.
5. Shortlist no more than three candidates per problem node.
6. Return `KEEP`, `UPDATE`, `REPLACE`, `REMOVE`, `ZERO_SKILL`, or `NEEDS_EVAL` with evidence.
7. Build a reversible repair plan. Do not apply a new or replacement third-party skill automatically.

Allow automatic repair only for a technically damaged copy of an already approved pinned artifact when the source copy is intact and the user’s requested repair scope covers it. Require the user for any new skill, role/scope/budget change, material architecture compromise, unavailable access, irreversible action, or real human approval.

## Report truthfully

Lead with the result or next practical step. Explain technical meaning plainly.

Never expose secret values, private chat links, personal data, signed URLs, or credentials in repository artifacts or reports. Never claim an unobserved test, CI result, deployment, model availability, approval, or PM decision.

When usage telemetry is unavailable, write exactly:

```text
нет доступной телеметрии
```
