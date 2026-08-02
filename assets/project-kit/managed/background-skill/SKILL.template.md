---
name: devflow-node
description: Execute one configured VibeCode Control workflow node in a repository. Use for background Claude or Codex implementation, verification, review, merge-gate, or post-merge work governed by .agent-flow.
---

# VibeCode Control node execution

1. Read `AGENTS.md`, agent-specific instructions, `.agent-flow/config.json`, `.agent-flow/workflow.json`, and `.agent-flow/skills.lock.json`.
2. Require the caller to identify the node. Resolve its action, role, configured agent, model, effort, permissions, assigned skills, checks, and expected evidence.
3. Run `python3 .agent-flow/devflow.py --repo . skills verify --node <node>` on POSIX or `py .agent-flow\devflow.py --repo . skills verify --node <node>` on Windows. Stop as `BLOCKED` on missing configuration, an unresolved decision, an unavailable required skill, or checksum drift.
4. Load every assigned required skill explicitly. Do not fetch or update a skill during the run.
5. Perform only the node action within its permission envelope. Do not expand scope, weaken guardrails, or substitute an agent/model silently.
6. Record actual commands, checks, evidence, current head SHA, agent, model, effort, and loaded skill versions. Never infer a successful result.
7. Follow bounded retries. Escalate only a genuine product decision, material compromise, access, irreversible risk, or human approval as `HUMAN_NEEDED`.
