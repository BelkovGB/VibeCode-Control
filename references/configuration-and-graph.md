# Configuration and graph

## Contents

1. Sources and precedence
2. Project configuration
3. Typed model and effort
4. Effective configuration
5. State-machine contract
6. Validation
7. Safe changes

## Sources and precedence

Resolve conflicts in this order:

1. Latest explicit PM decision for product scope, priorities, budget, and human approval.
2. Current repository sources of truth for actual behavior and project-specific rules.
3. `.agent-flow/config.json` for execution assignments and VibeCode Control policy.
4. VibeCode Control defaults.

Choose the source by question:

| Question | Source of truth |
| --- | --- |
| What actually works | `main`, code, tests, and fresh runtime verification |
| What is being implemented | Open PR head, review threads, and CI |
| What an implementer must do | Ready Issue and its fresh comments |
| Product scope | Approved product strategy and current product rules |
| Priorities | Roadmap, tracking Issues, and the latest PM decision |
| Agent behavior | Applicable `AGENTS.md`, `CLAUDE.md`, policy, workflow, and VibeCode Control config |
| Why a decision was made | Decision log or ADR, treated as history rather than live state |

## Project configuration

Use JSON so project-local tooling works with Python stdlib on Windows and POSIX. Validate `.agent-flow/config.json` against the bundled schema and deterministic checks.

Keep logical roles independent from concrete agents:

- `human-pm`;
- `product-lead`;
- `researcher`;
- `architect`;
- `implementer`;
- `reviewer`;
- `qa`;
- `release-operator`.

Record `agent`, `model`, `effort`, and `permissions` per role. Use `node_overrides` only for a justified exception. Record actual values in each run because configured and executed values may differ. That comparison is mode-aware: `explicit` must match the actual value exactly, `inherited` and `unset` require the actual observed value while the configuration stays as written, and `not-applicable` rejects any actual value as fabricated.

A model name is not verified until the actual surface reports it available. Never infer availability from documentation alone.

Workflow logic is shared between Codex and Claude. Execution configuration is not: agent identifiers, model names, effort vocabularies, and permission profiles are client-specific and must not be copied across clients without an explicit decision. Moving a stage to another client does not carry the source client's default model or effort with it.

## Typed model and effort

Every `model` and `effort` parameter under `roles.<role>` and `node_overrides.<node>` states its mode. `config.schema.json` defines the shape once as `$defs.typedParameter` and now also declares `node_overrides`; `schema_version` stays 1.

Chosen and pinned:

```json
"model": {"mode": "explicit", "value": "<model the client reports available>"},
"effort": {"mode": "explicit", "value": "high"}
```

Resolved by the client at run time. It must be observed and recorded during the run, never invented:

```json
"model": {"mode": "inherited"}
```

Deliberately absent. It must never be materialized into a concrete value:

```json
"effort": {"mode": "unset"}
```

The role executes no model, because its agent is `human`, `script`, or `deterministic`:

```json
"model": {"mode": "not-applicable"},
"effort": {"mode": "not-applicable"}
```

Only `explicit` carries a `value` key. A `value` next to any other mode is an error, so nothing absent can later be mistaken for something configured.

The neutral template ships every machine role as `agent: "unresolved"` with `model` and `effort` in `{"mode": "undecided"}`, and `policy.language` as `"undecided"`. `undecided` is not the same as `unset`: `unset` is the owner's decision that a parameter is absent and does not hold anything, while `undecided` means nobody has chosen and blocks the `roles` setup stage, node preflight and any delivery `PASS`. An `unresolved` agent forbids a decided `model` or `effort`: choosing a model before an executor would decide on the owner's behalf.

A role whose agent does not execute a model must use `not-applicable` for both `model` and `effort`; an executing agent must not use it for either. A missing `model` or `effort` key is an error, not an implicit default: write `{"mode": "unset"}` explicitly.

A bare string is the legacy spelling. It is accepted on read and normalized on write:

| Legacy scalar | Normalized to |
| --- | --- |
| A concrete value, for example `"high"` | `{"mode": "explicit", "value": "high"}` |
| `"inherit"` | `{"mode": "inherited"}` |
| `"not-applicable"` | `{"mode": "not-applicable"}` |
| `"unset"` | `{"mode": "unset"}` |
| `"unconfigured"` or `"undecided"` | `{"mode": "undecided"}` |

