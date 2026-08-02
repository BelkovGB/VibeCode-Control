# VibeCode Control implementation node

Act as the configured `implementer` for the Issue supplied by the workflow. Load `devflow-node` explicitly. Read the repository rules and `.agent-flow` configuration first. Resolve the exact workflow node, agent/model/effort profile, permissions, and exact assigned skill names from `.agent-flow/skills.lock.json`; load every required assigned skill explicitly.

Run `python3 .agent-flow/devflow.py --repo . operate --node <node>` (`py` on Windows). Stop unless it returns `PASS`; report `PARTIAL` or `BLOCKED` rather than inventing executor, model, effort, skill, GitHub, or CI availability.

Implement only the ready Issue. For behavior changes, provide fresh evidence of `RED → GREEN → REFACTOR`. Run the risk-based checks, preserve every guardrail, update architecture documentation in the same PR when architecture changes, and report evidence bound to the current head SHA. Do not merge and do not change product scope or priorities.
