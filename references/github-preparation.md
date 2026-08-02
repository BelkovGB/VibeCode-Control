# GitHub preparation runbook

## Contents

1. What this runbook is for
2. Before you start
3. How to read a step
4. Repository basics
5. Branch ruleset and merge protection
6. CI and required checks
7. Background runners and secrets
8. Templates
9. Merge policy
10. Review-gate requirements
11. Record the result in VibeCode Control
12. Verify the whole stage
13. Common blockers

## What this runbook is for

VibeCode Control governs delivery, but it does not enforce it. Issues are the backlog, pull requests and CI are the external gates, and merge applies to one verified SHA. All of that lives on GitHub, so a repository that is not prepared leaves the release-critical gates correctly `BLOCKED`.

This runbook is an instruction, not an automation. VibeCode Control never changes a GitHub setting for you: it checks what you claim and refuses to accept a claim without fresh evidence. The principles behind that split are in [adapters-and-security.md](adapters-and-security.md); this file is the practical sequence.

A repository with no ruleset is the normal starting point, not a fault:

```bash
gh api repos/<owner>/<repo>/rulesets
```

```text
[]
```

That empty list is exactly why `devflow operate --node merge_gate` reports `BLOCKED` until you finish this runbook.

## Before you start

| Requirement | Check | Expected |
| --- | --- | --- |
| Git | `git --version` | any supported version |
| GitHub CLI, authenticated | `gh auth status` | `✓ Logged in to github.com account <you>` |
| Python 3.10+ for the VibeCode Control CLI | `python3 --version` (`py --version` on Windows) | `3.10` or newer |
| Admin rights on the repository | `gh api repos/<owner>/<repo> --jq .permissions.admin` | `true` |

Without admin rights you can still complete the CI and template steps, but rulesets and Actions policy need an owner. Ask for them rather than recording an unverified claim.

Substitute your own `<owner>/<repo>` everywhere. Nothing in this runbook needs a specific account.

## How to read a step

Every step below is one row:

- **Setting** — what you change on GitHub.
- **Feeds** — which VibeCode Control gate depends on it.
- **How** — the `gh` command, or the UI path when the API is not the simpler route.
- **Verify** — the command whose output is your evidence, and what that output looks like when the setting is in place.
- **Without it** — what VibeCode Control reports, in the exact words you will see.

Two rules apply to every row:

- Never record a setting as `verified` in `.agent-flow/config.json` from memory or intent. Run the verify command, read the output, and record it in the same session.
- A verify command that fails because your token lacks a scope is not evidence of anything. `gh api repos/<owner>/<repo>/actions/permissions/workflow` answers `HTTP 403` when the token has no Actions policy permission — that is a missing check, not a passing one.

## Repository basics

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Repository exists with a default branch | every gate; `git-github` setup stage | `gh repo create <owner>/<repo> --private --clone` or push an existing clone | `gh repo view <owner>/<repo> --json defaultBranchRef,visibility` → `{"defaultBranchRef":{"name":"main"},"visibility":"PRIVATE"}` | `setup check --stage git-github` is `BLOCKED` with `Local Git repository is not initialized` |
| Remote is configured and observable | `git-github` stage evidence | `git remote add origin https://github.com/<owner>/<repo>.git` | `git remote -v` → one `origin` entry | gap `Git remote is not configured or not observable` |
| `origin/HEAD` resolves | default-branch reporting in `devflow inspect` | `git remote set-head origin --auto` | `git symbolic-ref refs/remotes/origin/HEAD` → `refs/remotes/origin/main` | `inspect` reports `default_branch: unverified` |

Rulesets and branch protection are not available on every plan for private repositories. If your plan does not offer them, that is a real limit: make the repository public, upgrade, or accept that the merge gate stays `BLOCKED`. Do not record `ruleset_verified` to work around a plan limit.

## Branch ruleset and merge protection

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Ruleset on the default branch requiring a pull request | `merge_gate`, `merge` (release stage) | Repository → Settings → Rules → Rulesets → New branch ruleset, target the default branch, enable **Require a pull request before merging** | `gh api repos/<owner>/<repo>/rulesets --jq '.[] \| {id, name, enforcement}'` → at least one entry with `"enforcement": "active"` | `operate --node merge_gate` is `BLOCKED` with `A remote merge ruleset has not been verified` |
| Required status checks in the ruleset | `merge_gate`; the required-check rule in `run record` | In the same ruleset enable **Require status checks to pass** and add each CI job by name | `gh api repos/<owner>/<repo>/rulesets/<id> --jq '.rules[] \| select(.type=="required_status_checks")'` → the job names you added | `operate` on a review or release node is `BLOCKED` with `No remotely verified required-check set is configured` |
| Block force pushes | guardrail integrity; evidence bound to a head SHA | Enable **Block force pushes** in the ruleset | the same `rulesets/<id>` output contains a rule of type `non_fast_forward` | a rewritten history silently invalidates recorded evidence |
| Require conversation resolution | `final_review`, `merge_gate` | Enable **Require conversation resolution before merging** | `gh api repos/<owner>/<repo>/rulesets/<id> --jq '.rules[].type'` lists `required_review_thread_resolution` | a blocking review thread can be merged past |

