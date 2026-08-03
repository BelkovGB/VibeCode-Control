# Background adapters, GitHub, CI, and security

## Contents

1. Enforcement boundary
2. Client portability boundary
3. Session transport
4. Background Codex and Claude
5. Managed instructions and guarded paths
6. Git and GitHub audit
7. CI/CD gates
8. Observability
9. Security boundaries

## Enforcement boundary

The personal VibeCode Control skill teaches and installs the workflow. The project CLI validates configuration, creates reversible file plans, verifies the graph and skill integrity, and records evidence. GitHub, CI, runner configuration, hooks, tests, and deployment systems enforce real external gates.

Do not claim that a `SKILL.md`, prompt, or workflow file alone blocks merge or runs continuously.

## Client portability boundary

Workflow logic is shared. The graph, stages, gates, evidence contracts, and node permissions mean the same thing for Codex and for Claude.

Execution configuration is client-specific. Agent identifiers, model names, effort vocabularies, and permission profiles are not interchangeable and must not be copied from one client to another without an explicit recorded decision.

Moving a stage between clients does not carry the source client's chosen model or effort with it, and the CLI now enforces that rather than asking for discipline. `devflow role set` compares the client of the previous agent with the client of the new one: an `explicit` model or effort is reset to `undecided` and must be chosen again, `inherited` stays because the new client resolves it itself, and `unset` and `undecided` carry no value to move. Two agents of the same client transfer without a reset. The reset is loud: the command lists every parameter it cleared.

The reset cascades into `node_overrides`. An override that names no agent of its own resolves against the role's client, so its chosen values would otherwise slip past the reset one level down; an override that names its own agent keeps its own client and its values.

Which agents exist is not guessed. The engine ships a registry of client adapters — agent identifiers, project and personal skill roots, managed instruction file, and the effort vocabulary the client can express — and a project extends it with an optional `clients` block in `.agent-flow/config.json`. The registry lives in the engine rather than the kit because `devflow install` runs without a project at all, and a copy of engine facts inside a guarded configuration would go stale without `upgrade` ever replacing it. Any reference in `roles.*.agent` or `node_overrides.*.agent` to an agent that no adapter declares is a validation error naming the exact pointer, which is what catches a typo such as `devflow_development` against `devflow-development`. Client membership is exact: a name that merely contains `codex` or `claude` is not that client. Resolve the parameters again for the target client: an `explicit` value is chosen anew, an `inherited` value is observed in the new client at run time and recorded, and an `unset` parameter stays absent instead of acquiring the previous client's default.

## Session transport

Nodes can be executed by chat sessions the owner created beforehand, coordinated by messages between those sessions. This runs the full `Issue → implementation → review → merge` cycle without GitHub Actions or cloud runners, and context isolation comes for free: different sessions are different contexts.

Whether a client can carry messages between sessions is an adapter capability, `session_messaging`, not an inference from the client name. The engine declares it `true` for `claude` and `false` for `codex`; a project whose client gained the capability extends the registry with a `clients` block instead of editing the rule.

### Create the chats before configuring

The CLI never creates, starts, or sees sessions. Create them first, then record them:

1. Decide which roles this project executes through sessions. One chat per role is the usual shape; the implementer and the independent reviewer must be different chats, and the CLI refuses a registry where one session holds both.
2. Create each chat in the client and give it a name you will not change — the registry stores the name, and a renamed chat silently stops matching.
3. Open each chat once and let it read the repository rules and `.agent-flow` configuration, so it starts from the project's own canon rather than from the assignment text.
4. Record the registry, one role at a time:

```bash
devflow config set automation.sessions '{"mode": "explicit", "client": "claude", "roles": {}}'
devflow config set automation.sessions.roles.implementer '{"mode": "explicit", "session": "<chat name>"}'
devflow config set automation.sessions.roles.reviewer '{"mode": "explicit", "session": "<chat name>"}'
```

The registry is checked against the roles it names. A role whose agent belongs to a different client cannot be bound to this transport's sessions, and neither can a role whose agent executes no model — both are refused at write time with the exact pointer, instead of surfacing later as a mismatched `actual_agent` in a run record. A role whose executor is still `unresolved` may be bound; that decision is already pending on the `roles` stage. Roles executed by `human`, `script`, or `deterministic` are never asked about a session, because an agent that executes no model receives no assignment here by definition.

A role this project does not execute through a session is `{"mode": "not-applicable"}`. A project that runs no sessions at all declares `automation.sessions` as `{"mode": "not-applicable"}`. The shipped template declares `{"mode": "undecided"}` and chooses nothing, so the `automation` setup stage asks. Run `devflow session check` to see the resolved node → session bindings, and `devflow doctor` to see the same as one finding.

