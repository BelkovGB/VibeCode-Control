# Product, delivery, and quality rules

## Contents

1. Authority
2. Product lifecycle
3. Ready Issues and backlog
4. Implementation and evidence
5. Review, merge, and documentation
6. Self-modifying workflows
7. Stall control
8. Limits

## Authority

The user/PM approves product focus, target audience, MVP boundaries, roadmap, major priorities, budget, material compromises, and `GO / PIVOT / HOLD / STOP`.

The product/technical lead investigates, recommends, designs architecture inside approved scope, prepares Issues, manages backlog, reviews, verifies, and performs allowed merge/release operations.

The implementer executes a ready Issue, writes tests, fixes verified findings, and prepares a PR. The implementer does not change product scope, roadmap, or priorities and does not merge.

Do not treat an AI proposal as a PM decision. Within approved scope, make safe technical and operational decisions without repeatedly asking the PM.

## Product lifecycle

### Hypothesis research

Determine the problem, audience, present alternatives, competitors, evidence of demand and willingness to pay, monetization, development and operating cost, technical/platform/legal/reputation risks, and the cheapest test of the critical assumptions.

End with `GO`, `PIVOT`, `HOLD`, or `STOP` as a recommendation. The PM decides. Keep rejected or pre-GO research outside the code repository; after `GO`, store only the approved product summary needed by the team.

### Product definition

Propose audience, value, primary scenario, MVP in/out, success and stop criteria, risks, experiments, and high-level roadmap. Require explicit PM approval before treating it as scope.

### Development readiness

Decompose only the nearest stage in detail. Establish architecture, repository rules, canonical documents, roles, tests, CI, review, release gates, and ready Issues. Do not create a detailed distant backlog prematurely.

## Ready Issues and backlog

An Issue is ready only if it contains:

- goal;
- explicit scope and exclusions;
- completed or named dependencies;
- acceptance criteria;
- relevant canonical documents;
- risk class;
- required checks and evidence;
- architecture-impact decision and documents to update;
- no unresolved product choice;
- no conflict with active work.

The architecture-impact decision is not made while writing the Issue. The graph has a `design` node between the scope gate and Issue preparation: the architect produces the design decision (an ADR when the architecture impact is real), the test specification, and the Issue draft, and Issue preparation packages that output. Its check requires the architecture-impact entry to reference the design artifact rather than to invent one, so the same decision is not taken twice in two places.

Design is bounded by the declared project scale. `project.scale` names a profile whose complexity budget states what this project is allowed to be — a prototype gets one service, an OSS library counts every dependency as its consumers' dependency — and the budget travels with the node assignment so the proposal is made against it rather than judged after the fact. The budget is declared, not measured: `final_review` checks that the solution matches the declared scale, and a proposal that exceeds it has to justify the excess rather than hope nobody counts. A task's risk class may raise gates above the profile defaults; it may not lower them.

Design produces a proposal, never a product decision. When designing surfaces a choice that the approved scope does not cover, the node routes to `human_needed` under `design.decision_required` — the same way the scope gate already routes an unapproved product question. There is no return edge into the scope gate: the PM answers, and the run starts again with an approved scope.

Use one Issue, one branch, and one PR. Use `Closes #N` only for complete delivery and `Related to #N` for an explicitly accepted partial split.

Size an Issue around one feature or one decision. Decompose larger work until each part is ready on its own; a piece that cannot reach Definition of Ready without carrying several unrelated decisions is not one Issue.

Several small related features may share one Issue only when they live in the same place — one file or one module — and the resulting PR still reviews in a single pass.

A small incidental fix in a module already being changed belongs in the active Issue, added by explicitly updating its scope rather than silently. Anything the active scope does not cover goes back to the backlog.

Do not mix a change to a guarded or central file with feature work unless the feature genuinely requires it: a guarded change deserves its own review attention.

The boundary is qualitative and has no invented threshold. When a PR stops being reviewable in one pass — a reviewer cannot hold its scope, evidence, and risk at once — the work needed decomposition earlier, and the next Issue must be split.

Default to one active implementation PR. Enable two independent streams only through an explicit project decision and configuration. When parallel work is enabled:

