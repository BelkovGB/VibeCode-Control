# User help and setup stages

## Contents

1. Quick start
2. Two lifecycles
3. Setup stages
4. Status contract
5. Command map
6. Windows examples
7. Common blockers

## Quick start

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

Use `setup mark` only for evidence that cannot be derived locally, such as a completed pilot. A manual `PASS` must not override a deterministic graph, checksum, security, or configuration failure.

## Status contract

- `PASS`: current evidence confirms the stage.
- `PARTIAL`: work can continue carefully, but a gap or external verification remains.
- `BLOCKED`: continuing would violate a required decision, integrity check, or safety gate.
- `NOT_APPLICABLE`: the stage is not relevant and the reason is recorded.

Do not use `PASS` for “looks plausible,” “file exists,” or “agent said done.”

## Command map

```text
devflow help [overview|modes|setup|configuration|skills|safety|windows]

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
devflow config show --effective
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
devflow operate --node <id>
devflow run record --node <id> --status <status> --head-sha <sha> --issue <ref> --pr <ref> --evidence "<expected_evidence>=<artifact-ref>" --actual-agent <id> --actual-model <id> --actual-effort <level>
devflow run show [run-id]
```

`config`, `role`, `model`, `permissions`, `skills assign/none`, and `setup mark` are explicit configuration mutations for future runs. They still record a local apply manifest.

Default plan output is a bounded diff preview. If a guarded file is truncated, rerun with `--diff-path <path> --full-diff`. Reports and plans may only create new JSON files in their dedicated `.agent-flow/.local/reports/` and `.agent-flow/.local/plans/` directories; they never overwrite an existing path. When a plan is saved, retain the printed SHA-256 and provide it to `apply`; any changed plan must be reviewed and hashed again.

For a delivery-node `PASS`, repeat `--evidence` for every exact label in that node’s `expected_evidence`, for example `--evidence "passing targeted tests=ci://run/123"`. VibeCode Control also requires a clean worktree at the actual local Git HEAD, Issue/PR references, observed agent/model/effort, a passing node preflight, and the stage-specific remote prerequisites.

## Windows examples

From PowerShell in the project root:

```powershell
py .agent-flow\devflow.py setup next
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
| Unresolved node skill decision | Background prompt is incomplete | Review the node matrix and accept skill or zero-skill |
| Skill checksum drift | Pinned content was altered | Quarantine; inspect diff; restore pinned copy or approve update |
| Remote GitHub settings unverified | Local workflow file is not an enforced gate | Query rulesets/required checks through GitHub |
| Baseline unmeasured | Thresholds would be invented | Run existing project commands and capture results |
| Rollback drift | User or agent changed a managed file after apply | Stop; reconcile manually without destroying new work |
| Two failed correction cycles | The approach is stalling | Present stop-check options and PM recommendation |
