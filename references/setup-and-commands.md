# User help and setup stages

## Contents

1. Quick start
2. Two lifecycles
3. Setup stages
4. Status contract
5. Command map
6. Doctor findings
7. Migration for earlier installations
8. Windows examples
9. Common blockers

## Quick start

Install the skill for your own client first, dry-run then apply:

```bash
python3 <devflow-skill>/scripts/devflow.py install
python3 <devflow-skill>/scripts/devflow.py install --client claude --apply
```

Run a read-only inspection first:

```bash
python3 <devflow-skill>/scripts/devflow.py --repo <project> inspect
```

Use the recommended mode:

```bash
# New repository: show diff, then apply
python3 <devflow-skill>/scripts/devflow.py --repo <project> init
python3 <devflow-skill>/scripts/devflow.py --repo <project> init --apply

# Existing repository: show diff, then apply
python3 <devflow-skill>/scripts/devflow.py --repo <project> adopt
python3 <devflow-skill>/scripts/devflow.py --repo <project> adopt --apply
```

After installation, use the project-local copy:

```bash
python3 .agent-flow/devflow.py setup next
```

## Two lifecycles

Do not mix the product lifecycle with VibeCode Control setup.

Product lifecycle:

1. Hypothesis research and `GO / PIVOT / HOLD / STOP` recommendation.
2. Product definition and explicit PM approval.
3. Development readiness.
4. Development and release.
5. Backlog management.
6. Stall control.
7. Limits and cost control.

VibeCode Control setup lifecycle:

1. Inspection.
2. Product context.
3. Roles, agents, models, effort, and permissions.
4. State graph.
5. Canonical documentation.
6. Local Git and remote GitHub.
7. Baseline and quality gates.
8. Skills per node.
9. Background automation.
10. One low-risk pilot Issue.

## Setup stages

Use `setup check` after every material configuration step. Use `setup next` to show the first stage that is not `PASS` or `NOT_APPLICABLE`.

Each result must include:

```json
{
  "status": "PASS | PARTIAL | BLOCKED | NOT_APPLICABLE",
  "evidence": [],
  "gaps": [],
  "recommendation": "one practical recommendation",
  "next_stage": "stage or null",
  "next_command": "exact command or null",
  "requires_user_decision": false
}
```

The `roles` stage is not confirmed by a filled-in configuration file. Verify it against the effective-configuration matrix from `devflow config effective`: every node with its stage, owner, agent, model, and effort, plus the mode of each model and effort value and the source that produced it. The mode is one of `explicit` (chosen and pinned), `inherited` (resolved by the client at run time, so the actual value must be observed and recorded, never invented), `unset` (deliberately absent and never materialized into a concrete value), or `not-applicable` (the role executes no model, as for the `human`, `script`, and `deterministic` agents). The source names the level — `node-override`, `role`, `node`, or `absent` — with its pointer, for example `roles.reviewer.model`, and the file it came from.

A legacy bare string is still accepted on read, but it produces a validation warning naming the exact pointers and holds the stage at `PARTIAL` until `devflow config normalize --apply` runs. A configuration error holds the stage at `BLOCKED`: a role whose agent does not execute a model must use `not-applicable` for both model and effort, an executing agent must not use `not-applicable`, and a missing `model` or `effort` key is an error that asks the author to write `{"mode": "unset"}` explicitly instead of letting a default appear. An unverified or ambiguous parameter stays `PARTIAL` or `BLOCKED`; VibeCode Control does not resolve it with a default or a silent fallback. A declared `inherited` or `unset` mode is not ambiguous: it is a recorded decision, it carries no value to verify, and it does not hold the stage. A parameter still in `{"mode": "undecided"}`, or a role whose `agent` is still `"unresolved"`, does hold it: the stage is `BLOCKED` and every pending decision is listed with the exact command that settles it. The `context` stage likewise requires an explicit `policy.language`; the template ships no default. That requirement is enforced when evidence is recorded, where the actually observed value must be supplied.

Use `setup mark` only for evidence that cannot be derived locally, such as a completed pilot. A manual `PASS` must not override a deterministic graph, checksum, security, or configuration failure.