If your organization uses classic branch protection instead, verify it with `gh api repos/<owner>/<repo>/branches/<branch>/protection`. On a repository with no protection that call answers `HTTP 404` — a plain, honest "not configured".

## CI and required checks

Measure the baseline before you write a workflow. VibeCode Control records quality commands in `.agent-flow/config.json` under `quality.commands`, and a command you have never run is not a baseline.

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Measured baseline commands | `quality` setup stage; the acceptance-to-check map | run your lint, typecheck and test commands locally, then `devflow config set quality.commands.unit '["<your test command>"]'` | `devflow config show --effective` shows the commands you actually ran | the `quality` stage stays `PARTIAL` with `baseline not measured` |
| A workflow that runs exactly those commands | `quality_gates`, `merge_gate` | add `.github/workflows/<name>.yml` running the measured commands | `gh api repos/<owner>/<repo>/actions/workflows --jq '.workflows[].path'` lists the file | `devflow audit ci` reports `No GitHub Actions workflow detected` |
| Job names match the required-check names | the required-check rule in `run record` | name each job exactly as it appears in the ruleset | `gh api repos/<owner>/<repo>/commits/<sha>/check-runs --jq '.check_runs[] \| {name, conclusion}'` → the same names | a required check never reports, so `run record` refuses the `PASS` with `PASS требует conclusion=success для каждой обязательной проверки` |

Do not invent commands to fill the workflow. A job that runs a command your project does not have produces a green check that proves nothing, which is exactly what the evidence rules exist to prevent.

## Background runners and secrets

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Secrets stored as GitHub secrets only | security boundary | `gh secret set <NAME> --repo <owner>/<repo>` and paste the value at the prompt | `gh secret list --repo <owner>/<repo>` → the name, never the value | a token in a config file, prompt or plan leaks into every clone and diff |
| `GITHUB_TOKEN` permissions reduced to what the job needs | least privilege for background runs | set `permissions:` per job in the workflow file | read the `permissions:` block in the workflow; `gh api repos/<owner>/<repo>/actions/permissions/workflow` reports the repository default when your token may read it | a background run holds write scope it never needed |
| Fork pull requests cannot read secrets | prompt-injection and secret-exfiltration boundary | avoid `pull_request_target` for untrusted content; keep secrets out of workflows triggered by forks | review the workflow triggers; `gh api repos/<owner>/<repo>/actions/permissions --jq .` for the Actions policy | untrusted PR content can reach a job that holds your secrets |
| Runner checks out the repository before invoking the agent | project-scoped skills, node preflight | add an explicit checkout step to the workflow | the workflow log shows the checkout before the agent step | the agent cannot load `.agents/skills` or `.claude/skills`, and preflight reports missing project skills |
| Background executor availability confirmed | node preflight | run one real background job end to end, then `devflow config set automation.background_workers verified` | the workflow run you just observed | preflight reports `Background executor availability is unverified` |

VibeCode Control already installs the project-scoped copies of `devflow-node` into `.agents/skills` and `.claude/skills`. Committing them is what makes them reachable from a background runner; a personal skill in your home directory is not.

## Templates

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Issue form for ready Issues | `prepare_issue` node | installed by `devflow init` / `adopt` at `.github/ISSUE_TEMPLATE/devflow-task.yml` | `git show HEAD:.github/ISSUE_TEMPLATE/devflow-task.yml \| head -3` | Issues arrive without scope, acceptance criteria or risk class |
| Pull request template managed block | `final_review`, `merge_gate` | installed as a managed block in `.github/pull_request_template.md` | `devflow doctor` reports the `managed-blocks` check as `PASS` | a PR arrives without the evidence section reviewers rely on |

Both files are managed. Your own text outside the `devflow:managed` markers is preserved; edits inside them are reported as drift by `devflow doctor` and rewritten by `devflow upgrade`.

## Merge policy

| Setting | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| Allowed merge methods | `merge` node behaviour | Settings → General → Pull Requests, or `gh api -X PATCH repos/<owner>/<repo> -f squash_merge_allowed=true -f merge_commit_allowed=false` | `gh repo view <owner>/<repo> --json mergeCommitAllowed,squashMergeAllowed,rebaseMergeAllowed` | the release operator has to guess the project's merge convention |
| Delete branch on merge | branch hygiene; recorded in `github.delete_branch_on_merge` | `gh api -X PATCH repos/<owner>/<repo> -f delete_branch_on_merge=true` | `gh repo view <owner>/<repo> --json deleteBranchOnMerge` → `{"deleteBranchOnMerge":true}` | merged branches accumulate; VibeCode Control records the field but does not gate on it |

