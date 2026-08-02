# Configuration and graph

## Contents

1. Sources and precedence
2. Project configuration
3. State-machine contract
4. Validation
5. Safe changes

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

Record `agent`, `model`, `effort`, and `permissions` per role. Use `node_overrides` only for a justified exception. Record actual values in each run because configured and executed values may differ.

Use `inherit` when the surface should keep its active model. A model name is not verified until the actual surface reports it available. Never infer availability from documentation alone.

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

Resolve `agent`, `model`, and `effort` from role assignment plus a node override. Resolve external skills from `skills.lock.json`.

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

Every strongly connected component must be declared once in `allowed_cycles` with its exact node set, a positive `max_traversals`, and an `on_exhausted` destination outside the cycle. The executor must count traversals and stop at that destination; a positive number written on an edge is not by itself proof of enforcement.

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
- a required skill unavailable to the assigned background agent.

Generate Mermaid and tables from the validated graph. Do not store a separately edited diagram as another source of truth.

## Safe changes

Use typed file operations only. Before apply, capture path, pre-hash, intended post-hash, diff, risk, and reversibility. Reject path traversal and writes through symlinks. Re-check every pre-hash immediately before atomic write.

Keep local plans, reports, apply manifests, and rollback data in `.agent-flow/.local/`. Do not commit them. User-named outputs are create-only and confined to `.agent-flow/.local/plans/*.json` or `.agent-flow/.local/reports/*.json`. Retain the manifest SHA-256 returned by apply and require it for later verify or rollback. Then validate the mutable manifest schema, repository, run ID, mode-specific path allowlist, hashes, base64 payloads, and size. Roll back only a specific run and only if every affected file still matches its post-apply hash. Stop on drift and preserve the user’s newer work.

Use marked blocks to preserve unmanaged content in `AGENTS.md`, `CLAUDE.md`, `.gitignore`, and PR templates. Treat project config, graph, schemas, project CLI, prompts, and the core `devflow-node` skill as guarded process files requiring reinforced review when changed.