While legacy spellings remain, validation emits a warning naming the exact pointers, for example `roles.reviewer.model`. `devflow model set` takes the scalar on the command line and stores the typed form.

Migrate an installed project with `devflow config normalize`. The dry run shows the plan and the diff and returns `PARTIAL` with the next command; `devflow config normalize --apply` writes the rewritten file. The rewrite is deterministic and idempotent, so a second run returns `NOT_APPLICABLE`. It returns `BLOCKED` and writes nothing if the normalized configuration would be invalid.

## Effective configuration

Resolve `model` and `effort` in this order: `node_overrides.<node>`, then `roles.<role>`, then absent. Resolve `permissions` in this order: `node_overrides.<node>`, then the node in `workflow.json`, then `roles.<role>`.

Every resolved field reports `{value, mode, source: {level, pointer, file}}`. `level` is `node-override`, `role`, `node`, or `absent`. `pointer` is the exact key, for example `roles.reviewer.model`. `file` is `.agent-flow/config.json` or `.agent-flow/workflow.json`, and both are null when the level is `absent`.

`devflow config effective [--format table|json]` renders the matrix:

```
| Узел | Этап | Владелец | Agent | Model | Model mode | Model источник | Effort | Effort mode | Effort источник |
```

Read each parameter across its three columns: the value, the mode that says how it was chosen, and the pointer that says which key chose it. A parameter with no configured value renders `—`, so for `inherited`, `unset`, and `not-applicable` the mode column carries the meaning. `--format json` returns the same rows with the `agent` and `permissions` cells included and with the source pointer, file, and level for every field.

Read the matrix twice around every change. Before apply it is attached to every plan that rewrites `.agent-flow/config.json` or `.agent-flow/workflow.json`, so the reviewer approves the resolved execution profile rather than a diff of keys. A plan that leaves both of those files untouched carries no matrix, which keeps an unrelated earlier run verifiable after a later authorized configuration change. After apply the matrix is rebuilt from the files on disk and compared cell by cell with the approved plan, across stage, state, owner, agent, model, effort, their modes, and permissions.

Any difference aborts the apply and rolls the write back, and `devflow verify` returns `BLOCKED` with the differences listed in `effective_configuration_drift` as `<node>.<cell>: план=…, файлы=…`. There is no fallback and no reconciliation. On that status the files no longer match what was approved: do not re-run apply and do not hand-edit a file to match the matrix. Fix the pointer named in the difference, rebuild the plan, and have it approved again.

`devflow operate --node <id>` returns `effective_configuration` for the node alongside `required_artifacts` and `self_modification`.

## State-machine contract

Treat `.agent-flow/workflow.json` as canonical. Each node must contain:

```json
{
  "id": "implement",
  "stage": "implementation",
  "state": "GREEN_REFACTOR",
  "entry_condition": "red.proven",
  "action": "implement_minimal_scope_then_refactor",
  "role": "implementer",
  "permissions": "workspace-write-no-merge",
  "competencies": ["stack implementation"],
  "inputs": ["ready issue", "failing test"],
  "expected_evidence": ["passing targeted tests", "head SHA"],
  "checks": ["scope unchanged", "guardrails preserved"],
  "timeout_minutes": 180
}
```

Resolve `agent`, `model`, and `effort` from `.agent-flow/config.json` only, through the role assignment and an optional node override. A `model` or `effort` key written inside a workflow node is a validation error, because it would be silently ignored. Resolve external skills from `skills.lock.json`.

A node may declare `evidence_contract`, which binds a name from `expected_evidence` to the artifact that proves the node ran:

```json
"expected_evidence": ["review verdict bound to head SHA"],
"evidence_contract": {
  "review verdict bound to head SHA": {"kind": "review", "required": true}
}
```

