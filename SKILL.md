---
name: vibecode-control
description: Use VibeCode Control to install, initialize, adopt, inspect, configure, operate, audit, repair, or upgrade a software project for controlled AI-assisted development with Codex, Claude, Git, GitHub, CI, tests, reviews, state graphs, typed role/model/effort routing with provenance, background-agent skill delivery, and evidence-based quality gates. Use when installing this skill for Codex or Claude, starting a separate product project, bringing an existing or legacy repository under the process, changing agent roles or models, resolving the effective configuration, showing the workflow graph, checking setup stages and next steps, selecting skills per graph node, diagnosing automation failures, or running a periodic scheme and skill review.
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
5. Treat `inspect`, `setup check`, `graph`, `config effective`, `audit`, `doctor`, and dry-runs as read-only. An explicit `inspect --output` may only create a new JSON report under `.agent-flow/.local/reports/`; a saved plan may only create a new JSON file under `.agent-flow/.local/plans/`.
6. Before a mutation, inspect the typed plan and diff. Use `--diff-path` and `--full-diff` for any truncated guarded file. A saved plan may be applied only with the SHA-256 printed when that exact plan was saved. Apply only within the user’s requested init, adopt, upgrade, repair, or configuration scope. Verify the resulting run immediately.

## Choose the mode

- Use `install` to place this skill into the personal Codex and Claude skill directories.
- Use `inspect` first in every unfamiliar repository.
- Use `init` only for a new or effectively empty project.
- Use `adopt` for an existing or legacy project. Measure its baseline, identify gaps, and plan small migration PRs. Do not rewrite the whole project or impose ideal absolute thresholds immediately.
- Use `operate --node <id>` before one configured background node.
- Use `graph --migrate` to add the missing review-artifact contracts to a graph written before that contract.
- Use `upgrade` to update VibeCode Control-managed files and project CLI through a diff.
- Use `doctor` for a fast offline health check.
- Use `scheme check` when the whole automation is failing, a model/effort/stack/architecture changed, retries repeat, a pinned skill changed, a review date is due, or the user asks to re-evaluate the scheme.

Install this skill for the local clients with:

```bash
devflow install [--client codex|claude|both] [--apply] [--force] [--home PATH]
```

It targets `~/.agents/skills/vibecode-control` for Codex and `~/.claude/skills/vibecode-control` for Claude. The dry-run reports source, target, file count, total bytes, source checksum, installed checksum, and the create/update/remove lists. `--apply` writes atomically, removes files left over from a previous install, and verifies the installed tree checksum against the source. It refuses to overwrite a different skill at the target path without `--force`, refuses a symlinked target, and never writes outside that client’s skills directory. `.git` is never copied and is excluded from the checksum.

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
- actual agent, model, effort, and permission profile, each with its mode and resolved source;
- expected evidence and checks;
- assigned skills or an explicit `zero-skill` decision.

For every edge, require a named condition, bounded retries, and an explicit failure destination. Validate reachability, terminal paths, unknown roles, unsafe conditions, stale merge evidence, and unbounded cycles.

Read [configuration-and-graph.md](references/configuration-and-graph.md) before changing the graph, schemas, roles, models, effort, permissions, or source precedence.

## Configure roles, models, and effort honestly

Separate logical roles from concrete agents. Use the project configuration to assign Codex, Claude, another approved executor, or a human to a role.

Every `model` and `effort` parameter in `.agent-flow/config.json`, under `roles.<role>` and `node_overrides.<node>`, is typed and carries a mode:

- `{"mode": "explicit", "value": "<model or effort>"}` — chosen and pinned;
- `{"mode": "inherited"}` — resolved by the client at run time; observe and record the actual value, never invent it;
- `{"mode": "unset"}` — deliberately absent; never materialize it into a concrete value;
- `{"mode": "not-applicable"}` — the role executes no model (agent `human`, `script`, `deterministic`).
- `{"mode": "undecided"}` — nobody has chosen yet. The neutral template ships this state; it blocks the `roles` setup stage, node preflight and any delivery `PASS` until the owner decides.

