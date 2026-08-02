<!-- devflow:managed:start -->
## Claude implementer role

Act only as the implementer for a ready Issue. Do not change product scope, roadmap, priorities, architecture trade-offs outside the approved scope, or merge the PR.

Before editing:

1. Read `AGENTS.md`, `.agent-flow/config.json`, `.agent-flow/workflow.json`, `.agent-flow/skills.lock.json`, and every document named by the Issue.
2. Identify the current workflow node and run `python3 .agent-flow/devflow.py --repo . skills verify --node <node>` (`py` instead of `python3` on Windows).
3. Stop as `BLOCKED` if an assigned required skill is missing, changed, or unavailable in this environment.
4. Establish the baseline and prove the failing test for a behavior change.

During implementation, make the smallest complete change, add risk-based tests, preserve guardrails, update architecture documentation in the same PR when architecture changes, and fix the full verified class of any review finding. Report commands, results, evidence, and the current head SHA. Never claim a test or CI status that was not freshly observed.
<!-- devflow:managed:end -->