`kind` is one of `review`, `comment`, `findings`, `report`, `check-run`. Every contract key must also appear in `expected_evidence`, and `required` must be a boolean. A node in the `review` stage should declare at least one required artifact: a successful job without the artifact it was supposed to produce is not a passed check. A review-stage node without one is a validation warning, not an error — the warning names the node and states that `PASS` is forbidden for it until the graph is migrated, so a graph written before this contract stays valid and `doctor`, `upgrade`, and the migration keep working on it. The gate is enforced at record time: `devflow run record` refuses a `PASS` on a review-stage node that declares no required artifact and names the migration command. The shipped graph declares the contract for `implementer_review`, where `self-review report` is `findings`, and for `final_review`, where `review verdict bound to head SHA` is `review`.

Migrate an older graph with `devflow graph --migrate`. The dry run shows the plan and the diff and returns `PARTIAL` with the next command; `devflow graph --migrate --apply` writes `.agent-flow/workflow.json` through the normal plan machinery under the `graph-migrate` plan mode, which may write that file and nothing else. The tool only migrates node IDs that also exist in the canonical shipped graph, only by copying that graph's declaration, and only when every contract key is already present in that node's `expected_evidence`. A review node this skill does not ship is never given a guessed artifact kind: it is listed under `requires_explicit_decision`, and the operator adds its `evidence_contract` to `.agent-flow/workflow.json` explicitly. A graph that already declares its contracts returns `NOT_APPLICABLE`. For a project installed before both contracts the full order is `devflow config normalize --apply`, then `devflow graph --migrate --apply`, then `devflow upgrade --apply`.

Each edge must contain:

```json
{
  "from": "quality_gates",
  "to": "fix_findings",
  "condition": "quality.failed",
  "max_retries": 2,
  "on_failure": "human_needed"
}
```

Use only named predicates. Do not execute arbitrary expressions or shell from graph conditions.

Every strongly connected component must be declared once in `allowed_cycles` with its exact node set, a positive `max_traversals`, and an `on_exhausted` destination outside the cycle.

The CLI counts the traversals, so the number is enforced rather than merely written down. For one cycle and one Issue, `traversals = max over the cycle's nodes of (records of that node − 1)`: a traversal is a re-entry, and the first record of each node is free because nodes on the main path are recorded once before any correction. Only `PASS`, `PARTIAL` and `FAIL` count; `BLOCKED` and `HUMAN_NEEDED` are stops and never consume the budget.

Records are grouped by a normalized Issue key: the reference is trimmed, a GitHub issue URL contributes its number, otherwise the last integer in the string is used, otherwise the lowercased string. The key is stored in the run record as `issue_key` beside the raw `issue`, so the grouping can be audited. Two unrelated references that normalize to the same key only tighten the budget, which is the safe direction. Every record of a node inside a declared cycle therefore requires `--issue`, for every status.

`devflow operate --node <node> --issue <ref>` reports the budget and turns `BLOCKED` when it is spent, so another traversal never starts. `devflow run record` keeps a per-node backstop: a node already recorded `max_traversals + 1` times is refused without `--human-decision <ref>`. The cap is deliberately per node rather than global, because the review tail of the last legal traversal is written after the traversal count has already reached its maximum.

The count comes from the local run-record history of this checkout, and `.agent-flow/.local/` is not committed. Counting across machines belongs to the coordinator, which must pass the same `--issue`.

`automation.workspaces` records the directory roles: `control_checkout` holds the control plane, `issue_worktree` is where the work for an Issue happens, and `scratch` is throwaway state. A role is either `{"mode": "explicit", "path": ..., "changes": ..., "dependencies": ..., "tests": ...}`, or `not-applicable` when the project has no such directory, or `undecided` until the owner chooses. The three permissions are booleans and required, because "may I build here" is a decision rather than an assumption. The shipped kit declares nothing, so the setup stage asks for each role with one concrete question.

`devflow doctor` reports what it can check locally: a declared directory that does not exist, a control checkout that doubles as the issue worktree, dependency installation permitted inside the control checkout, and a scratch directory that lives inside the repository without being ignored by git.

`quality.validation_plan` maps a change type to the checks it may skip: each entry needs `paths` that define the type, a `skip_checks` list, and a `reason`, because an exclusion is explained rather than assumed. The shipped kit carries no plan, so nothing is minimized until the owner writes one. An entry that names a merge-gate invariant, a check required by the repository, or a required `evidence_contract` artifact is rejected by validation.