A bare string is the legacy spelling. It is accepted on read and normalized on write—a concrete value to explicit, `inherit` to inherited, `not-applicable` to not-applicable, `unset` or `unconfigured` to unset—and reported as a validation warning naming the exact pointers. `config.schema.json` defines this as `$defs.typedParameter` (explicit object, mode-only object, or legacy string) and declares `node_overrides`; `schema_version` stays `1`. A role whose agent executes no model must use not-applicable for both `model` and `effort`; an executing agent must not. A missing `model` or `effort` key is an error: write `{"mode": "unset"}` explicitly instead of letting a default appear. A declared `inherited` or `unset` mode does not warn and does not degrade preflight — it is a decision, not a gap. It is enforced at `run record`, which refuses a `PASS` unless the actually observed value is supplied.

Read the effective configuration before judging or changing execution configuration:

```bash
devflow config effective [--format table|json]
```

The matrix renders `| Узел | Этап | Владелец | Agent | Model | Model mode | Model источник | Effort | Effort mode | Effort источник |`. Model and effort resolve as `node_overrides[<node>]` → `roles[<node.role>]` → absent; permissions resolve as `node_overrides[<node>]` → the node in `.agent-flow/workflow.json` → `roles[<node.role>]`. Every resolved field reports `{value, mode, source: {level, pointer, file}}`, where `level` is `node-override`, `role`, `node`, or `absent`, `pointer` is for example `roles.reviewer.model`, and `file` is `.agent-flow/config.json` or `.agent-flow/workflow.json`. A node-level `model` or `effort` key in `workflow.json` is a validation error, not a silently ignored value.

Attach the matrix only to a plan that rewrites `.agent-flow/config.json` or `.agent-flow/workflow.json`; this keeps an unrelated earlier run verifiable after a later authorized configuration change. After such a plan is applied, the matrix is rebuilt from the files on disk and compared cell by cell with the approved plan. A mismatch aborts the apply, rolls the write back, and makes `devflow verify` return `BLOCKED` with an `effective_configuration_drift` list. There is no fallback and no reconciliation.

Use:

```bash
devflow role set <role> <agent>
devflow model set <role-or-node> <model> --effort <level>
devflow permissions set <role-or-node> <profile>
devflow config effective
devflow config show --effective
devflow graph --migrate [--apply] [--full-diff]
```

For a project installed before this contract, migrate with `devflow config normalize` (dry-run showing the plan and diff) and then `devflow config normalize --apply`. It rewrites untyped model and effort into the canonical typed form, is deterministic and idempotent—a second run returns `NOT_APPLICABLE`—and is blocked if the resulting configuration would be invalid.

Migrate a graph written before the review-artifact contract with `devflow graph --migrate`. It adds the missing contracts only to node ids that also exist in the canonical shipped graph, only by copying that graph’s declaration, and only when every contract key is already present in that node’s `expected_evidence`. A review node this tool does not ship gets no guessed artifact kind: it is listed under `requires_explicit_decision` and the operator must add the `evidence_contract` to `.agent-flow/workflow.json` explicitly. The dry-run returns `PARTIAL` with the plan and diff; `--apply` writes through the normal plan machinery under the new `graph-migrate` plan mode, which may write `.agent-flow/workflow.json` and nothing else. A graph that already declares its contracts returns `NOT_APPLICABLE`.

The full migration order for a project installed before this change is:

```bash
devflow config normalize --apply   # typed model and effort
devflow graph --migrate --apply    # review-artifact contracts
devflow upgrade --apply            # regenerated managed instructions and project CLI
```

Apply a changed model or effort only to future runs. Check its availability on the actual execution surface. If compatibility cannot be verified, report `PARTIAL` or `BLOCKED`; never select a silent fallback and never resolve an `unset` parameter into a value to make a run proceed. When a model, effort, agent, permissions, stack, or node action changes, mark that node’s skill decision for revalidation.

## Keep the portability boundary

Workflow logic is shared between Codex and Claude. Execution configuration is client-specific: agent identifiers, model names, effort vocabularies, and permission profiles are not interchangeable and must not be copied across clients without an explicit decision. Moving a stage between clients does not carry the source client’s default model or effort with it.

## Regenerate managed instructions per role

The Claude managed block is generated from the installed configuration, not a fixed template. It lists exactly the roles whose agent maps to Claude, with their permission profiles and the workflow nodes they own; it grants merge authority only when `release-operator` is assigned to Claude and otherwise states that merging is not permitted; it emits implementer-specific and reviewer/QA-specific paragraphs only for the roles actually assigned; and when no role is assigned to Claude it says exactly that instead of claiming the implementer role. Do not assume Claude is the implementer. The block always forbids combining implementation and independent final review in one session.