## Status contract

- `PASS`: current evidence confirms the stage.
- `PARTIAL`: work can continue carefully, but a gap or external verification remains.
- `BLOCKED`: continuing would violate a required decision, integrity check, or safety gate.
- `NOT_APPLICABLE`: the stage is not relevant and the reason is recorded.

Do not use `PASS` for “looks plausible,” “file exists,” or “agent said done.”

Preparing the GitHub side of a repository — rulesets, required checks, Actions policy, secrets and merge policy — is a step-by-step runbook of its own: [github-preparation.md](github-preparation.md). It gives each setting a verify command and states what VibeCode Control reports without it.

## Command map

```text
devflow help [overview|modes|setup|configuration|install|skills|safety|windows]
devflow install [--client codex|claude|both] [--apply] [--force] [--home <path>]

devflow inspect [--deep] [--output .agent-flow/.local/reports/<new-name>.json]
devflow init|adopt|upgrade [--apply] [--full-diff] [--diff-path <relative-path>]
devflow plan init|adopt|upgrade|repair [--output .agent-flow/.local/plans/<new-name>.json] [--full-diff] [--diff-path <relative-path>]
devflow apply --plan <relative-path> --expected-sha256 <hash-shown-when-saved>
devflow verify <run-id> --expected-manifest-sha256 <hash-returned-by-apply>
devflow rollback <run-id> --expected-manifest-sha256 <hash-returned-by-apply>

devflow setup check [--stage <id>]
devflow setup next
devflow setup mark <stage> <status> --evidence <reference>
devflow status
devflow next

devflow graph --format mermaid|table|json
devflow graph --migrate [--apply] [--full-diff]
devflow config show --effective
devflow config effective [--format table|json]
devflow config normalize [--apply] [--full-diff]
devflow config set <dotted-path> <JSON-or-string>
devflow role set <role> <agent>
devflow model set <role-or-node> <model> --effort <level>
devflow permissions set <role-or-node> <profile>

devflow skills list
devflow skills recommend|plan [--node <id>]
devflow skills explain <node>
devflow skills search [--node <id>]
devflow skills register|update <name> --path <folder> --source <url> --commit <sha> --license <license> --approved-by-user --apply
devflow skills assign <name> --node <id> --level required|recommended|optional
devflow skills none --node <id> --reason <text>
devflow skills unassign <name> --node <id>
devflow skills remove <name> [--apply]
devflow skills audit [--node <id>] [--deep]
devflow skills verify [--node <id>]
devflow skills sync [--apply]
devflow skills evaluate <node>

devflow audit git|code|quality|ci|docs|security|skills|all [--deep]
devflow doctor [--deep] [--refresh-skills] [--repair-plan]
devflow scheme check
devflow scheme repair [--apply]
devflow pipeline check
devflow scale show
devflow scale set <profile> --decision-ref <ref>
devflow session check
devflow session assign --node <id> --issue <ref> [--change-type <type>] [--pm-go <ref>]
devflow operate --node <id> [--issue <ref>]
devflow run record --node <id> --status <status> --head-sha <sha> --issue <ref> --pr <ref> --evidence "<expected_evidence>=<artifact-ref>" --check <name>=<conclusion> --human-decision <ref> --actual-agent <id> --actual-model <id> --actual-effort <level>
devflow run show [run-id]
```

`config`, `role`, `model`, `permissions`, `skills assign/none`, and `setup mark` are explicit configuration mutations for future runs. They still record a local apply manifest.

`devflow config effective` renders one row per node: `| Узел | Этап | Владелец | Agent | Model | Model mode | Model источник | Effort | Effort mode | Effort источник |`. Model and effort resolve as `node_overrides[node]` → `roles[node.role]` → absent; permissions resolve as `node_overrides[node]` → the node in `workflow.json` → `roles[node.role]`. A node-level `model` or `effort` key in `workflow.json` is a validation error, not a silently ignored field: move it to `node_overrides` in `.agent-flow/config.json`. `devflow model set <role-or-node> <model> --effort <level>` writes the typed form: a concrete value becomes `explicit`, while `inherit`, `unset`, and `not-applicable` set the matching mode with no value.