`clients` extends the engine's adapter registry. Each entry declares `agents`, `project_skill_root`, `personal_skill_root`, `managed_instructions`, an `effort` vocabulary and a `models` list; the shipped kit carries no block, and a project adds one only for a client the engine does not know. The `effort` vocabulary states what the client can express: an `explicit` effort outside it is a validation error, and at a client that declares no vocabulary an `explicit` or `inherited` effort is an error too, because there is nothing to confirm it against. The error names the extension path. `models` stays empty by default — a verified list belongs to `models.available`, which is a project fact rather than an engine one.

`automation.pipeline` bounds the chain of tasks rather than the passes inside one. `{"mode": "manual"}` is the shipped default and runs nothing autonomously; `{"mode": "count", "value": N, "decision_ref": "<ref>"}` allows N tasks; `{"mode": "until", "value": "<issue-ref>", "decision_ref": "<ref>"}` runs up to and including a control task, whose reference is normalized by the same rule as a run record's Issue. A task counts as consumed once any run record exists for its Issue since the budget started, so while a budget is active every record requires `--issue`. The budget's identity is `(decision_ref, mode, value)`: a new decision restarts the count, and changing the mode or value under the same reference is refused as a silent extension. `devflow pipeline check` reports the remainder and the reason for a refusal.

`policy.max_fix_cycles` caps every declared `max_traversals`. Its ceiling is 3; a value from 4 to 10 additionally requires `policy.max_fix_cycles_decision_ref`, a non-empty reference to the PM decision that raised it. `max_retries` on an edge outside `allowed_cycles` is a separate executor-side mechanism and is not part of this budget.

## Validation

Block automation on:

- duplicate, malformed, or unknown node IDs;
- unknown roles;
- missing actions, permissions, evidence, checks, or timeout;
- missing entry or terminal node;
- unreachable nodes;
- a nonterminal node without an exit;
- an outgoing edge from a terminal node;
- missing or unbounded retry limits;
- an unknown failure destination;
- an unsafe condition string;
- a merge path without verified head SHA and green required checks;
- a required skill unavailable to the assigned background agent;
- a `model` or `effort` key inside a workflow node;
- a missing `model` or `effort` key on a role, an unknown mode, or a `value` next to a non-explicit mode;
- `not-applicable` on an executing agent, or an executable mode on `human`, `script`, or `deterministic`;
- an evidence contract key absent from `expected_evidence`, an unknown artifact kind, or a non-boolean `required`;
- an effective-configuration matrix rebuilt from the files that does not match the approved plan.

Warn without blocking on a review-stage node that declares no required artifact. The warning names the node and states that `PASS` is forbidden for it until the graph is migrated with `devflow graph --migrate --apply`; the graph stays valid and `devflow run record` refuses the `PASS`.

Generate Mermaid and tables from the validated graph. Do not store a separately edited diagram as another source of truth.

## Safe changes

Use typed file operations only. Before apply, capture path, pre-hash, intended post-hash, diff, risk, and reversibility. Reject path traversal and writes through symlinks. Re-check every pre-hash immediately before atomic write.

Keep local plans, reports, apply manifests, and rollback data in `.agent-flow/.local/`. Do not commit them. User-named outputs are create-only and confined to `.agent-flow/.local/plans/*.json` or `.agent-flow/.local/reports/*.json`. Retain the manifest SHA-256 returned by apply and require it for later verify or rollback. Then validate the mutable manifest schema, repository, run ID, mode-specific path allowlist, hashes, base64 payloads, and size. Roll back only a specific run and only if every affected file still matches its post-apply hash. Stop on drift and preserve the user’s newer work. When the plan carries an effective-configuration matrix, apply also rebuilds it from the written files before the manifest is stored and rolls the whole run back on any difference.

Use marked blocks to preserve unmanaged content in `AGENTS.md`, `CLAUDE.md`, `.gitignore`, and PR templates. Treat project config, graph, schemas, project CLI, prompts, and the core `devflow-node` skill as guarded process files requiring reinforced review when changed.
