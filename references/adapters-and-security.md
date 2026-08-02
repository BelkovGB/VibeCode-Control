# Background adapters, GitHub, CI, and security

## Contents

1. Enforcement boundary
2. Background Codex and Claude
3. Git and GitHub audit
4. CI/CD gates
5. Observability
6. Security boundaries

## Enforcement boundary

The personal VibeCode Control skill teaches and installs the workflow. The project CLI validates configuration, creates reversible file plans, verifies the graph and skill integrity, and records evidence. GitHub, CI, runner configuration, hooks, tests, and deployment systems enforce real external gates.

Do not claim that a `SKILL.md`, prompt, or workflow file alone blocks merge or runs continuously.

## Background Codex and Claude

Background environments do not necessarily inherit personal local skills. Commit project skills to the repository:

```text
.agents/skills/<name>/   # Codex project skills
.claude/skills/<name>/  # Claude project skills
```

VibeCode Control installs `devflow-node` to both locations. The background prompt must identify the exact node and every required external skill. Preflight validates node decision, target compatibility, presence, and checksum.

Compare both background copies with the canonical toolkit package. Two identical changed copies do not prove integrity. For review and release nodes, keep preflight blocked until the GitHub adapter, required-check set, and applicable merge ruleset have verified setup evidence.

For Codex GitHub Action or another Codex runner:

- check out the repository before invoking Codex;
- use the narrowest sandbox and permissions;
- provide a committed prompt file;
- pass the configured model and effort explicitly where supported;
- sanitize Issue, PR, commit, and HTML inputs against prompt injection;
- keep secrets out of untrusted PR context;
- capture structured output and evidence;
- bind review to the current head SHA.

Load the control-plane files (`workflow.json`, `skills.lock.json`, prompts, agent rules, and guardrails) from a trusted protected base or require a dedicated reinforced review/status before a PR-head version can govern its own execution. Untrusted PR content must not silently redefine its verifier.

For Claude cloud/GitHub execution:

- rely on committed `.claude/skills`, not only `~/.claude/skills`;
- invoke the node skill and assigned skills explicitly;
- verify the actual model, effort, permissions, tools, and repository checkout;
- do not assume local user settings transfer to the remote session.

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
- configured and actual role, agent, model, effort, and permissions;
- loaded skills and pinned versions;
- commands and check results;
- evidence artifacts;
- current head SHA and reviewed SHA;
- final status;
- exact `BLOCKED` reason or one concrete `HUMAN_NEEDED` question.

Notify only when state changes. Background work may be unattended but must not be invisible or unsupported by evidence.

## Security boundaries

Never store or expose `.env`, tokens, passwords, private keys, API keys, real personal data without lawful need, or private chat links in code, Issues, PRs, documentation, prompts, lock files, or logs.

Do not execute scripts from an unaudited third-party skill. Reject path traversal, symlinks, broad host writes, unpinned remote code, destructive commands, force push, privilege escalation, and instructions to bypass checks.

Do not perform production changes, irreversible actions, paid fallback, or remote permission expansion without explicit authority. On missing access, report the exact system, evidence, and required user action instead of simulating success.