- keep at most one implementation PR in each stream;
- branch from the current default branch;
- keep fixes and implementations in separate branches and PRs;
- do not use stacked PRs unless separately approved;
- serialize work that touches the same central files, migrations or schemas, production data, trust gates, or another high-collision surface;
- use current GitHub state as the source of stream occupancy.

Use GitHub as the source of active work. Keep `Issue → run → branch → PR → head SHA` traceability. Maintain roadmap links, dependencies, blockers, duplicates, and obsolete work. Do not let urgent small changes silently displace the stage goal.

Revise priorities when demand, principal risk, blocking impact, cost, simpler alternatives, MVP relevance, or user evidence materially changes. Explain consequences and require PM approval for a product-level change.

## Implementation and evidence

Measure existing checks before changing a legacy project. Introduce stricter gates progressively from a documented baseline.

For behavior changes:

1. Create or select a test that fails for the intended missing behavior.
2. Capture fresh RED evidence and confirm the failure reason.
3. Implement the smallest complete change to reach GREEN.
4. Refactor without losing GREEN.

Use characterization tests when old behavior is not safely specified. Select unit, integration, contract, scenario/E2E, security, changed-code coverage, and mutation checks by risk. Limit mutation testing to critical changed logic.

Keep fixtures, seed data, and environments reproducible. Do not use retries to conceal flaky or real failures. Never weaken existing tests, linters, type checks, security rules, thresholds, CI, or workflow rules to make a PR green.

Every required gate states where it came from. `repository-policy` is what the repository itself demands — the checks in `github.required_checks` and the merge-gate invariants. `skill` is what the graph and its skills demand — a node's `checks` and the artifacts of its `evidence_contract`. `risk-escalation` is what the risk class added. An unknown origin is an error. Each gate also carries a `scope`, today always `repository`, and a `reason`.

A small change may run a smaller set of checks, but only where the repository's policy allows it. Declare the change type with `--change-type`; the CLI verifies the declaration against the actual diff and grants the minimal plan only when every changed path belongs to that type. A claim the diff does not support grants nothing and says which paths fell outside it. Without a comparable base, with no visible change at all, with no `quality.validation_plan`, or with a type the policy does not declare, the full set applies and the reason is stated rather than left silent.

Minimization covers what to run, never what to trust. Only `skill`-origin node checks and the extent of the quality commands can be reduced. The merge-gate invariants, the artifacts of an `evidence_contract`, the cycle and chain budgets, and the reinforced review of guarded files are never removable — by any change type and by any owner policy. A `validation_plan` that names one of them in `skip_checks` is a configuration error.

A run record keeps the three states apart and never collapses them: `required-and-proven`, `not-required-for-this-change` with the change type and the reason it was excluded, and `required-and-unproven`, which blocks. A reader a year later must be able to tell a gate that did not apply from a gate that was skipped.

Map every acceptance criterion to a check, observed result, and durable artifact. Bind evidence to the current head SHA. A new commit invalidates prior approval and any result that no longer corresponds to the code.

Record the outcome with `devflow run record`. A delivery `PASS` requires named evidence: every entry of the node's `expected_evidence` written as `<name>=<reference>`, and every artifact the node's `evidence_contract` marks as required written as `<name>=<kind>:<reference>`, so the kind is proven instead of assumed.

Report checks with `devflow run record --check NAME=CONCLUSION`. Allowed conclusions: `success`, `failure`, `cancelled`, `skipped`, `neutral`, `timed_out`, `action_required`, `stale`. Only `success` proves a check. Any other reported conclusion blocks the `PASS`, and every name in `config.github.required_checks` must be reported as `success` before a delivery `PASS`. The gate applies on the `verification`, `review` and `release` stages. On an `implementation` stage conclusions are recorded as evidence and not judged: a `tdd_red` node must prove a test that legitimately fails, so `--check tests=failure` there is recorded and does not block the `PASS`.

The run record compares the configured execution parameters (`agent`, `model`, `effort`) with the observed ones by mode:

- `explicit` — the actual value must match the configured value exactly; a silent fallback is a failure;
- `inherited` — the value the client actually used must be observed and recorded;
- `unset` — record the actually used value in the run record, but never write it back into the configuration;
- `not-applicable` — the role executes no model; recording any model or effort for it is fabricated evidence and is rejected;
- `undecided` — nobody has chosen the parameter yet; the node cannot preflight and cannot record a `PASS` until the owner decides.