Default plan output is a bounded diff preview. If a guarded file is truncated, rerun with `--diff-path <path> --full-diff`. Reports and plans may only create new JSON files in their dedicated `.agent-flow/.local/reports/` and `.agent-flow/.local/plans/` directories; they never overwrite an existing path. When a plan is saved, retain the printed SHA-256 and provide it to `apply`; any changed plan must be reviewed and hashed again.

A plan that rewrites `.agent-flow/config.json` or `.agent-flow/workflow.json` carries the effective-configuration matrix it promises; a plan that touches other files does not, so an unrelated earlier run stays verifiable after a later authorized configuration change. After such a plan is applied, the matrix is rebuilt from the files actually written to disk and compared with the approved one cell by cell. A mismatch aborts the apply, the write is rolled back, and `devflow verify` returns `BLOCKED` with an `effective_configuration_drift` list. There is no fallback and no automatic reconciliation: fix the configuration and build a new plan.

For a delivery-node `PASS`, repeat `--evidence` for every exact label in that node’s `expected_evidence`, for example `--evidence "passing targeted tests=ci://run/123"`. VibeCode Control also requires a clean worktree at the actual local Git HEAD, Issue/PR references, observed agent/model/effort, a passing node preflight, and the stage-specific remote prerequisites.

A node may additionally declare an `evidence_contract` that binds an `expected_evidence` label to an artifact kind — `review`, `comment`, `findings`, `report`, or `check-run` — and marks it required. The shipped graph declares it for `implementer_review` (“self-review report” → `findings`) and `final_review` (“review verdict bound to head SHA” → `review`). Every contracted artifact must be present and written as `<name>=<kind>:<reference>`; the kind is part of the proof. The shape rules are hard validation errors: a contract key that is not in `expected_evidence`, an unknown artifact kind, and a non-boolean `required`. A review-stage node that declares no required artifact is only a validation warning — it names the node and states that `PASS` is forbidden for that node until the graph is migrated. The graph therefore stays valid, so `doctor`, `upgrade`, and the migration keep working on a project installed before this contract existed. The gate is enforced where it matters instead: `devflow run record` refuses a `PASS` on a review-stage node that declares no required artifact, and the error names the migration command.

`devflow graph --migrate [--apply] [--full-diff]` adds the missing review-artifact contracts to a graph written before the contract existed. It migrates only node IDs that also exist in the canonical shipped graph, only by copying that graph’s declaration, and only when every contract key is already present in that node’s `expected_evidence`. A review node this skill does not ship is never given a guessed artifact kind: it is listed under `requires_explicit_decision`, and the operator adds the `evidence_contract` to `.agent-flow/workflow.json` explicitly. The dry run returns `PARTIAL` with the plan and the diff; `--apply` writes through the normal plan machinery under the `graph-migrate` plan mode, which is allowed to write `.agent-flow/workflow.json` and nothing else. A graph that already declares its contracts returns `NOT_APPLICABLE`.

Report observed checks with `--check <name>=<conclusion>`. Allowed conclusions are `success`, `failure`, `cancelled`, `skipped`, `neutral`, `timed_out`, `action_required`, and `stale`. Only `success` proves a check: a reported `skipped` or `neutral` blocks the `PASS`, and every name in `config.github.required_checks` must be reported with `success`. The gate applies on the `verification`, `review` and `release` stages. On an `implementation` stage conclusions are recorded as evidence and not judged: a `tdd_red` node must prove a test that legitimately fails, so `--check tests=failure` there is recorded and does not block the `PASS`. After the merge, do not dispatch a workflow against the closed PR when it needs `refs/pull/<N>/merge`: the ref no longer exists, so the dispatch fabricates a result instead of proving one. `devflow run record` rejects such evidence on the post-merge node only — id `post_merge` or state `POST_MERGE_VERIFY`. Before the merge that ref is the canonical merge-gate reference and stays usable.