`AGENTS.md` keeps the client-neutral process block, extended with the execution-configuration and review rules above, the self-modifying-workflow rules, and the recommendation to pass multi-line Markdown to the GitHub CLI with `--body-file` or stdin.

Blocks are regenerated through `init`, `adopt`, `upgrade`, and `repair`. `role set` does not widen the write allowlist, so run `devflow upgrade` after reassigning a role to refresh the instructions. `devflow doctor` runs a `managed-blocks` check: a missing block or duplicated markers is `BLOCKED`; a block that is stale relative to the configured roles is `PARTIAL` with the recommendation to run `devflow upgrade`.

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

`devflow operate --node <id>` returns `effective_configuration`, `required_artifacts`, and `self_modification`—the base ref, the merge base, and which guarded paths this branch changes (`.agent-flow/`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/`, `.github/devflow/prompts/`, both `devflow-node` skill copies). When the base cannot be determined locally, it says so instead of guessing.

Require:

- a ready Issue with goal, boundaries, dependencies, risk class, acceptance criteria, relevant documents, checks, and architecture impact;
- one Issue → one branch → one PR;
- baseline measurement before tightening legacy thresholds;
- `RED → GREEN → REFACTOR` for behavior changes, with fresh RED evidence;
- characterization tests for legacy behavior when needed;
- unit, integration, contract, scenario/E2E, security, coverage, and targeted mutation checks according to risk;
- an acceptance-criterion → check → result → artifact map;
- evidence bound to the current head SHA;
- a successful delivery run record only when local Git HEAD matches, `operate` passes, every workflow `expected_evidence` has a named artifact reference, and every contracted artifact and required check is satisfied;
- no weakening of tests, lint, thresholds, CI, security policy, agent rules, or other guardrails;
- independent final review against Issue, scope, architecture, policies, and evidence;
- merge only of the exact verified SHA with required checks green and blocking threads resolved;
- only risk- or policy-required post-merge/deploy checks.

A workflow node may declare `evidence_contract`, mapping an `expected_evidence` name to `{"kind": "review"|"comment"|"findings"|"report"|"check-run", "required": true}`. The shipped graph declares it for `implementer_review` (“self-review report” → `findings`) and `final_review` (“review verdict bound to head SHA” → `review`). A review-stage node with no required contract produces a validation *warning* that names the node and states that `PASS` is forbidden for it until the graph is migrated; the graph stays valid, so `doctor`, `upgrade`, and the migration keep working. The gate is enforced where it matters: `devflow run record` refuses a `PASS` on a review-stage node that declares no required artifact, and the error names the migration command. The shape rules stay hard validation errors: a contract key that is not in `expected_evidence`, an unknown artifact kind, and a non-boolean `required`.

Record observed checks with `devflow run record --check NAME=CONCLUSION`. Allowed conclusions are `success`, `failure`, `cancelled`, `skipped`, `neutral`, `timed_out`, `action_required`, and `stale`; only `success` proves a check. A delivery `PASS` requires every contracted artifact present and written as `<name>=<kind>:<reference>`, and every check in `config.github.required_checks` reported with conclusion `success`. Any other reported conclusion—including a green-looking `skipped`—blocks the `PASS`. The gate applies on the `verification`, `review` and `release` stages. On an `implementation` stage conclusions are recorded as evidence and not judged: a `tdd_red` node must prove a test that legitimately fails, so `--check tests=failure` there is recorded and does not block the `PASS`. After merge, do not dispatch a workflow against the closed PR when it needs `refs/pull/<N>/merge`: on the post-merge node (id `post_merge` or state `POST_MERGE_VERIFY`) the CLI rejects evidence referencing that ref, because a closed PR has no such ref and a control dispatch against it fabricates a result. Before the merge that ref is the canonical merge-gate reference and stays usable.

The run record stores `checks`, plus `configured.modes` and `configured.sources` per parameter. The configured-vs-actual comparison is mode-aware: explicit must match exactly; inherited requires the actual observed value; unset requires the actual observed value while staying unset in the configuration; not-applicable rejects any actual value as fabricated.

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