An observed effort must belong to the client's effort vocabulary; a value the client cannot express is a lie in any mode and is rejected. When the client declares no effort vocabulary at all, an `unset` effort needs no observed value: the record stores it as absent with `effort_note: client-has-no-effort-vocabulary`, which is a contract rather than a substituted value. The record also stores the resolved `client`.

The record stores `checks` plus `configured.modes` and `configured.sources` per parameter, so a later reader sees which value was pinned, which was observed at run time, and where each came from.

## Review, merge, and documentation

Use implementer review and independent final review as additional safeguards. Verify against the ready Issue, product scope, architecture, project policy, actual diff, and fresh objective evidence. Never combine implementation and independent final review in one session.

A successful job is not a passed check. A review node declares its artifact in `evidence_contract`, mapping an expected evidence name to a kind — `review`, `comment`, `findings`, `report`, or `check-run`. The shipped graph declares `self-review report` as `findings` for `implementer_review` and `review verdict bound to head SHA` as `review` for `final_review`. Without that artifact recorded as `<name>=<kind>:<reference>` the node cannot be `PASS`. A graph written before this contract keeps review nodes that declare nothing: validation warns and names the node instead of failing, so the graph stays valid, and `devflow run record` refuses the `PASS` on such a node until `devflow graph --migrate --apply` adds the missing contracts. Read the conclusion together with annotations and logs; a job that merely finished proves nothing.

Require the implementer to fix the full verified class of a defect and add regression protection. Close blocking threads. Keep the branch current according to repository policy.

Merge only when:

- agreed scope is complete;
- every acceptance criterion is verified;
- every check in `config.github.required_checks` is reported with conclusion `success` for the current head;
- blocking findings and threads are resolved;
- documentation matches actual post-merge behavior;
- PR description matches current head;
- no secret or unapproved feature is introduced;
- approval matches the exact head SHA.

When architecture changes, update `docs/ARCHITECTURE.md` in the same PR. Update related diagrams, `README`, ADRs, and runbooks as needed. Document the resulting reality, not a plan or discussion history. Block merge if architecture docs are stale.

Run only post-merge, deploy, smoke, or operational checks required by repository policy, task criteria, or change risk. After the merge, do not dispatch a workflow against the closed PR when it needs `refs/pull/<N>/merge`: the ref no longer exists, so the dispatch fabricates a result instead of proving one. Use an open test PR or the next working PR. `devflow run record` rejects evidence referencing `refs/pull/<N>/merge` on the post-merge node only — id `post_merge` or state `POST_MERGE_VERIFY`. Before the merge that ref is the canonical merge-gate reference and stays usable.

Pass multi-line Markdown to the GitHub CLI with `--body-file` or stdin instead of a multi-line `--body`, so line breaks survive the shell.

## Self-modifying workflows

A PR that changes the control plane verifying it may be checked by a version other than the one under review. Guarded paths are `.agent-flow/`, `AGENTS.md`, `CLAUDE.md`, `.github/workflows/`, `.github/devflow/prompts/`, and both `devflow-node` skill copies.

- `devflow operate --node <id>` reports `self_modification`: the base ref, the merge base, and the guarded paths this branch changes. If the base cannot be determined locally it says so; do not guess it.
- Determine whether the base or the head version actually executed before trusting a result.
- Inspect annotations and logs, not only the conclusion.
- Do not repeat a run without changing the cause of the failure; a re-run is not a fix.
- When an action requires workflow identity with the default branch, record a one-time exception with its reason and perform a full manual review of the change.

## Stall control

Stop after no more than two correction cycles without material progress. Present:

1. Exact blocker.
2. Why another identical cycle is unlikely to help.
3. Evidence already checked.
4. Options: continue, simplify, split, replace approach, defer, or stop.
5. Consequences for time, quality, risk, and roadmap.
6. Recommended option.

The PM decides. Continue only safe independent work while waiting; do not repeat the blocked approach indefinitely.

These six points are the required format of the analysis when a cycle budget runs out. The CLI counts the traversals so the executor is no longer the only one counting.