### Assign a node

```bash
devflow session assign --node implement --issue 17
```

The command renders the assignment and prints it. It does not send it: delivery stays with the coordinator, because the CLI has no way to reach a chat. The text carries the session name, the node, the Issue, the actual head SHA from local Git, the expected evidence taken from the node's `evidence_contract`, the exact preflight command, the command that produces the answer, and the restart rule. The wording lives in `.agent-flow/prompts/session-assignment.md` and can be changed by the project; the facts are always filled by the CLI, so nothing is retyped and nothing drifts.

Assignment is bound to the chain budget. While `automation.pipeline` is `manual` the command refuses to render without `--pm-go <ref>`, and that reference is written into the assignment text. On a spent budget a new Issue is refused, while an Issue the budget already counted still renders — the budget counts tasks, and refusing to continue one would throw away half-finished work.

### What this transport does not prove

A named session is the owner's claim, not evidence. Liveness of a session, delivery of an assignment, and the identity of the chat behind a name are not locally verifiable, and every surface says so instead of implying a pass: `session check`, the `transport` field of `devflow operate`, and the rendered assignment. `automation.background_workers: verified` remains a separate gate that the owner sets after actually observing a run, exactly as for background runners.

If a session dies in the middle of a node, the node restarts whole from the last recorded `run record`. That record and its head SHA are the checkpoint; nobody resumes a dead session from the middle.

## Background Codex and Claude

Background environments do not necessarily inherit personal local skills. Commit project skills to the repository:

```text
.agents/skills/<name>/   # Codex project skills
.claude/skills/<name>/  # Claude project skills
```

VibeCode Control installs `devflow-node` to both locations. The background prompt must identify the exact node and every required external skill. Preflight validates node decision, target compatibility, presence, and checksum.

User-level skills are a different scope and do not travel with the repository. `devflow install [--client codex|claude|both]` installs or updates this skill at `~/.agents/skills/vibecode-control` for Codex and `~/.claude/skills/vibecode-control` for Claude. The dry run reports source, target, file count, total bytes, source checksum, installed checksum, and the create/update/remove lists; `--apply` writes atomically, deletes files left over from a previous install, and re-hashes the installed tree against the source. Installation refuses a symlinked target, refuses to overwrite a different skill at that path without `--force`, never writes outside the selected client's skills directory, and never copies `.git` or folds it into the checksum.

Compare both background copies with the canonical toolkit package. Two identical changed copies do not prove integrity. For review and release nodes, keep preflight blocked until the GitHub adapter, required-check set, and applicable merge ruleset have verified setup evidence.

For Codex GitHub Action or another Codex runner:

- check out the repository before invoking Codex;
- use the narrowest sandbox and permissions;
- provide a committed prompt file;
- pass the effective model and effort from `devflow config effective`, never a client default: an `inherited` parameter is observed in the run and recorded, an `unset` parameter stays absent;
- sanitize Issue, PR, commit, and HTML inputs against prompt injection;
- keep secrets out of untrusted PR context;
- capture structured output and evidence;
- bind review to the current head SHA.

Load the control-plane files (`workflow.json`, `skills.lock.json`, prompts, agent rules, and guardrails) from a trusted protected base or require a dedicated reinforced review/status before a PR-head version can govern its own execution. Untrusted PR content must not silently redefine its verifier.

For Claude cloud/GitHub execution:

- rely on committed `.claude/skills`, not only `~/.claude/skills`;
- invoke the node skill and assigned skills explicitly;
- verify the actual model, effort, permissions, tools, and repository checkout against the effective configuration and the mode of each parameter;
- read the generated managed block in `CLAUDE.md` for the roles this project actually assigns to Claude, instead of assuming the implementer role;
- do not assume local user settings transfer to the remote session.

## Managed instructions and guarded paths

The Claude managed block is generated from the installed configuration, not shipped as a fixed template. It lists exactly the roles whose agent maps to Claude, their permission profiles, and the workflow nodes they own; it grants merge authority only when `release-operator` is assigned and otherwise states that merging is not permitted; and when no role is assigned to Claude it says exactly that. It always forbids combining implementation and independent final review in one session. `AGENTS.md` carries the client-neutral process block shipped to every project.

Do not compare a managed block against remembered text. `devflow doctor` runs a `managed-blocks` check: a missing block or duplicated markers is `BLOCKED`; a block that is stale relative to the configured roles is `PARTIAL` with the recommendation to run `devflow upgrade`. Blocks are regenerated by `init`, `adopt`, `upgrade`, and `repair`. `role set` does not widen the write allowlist, so run `devflow upgrade` after reassigning a role to refresh the instructions.