## Review-gate requirements

These follow the merged implementation of the review trust gate. Configure GitHub so an honest `PASS` is reachable.

| Requirement | Feeds | How | Verify | Without it |
| --- | --- | --- | --- | --- |
| The review node publishes an artifact of the declared kind | `evidence_contract` on `implementer_review` and `final_review` | have the reviewer publish a real review, comment or findings artifact, then record it as `devflow run record --evidence "review verdict bound to head SHA=review:<url>"` | `gh pr view <n> --json reviews --jq '.reviews[] \| {author: .author.login, state}'` returns the published review | `run record` refuses the `PASS`: a successful job without the declared artifact is not a passed check |
| Every required check concludes `success` | the required-check rule on verification, review and release nodes | make the CI jobs actually pass | `gh api repos/<owner>/<repo>/commits/<sha>/check-runs --jq '.check_runs[] \| {name, conclusion}'` → `"conclusion":"success"` | `run record` refuses the `PASS` and names each unproven check |
| A `skipped` check is treated as unproven | the same rule | do not gate on a job that skips itself under normal conditions | the same `check-runs` output shows `"conclusion":"skipped"` | recording it produces `зелёный skipped или neutral не считается выполненной проверкой` |
| A PR that changes the workflow verifying it is reviewed against the version that ran | self-modification evidence in `operate` | check `self_modification` in `devflow operate --node <id>`, then determine from the run whether the base or the head version executed | `gh run view <run-id> --json headBranch,workflowDatabaseId` plus the workflow file at that ref | an untrusted PR can silently redefine its own verifier |
| No post-merge dispatch against a closed pull request | the post-merge rule in `run record` | run post-merge checks on the merge commit, or use an open follow-up PR | `gh api repos/<owner>/<repo>/commits/<merge-sha>/check-runs` | evidence referencing `refs/pull/<N>/merge` is rejected on the post-merge node, because a closed PR has no such ref |

Effort and model are not GitHub settings. They come from the effective configuration, and a background job must pass the values `devflow config effective` reports — an `inherited` parameter is observed in the run and recorded, an `unset` one stays absent.

## Record the result in VibeCode Control

Only after you have run the verify commands in this session:

```bash
devflow config set github.remote_settings verified
devflow config set github.required_checks '["<check name>", "<check name>"]'
devflow config set github.ruleset_verified true
devflow config set github.delete_branch_on_merge verified
devflow config set github.codeowners_verified true
devflow config set automation.background_workers verified
```

Which of these actually gate:

| Field | Gates |
| --- | --- |
| `github.remote_settings` | `git-github` setup stage, `audit ci`, every review and release node preflight |
| `github.required_checks` | review and release node preflight; the required-check rule in `run record` |
| `github.ruleset_verified` | release-stage node preflight |
| `automation.background_workers` | preflight of any node whose agent is not `human`, `script` or `deterministic` |
| `github.delete_branch_on_merge`, `github.codeowners_verified` | recorded for the reader; no gate reads them today |

Recording a field is a claim you are making. `devflow doctor` cannot re-check GitHub for you, so an incorrect claim survives until someone notices — which is why the verify column exists.

## Verify the whole stage

```bash
devflow audit git
devflow setup check --stage git-github
devflow operate --node merge_gate
```

Expected once the runbook is complete: `audit git` reports `PASS`, the `git-github` stage reports `PASS` with `branch`, `dirty` and `remotes` evidence, and `operate --node merge_gate` no longer lists a GitHub gap. Nodes may still be `BLOCKED` for unrelated reasons — an unresolved skill decision or an undecided executor — and those are different gaps with their own next steps.

## Common blockers

`BLOCKED` is the protection working, not the tool breaking. Each one names its next step.

| What you see | What it means | Next step |
| --- | --- | --- |
| `Local Git repository is not initialized` | the path is not a Git worktree | `git init` and add the remote |
| `Git remote is not configured or not observable` | no remote, or `git remote -v` failed | add `origin` and fetch once |
| `Remote GitHub rulesets, required checks, and merge policy are unverified` | nobody has checked GitHub in this project yet | run the verify commands above, then record the fields |
| `GitHub remote settings and adapter access are unverified for review/release` | `github.remote_settings` is not `verified` | complete the ruleset section first |
| `No remotely verified required-check set is configured` | `github.required_checks` is empty | add the CI job names after seeing them report |
| `A remote merge ruleset has not been verified` | `github.ruleset_verified` is not `true` | create the ruleset, verify with `gh api`, then record |
| `Background executor availability is unverified` | no background run has been observed | run one real background job, then record |
| `rulesets` returns `[]` | the repository has no ruleset at all | this is the starting state; create one |
| `HTTP 404` from the branch protection endpoint | no classic protection on that branch | expected when you use rulesets instead |
| `HTTP 403` from an Actions policy endpoint | your token lacks that permission | ask an owner to check, or record nothing |