The run record stores the reported `checks` and, per parameter, `configured.modes` and `configured.sources`. Comparison of configured against actual is mode-aware: `explicit` must match exactly; `inherited` requires the actually observed value; `unset` requires the observed value while the configuration stays unset; `not-applicable` rejects any actual value as fabricated.

A node inside a declared cycle also carries a budget. Pass `--issue <ref>` to `operate` to see how many traversals this Issue has spent and how many remain; without it the budget cannot be evaluated and the preflight says so. A spent budget makes the preflight `BLOCKED` and asks for the six-point Stall control analysis, and `run record` refuses a further attempt on that node without `--human-decision <ref>`. The count comes from the local run-record history of this checkout.

`devflow operate --node <id>` returns the node preflight together with `effective_configuration`, `required_artifacts` (the node’s evidence contract), and `self_modification` — the base ref used, the merge base, and which guarded paths this branch changes (`.agent-flow/`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/`, `.github/devflow/prompts/`, both `devflow-node` skill copies). If the base cannot be determined locally, it says so instead of guessing.

`devflow install` installs this skill as a personal skill: Codex at `~/.agents/skills/vibecode-control`, Claude at `~/.claude/skills/vibecode-control`. The dry-run reports source, target, file count, total bytes, source checksum, installed checksum, and the create/update/remove lists. `--apply` writes atomically, removes files left over from a previous install, and verifies the installed tree checksum against the source. It refuses to overwrite a different skill at the target path without `--force`, refuses a symlinked target, and never writes outside that client’s skills directory. `.git` is never copied and is excluded from the checksum.

Workflow logic is shared between Codex and Claude. Execution configuration is not: agent identifiers, model names, effort vocabularies, and permission profiles are client-specific and must not be copied across clients without an explicit decision. Moving a stage from one client to the other does not carry the source client’s default model or effort with it.

## Doctor findings

`devflow doctor` returns one finding per check — `config`, `graph`, `skills-lock`, `skills`, `setup`, `security`, `project-cli`, `managed-blocks`, `skill-review-schedule` — and the overall status is the worst of them.

`managed-blocks` compares the managed block in `AGENTS.md` and `CLAUDE.md` with the block generated from the installed configuration:

- `PASS`: both blocks match the configured roles.
- `PARTIAL`: a block is present but stale relative to the configured roles; run `devflow upgrade`.
- `BLOCKED`: a block is missing, or its markers are missing or duplicated.
- `NOT_APPLICABLE`: the project configuration is not installed yet.

The Claude block is generated, not a fixed template. It lists exactly the roles whose agent maps to Claude, with their permission profiles and the workflow nodes they own; it grants merge authority only when `release-operator` is assigned to Claude and otherwise states that merging is not permitted; it emits implementer-specific and reviewer/QA-specific paragraphs only for the roles actually assigned; and when no role is assigned to Claude it says exactly that instead of claiming the implementer role. It always forbids combining implementation and independent final review in one session. `AGENTS.md` keeps the client-neutral process block.

Blocks are regenerated by `init`, `adopt`, `upgrade`, and `repair`. `devflow role set` changes the configuration only and does not widen the write allowlist to the instruction files, so run `devflow upgrade --apply` after reassigning a role, then re-check `doctor`.

## Migration for earlier installations

A project installed before the typed execution contract keeps bare `model` and `effort` strings, and a project installed before the review-artifact contract keeps review nodes with no `evidence_contract`. Both are accepted on read and reported as validation warnings naming the exact pointers or nodes, so the configuration and the graph stay usable. Migrate in three steps, each shown as a dry-run before it is applied:

```bash
python3 .agent-flow/devflow.py config normalize
python3 .agent-flow/devflow.py config normalize --apply
python3 .agent-flow/devflow.py graph --migrate
python3 .agent-flow/devflow.py graph --migrate --apply
python3 .agent-flow/devflow.py upgrade
python3 .agent-flow/devflow.py upgrade --apply
```

Keep that order: `config normalize --apply` for the typed model and effort, `graph --migrate --apply` for the review-artifact contracts, `upgrade --apply` to regenerate the managed instructions and the project CLI.

`config normalize` shows the plan and diff first. It rewrites each bare string into its canonical typed form: a concrete value becomes `{"mode": "explicit", "value": "<value>"}`, `"inherit"` becomes `{"mode": "inherited"}`, `"not-applicable"` becomes `{"mode": "not-applicable"}`, and `"unset"` or `"unconfigured"` becomes `{"mode": "unset"}`. It is deterministic and idempotent: a second run returns `NOT_APPLICABLE`. It returns `BLOCKED` if the normalized configuration would be invalid, so fix the configuration instead of forcing the migration. `schema_version` stays `1`.

`graph --migrate` shows the plan and diff first and writes only `.agent-flow/workflow.json` under the `graph-migrate` plan mode. It copies the declaration from the canonical shipped graph for every node ID that graph also contains, and only when every contract key already appears in that node’s `expected_evidence`. A review node this skill does not ship is reported under `requires_explicit_decision` instead of being given a guessed kind: add its `evidence_contract` by hand. A graph that already declares its contracts returns `NOT_APPLICABLE`.

`upgrade --apply` then regenerates the role-aware managed blocks from the installed roles and the project CLI. Confirm with `devflow doctor` that `config` and `graph` have no warnings and `managed-blocks` is `PASS`.

It also refreshes `.agent-flow/setup-stages.json`, so a setup stage this skill added after the project was installed becomes part of `setup`. Until that runs, the diagnostic commands stay usable instead of failing on the missing stage: `setup check`, `setup next`, and `doctor` still report every stage this CLI evaluates, and a stage the installed definitions do not declare is reported as `PARTIAL` with the gap “Определения этапов устарели (нет `<stage>`)” and `devflow upgrade` as its next command.

## Windows examples

From PowerShell in the project root:

```powershell
py .agent-flow\devflow.py setup next
py .agent-flow\devflow.py config effective
py .agent-flow\devflow.py config show --effective
py .agent-flow\devflow.py model set reviewer <model> --effort xhigh
py .agent-flow\devflow.py skills verify --node implement
py .agent-flow\devflow.py doctor
```

Use `python3 .agent-flow/devflow.py ...` on Linux and macOS. Do not tell the user that the `devflow` executable exists globally unless it was actually installed in `PATH`.

## Common blockers

| Blocker | Meaning | Next action |
| --- | --- | --- |
| Product stage unassessed | VibeCode Control cannot infer PM approval | Record the stage and decision reference |
| Model unavailable or unverified | The configured executor may not run as specified | Verify the actual surface or choose explicitly |
| Untyped model or effort | Configuration predates the typed execution contract | Run `config normalize`, review the diff, then `--apply` |
| Effective-configuration drift | Files on disk do not match the approved matrix | Apply was rolled back and `verify` is BLOCKED; fix the configuration and build a new plan |
| Stale or missing managed block | Instructions no longer match the configured roles | Run `devflow upgrade --apply`, then re-check `doctor` |
| Stage definitions older than the CLI | `.agent-flow/setup-stages.json` predates a stage this skill added; `setup` and `doctor` keep working and mark the stage `PARTIAL` | Run `devflow upgrade`, review the diff, then `--apply` |
| Contracted review artifact missing | A green run is not a passed review | Record the artifact as `<name>=<kind>:<reference>` or keep the node below PASS |
| Review node declares no required artifact | Graph predates the review-artifact contract; validation warns and `run record` refuses PASS | Run `devflow graph --migrate`, review the diff, then `--apply` |
| Unresolved node skill decision | Background prompt is incomplete | Review the node matrix and accept skill or zero-skill |
| Skill checksum drift | Pinned content was altered | Quarantine; inspect diff; restore pinned copy or approve update |
| Remote GitHub settings unverified | Local workflow file is not an enforced gate | Query rulesets/required checks through GitHub |
| Baseline unmeasured | Thresholds would be invented | Run existing project commands and capture results |
| Rollback drift | User or agent changed a managed file after apply | Stop; reconcile manually without destroying new work |
| Two failed correction cycles | The approach is stalling | Present stop-check options and PM recommendation |
