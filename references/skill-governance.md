# Skill governance

## Contents

1. Decision unit
2. Zero-skill
3. Recommendation matrix
4. Allowed discovery
5. Static audit
6. Pin, copy, and verify
7. Evaluation
8. Revalidation and scheme check

## Decision unit

Assign a third-party skill to a concrete execution profile, not to a vague role:

```text
node + action + agent + model + effort + permissions + stack/version + risk
```

Treat these as separate mechanisms:

- VibeCode Control: process orchestration and checks.
- Project rules: durable repository conventions and domain policy.
- Scripts, CI, and hooks: deterministic enforcement.
- MCP or apps: live external data and actions.
- Third-party skills: optional procedural knowledge for a specific node.

Do not recommend a skill when a project rule, script, CI gate, hook, or MCP is the correct mechanism.

## Zero-skill

Require a decision for every active node. Accept `zero-skill` as a positive, reasoned choice.

Recommend zero-skill when:

- the current model already passes the node scenarios reliably;
- project rules define the procedure clearly;
- a deterministic script or CI gate performs the action;
- a candidate duplicates the model, VibeCode Control, or another assigned skill;
- a candidate is too generic or increases context without a concrete gap;
- benefit is unproven while cost, latency, permissions, or risk increase;
- it conflicts with current project rules or guardrails;
- it uses obsolete APIs or commands;
- it requires permissions outside the node envelope;
- the same skill would create a shared blind spot for implementer and reviewer.

Use no more than two third-party skills on a node: normally one narrow stack/domain skill and one policy/security skill. Require a separate rationale and compatibility test for more.

## Recommendation matrix

Present one consolidated table:

| Node | Action | Agent/model/effort | Gap | Candidate | Verdict | Evidence | Risk | User decision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Use these verdicts:

- `REQUIRED`: mandatory project or compliance procedure not safely covered elsewhere.
- `RECOMMENDED`: concrete added value is source-backed or project-tested.
- `OPTIONAL`: plausible but nonessential benefit.
- `NOT_NEEDED`: zero-skill is currently the better design.
- `REJECT`: unsafe, incompatible, conflicting, or irrelevant.
- `EVALUATE`: plausible candidate with insufficient comparative evidence.

Track evidence independently:

- `project-tested`: the pinned skill improved fixed project scenarios versus zero-skill.
- `source-backed`: official provider skill, not yet compared on this project.
- `heuristic`: content looks relevant; no performance claim.
- `unknown`: insufficient evidence.
- `user-approved`: user chose it after seeing the recommendation and audit.

Age alone is not staleness. Mark stale only after confirmed incompatible APIs/commands, policy conflict, or comparative regression.

Ask one user question after the matrix: accept the proposed set for all nodes or edit selected rows. Never silently install candidates.

## Allowed discovery

Search only:

1. `https://www.skills.sh`, including its Official and Audits surfaces.
2. `https://github.com/openai/skills`.
3. Official OpenAI/Codex documentation and repositories directly linked or recommended by it.
4. `https://github.com/anthropics/skills`.
5. Official Anthropic/Claude documentation and repositories directly linked or recommended by it.
6. Additional exact prefixes explicitly added by the user to `allowed_sources.extra`.

Do not discover through unrestricted GitHub, general search results, blogs, package lists, or “awesome” repositories. A direct candidate URL supplied by the user may be audited as a manual candidate but does not expand discovery scope.

Use skills.sh for discovery only. Its ranking is based on installations, and its own documentation does not guarantee every listed skill’s quality or security.

Shortlist no more than three challengers per problem node.

## Static audit

Audit exact local bytes without executing any included script.

Check:

- `SKILL.md` frontmatter and scope;
- every reference, script, template, and asset;
- path traversal and symlinks;
- binary and oversized files;
- installers and runtime dependencies;
- network access and dynamic remote-code execution;
- credential, secret, `.env`, or host-environment access;
- writes outside the repository;
- destructive commands, force push, privilege escalation, and broad permissions;
- attempts to alter other skills, `AGENTS.md`, `CLAUDE.md`, CI, tests, thresholds, or security policy;
- instructions to skip or weaken checks;
- obfuscation, dynamic execution, or `shell=True`;
- license and provenance;
- platform-specific Claude extensions that Codex may not support, and vice versa;
- conflict or duplication with current project rules and assigned skills.

Treat automated findings as triage. Review every high or critical finding. Do not use `--approved-by-user` merely to bypass a real risk.

## Pin, copy, and verify

Require:

- canonical source URL;
- full 40-character Git commit SHA;
- deterministic SHA-256 tree checksum;
- license;
- audit result and date;
- review date;
- targets (`claude`, `codex`);
- assigned nodes and levels;
- explicit user approval.

Registration must inspect a clean local Git checkout at the exact commit. Verify `HEAD`, origin, repository subpath, Git-tracked file set, and local bytes before copying. A user-supplied SHA string alone is not provenance.

Materialize the approved package into `.agent-flow/vendor-skills/<name>` and copy it to `.agents/skills/<name>` and/or `.claude/skills/<name>`. Do not use symlinks; copies are more reliable across Windows and ephemeral runners.

Before each background node, verify the target copy against the lock checksum. On unexplained drift, mark it `BLOCKED` or quarantined. Restore automatically only from the intact, already approved vendor copy and only inside an explicitly requested repair.

Protect `.agent-flow/skills.lock.json`, vendor copies, `.agents/skills`, and `.claude/skills` with reinforced repository review or CODEOWNERS. A coordinated PR can rewrite local bytes and local metadata together; local checks cannot substitute for a trusted remote approval/status bound to the current SHA.

Do not use floating branches, `latest`, unpinned tags, or network updates during ordinary execution.

Before removal, clear every node assignment explicitly. Review the removal plan, then delete the lock entry and materialized Claude/Codex/vendor files together. Never silently fall back from a removed required skill.

## Evaluation

Use the same:

- repository snapshot and task scenarios;
- model and effort;
- permission envelope;
- tools and external context;
- objective checks and scoring.

Compare:

1. Current model with zero-skill.
2. Current pinned incumbent.
3. New pinned challenger.

Use at least a normal, boundary, and failure scenario for the node. Measure correctness, acceptance and policy compliance, critical defects, hallucinated capabilities, guardrail interference, unnecessary actions, and stalled retries. Measure time or cost only when telemetry exists.

If the runner or telemetry is unavailable, state `эмпирически не проверено` and keep the candidate unverified.

## Revalidation and scheme check

Do a cheap presence/checksum preflight on every background run. Do a full evaluation only when:

- the user explicitly requests a scheme check;
- a node or gate repeatedly fails;
- model, effort, agent, permissions, stack, architecture, or node action changes;
- VibeCode Control or a pinned skill updates;
- a vulnerability or incompatibility is reported;
- `review_after` is due.

During `scheme check`, inspect recent evidence, compare incumbent and zero-skill, search allowlisted alternatives, and return one of:

- `KEEP`;
- `UPDATE`;
- `REPLACE`;
- `REMOVE`;
- `ZERO_SKILL`;
- `NEEDS_EVAL`.

Build a reversible plan. Require user approval for a new, replacement, or materially changed third-party skill.