`devflow agents normalize` is the one operation that restructures the whole of `AGENTS.md` rather than its managed block, so it is a separate explicit command with a plan, a diff and a confirmation, and its plan mode may write only `AGENTS.md`, `CLAUDE.md` and `docs/agents/**`. The split is deterministic and structural — headings decide — and completeness is verified rather than promised: every section of the original must be found in the router or in a moved document, character for character after whitespace normalisation, or no plan is produced. Shortening somebody else's text without their confirmation is content loss dressed up as normalisation, and the tool does not do it.

Two things are excluded from that accounting because the mechanism owns them: the managed block, marked in the map as regenerated, and the generated sections. Generated sections carry their own marker pair, so `doctor` can compare "Build and checks" with the measured `quality.commands` and "Repository structure" with the inspection without guessing from prose; prose that used to occupy a generated slot always moves to `docs/agents/`, since generation never melts foreign words into its own text. An unmeasured baseline yields an honest absence and the command that would measure it, never an invented command.

Nested `AGENTS.md` files are listed by the plan and never touched: both clients read them and they belong to their own directories. Monorepo zones are where that ownership will be expressed — see the zones work in #12.

Guarded control-plane paths:

```text
.agent-flow/
AGENTS.md
CLAUDE.md
.github/workflows/
.github/devflow/prompts/
.agents/skills/devflow-node/
.claude/skills/devflow-node/
```

`devflow operate --node <id>` returns `self_modification` with the base ref used, the merge base, and the guarded paths this branch changes. When the base cannot be determined locally, the report says so explicitly and leaves `self_modifying` unresolved instead of assuming the branch is safe; the base/head comparison then belongs to the GitHub adapter. A branch that rewrites its own verifier must be reviewed against the version that actually executed: check annotations and logs rather than the conclusion alone, do not re-run without changing the cause, and never dispatch a post-merge check against a closed PR whose evidence would need `refs/pull/<N>/merge`.

## Git and GitHub audit

Inspect local Git without destroying user work:

- disable repository-controlled fsmonitor and hook paths for VibeCode Control's read-only Git inspection commands;
- repository presence and worktree state;
- branch, upstream, remotes, and default branch;
- branch strategy and allowed merge methods;
- `.gitignore`, lock files, Git LFS, and large files;
- current-tree secret candidates; use dedicated approved tooling for history;
- existing `AGENTS.md`, `CLAUDE.md`, workflows, and conflicts.

Verify remote GitHub state separately through a current authenticated surface:

- rulesets or branch protection;
- required checks and merge methods;
- CODEOWNERS;
- Issue forms and PR templates;
- labels and deletion of merged branches;
- active PRs, current head, review threads, and baseline red CI;
- workflow and bot permissions.

Never infer remote enforcement from a committed YAML file.

## CI/CD gates

Configure according to stack and risk:

- explicit minimal permissions;
- external Actions pinned to commit SHA where policy requires it;
- no secrets for untrusted fork or PR code;
- timeout, concurrency, and cancellation of stale runs;
- cache isolation from untrusted data;
- lock-file and dependency verification;
- secret, dependency, license, SAST, and supply-chain checks by risk;
- reproducible tests and evidence artifacts;
- required checks tied to merge protection;
- build once and promote the same artifact when releases exist;
- readiness/health and post-deploy smoke;
- migration and rollback plans for database changes;
- backup restoration tests when production data makes them relevant.

Do not invent absolute coverage or mutation thresholds before measuring the baseline.

Treat changes to CI, test configuration, `AGENTS.md`, security policy, workflow graph, and VibeCode Control itself as guardrail changes that require reinforced review.

## Observability

Each background run should leave:

- run ID;
- Issue, branch, and PR;
- workflow node and state;
- configured and actual role, agent, model, effort, and permissions, with the mode and source of each configured parameter;
- loaded skills and pinned versions;
- commands and check conclusions; only `success` proves a check, and a green `skipped` does not;
- evidence artifacts;
- current head SHA and reviewed SHA;
- final status;
- exact `BLOCKED` reason or one concrete `HUMAN_NEEDED` question.

Notify only when state changes. Background work may be unattended but must not be invisible or unsupported by evidence.

## Security boundaries

Never store or expose `.env`, tokens, passwords, private keys, API keys, real personal data without lawful need, or private chat links in code, Issues, PRs, documentation, prompts, lock files, or logs.

Do not execute scripts from an unaudited third-party skill. Reject path traversal, symlinks, broad host writes, unpinned remote code, destructive commands, force push, privilege escalation, and instructions to bypass checks.

Do not perform production changes, irreversible actions, paid fallback, or remote permission expansion without explicit authority. On missing access, report the exact system, evidence, and required user action instead of simulating success.