A traversal is a re-entry, not a visit. Nodes on the main path are recorded once before any correction happens, so the first record of each node in a declared cycle is free: for one cycle and one Issue, `traversals = max over the cycle's nodes of (records of that node − 1)`. Only `PASS`, `PARTIAL` and `FAIL` count; `BLOCKED` and `HUMAN_NEEDED` are stops and never consume the budget they report on.

Enforcement has two layers. `devflow operate --node <node> --issue <ref>` reports the traversals and the remainder, and turns `BLOCKED` once the budget is spent, so another traversal never starts. `devflow run record` keeps a per-node cap as a backstop: a record of a node already stored `max_traversals + 1` times is refused. The cap is per node rather than global on purpose — the review tail of the last legal traversal is written after the traversal count has already reached its maximum, and must remain recordable.

Extending a spent budget is possible only through `--human-decision <ref>`, a non-empty reference to the PM decision. `devflow run record` stores it in the run record, and `devflow operate` accepts the same flag so the coordinator can proceed after the decision instead of being stopped by the preventive layer. The reference neither resets the budget nor raises `max_traversals`: it authorizes one step, the budget stays reported as spent with the reference beside it, and every later step must name it again. There is no silent extension.

Every record of a node inside a declared cycle requires `--issue`, for every status: a stop that is not attributed to an Issue is as useless as an attempt that is not.

The budget is counted from the local run-record history of this checkout. `.agent-flow/.local/` is not committed, so a background runner on a fresh checkout starts from an empty history. This layer is a backstop; counting across machines is the coordinator's responsibility, and it must pass the same `--issue`.

Edge retries — `max_retries` on an edge outside `allowed_cycles`, such as the one on `tdd_red` — are a separate executor-side mechanism and are not covered by this budget.

### Chain budget

A cycle budget bounds the passes inside one task. The chain from one merged task to the next is bounded separately, and an autonomous chain runs only against an explicit budget.

`automation.pipeline` states it: `{"mode": "manual"}` runs nothing autonomously and is what the template ships, `{"mode": "count", "value": N, "decision_ref": "<ref>"}` allows N tasks in a row, and `{"mode": "until", "value": "<issue-ref>", "decision_ref": "<ref>"}` runs up to and including a control task. A budget is a PM decision, so `count` and `until` require a non-empty `decision_ref`.

The coordinator calls `devflow pipeline check` before starting the next task, as required by the node-dispatch protocol. It reports the remainder, whether the next task is allowed, and — when it is not — the exact reason to paste into the report.

A task is consumed when at least one run record exists for its Issue since the budget started, whatever the status: `BLOCKED` and `HUMAN_NEEDED` consume a task too, because the attempt was made. Here the unit is a task, not a pass, and stopping early is safer than stopping late. While a budget is active, every run record therefore requires `--issue`: an unattributed record would spend the budget invisibly.

The budget's identity is the triple `(decision_ref, mode, value)`. A new decision starts the count again, and there is no separate reset command by construction. Changing the mode or the value under the same reference is refused at the moment of the change, and the configuration is not written: raising `count` from 5 to 50 without a new decision would be a silent extension. Repeating the same command is idempotent and keeps the count. `pipeline check` repeats the comparison, which is what catches a configuration edited by hand outside the CLI.

When the budget runs out, stop the chain and present the analysis:

1. Done — Issues, PRs and merged head SHAs.
2. In progress — what is started and where it stands.
3. Blocked — what is stuck and on what.
4. Recommendation — the next step, and the budget being requested for it.

The count comes from the local run-record history of this checkout, exactly as for the cycle budget.

## Limits

Track observed rate, review, context, tool, or runner limit signals. Consolidate independent checks and avoid unnecessary repeated reads. Warn when the selected order may exhaust an observable resource.

Never invent quota, token use, remaining percentage, or agent cost. If exact telemetry is unavailable, report:

```text
нет доступной телеметрии
```

Do not use an automatic paid fallback.

When the PM requests an end-of-day limit report, include completed major work, observed limit signals, the known remainder or the exact unavailable-telemetry phrase, risk for the next cycle, work to defer, and one concrete efficiency recommendation. A scheduled report requires a separate automation and an observable telemetry source.
