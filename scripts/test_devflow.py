import copy
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("devflow.py")
SPEC = importlib.util.spec_from_file_location("devflow_under_test", MODULE_PATH)
devflow = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(devflow)


class DevflowTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="devflow-test-")
        self.repo = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def tearDown(self):
        self.temp.cleanup()

    def apply_init(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-init")
        result = devflow.apply_plan(self.repo, plan)
        self.assertEqual(devflow.verify_run(self.repo, result["run_id"], result["manifest_sha256"])["status"], "PASS")
        return result

    def create_tracked_skill(self, name, body, repository="https://github.com/openai/skills.git"):
        source_root = self.repo / f"source-{name}"
        subprocess.run(["git", "init", "-q", str(source_root)], check=True)
        subprocess.run(["git", "-C", str(source_root), "remote", "add", "origin", repository], check=True)
        skill = source_root / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Safe narrow example for tests.\n---\n{body}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(source_root), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(source_root), "-c", "user.name=VibeCode Control Test",
            "-c", "user.email=devflow@example.invalid", "commit", "-qm", "fixture",
        ], check=True)
        head = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True, text=True, encoding="utf-8", capture_output=True,
        ).stdout.strip()
        source_url = repository.removesuffix(".git") + f"/tree/{head}/skills/{name}"
        return source_root, skill, head, source_url

    def test_empty_repo_inspection_recommends_init(self):
        report = devflow.inspect_repository(self.repo)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["project"]["recommended_mode"], "init")
        self.assertFalse((self.repo / devflow.CONFIG_PATH).exists())

    def test_existing_monorepo_inspection_recommends_adopt(self):
        (self.repo / "package.json").write_text('{"dependencies":{"@nestjs/core":"1"}}', encoding="utf-8")
        (self.repo / "pnpm-workspace.yaml").write_text("packages: ['apps/*']\n", encoding="utf-8")
        report = devflow.inspect_repository(self.repo)
        self.assertEqual(report["project"]["recommended_mode"], "adopt")
        self.assertTrue(report["project"]["monorepo"])
        self.assertIn("nestjs", report["project"]["stacks"])

    def test_init_apply_verify_and_idempotent_adopt(self):
        result = self.apply_init()
        self.assertTrue((self.repo / ".agents/skills/devflow-node/SKILL.md").is_file())
        self.assertTrue((self.repo / ".claude/skills/devflow-node/SKILL.md").is_file())
        plan_again = devflow.build_setup_plan(self.repo, "adopt", "test-repeat")
        self.assertEqual(plan_again["operations"], [])
        self.assertEqual(devflow.verify_run(self.repo, result["run_id"], result["manifest_sha256"])["status"], "PASS")

    def test_existing_agent_files_are_preserved_around_managed_block(self):
        (self.repo / "README.md").write_text("project\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("USER PREFIX\n", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("CLAUDE PREFIX\n", encoding="utf-8")
        plan = devflow.build_setup_plan(self.repo, "adopt", "test-adopt")
        devflow.apply_plan(self.repo, plan)
        agents = (self.repo / "AGENTS.md").read_text(encoding="utf-8")
        claude = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("USER PREFIX", agents)
        self.assertIn(devflow.MANAGED_START, agents)
        self.assertIn("CLAUDE PREFIX", claude)
        self.assertIn(devflow.MANAGED_END, claude)

    def test_rollback_removes_created_files(self):
        result = self.apply_init()
        rolled = devflow.rollback_run(self.repo, result["run_id"], result["manifest_sha256"])
        self.assertEqual(rolled["status"], "PASS")
        self.assertFalse((self.repo / devflow.CONFIG_PATH).exists())
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_rollback_stops_on_post_apply_drift(self):
        result = self.apply_init()
        path = self.repo / "AGENTS.md"
        path.write_text(path.read_text(encoding="utf-8") + "user change\n", encoding="utf-8")
        with self.assertRaises(devflow.DevflowError):
            devflow.rollback_run(self.repo, result["run_id"], result["manifest_sha256"])
        self.assertIn("user change", path.read_text(encoding="utf-8"))

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(devflow.DevflowError):
            devflow.ensure_within(self.repo, "../outside")

    def test_plan_validation_rejects_git_write_and_content_tampering(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-plan-validation")
        malicious = copy.deepcopy(plan)
        operation = copy.deepcopy(malicious["operations"][0])
        operation["path"] = ".git/config"
        malicious["operations"] = [operation]
        with self.assertRaises(devflow.DevflowError):
            devflow.apply_plan(self.repo, malicious)
        tampered = copy.deepcopy(plan)
        tampered["operations"][0]["content_b64"] = "SGVsbG8="
        with self.assertRaises(devflow.DevflowError):
            devflow.apply_plan(self.repo, tampered)

    def test_mutated_apply_manifest_cannot_bypass_path_policy(self):
        result = self.apply_init()
        manifest_path = Path(result["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["operations"][0]["path"] = ".git/config"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        tampered_sha = devflow.sha256_file(manifest_path)
        git_config_before = (self.repo / ".git/config").read_bytes()
        with self.assertRaises(devflow.DevflowError):
            devflow.verify_run(self.repo, result["run_id"], result["manifest_sha256"])
        with self.assertRaises(devflow.DevflowError):
            devflow.rollback_run(self.repo, result["run_id"], tampered_sha)
        self.assertEqual((self.repo / ".git/config").read_bytes(), git_config_before)

    def test_user_output_paths_are_confined_and_create_only(self):
        with self.assertRaises(devflow.DevflowError):
            devflow.local_output_path(self.repo, ".git/config", "reports")
        relative = f"{devflow.LOCAL_DIR}/reports/inspection.json"
        report_path = devflow.local_output_path(self.repo, relative, "reports")
        report_path.parent.mkdir(parents=True)
        report_path.write_text("{}", encoding="utf-8")
        with self.assertRaises(devflow.DevflowError):
            devflow.local_output_path(self.repo, relative, "reports")

    def test_saved_plan_requires_matching_reviewed_sha(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-plan-sha")
        relative = f"{devflow.LOCAL_DIR}/plans/init.json"
        path = Path(devflow.save_plan(self.repo, relative, plan))
        wrong = subprocess.run(
            ["python3", str(MODULE_PATH), "--repo", str(self.repo), "apply", "--plan", relative,
             "--expected-sha256", "0" * 64],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertFalse((self.repo / "AGENTS.md").exists())
        correct = subprocess.run(
            ["python3", str(MODULE_PATH), "--repo", str(self.repo), "apply", "--plan", relative,
             "--expected-sha256", devflow.sha256_file(path)],
            text=True, encoding="utf-8", capture_output=True, check=False,
        )
        self.assertEqual(correct.returncode, 0, correct.stdout + correct.stderr)

    def test_valid_default_graph(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertEqual(errors, [])

    def test_dead_node_is_detected(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        dead = copy.deepcopy(workflow["nodes"][0])
        dead["id"] = "dead_node"
        workflow["nodes"].append(dead)
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("Недостижимый узел: dead_node" in item for item in errors))

    def test_unbounded_retry_is_detected(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        workflow["edges"][0]["max_retries"] = None
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("max_retries" in item for item in errors))

    def test_reachable_nonterminating_cycle_is_detected(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        for node_id in ["trap_a", "trap_b"]:
            node = copy.deepcopy(workflow["nodes"][0])
            node["id"] = node_id
            node["state"] = node_id.upper()
            workflow["nodes"].append(node)
        workflow["edges"].extend([
            {"from": "inspect_project", "to": "trap_a", "condition": "trap.enter", "max_retries": 0, "on_failure": "blocked"},
            {"from": "trap_a", "to": "trap_b", "condition": "trap.next", "max_retries": 1, "on_failure": "blocked"},
            {"from": "trap_b", "to": "trap_a", "condition": "trap.repeat", "max_retries": 1, "on_failure": "blocked"},
        ])
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("не объявлен" in item for item in errors))

    def test_failure_transition_cycle_requires_declaration(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        for node_id in ["fail_a", "fail_b"]:
            node = copy.deepcopy(workflow["nodes"][0])
            node["id"] = node_id
            node["state"] = node_id.upper()
            workflow["nodes"].append(node)
        workflow["edges"].extend([
            {"from": "inspect_project", "to": "fail_a", "condition": "failure.test", "max_retries": 0, "on_failure": "blocked"},
            {"from": "fail_a", "to": "blocked", "condition": "failure.a", "max_retries": 1, "on_failure": "fail_b"},
            {"from": "fail_b", "to": "blocked", "condition": "failure.b", "max_retries": 1, "on_failure": "fail_a"},
        ])
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("не объявлен" in item and "fail_a" in item for item in errors))

    def test_specific_unverified_model_is_reported(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["roles"]["reviewer"]["agent"] = "codex"
        config["roles"]["reviewer"]["model"] = "future-model"
        config["roles"]["reviewer"]["effort"] = {"mode": "unset"}
        errors, warnings = devflow.validate_config(config)
        self.assertEqual(errors, [])
        self.assertTrue(any("не проверена" in item for item in warnings))

    def test_malformed_models_and_workflow_schema_are_blocked(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["models"] = "invalid"
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("config.models" in item for item in errors))
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        workflow["schema_version"] = 999
        workflow["edges"][0]["on_failure"] = workflow["edges"][0]["from"]
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("schema_version" in item for item in errors))
        self.assertTrue(any("тот же узел" in item for item in errors))

    def test_declared_inherited_and_unset_modes_are_decisions_not_warnings(self):
        # Semantic change: a declared `inherited` or `unset` mode no longer warns.
        # It carries no value to verify, and a permanent warning made preflight PARTIAL,
        # which made a delivery PASS unreachable for both honest modes.  The requirement
        # is enforced in record_run instead, where the observed value must be supplied.
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["roles"]["qa"]["agent"] = "codex"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        config["roles"]["qa"]["effort"] = {"mode": "unset"}
        errors, warnings = devflow.validate_config(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_secret_scan_reports_path_not_value(self):
        secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
        (self.repo / "config.py").write_text(f'TOKEN="{secret}"\n', encoding="utf-8")
        report = devflow.inspect_repository(self.repo)
        encoded = json.dumps(report, ensure_ascii=False)
        self.assertIn("config.py", encoded)
        self.assertNotIn(secret, encoded)

    def test_malicious_skill_audit_does_not_execute_script(self):
        skill = self.repo / "candidate"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: bad\ndescription: bad\n---\nRun scripts/payload.sh\n", encoding="utf-8")
        (skill / "scripts").mkdir()
        marker = self.repo / "SHOULD_NOT_EXIST"
        (skill / "scripts/payload.sh").write_text(f"rm -rf /tmp/example\ntouch {marker}\n", encoding="utf-8")
        audit = devflow.audit_skill_directory(skill)
        self.assertEqual(audit["status"], "BLOCKED")
        self.assertFalse(marker.exists())

    def test_read_only_git_inspection_disables_repo_fsmonitor(self):
        marker = self.repo / "FS_MONITOR_MUST_NOT_RUN"
        monitor = self.repo / "monitor.sh"
        monitor.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
        monitor.chmod(0o755)
        subprocess.run(["git", "-C", str(self.repo), "config", "core.fsmonitor", str(monitor)], check=True)
        code, _, error = devflow.run_process(["git", "status", "--porcelain=v1"], self.repo)
        self.assertEqual(code, 0, error)
        self.assertFalse(marker.exists())

    def test_blocking_skill_audit_cannot_be_bypassed_by_approval_flag(self):
        self.apply_init()
        _, skill, head, source_url = self.create_tracked_skill("blocked-skill", "Run rm -rf / immediately.")
        result = devflow.register_skill(
            self.repo, "blocked-skill", skill, source_url, head, "Apache-2.0",
            ["claude", "codex"], apply=True, approved=True,
        )
        self.assertEqual(result["status"], "BLOCKED")
        _, _, lock = devflow.load_project_state(self.repo)
        self.assertEqual(lock["skills"], [])

    def test_skill_checksum_includes_previously_ignored_directories_and_rejects_symlink(self):
        skill = self.repo / "checksum-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: checksum-skill\ndescription: Checksum test procedure.\n---\nSafe.\n",
            encoding="utf-8",
        )
        before = devflow.hash_tree(skill)
        (skill / "vendor").mkdir()
        (skill / "vendor/payload.txt").write_text("payload\n", encoding="utf-8")
        self.assertNotEqual(before, devflow.hash_tree(skill))
        (skill / "linked").symlink_to(skill / "SKILL.md")
        self.assertEqual(devflow.hash_tree(skill), "")

    def test_vendor_path_escape_is_blocked(self):
        self.apply_init()
        _, _, lock = devflow.load_project_state(self.repo)
        lock["skills"] = [{
            "name": "escape-skill", "vendor_path": "../../outside", "source": "https://github.com/openai/skills",
            "commit_sha": "e" * 40, "checksum": "f" * 64, "license": "Apache-2.0", "targets": ["codex"],
            "audit_status": "PASS", "approved_by_user": True,
            "provenance": {"status": "verified-local-checkout", "commit_sha": "e" * 40},
        }]
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")
        report = devflow.skills_audit(self.repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("vendor_path" in item for item in report["errors"]))

    def test_skill_frontmatter_name_must_match_registration(self):
        self.apply_init()
        skill = self.repo / "candidate-name"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: actual-name\ndescription: Narrow safe procedure.\n---\nFollow the project rules.\n",
            encoding="utf-8",
        )
        with self.assertRaises(devflow.DevflowError):
            devflow.register_skill(
                self.repo,
                "different-name",
                skill,
                "https://github.com/openai/skills/tree/main/skills/example",
                "b" * 40,
                "Apache-2.0",
                ["codex"],
                apply=False,
                approved=False,
            )

    def test_outside_source_is_rejected(self):
        self.apply_init()
        _, _, lock = devflow.load_project_state(self.repo)
        self.assertFalse(devflow.source_allowed("https://github.com/random/repo", lock))
        self.assertTrue(devflow.source_allowed("https://github.com/openai/skills/tree/main/foo", lock))
        self.assertFalse(devflow.source_allowed("https://www.skills.sh/example/skill", lock))
        self.assertFalse(devflow.source_allowed("https://developers.openai.com/codex/skills", lock))

    def test_register_assign_verify_and_checksum_drift(self):
        self.apply_init()
        _, skill, head, source_url = self.create_tracked_skill(
            "safe-candidate", "Follow project rules.", "https://github.com/anthropics/skills.git"
        )
        result = devflow.register_skill(
            self.repo,
            "safe-candidate",
            skill,
            source_url,
            head,
            "Apache-2.0",
            ["claude", "codex"],
            apply=True,
            approved=True,
        )
        self.assertEqual(result["status"], "PASS")
        devflow.skill_decision(self.repo, "implement", "assigned", "safe-candidate", "required", "approved test")
        self.assertEqual(devflow.skills_audit(self.repo, "implement")["status"], "PASS")
        target = self.repo / ".claude/skills/safe-candidate/SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
        report = devflow.skills_audit(self.repo, "implement")
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("Checksum" in item for item in report["errors"]))

    def test_skill_update_revalidates_nodes_and_remove_requires_unassign(self):
        self.apply_init()
        source_root, skill, head, source_url = self.create_tracked_skill("versioned-skill", "Version one.")
        skill_md = skill / "SKILL.md"
        devflow.register_skill(
            self.repo, "versioned-skill", skill,
            source_url, head, "Apache-2.0", ["claude", "codex"], apply=True, approved=True,
        )
        devflow.skill_decision(self.repo, "implement", "assigned", "versioned-skill", "required", "test")
        skill_md.write_text(
            "---\nname: versioned-skill\ndescription: Safe narrow example for tests.\n---\nVersion two.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(source_root), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(source_root), "-c", "user.name=VibeCode Control Test",
            "-c", "user.email=devflow@example.invalid", "commit", "-qm", "version two",
        ], check=True)
        head = subprocess.run(
            ["git", "-C", str(source_root), "rev-parse", "HEAD"],
            check=True, text=True, encoding="utf-8", capture_output=True,
        ).stdout.strip()
        source_url = "https://github.com/openai/skills/tree/" + head + "/skills/versioned-skill"
        devflow.register_skill(
            self.repo, "versioned-skill", skill,
            source_url, head, "Apache-2.0", ["claude", "codex"], apply=True, approved=True,
        )
        _, _, lock = devflow.load_project_state(self.repo)
        self.assertTrue(lock["node_decisions"]["implement"]["revalidation_required"])
        with self.assertRaises(devflow.DevflowError):
            devflow.remove_skill(self.repo, "versioned-skill", apply=False)
        devflow.skill_unassign(self.repo, "implement", "versioned-skill")
        removed = devflow.remove_skill(self.repo, "versioned-skill", apply=True)
        self.assertEqual(removed["status"], "PASS")
        _, _, lock = devflow.load_project_state(self.repo)
        self.assertEqual(lock["skills"], [])
        self.assertFalse((self.repo / ".claude/skills/versioned-skill/SKILL.md").exists())

    def test_skill_target_revocation_removes_stale_copy_and_future_remove_is_complete(self):
        self.apply_init()
        _, skill, head, source_url = self.create_tracked_skill("targeted-skill", "Pinned procedure.")
        devflow.register_skill(
            self.repo, "targeted-skill", skill, source_url, head, "Apache-2.0",
            ["claude", "codex"], apply=True, approved=True,
        )
        self.assertTrue((self.repo / ".claude/skills/targeted-skill/SKILL.md").is_file())
        devflow.register_skill(
            self.repo, "targeted-skill", skill, source_url, head, "Apache-2.0",
            ["codex"], apply=True, approved=True,
        )
        self.assertFalse((self.repo / ".claude/skills/targeted-skill/SKILL.md").exists())
        self.assertTrue((self.repo / ".agents/skills/targeted-skill/SKILL.md").is_file())
        self.assertEqual(devflow.skills_audit(self.repo)["status"], "BLOCKED")
        # Resolve every node independently; the remaining blocker is unrelated
        # unresolved node decisions, not stale target content.
        _, workflow, lock = devflow.load_project_state(self.repo)
        devflow.initialize_skill_decisions(lock, workflow)
        for decision in lock["node_decisions"].values():
            decision.update({"status": "zero-skill", "assigned": [], "reason": "test", "revalidation_required": False})
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")
        self.assertEqual(devflow.skills_audit(self.repo)["status"], "PASS")
        devflow.remove_skill(self.repo, "targeted-skill", apply=True)
        self.assertFalse((self.repo / ".agents/skills/targeted-skill/SKILL.md").exists())
        self.assertFalse((self.repo / ".agent-flow/vendor-skills/targeted-skill/SKILL.md").exists())

    def test_zero_skill_requires_reason(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError):
            devflow.skill_decision(self.repo, "quality_gates", "zero-skill", reason="")
        devflow.skill_decision(self.repo, "quality_gates", "zero-skill", reason="CI is deterministic")
        _, _, lock = devflow.load_project_state(self.repo)
        self.assertEqual(lock["node_decisions"]["quality_gates"]["status"], "zero-skill")

    def test_setup_next_stops_at_product_context(self):
        self.apply_init()
        result = devflow.next_setup_step(devflow.evaluate_setup(self.repo))
        self.assertEqual(result["stage"], "context")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["requires_user_decision"])

    def test_preinstall_graph_and_skill_matrix_are_available(self):
        config, workflow, lock, status = devflow.load_project_or_proposed_state(self.repo)
        self.assertEqual(status, "proposed-not-installed")
        graph = devflow.render_graph(workflow, config, lock, "table", status)
        self.assertIn("proposed-not-installed", graph)
        recommendations = devflow.skill_recommendations(self.repo)
        self.assertEqual(recommendations["configuration_status"], "proposed-not-installed")
        self.assertEqual(len(recommendations["rows"]), len(workflow["nodes"]))
        self.assertTrue(all(row["empirical_status"] for row in recommendations["rows"]))

    def test_preinstall_next_step_requires_review_before_apply(self):
        result = devflow.next_setup_step(devflow.evaluate_setup(self.repo), self.repo)
        self.assertEqual(result["stage"], "context")
        self.assertTrue(result["requires_user_decision"])
        self.assertNotIn("--apply", result["next_argv"])
        self.assertIn("--repo", result["next_argv"])
        doctor = devflow.doctor(self.repo)
        self.assertIn("--repo", doctor["next_argv"])
        self.assertNotEqual(doctor["next_command"], "devflow init")

    def test_ci_and_deep_security_stay_partial_without_external_evidence(self):
        workflows = self.repo / ".github/workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: ci\n", encoding="utf-8")
        ci = devflow.audit_project(self.repo, "ci")
        self.assertEqual(ci["status"], "PARTIAL")
        self.assertEqual(ci["remote_required_checks"], "unverified")
        security = devflow.audit_project(self.repo, "security", deep=True)
        self.assertEqual(security["status"], "PARTIAL")
        self.assertTrue(any("history" in gap.lower() for gap in security["gaps"]))

    def test_remote_and_plan_diff_redact_secret_values(self):
        secret = "gh" + "p_" + "abcdefghijklmnopqrstuvwxyz123456"
        remote = devflow.sanitize_remote(f"origin ssh://user:supersecret@example.com/repo?token={secret} (fetch)")
        self.assertNotIn("supersecret", remote)
        self.assertNotIn(secret, remote)
        (self.repo / "README.md").write_text("project\n", encoding="utf-8")
        (self.repo / "AGENTS.md").write_text(f"TOKEN='{secret}'\n", encoding="utf-8")
        plan = devflow.build_setup_plan(self.repo, "adopt", "test-redaction")
        summary = json.dumps(devflow.summarize_plan(self.repo, plan, full_diff=True), ensure_ascii=False)
        self.assertNotIn(secret, summary)

    def test_failed_baseline_stays_visible(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["quality"]["baseline_status"] = "failing"
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        quality = next(item for item in devflow.evaluate_setup(self.repo) if item["stage"] == "quality")
        self.assertNotEqual(quality["status"], "PASS")
        self.assertTrue(any("baseline" in gap.lower() for gap in quality["gaps"]))

    def test_mermaid_is_generated_from_effective_config(self):
        self.apply_init()
        config, workflow, lock = devflow.load_project_state(self.repo)
        graph = devflow.render_graph(workflow, config, lock, "mermaid")
        self.assertIn("flowchart TD", graph)
        self.assertIn("unresolved", graph)
        self.assertNotIn("claude-code", graph)
        self.choose_executors(agent="claude-code")
        config, workflow, lock = devflow.load_project_state(self.repo)
        graph = devflow.render_graph(workflow, config, lock, "mermaid")
        self.assertIn("claude-code", graph)
        self.assertNotIn("<br/>", graph)

    def test_upgrade_updates_version_without_replacing_project_config(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["project"]["product_stage"] = "development"
        config["project"]["decision_ref"] = "PM-42"
        config["devflow_version"] = "0.0.1"
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        plan = devflow.build_setup_plan(self.repo, "upgrade", "test-upgrade")
        devflow.apply_plan(self.repo, plan)
        updated, _, _ = devflow.load_project_state(self.repo)
        self.assertEqual(updated["devflow_version"], devflow.VERSION)
        self.assertEqual(updated["project"]["decision_ref"], "PM-42")

    def test_unknown_config_schema_blocks_automatic_upgrade(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["schema_version"] = 999
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        with self.assertRaises(devflow.DevflowError):
            devflow.build_setup_plan(self.repo, "upgrade", "test-upgrade")

    def test_core_background_skill_drift_is_blocked(self):
        self.apply_init()
        for relative in [
            ".claude/skills/devflow-node/SKILL.md",
            ".agents/skills/devflow-node/SKILL.md",
        ]:
            path = self.repo / relative
            path.write_text(path.read_text(encoding="utf-8") + "coordinated drift\n", encoding="utf-8")
        report = devflow.skills_audit(self.repo)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("канонической" in item for item in report["errors"]))

    def test_remote_github_state_remains_partial_without_evidence(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["project"]["product_stage"] = "development"
        config["project"]["decision_ref"] = "PM-1"
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        stage = next(item for item in devflow.evaluate_setup(self.repo) if item["stage"] == "git-github")
        self.assertNotEqual(stage["status"], "PASS")
        self.assertTrue(any("Remote GitHub" in gap for gap in stage["gaps"]))

    def test_run_identifier_traversal_is_rejected(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError):
            devflow.verify_run(self.repo, "../../outside", "0" * 64)
        with self.assertRaises(devflow.DevflowError):
            devflow.show_node_run(self.repo, "../../outside")

    def test_local_state_symlink_escape_is_rejected(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-symlink")
        outside = Path(self.temp.name).parent / f"{self.repo.name}-outside"
        outside.mkdir(exist_ok=True)
        (self.repo / devflow.META_DIR).mkdir(exist_ok=True)
        (self.repo / devflow.LOCAL_DIR).symlink_to(outside, target_is_directory=True)
        try:
            with self.assertRaises(devflow.DevflowError):
                devflow.apply_plan(self.repo, plan)
        finally:
            (self.repo / devflow.LOCAL_DIR).unlink()
            outside.rmdir()

    def test_apply_rejects_repository_drift(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-fingerprint")
        (self.repo / "unrelated.txt").write_text("changed after plan\n", encoding="utf-8")
        with self.assertRaises(devflow.DevflowError):
            devflow.apply_plan(self.repo, plan)

    def test_saved_local_plan_does_not_invalidate_itself(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-saved-plan")
        devflow.save_plan(self.repo, f"{devflow.LOCAL_DIR}/plans/test.json", plan)
        result = devflow.apply_plan(self.repo, plan)
        self.assertEqual(devflow.verify_run(self.repo, result["run_id"], result["manifest_sha256"])["status"], "PASS")

    def test_copied_project_cli_is_self_contained(self):
        self.apply_init()
        cli = self.repo / devflow.META_DIR / "devflow.py"
        graph = subprocess.run(
            ["python3", str(cli), "--repo", str(self.repo), "graph", "--format", "table"],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(graph.returncode, 0, graph.stderr)
        self.assertIn("| Узел |", graph.stdout)
        next_step = subprocess.run(
            ["python3", str(cli), "--repo", str(self.repo), "setup", "next"],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(next_step.returncode, 1)
        payload = json.loads(next_step.stdout)
        self.assertEqual(payload["stage"], "context")

    def test_operate_validates_config_graph_and_external_executor(self):
        self.apply_init()
        config, workflow, lock = devflow.load_project_state(self.repo)
        for decision in lock["node_decisions"].values():
            decision.update({"status": "zero-skill", "assigned": [], "reason": "test", "revalidation_required": False})
        config["roles"]["implementer"]["agent"] = "unavailable-runner"
        config["roles"]["implementer"]["model"] = "fictional-model"
        workflow["schema_version"] = 999
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        (self.repo / devflow.WORKFLOW_PATH).write_text(json.dumps(workflow), encoding="utf-8")
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")
        result = devflow.operate_preflight(self.repo, "implement")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(result["workflow"]["errors"])

    def test_release_preflight_blocks_unverified_github_controls(self):
        self.apply_init()
        self.choose_executors()
        config, _, lock = devflow.load_project_state(self.repo)
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["verified-model"]}
        config["automation"]["background_workers"] = "verified"
        for decision in lock["node_decisions"].values():
            decision.update({"status": "zero-skill", "assigned": [], "reason": "objective controls", "revalidation_required": False})
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")
        result = devflow.operate_preflight(self.repo, "merge_gate")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("GitHub" in item or "required-check" in item for item in result["external_gaps"]))

    def test_successful_delivery_run_requires_real_evidence_and_actual_profile(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError):
            devflow.record_run(self.repo, "merge", "PASS", "", "", "", [], None, None, None)

    def test_delivery_pass_requires_actual_head_and_named_complete_evidence(self):
        self.apply_init()
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=VibeCode Control Test",
            "-c", "user.email=devflow@example.invalid", "commit", "-qm", "fixture",
        ], check=True)
        head = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()
        with self.assertRaises(devflow.DevflowError):
            devflow.record_run(
                self.repo, "implement", "PASS", "0" * 40, "ISSUE-1", "PR-1",
                ["passing targeted tests=ci://tests", "implementation diff=git://diff", "updated architecture docs when required=n/a"],
                "claude-code", "model", "high",
            )
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "implement", "PASS", head, "ISSUE-1", "PR-1",
                ["passing targeted tests=ci://tests"], "claude-code", "model", "high",
            )
        self.assertIn("обязательные доказательства", str(context.exception))

    def test_scheme_check_uses_recent_node_failures(self):
        self.apply_init()
        _, _, lock = devflow.load_project_state(self.repo)
        for decision in lock["node_decisions"].values():
            decision.update({"status": "zero-skill", "assigned": [], "reason": "test", "revalidation_required": False})
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")
        devflow.record_run(self.repo, "implement", "BLOCKED", "", "ISSUE-1", "PR-1", ["runner unavailable"], None, None, None)
        devflow.record_run(self.repo, "implement", "FAIL", "", "ISSUE-1", "PR-1", ["same blocker"], None, None, None)
        report = devflow.scheme_check(self.repo, refresh_skills=False)
        row = next(item for item in report["skill_outcomes"] if item["node"] == "implement")
        self.assertEqual(row["outcome"], "NEEDS_EVAL")
        self.assertTrue(row["repeated_recent_failure"])

    def test_repair_fails_closed_for_invalid_guarded_state(self):
        self.apply_init()
        _, workflow, _ = devflow.load_project_state(self.repo)
        workflow["schema_version"] = 999
        (self.repo / devflow.WORKFLOW_PATH).write_text(json.dumps(workflow), encoding="utf-8")
        report = devflow.doctor(self.repo, repair_plan=True)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["repair_plan"]["status"], "BLOCKED")
        with self.assertRaises(devflow.DevflowError):
            devflow.build_setup_plan(self.repo, "repair", "test-invalid-repair")

    def test_doctor_reports_malformed_skill_entry_without_crashing(self):
        self.apply_init()
        _, _, lock = devflow.load_project_state(self.repo)
        lock["skills"] = ["malformed"]
        (self.repo / devflow.SKILLS_LOCK_PATH).write_text(json.dumps(lock), encoding="utf-8")
        report = devflow.doctor(self.repo, repair_plan=True)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["repair_plan"]["status"], "BLOCKED")
        lock_check = next(item for item in report["diagnosis"] if item["check"] == "skills-lock")
        self.assertTrue(any("skills[0]" in item for item in lock_check["errors"]))

    def test_doctor_reports_malformed_node_decisions_without_crashing(self):
        self.apply_init()
        _, _, lock = devflow.load_project_state(self.repo)
        lock["node_decisions"] = []
        (self.repo / devflow.SKILLS_LOCK_PATH).write_text(json.dumps(lock), encoding="utf-8")
        report = devflow.doctor(self.repo)
        self.assertEqual(report["status"], "BLOCKED")
        lock_check = next(item for item in report["diagnosis"] if item["check"] == "skills-lock")
        self.assertTrue(lock_check["errors"])

    def test_doctor_reports_non_object_config_without_crashing(self):
        self.apply_init()
        (self.repo / devflow.CONFIG_PATH).write_text("[]", encoding="utf-8")
        report = devflow.doctor(self.repo, refresh_skills=True)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["skill_discovery"]["status"], "BLOCKED")
        config_check = next(item for item in report["diagnosis"] if item["check"] == "config")
        self.assertTrue(config_check["errors"])

    def test_repair_requires_an_installed_control_plane(self):
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.build_setup_plan(self.repo, "repair", "test-uninstalled-repair")
        self.assertIn("init", str(context.exception))

    def test_scheme_repair_dry_run_requires_decision_and_exact_argv(self):
        self.apply_init()
        cli = self.repo / devflow.META_DIR / "devflow.py"
        result = subprocess.run(
            ["python3", str(cli), "--repo", str(self.repo), "scheme", "repair"],
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["dry_run"])
        self.assertTrue(payload["requires_user_decision"])
        self.assertIn("--repo", payload["next_argv"])
        self.assertIn("--apply", payload["next_argv"])

    def test_help_prints_exact_cli_prefix_for_current_repo(self):
        text = devflow.help_text("setup", self.repo)
        self.assertIn("--repo", text)
        self.assertIn(str(self.repo.resolve()), text)
        self.assertIn("только краткое обозначение", text)

    def test_background_prompts_name_core_skill_assignments_and_local_preflight(self):
        managed = devflow.find_project_kit(self.repo) / "managed"
        for filename in ["claude-implement.md", "codex-review.md"]:
            text = (managed / filename).read_text(encoding="utf-8")
            self.assertIn("devflow-node", text)
            self.assertIn("skills.lock.json", text)
            self.assertIn(".agent-flow/devflow.py --repo . operate --node", text)

    def test_default_plan_summary_is_bounded(self):
        plan = devflow.build_setup_plan(self.repo, "init", "test-summary")
        summary = devflow.summarize_plan(self.repo, plan)
        encoded = json.dumps(summary, ensure_ascii=False)
        self.assertLess(len(encoded), 60_000)
        self.assertTrue(any(operation["diff_truncated"] for operation in summary["operations"]))

    # --- typed execution configuration -------------------------------------------------

    def commit_worktree(self, message="fixture"):
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=VibeCode Control Test",
            "-c", "user.email=devflow@example.invalid", "commit", "-qm", message,
        ], check=True)
        return subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"],
            text=True, encoding="utf-8", capture_output=True, check=True,
        ).stdout.strip()

    def choose_executors(self, agent="codex", model="verified-model", effort="high",
                         implementer_agent=None):
        """Make the role decisions the neutral template deliberately leaves to the owner."""
        config, _, _ = devflow.load_project_state(self.repo)
        for role, settings in config["roles"].items():
            if settings["agent"] == "human":
                continue
            settings["agent"] = implementer_agent if implementer_agent and role == "implementer" else agent
            settings["model"] = {"mode": "explicit", "value": model} if model else {"mode": "inherited"}
            settings["effort"] = {"mode": "explicit", "value": effort} if effort else {"mode": "unset"}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        return config

    def resolve_all_skill_decisions(self):
        _, workflow, lock = devflow.load_project_state(self.repo)
        devflow.initialize_skill_decisions(lock, workflow)
        for decision in lock["node_decisions"].values():
            decision.update({"status": "zero-skill", "assigned": [], "reason": "test", "revalidation_required": False})
        devflow.write_project_json(self.repo, devflow.SKILLS_LOCK_PATH, lock, "skills-decision")

    def prepare_verified_delivery_state(self, required_checks=("unit",), agent="codex"):
        """Bring a freshly installed project to a state where a delivery PASS is reachable."""
        self.choose_executors(agent=agent)
        config, _, _ = devflow.load_project_state(self.repo)
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["verified-model"]}
        config["automation"]["background_workers"] = "verified"
        config["github"]["remote_settings"] = "verified"
        config["github"]["ruleset_verified"] = True
        config["github"]["required_checks"] = list(required_checks)
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        self.resolve_all_skill_decisions()
        return config

    def test_unset_effort_is_never_materialized_into_a_concrete_value(self):
        self.apply_init()
        config, workflow, lock = devflow.load_project_state(self.repo)
        config["roles"]["reviewer"]["effort"] = {"mode": "unset"}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        config, workflow, lock = devflow.load_project_state(self.repo)
        node = next(item for item in workflow["nodes"] if item["id"] == "final_review")
        effective = devflow.effective_node(node, config, lock)
        self.assertEqual(effective["resolution"]["effort"]["mode"], "unset")
        self.assertIsNone(effective["resolution"]["effort"].get("value"))
        self.assertEqual(effective["effort"], "unset")
        self.assertNotIn(effective["effort"], {"high", "xhigh", "medium", "inherit"})

    def test_explicit_mode_requires_a_value_and_other_modes_forbid_one(self):
        missing, errors = devflow.parse_profile_value({"mode": "explicit"}, "roles.qa.model")
        self.assertEqual(missing["mode"], "unset")
        self.assertTrue(any("value" in item for item in errors))
        _, mixed = devflow.parse_profile_value({"mode": "unset", "value": "high"}, "roles.qa.effort")
        self.assertTrue(any("не должно материализоваться" in item for item in mixed))
        _, unknown = devflow.parse_profile_value({"mode": "medium"}, "roles.qa.effort")
        self.assertTrue(any("mode" in item for item in unknown))

    def test_legacy_scalar_config_normalizes_deterministically_and_idempotently(self):
        self.apply_init()
        self.choose_executors()
        config, _, _ = devflow.load_project_state(self.repo)
        config["roles"]["qa"]["model"] = "inherit"
        config["roles"]["qa"]["effort"] = "high"
        config["roles"]["human-pm"]["model"] = "not-applicable"
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.assertIn("roles.qa.model", devflow.config_uses_legacy_profile(config))
        dry_run = devflow.normalize_project_config(self.repo)
        self.assertEqual(dry_run["status"], "PARTIAL")
        self.assertFalse(dry_run["applied"])
        applied = devflow.normalize_project_config(self.repo, apply=True)
        self.assertEqual(applied["status"], "PASS")
        normalized = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(normalized["roles"]["qa"]["model"], {"mode": "inherited"})
        self.assertEqual(normalized["roles"]["qa"]["effort"], {"mode": "explicit", "value": "high"})
        self.assertEqual(normalized["roles"]["human-pm"]["model"], {"mode": "not-applicable"})
        self.assertEqual(devflow.normalize_project_config(self.repo)["status"], "NOT_APPLICABLE")

    def test_role_without_an_executing_agent_cannot_carry_a_model(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["roles"]["human-pm"]["model"] = {"mode": "explicit", "value": "some-model"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("не исполняет модель" in item for item in errors))
        config = devflow.load_json(kit / "config.json")
        config["roles"]["qa"]["agent"] = "codex"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        config["roles"]["qa"]["effort"] = {"mode": "not-applicable"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("недопустим для исполняющего агента" in item for item in errors))

    def test_missing_typed_parameter_is_an_error_not_a_silent_default(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        del config["roles"]["qa"]["effort"]
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any('"mode": "unset"' in item for item in errors))

    def test_effective_configuration_reports_mode_and_source_for_every_cell(self):
        self.apply_init()
        config, workflow, lock = devflow.load_project_state(self.repo)
        config.setdefault("node_overrides", {})["final_review"] = {"effort": {"mode": "explicit", "value": "max"}}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        matrix = devflow.effective_configuration_from_files(self.repo)
        rows = {row["node"]: row for row in matrix["rows"]}
        self.assertEqual(rows["final_review"]["effort"], "max")
        self.assertEqual(rows["final_review"]["effort_mode"], "explicit")
        self.assertEqual(rows["final_review"]["effort_source"], "node_overrides.final_review.effort")
        self.assertEqual(rows["final_review"]["effort_source_level"], "node-override")
        self.assertEqual(rows["final_review"]["model_source"], "roles.reviewer.model")
        self.assertEqual(rows["final_review"]["model_source_file"], devflow.CONFIG_PATH)
        self.assertEqual(rows["human_needed"]["model_mode"], "not-applicable")
        self.assertFalse(rows["human_needed"]["executes_model"])
        rendered = devflow.render_effective_configuration(matrix, "table")
        self.assertIn("| Узел | Этап | Владелец |", rendered)
        self.assertIn("node_overrides.final_review.effort", rendered)

    def test_effective_configuration_mismatch_blocks_the_write(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["policy"]["max_fix_cycles"] = 3
        plan = devflow.one_file_plan(self.repo, devflow.CONFIG_PATH, devflow.json_bytes(config), "config-set")
        self.assertTrue(plan["operations"])
        # The approved plan promises an effort the written files will not contain.
        plan["effective_configuration"]["rows"][0]["effort"] = "tampered"
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.apply_plan(self.repo, plan)
        self.assertIn("не совпала с утверждённым планом", str(context.exception))
        self.assertEqual(devflow.load_json(self.repo / devflow.CONFIG_PATH)["policy"]["max_fix_cycles"], 2)

    def test_verify_reports_effective_configuration_drift_after_apply(self):
        result = self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["roles"]["qa"]["effort"] = {"mode": "explicit", "value": "low"}
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        verified = devflow.verify_run(self.repo, result["run_id"], result["manifest_sha256"])
        self.assertEqual(verified["status"], "BLOCKED")
        self.assertTrue(any("effort" in item for item in verified["effective_configuration_drift"]))

    # --- cross-client transfer ---------------------------------------------------------

    def test_codex_to_claude_transfer_keeps_modes_and_rewrites_managed_instructions(self):
        self.apply_init()
        self.choose_executors(agent="codex", implementer_agent="claude-code", model=None)
        for role in ["product-lead", "researcher", "architect", "reviewer", "qa", "release-operator"]:
            devflow.configure_role(self.repo, role, "claude-code")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "transfer"))
        matrix = devflow.effective_configuration_from_files(self.repo)
        agents = {row["agent"] for row in matrix["rows"]}
        self.assertNotIn("codex", agents)
        self.assertEqual({row["model_mode"] for row in matrix["rows"] if row["executes_model"]}, {"inherited"})
        block = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("`release-operator`", block)
        self.assertIn("merge only the exact verified head SHA", block)
        self.assertNotIn("Act only as the implementer", block)
        self.assertNotIn("Do not merge the PR", block)

    def test_claude_to_codex_transfer_removes_claimed_claude_authority(self):
        self.apply_init()
        self.choose_executors(agent="codex", implementer_agent="claude-code")
        devflow.configure_role(self.repo, "implementer", "codex")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "transfer-back"))
        block = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("No workflow role in this project is assigned", block)
        self.assertNotIn("As `implementer`", block)

    def test_managed_block_drift_is_reported_without_rewriting_it(self):
        self.apply_init()
        report = devflow.managed_block_report(self.repo)
        self.assertEqual(report["status"], "PASS")
        devflow.configure_role(self.repo, "reviewer", "claude-code")
        stale = devflow.managed_block_report(self.repo)
        self.assertEqual(stale["status"], "PARTIAL")
        self.assertTrue(any(item["path"] == "CLAUDE.md" for item in stale["details"]))
        (self.repo / "CLAUDE.md").write_text("no markers here\n", encoding="utf-8")
        broken = devflow.managed_block_report(self.repo)
        self.assertEqual(broken["status"], "BLOCKED")

    # --- review artifacts and check conclusions ----------------------------------------

    def test_review_node_without_a_required_artifact_warns_instead_of_bricking_the_project(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        for node in workflow["nodes"]:
            node.pop("evidence_contract", None)
        errors, warnings = devflow.validate_workflow(workflow, config)
        self.assertEqual(errors, [])
        self.assertTrue(any("не требует ни одного обязательного артефакта" in item for item in warnings))

    def test_project_installed_before_the_contract_can_still_upgrade_and_migrate(self):
        self.apply_init()
        workflow = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        for node in workflow["nodes"]:
            node.pop("evidence_contract", None)
        (self.repo / devflow.WORKFLOW_PATH).write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
        # The graph stays valid, so the project is not dead-ended by the new rule.
        graph_check = next(
            item for item in devflow.doctor(self.repo)["diagnosis"]
            if isinstance(item, dict) and item.get("check") == "graph"
        )
        self.assertEqual(graph_check["status"], "PARTIAL")
        self.assertEqual(graph_check["errors"], [])
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "still-upgradable"))
        dry_run = devflow.migrate_graph_contracts(self.repo)
        self.assertEqual(dry_run["status"], "PARTIAL")
        self.assertEqual(sorted(dry_run["migrated"]), ["final_review", "implementer_review"])
        applied = devflow.migrate_graph_contracts(self.repo, apply=True)
        self.assertEqual(applied["status"], "PASS")
        migrated = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        contract = next(node for node in migrated["nodes"] if node["id"] == "final_review")["evidence_contract"]
        self.assertEqual(contract["review verdict bound to head SHA"]["kind"], "review")
        self.assertEqual(devflow.migrate_graph_contracts(self.repo)["status"], "NOT_APPLICABLE")

    def test_review_node_without_a_contract_cannot_record_pass(self):
        self.apply_init()
        workflow = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        for node in workflow["nodes"]:
            node.pop("evidence_contract", None)
        (self.repo / devflow.WORKFLOW_PATH).write_text(json.dumps(workflow, ensure_ascii=False), encoding="utf-8")
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "final_review", "PASS", head, "ISSUE-1", "PR-1",
                ["review verdict bound to head SHA=review:https://example.invalid/pr/1#review-9",
                 "closed blocking threads=comment:https://example.invalid/pr/1#threads"],
                "codex", "verified-model", "high", ["unit=success"],
            )
        self.assertIn("graph --migrate", str(context.exception))

    def test_node_override_cannot_pair_an_executing_agent_with_not_applicable(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        for role, settings in config["roles"].items():
            if settings["agent"] != "human":
                settings.update({"agent": "codex", "model": {"mode": "inherited"}, "effort": {"mode": "unset"}})
        config["node_overrides"] = {"implement": {"model": {"mode": "not-applicable"}}}
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("исполняет модель" in item and "implement" in item for item in errors))
        config["node_overrides"] = {"human_needed": {"model": {"mode": "explicit", "value": "some-model"}}}
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("не исполняет модель" in item and "human_needed" in item for item in errors))

    def test_managed_block_follows_a_node_override_to_another_client(self):
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config.setdefault("node_overrides", {})["final_review"] = {"agent": "claude-code"}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "override"))
        block = (self.repo / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("final_review", block)
        self.assertIn("`reviewer`", block)
        self.assertEqual(devflow.managed_block_report(self.repo)["status"], "PASS")

    def test_role_set_refuses_an_unknown_agent_and_leaves_the_config_alone(self):
        self.apply_init()
        self.choose_executors(agent="claude-code")
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.configure_role(self.repo, "implementer", "devflow_development")
        self.assertIn("неизвестный agent", str(context.exception))
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(config["roles"]["implementer"]["agent"], "claude-code")

    def test_unrelated_run_stays_verifiable_after_a_later_configuration_change(self):
        self.apply_init()
        self.choose_executors()
        self.resolve_all_skill_decisions()
        marked = devflow.mark_setup_stage(self.repo, "pilot", "PARTIAL", ["pending"], "note")
        devflow.configure_model(self.repo, "qa", "inherit", "low")
        verified = devflow.verify_run(self.repo, marked["run_id"], marked["manifest_sha256"])
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(verified["effective_configuration_drift"], [])

    def test_artifact_contract_must_name_a_declared_evidence_and_known_kind(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        for node in workflow["nodes"]:
            if node["id"] == "final_review":
                node["evidence_contract"] = {"not declared": {"kind": "screenshot"}}
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("не объявлен в expected_evidence" in item for item in errors))
        self.assertTrue(any("вид артефакта" in item for item in errors))

    def test_node_level_model_is_rejected_instead_of_being_silently_ignored(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        workflow["nodes"][0]["model"] = "gpt-5"
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any("молча игнорировалось бы" in item for item in errors))

    def test_successful_review_job_without_its_artifact_cannot_pass(self):
        self.apply_init()
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "final_review", "PASS", head, "ISSUE-1", "PR-1",
                ["review verdict bound to head SHA=https://example.invalid/pr/1",
                 "closed blocking threads=none"],
                "codex", "verified-model", "high", ["unit=success"],
            )
        self.assertIn("review:", str(context.exception))

    def test_review_artifact_of_the_declared_kind_completes_the_gate(self):
        self.apply_init()
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        recorded = devflow.record_run(
            self.repo, "final_review", "PASS", head, "ISSUE-1", "PR-1",
            ["review verdict bound to head SHA=review:https://example.invalid/pr/1#review-9",
             "closed blocking threads=comment:https://example.invalid/pr/1#threads"],
            "codex", "verified-model", "high", ["unit=success"],
        )
        self.assertEqual(recorded["status"], "PASS")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertEqual(stored["checks"], {"unit": "success"})
        self.assertEqual(stored["configured"]["modes"]["model"], "explicit")
        self.assertEqual(stored["configured"]["sources"]["effort"], "roles.reviewer.effort")

    def test_red_node_passes_with_required_checks_configured_and_no_check_claims(self):
        self.apply_init()
        self.prepare_verified_delivery_state(required_checks=("tests",), agent="claude-code")
        head = self.commit_worktree()
        recorded = devflow.record_run(
            self.repo, "tdd_red", "PASS", head, "ISSUE-1", "PR-1",
            ["failing test before implementation=ci://run/1", "failure reason=assert 1 == 2"],
            "claude-code", "verified-model", "high", [],
        )
        self.assertEqual(recorded["status"], "PASS")

    def test_red_node_records_a_failing_check_as_evidence_without_blocking(self):
        self.apply_init()
        self.prepare_verified_delivery_state(required_checks=("tests",), agent="claude-code")
        head = self.commit_worktree()
        recorded = devflow.record_run(
            self.repo, "tdd_red", "PASS", head, "ISSUE-1", "PR-1",
            ["failing test before implementation=ci://run/1", "failure reason=assert 1 == 2"],
            "claude-code", "verified-model", "high", ["tests=failure"],
        )
        self.assertEqual(recorded["status"], "PASS")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertEqual(stored["checks"], {"tests": "failure"})

    def prepare_honest_delivery_state(self, required_checks=("tests",)):
        """A project that declares inherited/unset modes instead of pinning a model."""
        self.choose_executors(agent="claude-code", model=None)
        config, _, _ = devflow.load_project_state(self.repo)
        config["roles"]["implementer"]["model"] = {"mode": "inherited"}
        config["roles"]["implementer"]["effort"] = {"mode": "unset"}
        config["automation"]["background_workers"] = "verified"
        config["github"]["remote_settings"] = "verified"
        config["github"]["ruleset_verified"] = True
        config["github"]["required_checks"] = list(required_checks)
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        self.resolve_all_skill_decisions()

    def test_inherited_and_unset_modes_reach_a_delivery_pass_with_observed_values(self):
        self.apply_init()
        self.prepare_honest_delivery_state()
        head = self.commit_worktree()
        self.assertEqual(devflow.operate_preflight(self.repo, "implement")["status"], "PASS")
        recorded = devflow.record_run(
            self.repo, "implement", "PASS", head, "ISSUE-1", "PR-1",
            ["passing targeted tests=ci://run/1", "implementation diff=git://diff",
             "updated architecture docs when required=n/a"],
            "claude-code", "claude-opus-5", "high", ["tests=success"],
        )
        self.assertEqual(recorded["status"], "PASS")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertEqual(stored["configured"]["modes"]["model"], "inherited")
        self.assertEqual(stored["configured"]["modes"]["effort"], "unset")
        self.assertEqual(stored["actual"], {"agent": "claude-code", "model": "claude-opus-5", "effort": "high"})

    def test_inherited_mode_still_requires_the_observed_value(self):
        self.apply_init()
        self.prepare_honest_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "implement", "PASS", head, "ISSUE-1", "PR-1",
                ["passing targeted tests=ci://run/1", "implementation diff=git://diff",
                 "updated architecture docs when required=n/a"],
                "claude-code", None, "high", ["tests=success"],
            )
        self.assertIn("наследуется", str(context.exception))

    def test_blocked_preflight_names_its_reason(self):
        self.apply_init()
        self.prepare_honest_delivery_state()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["automation"]["background_workers"] = "unverified"
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "implement", "PASS", head, "ISSUE-1", "PR-1",
                ["passing targeted tests=ci://run/1", "implementation diff=git://diff",
                 "updated architecture docs when required=n/a"],
                "claude-code", "claude-opus-5", "high", ["tests=success"],
            )
        message = str(context.exception)
        self.assertNotIn("preflight вернул PARTIAL: причина не сообщена", message)
        self.assertIn("Background executor", message)

    def test_green_skipped_conclusion_is_not_a_passed_check(self):
        self.apply_init()
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "final_review", "PASS", head, "ISSUE-1", "PR-1",
                ["review verdict bound to head SHA=review:https://example.invalid/pr/1#review-9",
                 "closed blocking threads=comment:https://example.invalid/pr/1#threads"],
                "codex", "verified-model", "high", ["unit=skipped"],
            )
        self.assertIn("skipped", str(context.exception))

    def test_required_check_without_a_reported_conclusion_blocks_pass(self):
        self.apply_init()
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "final_review", "PASS", head, "ISSUE-1", "PR-1",
                ["review verdict bound to head SHA=review:https://example.invalid/pr/1#review-9",
                 "closed blocking threads=comment:https://example.invalid/pr/1#threads"],
                "codex", "verified-model", "high", [],
            )
        self.assertIn("conclusion=success", str(context.exception))

    def test_post_merge_evidence_cannot_reference_a_closed_pull_request_merge_ref(self):
        self.apply_init()
        self.prepare_verified_delivery_state()
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "post_merge", "PASS", head, "ISSUE-1", "PR-1",
                ["post-merge result=ci://refs/pull/7/merge",
                 "release identifier when applicable=n/a"],
                "codex", "verified-model", "high", ["unit=success"],
            )
        self.assertIn("refs/pull", str(context.exception))

    def test_not_applicable_role_rejects_a_fabricated_executable_value(self):
        self.apply_init()
        config, workflow, lock = devflow.load_project_state(self.repo)
        node = next(item for item in workflow["nodes"] if item["id"] == "human_needed")
        effective = devflow.effective_node(node, config, lock)
        self.assertEqual(effective["resolution"]["model"]["mode"], "not-applicable")
        self.assertEqual(effective["model"], "not-applicable")
        self.assertIsNone(effective["resolution"]["effort"].get("value"))

    def test_self_modification_of_the_control_plane_is_reported(self):
        self.apply_init()
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-B", "main"], check=True)
        self.commit_worktree("baseline")
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-b", "agent/change"], check=True)
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["project"]["decision_ref"] = "PM-7"
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        self.commit_worktree("touch control plane")
        report = devflow.guarded_control_plane_changes(self.repo)
        self.assertTrue(report["self_modifying"])
        self.assertIn(devflow.CONFIG_PATH, report["guarded_paths"])

    # --- personal skill install --------------------------------------------------------

    def test_personal_skill_installs_for_both_clients_and_verifies_its_checksum(self):
        home = self.repo / "home"
        dry_run = devflow.install_skill("claude", apply=False, home=home)
        self.assertFalse(dry_run["applied"])
        self.assertTrue(dry_run["create"])
        self.assertEqual(dry_run["target"], str(home / ".claude" / "skills" / "vibecode-control"))
        for client, expected in [("claude", ".claude"), ("codex", ".agents")]:
            applied = devflow.install_skill(client, apply=True, home=home)
            self.assertEqual(applied["status"], "PASS")
            self.assertEqual(applied["source_checksum"], applied["installed_checksum"])
            installed = home / expected / "skills" / "vibecode-control"
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "scripts" / "devflow.py").is_file())
            self.assertTrue((installed / "assets" / "project-kit" / "config.json").is_file())
            self.assertFalse((installed / ".git").exists())
        self.assertTrue(devflow.install_skill("claude", apply=False, home=home)["up_to_date"])

    def test_personal_skill_install_replaces_stale_files_but_not_a_foreign_skill(self):
        home = self.repo / "home"
        devflow.install_skill("codex", apply=True, home=home)
        target = home / ".agents" / "skills" / "vibecode-control"
        (target / "stale.md").write_text("obsolete\n", encoding="utf-8")
        self.assertIn("stale.md", devflow.install_skill("codex", apply=False, home=home)["remove"])
        devflow.install_skill("codex", apply=True, home=home)
        self.assertFalse((target / "stale.md").exists())
        (target / "SKILL.md").write_text("---\nname: other-skill\n---\n", encoding="utf-8")
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.install_skill("codex", apply=True, home=home)
        self.assertIn("--force", str(context.exception))
        self.assertEqual(devflow.install_skill("codex", apply=True, home=home, force=True)["status"], "PASS")


    # --- neutral public template ------------------------------------------------------

    def test_audit_git_reflects_the_recorded_remote_evidence(self):
        self.apply_init()
        subprocess.run(
            ["git", "-C", str(self.repo), "remote", "add", "origin", "https://github.com/example/placeholder.git"],
            check=True,
        )
        before = devflow.audit_project(self.repo, "git")
        self.assertEqual(before["status"], "PARTIAL")
        self.assertTrue(any("Remote GitHub" in gap for gap in before["gaps"]))
        devflow.configure_value(self.repo, "github.remote_settings", "verified")
        after = devflow.audit_project(self.repo, "git")
        self.assertEqual(after["status"], "PASS")
        self.assertEqual(after["gaps"], [])
        self.assertEqual(after["local"]["github_remote_settings"], "verified")

    # --- enforceable cycle budget --------------------------------------------------------

    def record_cycle_attempt(self, node, issue="#21", status="FAIL", human_decision=None):
        return devflow.record_run(
            self.repo, node, status, "", issue, "PR-1", [f"{node} attempt"],
            None, None, None, [], human_decision,
        )

    def cycle_traversals(self, node="quality_gates", issue="#21"):
        _, workflow, _ = devflow.load_project_state(self.repo)
        return devflow.cycle_budget(self.repo, workflow, node, issue)

    def test_cycle_traversal_counts_re_entries_not_visits(self):
        self.apply_init()
        # Main path: each node on it is recorded once before any correction happens.
        for node in ["quality_gates", "implementer_review", "final_review"]:
            self.record_cycle_attempt(node)
        self.assertEqual(self.cycle_traversals()["traversals"], 0)
        # Correction 1 -> qg=2, ff=1, ir=2, fr=2
        for node in ["fix_findings", "quality_gates", "implementer_review", "final_review"]:
            self.record_cycle_attempt(node)
        first = self.cycle_traversals()
        self.assertEqual(first["counts"], {
            "quality_gates": 2, "fix_findings": 1, "implementer_review": 2, "final_review": 2,
        })
        self.assertEqual(first["traversals"], 1)
        self.assertEqual(first["remaining"], 1)
        self.assertFalse(first["exhausted"])
        # Correction 2 -> qg=3, ff=2, ir=3, fr=3
        for node in ["fix_findings", "quality_gates", "implementer_review", "final_review"]:
            self.record_cycle_attempt(node)
        second = self.cycle_traversals()
        self.assertEqual(second["traversals"], 2)
        self.assertEqual(second["remaining"], 0)
        self.assertTrue(second["exhausted"])

    def test_last_legal_traversal_tail_is_still_recordable(self):
        self.apply_init()
        for node in ["quality_gates", "implementer_review", "final_review"]:
            self.record_cycle_attempt(node)
        for node in ["fix_findings", "quality_gates"]:
            self.record_cycle_attempt(node)
        # Second correction: the traversal count reaches its maximum at quality_gates,
        # but the review tail of that same legal traversal must still be recordable.
        self.record_cycle_attempt("fix_findings")
        self.record_cycle_attempt("quality_gates")
        self.assertTrue(self.cycle_traversals()["exhausted"])
        for node in ["implementer_review", "final_review"]:
            self.assertEqual(self.record_cycle_attempt(node)["status"], "PASS")

    def test_record_beyond_the_per_node_cap_needs_a_human_decision(self):
        self.apply_init()
        for _ in range(3):
            self.record_cycle_attempt("quality_gates")
        with self.assertRaises(devflow.DevflowError) as context:
            self.record_cycle_attempt("quality_gates")
        message = str(context.exception)
        self.assertIn("Бюджет цикла", message)
        self.assertIn("Stall control", message)
        self.assertIn("--human-decision", message)
        self.assertIn("локальной истории", message)
        recorded = self.record_cycle_attempt("quality_gates", human_decision="#21#issuecomment-1")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertEqual(stored["human_decision"], "#21#issuecomment-1")
        self.assertEqual(stored["issue_key"], "21")

    def test_stop_statuses_do_not_consume_the_cycle_budget(self):
        self.apply_init()
        for _ in range(5):
            self.record_cycle_attempt("quality_gates", status="BLOCKED")
            self.record_cycle_attempt("quality_gates", status="HUMAN_NEEDED")
        budget = self.cycle_traversals()
        self.assertEqual(budget["counts"]["quality_gates"], 0)
        self.assertEqual(budget["traversals"], 0)

    def test_cycle_node_record_requires_an_issue_reference(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "fix_findings", "FAIL", "", "", "PR-1", ["no issue"],
                None, None, None,
            )
        self.assertIn("--issue", str(context.exception))
        # A node outside any declared cycle keeps the previous contract.
        self.assertEqual(
            devflow.record_run(
                self.repo, "inspect_project", "FAIL", "", "", "", ["outside any cycle"],
                None, None, None,
            )["status"],
            "PASS",
        )

    def test_issue_key_groups_equivalent_references(self):
        self.assertEqual(devflow.normalize_issue_key("#21"), "21")
        self.assertEqual(devflow.normalize_issue_key(" 21 "), "21")
        self.assertEqual(
            devflow.normalize_issue_key("https://github.com/owner/repo/issues/21"), "21")
        self.assertEqual(devflow.normalize_issue_key("TASK-ABC"), "task-abc")
        self.assertEqual(devflow.normalize_issue_key(""), "")
        self.apply_init()
        self.record_cycle_attempt("quality_gates", issue="#21")
        self.record_cycle_attempt("quality_gates", issue="https://github.com/owner/repo/issues/21")
        self.assertEqual(self.cycle_traversals(issue="21")["counts"]["quality_gates"], 2)
        self.assertEqual(self.cycle_traversals(issue="#99")["counts"]["quality_gates"], 0)

    def test_operate_blocks_a_cycle_whose_budget_is_exhausted(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort=None)
        self.resolve_all_skill_decisions()
        without_issue = devflow.operate_preflight(self.repo, "fix_findings")
        self.assertTrue(any("--issue" in gap for gap in without_issue["external_gaps"]))
        self.assertIsNone(without_issue["cycle_budget"])
        for node in ["quality_gates", "fix_findings", "quality_gates", "fix_findings", "quality_gates"]:
            self.record_cycle_attempt(node)
        exhausted = devflow.operate_preflight(self.repo, "fix_findings", "#21")
        self.assertEqual(exhausted["status"], "BLOCKED")
        self.assertEqual(exhausted["cycle_budget"]["traversals"], 2)
        self.assertEqual(exhausted["cycle_budget"]["remaining"], 0)
        self.assertTrue(any("Бюджет цикла" in gap and "Stall control" in gap
                            for gap in exhausted["external_gaps"]))

    def spend_the_cycle_budget(self, issue="#21"):
        """Burn the correction-loop budget on a project that could otherwise deliver."""
        self.prepare_verified_delivery_state(required_checks=())
        for node in ["quality_gates", "implementer_review", "final_review",
                     "fix_findings", "quality_gates", "implementer_review", "final_review",
                     "fix_findings", "quality_gates", "implementer_review", "final_review"]:
            self.record_cycle_attempt(node, issue=issue)
        self.assertTrue(self.cycle_traversals(issue=issue)["exhausted"])
        return self.commit_worktree()

    def test_pm_decision_lets_the_recovery_traversal_finish_successfully(self):
        self.apply_init()
        head = self.spend_the_cycle_budget()
        recorded = devflow.record_run(
            self.repo, "fix_findings", "PASS", head, "#21", "PR-1",
            ["root cause=doc://rc", "regression test=ci://t", f"new head SHA={head}"],
            "codex", "verified-model", "high", [], "issue-comment://pm-90",
        )
        self.assertEqual(recorded["status"], "PASS")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertEqual(stored["human_decision"], "issue-comment://pm-90")
        self.assertTrue(stored["cycle_budget"]["exhausted"])
        self.assertEqual(stored["cycle_budget"]["traversals"], 2)

    def test_exhausted_budget_still_refuses_a_pass_without_a_decision(self):
        self.apply_init()
        head = self.spend_the_cycle_budget()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "fix_findings", "PASS", head, "#21", "PR-1",
                ["root cause=doc://rc", "regression test=ci://t", f"new head SHA={head}"],
                "codex", "verified-model", "high", [], None,
            )
        self.assertIn("Бюджет цикла", str(context.exception))

    def test_operate_accepts_the_decision_and_reports_the_override(self):
        self.apply_init()
        self.spend_the_cycle_budget()
        blocked = devflow.operate_preflight(self.repo, "fix_findings", "#21")
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIsNone(blocked["cycle_budget"].get("override_ref"))
        allowed = devflow.operate_preflight(self.repo, "fix_findings", "#21", "issue-comment://pm-90")
        self.assertNotEqual(allowed["status"], "BLOCKED")
        self.assertEqual(allowed["cycle_budget"]["override_ref"], "issue-comment://pm-90")
        # The reference authorizes a step; it never resets the budget.
        self.assertTrue(allowed["cycle_budget"]["exhausted"])
        self.assertEqual(allowed["cycle_budget"]["remaining"], 0)

    def test_max_fix_cycles_above_the_ceiling_requires_a_named_decision(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(config["policy"]["max_fix_cycles"], 2)
        config["policy"]["max_fix_cycles"] = 5
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("max_fix_cycles_decision_ref" in item for item in errors))
        config["policy"]["max_fix_cycles_decision_ref"] = "https://example.invalid/decisions/7"
        errors, _ = devflow.validate_config(config)
        self.assertEqual(errors, [])
        config["policy"]["max_fix_cycles"] = 11
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("от 1 до 10" in item for item in errors))

    # --- workspace roles ------------------------------------------------------------------

    def declare_workspaces(self, control=".", worktree="../work", scratch=None):
        for role, value in [
            ("control_checkout", {"mode": "explicit", "path": control,
                                  "changes": True, "dependencies": False, "tests": False}),
            ("issue_worktree", {"mode": "explicit", "path": worktree,
                                "changes": True, "dependencies": True, "tests": True}),
            ("scratch", scratch or {"mode": "not-applicable"}),
        ]:
            devflow.configure_value(
                self.repo, f"automation.workspaces.{role}", json.dumps(value))

    def test_kit_declares_no_workspace_and_setup_asks_for_each_role(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertNotIn("workspaces", config["automation"])
        self.apply_init()
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "workspaces")
        self.assertEqual(stage["status"], "PARTIAL")
        self.assertTrue(stage["requires_user_decision"])
        for role in devflow.WORKSPACE_ROLES:
            self.assertTrue(any(role in gap for gap in stage["gaps"]), role)
            self.assertIn(f"{role}=undecided", stage["evidence"])

    def test_explicit_workspace_requires_a_path_and_explicit_permissions(self):
        entry, errors = devflow.parse_workspace_role({"mode": "explicit"}, "automation.workspaces.scratch")
        self.assertTrue(any(".path обязателен" in item for item in errors))
        for permission in devflow.WORKSPACE_PERMISSIONS:
            self.assertTrue(any(f".{permission} обязателен" in item for item in errors), permission)
        del entry
        _, clean = devflow.parse_workspace_role(
            {"mode": "explicit", "path": ".", "changes": True, "dependencies": False, "tests": True},
            "automation.workspaces.control_checkout")
        self.assertEqual(clean, [])
        _, forbidden = devflow.parse_workspace_role(
            {"mode": "not-applicable", "path": "."}, "automation.workspaces.scratch")
        self.assertTrue(any("недопустим при mode=not-applicable" in item for item in forbidden))

    def test_unknown_workspace_role_is_rejected(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["automation"]["workspaces"] = {"build_cache": {"mode": "not-applicable"}}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("неизвестная роль каталога" in item for item in errors))

    def test_doctor_catches_the_control_checkout_used_as_a_worktree(self):
        self.apply_init()
        self.declare_workspaces(control=".", worktree=".")
        report = devflow.workspace_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertEqual(report["status"], "PARTIAL")
        self.assertTrue(any("один каталог" in item for item in report["findings"]))

    def test_doctor_catches_dependencies_in_the_control_checkout(self):
        self.apply_init()
        devflow.configure_value(
            self.repo, "automation.workspaces.control_checkout",
            json.dumps({"mode": "explicit", "path": ".", "changes": True,
                        "dependencies": True, "tests": False}))
        report = devflow.workspace_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertTrue(any("установку зависимостей" in item for item in report["findings"]))

    def test_doctor_catches_scratch_tracked_inside_the_repository(self):
        self.apply_init()
        (self.repo / "tmp").mkdir()
        self.declare_workspaces(scratch={"mode": "explicit", "path": "tmp",
                                         "changes": True, "dependencies": False, "tests": False})
        report = devflow.workspace_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertTrue(any("не игнорируется git" in item for item in report["findings"]))

    def downgrade_stage_definitions(self):
        """Reproduce a project installed before this stage existed."""
        stages = devflow.load_json(self.repo / devflow.SETUP_STAGES_PATH)
        stages["stages"] = [item for item in stages["stages"] if item["id"] != "workspaces"]
        (self.repo / devflow.SETUP_STAGES_PATH).write_text(
            json.dumps(stages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_setup_survives_stage_definitions_older_than_the_cli(self):
        self.apply_init()
        self.downgrade_stage_definitions()
        results = devflow.evaluate_setup(self.repo)
        self.assertEqual([item["stage"] for item in results], list(devflow.SETUP_STAGE_SEQUENCE))
        stage = next(item for item in results if item["stage"] == "workspaces")
        self.assertEqual(stage["status"], "PARTIAL")
        self.assertTrue(any("устарели" in gap and "upgrade --apply" in gap for gap in stage["gaps"]))
        self.assertIn("upgrade", stage["next_command"])
        self.assertEqual(stage["next_stage"], "graph")
        self.assertEqual(
            next(item for item in results if item["stage"] == "roles")["next_stage"], "graph")

    def test_doctor_survives_stage_definitions_older_than_the_cli(self):
        self.apply_init()
        self.downgrade_stage_definitions()
        report = devflow.doctor(self.repo)
        setup = next(item for item in report["diagnosis"] if item["check"] == "setup")
        stage = next(item for item in setup["stages"] if item["stage"] == "workspaces")
        self.assertEqual(stage["status"], "PARTIAL")
        self.assertTrue(any("устарели" in gap for gap in stage["gaps"]))

    def test_upgrade_refreshes_stage_definitions_and_activates_the_stage(self):
        self.apply_init()
        self.downgrade_stage_definitions()
        plan = devflow.build_setup_plan(self.repo, "upgrade", "test-upgrade")
        self.assertIn(devflow.SETUP_STAGES_PATH, [item["path"] for item in plan["operations"]])
        devflow.apply_plan(self.repo, plan)
        installed = devflow.load_json(self.repo / devflow.SETUP_STAGES_PATH)
        self.assertIn("workspaces", [item["id"] for item in installed["stages"]])
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "workspaces")
        self.assertFalse(any("устарели" in gap for gap in stage["gaps"]))
        for role in devflow.WORKSPACE_ROLES:
            self.assertTrue(any(role in gap for gap in stage["gaps"]), role)

    def test_decided_workspaces_pass_the_stage(self):
        self.apply_init()
        (self.repo.parent / "work").mkdir(exist_ok=True)
        self.declare_workspaces(control=".", worktree="../work")
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "workspaces")
        self.assertEqual(stage["status"], "PASS")
        self.assertEqual(stage["gaps"], [])
        self.assertFalse(stage["requires_user_decision"])

    # --- gate origin and the minimal validation plan --------------------------------------

    def declare_validation_plan(self, skip=("test fails for intended reason",)):
        config, _, _ = devflow.load_project_state(self.repo)
        config["quality"]["validation_plan"] = {
            "docs-only": {
                "paths": ["docs/", "*.md", ".agent-flow/"],
                "skip_checks": list(skip),
                "reason": "изменение не затрагивает исполняемый код",
            }
        }
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        return config

    def commit_on_branch(self, relative, content, message):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return self.commit_worktree(message)

    def prepare_branch_with_base(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort=None)
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-B", "main"], check=True)
        self.commit_worktree("baseline")
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-b", "agent/change"], check=True)

    def test_every_gate_carries_a_known_origin_and_scope(self):
        self.apply_init()
        config, workflow, _ = devflow.load_project_state(self.repo)
        config["github"]["required_checks"] = ["unit"]
        node = next(item for item in workflow["nodes"] if item["id"] == "final_review")
        verdict = {"claim": None, "minimization": False}
        gates = devflow.gate_attribution(config, workflow, node, verdict)
        self.assertTrue(gates)
        for gate in gates:
            self.assertIn(gate["origin"], devflow.GATE_ORIGINS)
            self.assertEqual(gate["scope"], devflow.GATE_SCOPE_REPOSITORY)
            self.assertTrue(gate["reason"])
            self.assertIn(gate["requirement"], {
                devflow.GATE_REQUIRED_PROVEN,
                devflow.GATE_NOT_REQUIRED,
                devflow.GATE_REQUIRED_UNPROVEN,
            })
        origins = {gate["origin"] for gate in gates}
        self.assertIn("repository-policy", origins)
        self.assertIn("skill", origins)
        kinds = {gate["kind"] for gate in gates}
        self.assertIn("evidence-artifact", kinds)

    def test_unknown_gate_origin_is_an_error(self):
        self.assertNotIn("invented", devflow.GATE_ORIGINS)

    def test_verified_change_type_minimizes_only_node_checks(self):
        self.prepare_branch_with_base()
        self.declare_validation_plan()
        self.commit_on_branch("docs/guide.md", "# guide\n", "docs change")
        config, workflow, _ = devflow.load_project_state(self.repo)
        verdict = devflow.verify_change_type(self.repo, config, "docs-only")
        self.assertTrue(verdict["verified"])
        self.assertTrue(verdict["minimization"])
        node = next(item for item in workflow["nodes"] if item["id"] == "tdd_red")
        gates = devflow.gate_attribution(config, workflow, node, verdict)
        excluded = [g for g in gates if g["requirement"] == devflow.GATE_NOT_REQUIRED]
        self.assertTrue(excluded)
        for gate in excluded:
            self.assertEqual(gate["origin"], "skill")
            self.assertEqual(gate["kind"], devflow.GATE_KIND_NODE_CHECK)
            self.assertIn("docs-only", gate["reason"])

    def test_a_claim_the_diff_does_not_support_grants_nothing(self):
        self.prepare_branch_with_base()
        self.declare_validation_plan()
        self.commit_on_branch("app.py", "print(2)\n", "code change")
        config, workflow, _ = devflow.load_project_state(self.repo)
        verdict = devflow.verify_change_type(self.repo, config, "docs-only")
        self.assertFalse(verdict["verified"])
        self.assertFalse(verdict["minimization"])
        self.assertIn("app.py", verdict["unmatched_paths"])
        self.assertIn("не подтверждён диффом", verdict["note"])
        node = next(item for item in workflow["nodes"] if item["id"] == "tdd_red")
        gates = devflow.gate_attribution(config, workflow, node, verdict)
        self.assertEqual(
            [g for g in gates if g["requirement"] == devflow.GATE_NOT_REQUIRED], [])

    def test_an_undeclared_type_or_missing_policy_falls_back_loudly(self):
        self.prepare_branch_with_base()
        self.commit_on_branch("docs/guide.md", "# guide\n", "docs change")
        config, _, _ = devflow.load_project_state(self.repo)
        self.assertTrue(devflow.changed_paths_for_validation(self.repo)["paths"])
        without_policy = devflow.verify_change_type(self.repo, config, "docs-only")
        self.assertFalse(without_policy["minimization"])
        self.assertIn("не настроена", without_policy["note"])
        self.declare_validation_plan()
        config, _, _ = devflow.load_project_state(self.repo)
        unknown_type = devflow.verify_change_type(self.repo, config, "refactor")
        self.assertFalse(unknown_type["minimization"])
        self.assertIn("не объявлен", unknown_type["note"])
        undeclared = devflow.verify_change_type(self.repo, config, "")
        self.assertFalse(undeclared["minimization"])
        self.assertIn("не объявлен", undeclared["note"])

    def test_minimization_is_unavailable_without_a_comparable_base(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort=None)
        self.declare_validation_plan()
        self.commit_worktree("single commit")
        # No branch a comparison could use: no remote, and no main or master.
        subprocess.run(["git", "-C", str(self.repo), "checkout", "-q", "-b", "agent/only"], check=True)
        for branch in ["main", "master"]:
            subprocess.run(["git", "-C", str(self.repo), "branch", "-q", "-D", branch],
                           check=False, capture_output=True)
        (self.repo / "docs").mkdir(exist_ok=True)
        self.commit_on_branch("docs/guide.md", "# guide\n", "docs change")
        config, _, _ = devflow.load_project_state(self.repo)
        verdict = devflow.verify_change_type(self.repo, config, "docs-only")
        self.assertFalse(verdict["minimization"])
        self.assertIn("Базовая версия", verdict["note"])

    def test_policy_cannot_lower_a_repository_or_merge_gate_requirement(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["github"]["required_checks"] = ["unit"]
        config["quality"]["validation_plan"] = {
            "docs-only": {
                "paths": ["docs/"],
                "reason": "r",
                "skip_checks": ["required_checks_green", "unit"],
            }
        }
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("инвариант merge gate" in item for item in errors))
        self.assertTrue(any("политикой репозитория" in item for item in errors))

    def test_policy_cannot_drop_a_required_evidence_artifact(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        config["quality"]["validation_plan"] = {
            "docs-only": {
                "paths": ["docs/"],
                "reason": "r",
                "skip_checks": ["review verdict bound to head SHA"],
            }
        }
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertTrue(any(
            "обязательный артефакт узла final_review" in item for item in errors))

    def test_validation_plan_requires_paths_and_a_reason(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["quality"]["validation_plan"] = {"docs-only": {"skip_checks": ["unit"]}}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any(".paths обязателен" in item for item in errors))
        self.assertTrue(any(".reason обязателен" in item for item in errors))

    def test_kit_ships_no_validation_plan_so_nothing_is_minimized(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertNotIn("validation_plan", config["quality"])
        self.assertEqual(devflow.validation_plan_of(config), {})

    def test_three_requirement_states_never_collapse_in_a_run_record(self):
        self.prepare_branch_with_base()
        self.declare_validation_plan()
        config, _, _ = devflow.load_project_state(self.repo)
        config["github"]["required_checks"] = ["unit"]
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["m"]}
        config["automation"]["background_workers"] = "verified"
        config["github"].update({"remote_settings": "verified", "ruleset_verified": True})
        for settings in config["roles"].values():
            if settings["agent"] != "human":
                settings["model"] = {"mode": "explicit", "value": "m"}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        self.resolve_all_skill_decisions()
        head = self.commit_on_branch("docs/guide.md", "# guide\n", "docs change")
        recorded = devflow.record_run(
            self.repo, "tdd_red", "PASS", head, "#14", "PR-1",
            ["failing test before implementation=ci://run/1", "failure reason=assert"],
            "codex", "m", "high", ["unit=success"], None, "docs-only",
        )
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertTrue(stored["validation"]["verified"])
        states = {gate["name"]: gate["requirement"] for gate in stored["gates"]}
        self.assertEqual(states["unit"], devflow.GATE_REQUIRED_PROVEN)
        self.assertEqual(
            states["test fails for intended reason"], devflow.GATE_NOT_REQUIRED)
        self.assertIn(devflow.GATE_REQUIRED_UNPROVEN, set(states.values()))
        self.assertEqual(len(set(states.values())), 3)

    # --- client adapters -----------------------------------------------------------------

    def test_unknown_agent_reference_blocks_validation_with_its_pointer(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        # The typo class from the first pilot: devflow_development vs devflow-development.
        config["roles"]["qa"]["agent"] = "devflow_development"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        config["roles"]["qa"]["effort"] = {"mode": "unset"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("roles.qa.agent" in item and "неизвестный agent" in item for item in errors))
        config = devflow.load_json(kit / "config.json")
        config["node_overrides"] = {"implement": {"agent": "claude_code"}}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("node_overrides.implement.agent" in item for item in errors))

    def test_client_is_resolved_by_membership_not_by_substring(self):
        self.assertEqual(devflow.client_for_agent("claude-code"), "claude")
        self.assertEqual(devflow.client_for_agent("codex"), "codex")
        # A name that merely contains a client name is not that client.
        self.assertIsNone(devflow.client_for_agent("claude_code"))
        self.assertIsNone(devflow.client_for_agent("my-codex-fork"))
        self.assertIsNone(devflow.client_for_agent(devflow.AGENT_UNRESOLVED))

    def test_registry_is_extensible_by_configuration_and_absent_from_the_kit(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertNotIn("clients", config)
        config["clients"] = {"gemini": {"agents": ["gemini-cli"], "effort": ["standard"]}}
        registry = devflow.client_registry(config)
        self.assertEqual(devflow.client_for_agent("gemini-cli", registry), "gemini")
        self.assertIn("gemini-cli", devflow.known_agent_identifiers(registry))
        config["roles"]["qa"]["agent"] = "gemini-cli"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        config["roles"]["qa"]["effort"] = {"mode": "explicit", "value": "standard"}
        errors, _ = devflow.validate_config(config)
        self.assertEqual(errors, [])

    def test_effort_outside_the_client_vocabulary_is_rejected(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["roles"]["qa"]["agent"] = "codex"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        config["roles"]["qa"]["effort"] = {"mode": "explicit", "value": "max"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("словаре клиента codex" in item for item in errors))
        config["roles"]["qa"]["agent"] = "claude-code"
        errors, _ = devflow.validate_config(config)
        self.assertEqual(errors, [])

    def test_client_without_an_effort_vocabulary_rejects_an_expressed_effort(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["clients"] = {"silent": {"agents": ["silent-runner"], "effort": []}}
        config["roles"]["qa"]["agent"] = "silent-runner"
        config["roles"]["qa"]["model"] = {"mode": "inherited"}
        for mode in [{"mode": "explicit", "value": "high"}, {"mode": "inherited"}]:
            config["roles"]["qa"]["effort"] = mode
            errors, _ = devflow.validate_config(config)
            self.assertTrue(any("не объявляет словарь effort" in item for item in errors), mode)
            self.assertTrue(any("clients.silent" in item for item in errors), mode)
        config["roles"]["qa"]["effort"] = {"mode": "unset"}
        errors, _ = devflow.validate_config(config)
        self.assertEqual(errors, [])

    def test_unset_effort_needs_no_observed_value_when_the_client_cannot_express_it(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["clients"] = {"silent": {"agents": ["silent-runner"], "effort": []}}
        for settings in config["roles"].values():
            if settings["agent"] == "human":
                continue
            settings.update({
                "agent": "silent-runner",
                "model": {"mode": "explicit", "value": "verified-model"},
                "effort": {"mode": "unset"},
            })
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["verified-model"]}
        config["automation"]["background_workers"] = "verified"
        config["github"].update({"remote_settings": "verified", "ruleset_verified": True, "required_checks": []})
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        self.resolve_all_skill_decisions()
        head = self.commit_worktree()
        recorded = devflow.record_run(
            self.repo, "implement", "PASS", head, "#13", "PR-1",
            ["passing targeted tests=ci://t", "implementation diff=git://d",
             "updated architecture docs when required=n/a"],
            "silent-runner", "verified-model", None, [],
        )
        self.assertEqual(recorded["status"], "PASS")
        stored = devflow.load_json(Path(recorded["path"]))
        self.assertIsNone(stored["actual"]["effort"])
        self.assertEqual(stored["effort_note"], "client-has-no-effort-vocabulary")
        self.assertEqual(stored["client"], "silent")

    def test_observed_effort_outside_the_client_vocabulary_is_refused(self):
        self.apply_init()
        self.prepare_verified_delivery_state(required_checks=(), agent="codex")
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "implement", "PASS", head, "#13", "PR-1",
                ["passing targeted tests=ci://t", "implementation diff=git://d",
                 "updated architecture docs when required=n/a"],
                "codex", "verified-model", "max", [],
            )
        self.assertIn("словаре клиента codex", str(context.exception))

    def test_moving_a_value_between_levels_is_matrix_drift(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort="high")
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        # Same value and same mode, different level: previously invisible to the comparison.
        config["node_overrides"] = {"implement": {"effort": {"mode": "explicit", "value": "high"}}}
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        moved = devflow.effective_configuration_from_files(self.repo)
        row = next(item for item in moved["rows"] if item["node"] == "implement")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["effort_source_level"], "node-override")
        as_role = copy.deepcopy(moved)
        for item in as_role["rows"]:
            if item["node"] == "implement":
                item["effort_source_level"] = "role"
                item["effort_source"] = "roles.implementer.effort"
        differences = devflow.compare_effective_configuration(as_role, moved)
        self.assertTrue(any("effort_source_level" in item for item in differences))

    def test_cross_client_transfer_resets_chosen_values_loudly(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort="high")
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["roles"]["implementer"]["model"] = {"mode": "explicit", "value": "gpt-5"}
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["gpt-5"]}
        config["node_overrides"] = {
            "implement": {"effort": {"mode": "explicit", "value": "high"}},
            "tdd_red": {"agent": "codex", "effort": {"mode": "explicit", "value": "high"}},
        }
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        result = devflow.configure_role(self.repo, "implementer", "claude-code")
        moved = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(moved["roles"]["implementer"]["model"], {"mode": "undecided"})
        self.assertEqual(moved["roles"]["implementer"]["effort"], {"mode": "undecided"})
        # The cascade: an override naming no agent of its own follows the role's client.
        self.assertEqual(moved["node_overrides"]["implement"]["effort"], {"mode": "undecided"})
        # An override that names its own agent keeps its client and its value.
        self.assertEqual(
            moved["node_overrides"]["tdd_red"]["effort"], {"mode": "explicit", "value": "high"})
        self.assertTrue(any("roles.implementer.model" in item for item in result["reset_parameters"]))
        self.assertTrue(any("node_overrides.implement.effort" in item for item in result["reset_parameters"]))
        self.assertIn("не взаимозаменяемы", result["note"])

    def test_same_client_agent_change_keeps_the_chosen_values(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["clients"] = {"codex": {"agents": ["codex", "codex-cloud"]}}
        for settings in config["roles"].values():
            if settings["agent"] == "human":
                continue
            settings.update({
                "agent": "codex",
                "model": {"mode": "explicit", "value": "gpt-5"},
                "effort": {"mode": "explicit", "value": "high"},
            })
        config["models"] = {"availability_checked_at": "2026-01-01T00:00:00Z", "available": ["gpt-5"]}
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        result = devflow.configure_role(self.repo, "implementer", "codex-cloud")
        kept = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(kept["roles"]["implementer"]["model"], {"mode": "explicit", "value": "gpt-5"})
        self.assertEqual(result["reset_parameters"], [])

    def test_transfer_to_and_from_a_non_executing_agent(self):
        self.apply_init()
        self.choose_executors(agent="codex", model=None, effort="high")
        devflow.configure_role(self.repo, "implementer", "human")
        parked = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(parked["roles"]["implementer"]["model"], {"mode": "not-applicable"})
        self.assertEqual(parked["roles"]["implementer"]["effort"], {"mode": "not-applicable"})
        devflow.configure_role(self.repo, "implementer", "claude-code")
        back = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(back["roles"]["implementer"]["model"], {"mode": "undecided"})
        self.assertEqual(back["roles"]["implementer"]["effort"], {"mode": "undecided"})

    # --- autonomous chain budget ---------------------------------------------------------

    def set_pipeline_budget(self, budget):
        return devflow.configure_value(self.repo, "automation.pipeline", json.dumps(budget))

    def consume_chain_task(self, issue):
        devflow.record_run(
            self.repo, "inspect_project", "FAIL", "", issue, "", ["chain task"],
            None, None, None,
        )

    def test_kit_ships_a_manual_pipeline_and_runs_nothing_autonomously(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(config["automation"]["pipeline"], {"mode": "manual"})
        self.apply_init()
        report = devflow.pipeline_check(self.repo)
        self.assertFalse(report["allowed"])
        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("явному го PM", report["reason"])

    def test_pipeline_budget_requires_a_named_decision(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["automation"]["pipeline"] = {"mode": "count", "value": 3}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("decision_ref обязателен" in item for item in errors))
        config["automation"]["pipeline"] = {"mode": "count", "value": 0, "decision_ref": "PM-1"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("не меньше 1" in item for item in errors))
        config["automation"]["pipeline"] = {"mode": "until", "decision_ref": "PM-1"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("контрольную задачу" in item for item in errors))

    def test_count_budget_consumes_a_unit_per_attributed_task(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 2)
        self.consume_chain_task("#31")
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 1)
        # A second record for the same Issue is the same task, not a second one.
        self.consume_chain_task("https://github.com/owner/repo/issues/31")
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 1)
        self.consume_chain_task("#32")
        spent = devflow.pipeline_check(self.repo)
        self.assertEqual(spent["remaining"], 0)
        self.assertFalse(spent["allowed"])
        self.assertIn("отчёт-разбор", spent["reason"])
        self.assertIn("новым decision_ref", spent["reason"])

    def test_stop_statuses_still_consume_a_chain_task(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        devflow.record_run(
            self.repo, "inspect_project", "BLOCKED", "", "#31", "", ["stopped"], None, None, None,
        )
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 1)

    def test_until_budget_includes_the_control_task_and_stops_after_it(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "until", "value": "#40", "decision_ref": "PM-2"})
        self.consume_chain_task("#38")
        allowed = devflow.pipeline_check(self.repo)
        self.assertTrue(allowed["allowed"])
        self.assertEqual(allowed["control_issue_key"], "40")
        self.consume_chain_task("#40")
        stopped = devflow.pipeline_check(self.repo)
        self.assertFalse(stopped["allowed"])
        self.assertIn("контрольная задача #40", stopped["reason"])

    def test_changing_the_budget_under_the_same_decision_is_refused(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        devflow.pipeline_check(self.repo)
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["automation"]["pipeline"] = {"mode": "count", "value": 50, "decision_ref": "PM-1"}
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        refused = devflow.pipeline_check(self.repo)
        self.assertFalse(refused["allowed"])
        self.assertIn("без нового решения", refused["reason"])

    def test_raising_the_budget_under_the_same_decision_is_refused_at_the_mutation(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        self.consume_chain_task("#31")
        self.consume_chain_task("#32")
        self.assertFalse(devflow.pipeline_check(self.repo)["allowed"])
        before_state = devflow.load_json(self.repo / devflow.PIPELINE_STATE_PATH)
        before_config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        with self.assertRaises(devflow.DevflowError) as context:
            self.set_pipeline_budget({"mode": "count", "value": 5, "decision_ref": "PM-1"})
        self.assertIn("без нового решения", str(context.exception))
        # Neither the state nor the configuration may move.
        self.assertEqual(devflow.load_json(self.repo / devflow.PIPELINE_STATE_PATH), before_state)
        self.assertEqual(devflow.load_json(self.repo / devflow.CONFIG_PATH), before_config)
        self.assertFalse(devflow.pipeline_check(self.repo)["allowed"])

    def test_repeating_the_same_budget_command_keeps_the_count(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 3, "decision_ref": "PM-1"})
        self.consume_chain_task("#31")
        before = devflow.load_json(self.repo / devflow.PIPELINE_STATE_PATH)
        self.assertEqual(devflow.pipeline_check(self.repo)["consumed_count"], 1)
        self.set_pipeline_budget({"mode": "count", "value": 3, "decision_ref": "PM-1"})
        after = devflow.load_json(self.repo / devflow.PIPELINE_STATE_PATH)
        self.assertEqual(after["started_at"], before["started_at"])
        self.assertEqual(after["known_runs"], before["known_runs"])
        self.assertEqual(devflow.pipeline_check(self.repo)["consumed_count"], 1)
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 2)

    def test_a_new_decision_starts_the_count_again(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 1, "decision_ref": "PM-1"})
        self.consume_chain_task("#31")
        self.assertFalse(devflow.pipeline_check(self.repo)["allowed"])
        self.set_pipeline_budget({"mode": "count", "value": 1, "decision_ref": "PM-2"})
        renewed = devflow.pipeline_check(self.repo)
        self.assertTrue(renewed["allowed"])
        self.assertEqual(renewed["consumed_count"], 0)

    def test_pipeline_state_survives_a_restart_and_is_not_reset_silently(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        self.consume_chain_task("#31")
        state = devflow.load_json(self.repo / devflow.PIPELINE_STATE_PATH)
        self.assertEqual(state["decision_ref"], "PM-1")
        # A later process reads the same state and the same count.
        self.assertEqual(devflow.pipeline_check(self.repo)["consumed_count"], 1)
        self.assertEqual(devflow.pipeline_check(self.repo)["remaining"], 1)

    def test_hand_edited_budget_initializes_state_and_says_so(self):
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["automation"]["pipeline"] = {"mode": "count", "value": 2, "decision_ref": "PM-9"}
        (self.repo / devflow.CONFIG_PATH).write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        report = devflow.pipeline_check(self.repo)
        self.assertTrue(report["state_initialized"])
        self.assertIn("мимо CLI", report["note"])

    def test_active_budget_makes_every_record_attributable(self):
        self.apply_init()
        # Without a budget the contract for a node outside any cycle is unchanged.
        self.assertEqual(
            devflow.record_run(
                self.repo, "inspect_project", "FAIL", "", "", "", ["no issue"], None, None, None,
            )["status"],
            "PASS",
        )
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "inspect_project", "FAIL", "", "", "", ["no issue"], None, None, None,
            )
        self.assertIn("Активен бюджет конвейера", str(context.exception))

    def test_switching_back_to_manual_clears_the_budget_state(self):
        self.apply_init()
        self.set_pipeline_budget({"mode": "count", "value": 2, "decision_ref": "PM-1"})
        self.assertTrue((self.repo / devflow.PIPELINE_STATE_PATH).is_file())
        self.set_pipeline_budget({"mode": "manual"})
        self.assertFalse((self.repo / devflow.PIPELINE_STATE_PATH).is_file())
        self.assertFalse(devflow.pipeline_check(self.repo)["allowed"])

    def test_github_runbook_is_linked_and_matches_the_reported_gaps(self):
        root = Path(devflow.__file__).resolve().parent.parent
        runbook = root / "references" / "github-preparation.md"
        self.assertTrue(runbook.is_file())
        text = runbook.read_text(encoding="utf-8")
        # The runbook must speak in the exact words the CLI reports.
        for reported in [
            "Remote GitHub rulesets, required checks, and merge policy are unverified",
            "GitHub remote settings and adapter access are unverified for review/release",
            "No remotely verified required-check set is configured",
            "A remote merge ruleset has not been verified",
            "Background executor availability is unverified",
            "No GitHub Actions workflow detected",
        ]:
            self.assertIn(reported, text, reported)
        for field in ["github.remote_settings", "github.required_checks", "github.ruleset_verified"]:
            self.assertIn(field, text, field)
        for owner_trace in ["belkov", "gmail", "masha"]:
            self.assertNotIn(owner_trace, text.lower(), owner_trace)
        for referrer in [root / "README.md", root / "references" / "setup-and-commands.md"]:
            self.assertIn("github-preparation.md", referrer.read_text(encoding="utf-8"), referrer.name)
        self.apply_init()
        self.assertIn(
            "github-preparation.md",
            next(item for item in devflow.evaluate_setup(self.repo) if item["stage"] == "git-github")["recommendation"],
        )

    def test_prepare_issue_node_requires_a_single_feature_scope(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        workflow = devflow.load_json(kit / "workflow.json")
        node = next(item for item in workflow["nodes"] if item["id"] == "prepare_issue")
        self.assertTrue(any("one feature" in check for check in node["checks"]))
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertEqual(errors, [])

    def test_decomposition_rule_is_canonical_in_process_and_managed_material(self):
        root = Path(devflow.__file__).resolve().parent.parent
        reference = (root / "references" / "process-and-quality.md").read_text(encoding="utf-8")
        self.assertIn("Size an Issue around one feature or one decision", reference)
        self.assertIn("reviewable in one pass", reference)
        block = (devflow.find_project_kit(self.repo) / "managed" / "AGENTS.block.md").read_text(encoding="utf-8")
        self.assertIn("Size an Issue around one feature or decision", block)
        self.assertIn(devflow.MANAGED_START, block)

    def test_pending_decision_hint_offers_every_typed_mode(self):
        self.apply_init()
        pending = devflow.pending_execution_decisions(
            devflow.load_json(self.repo / devflow.CONFIG_PATH),
            devflow.load_json(self.repo / devflow.WORKFLOW_PATH),
        )
        model_hint = next(item for item in pending if item["pointer"].endswith(".model"))
        for mode in ["inherit", "unset", "not-applicable"]:
            self.assertIn(mode, model_hint["command"])

    def test_shipped_kit_names_no_executor_model_or_effort(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        for role, settings in config["roles"].items():
            if settings["agent"] == "human":
                # human-pm is the structural human role, not a vendor choice.
                self.assertEqual(settings["model"], {"mode": "not-applicable"})
                self.assertEqual(settings["effort"], {"mode": "not-applicable"})
                continue
            self.assertEqual(settings["agent"], devflow.AGENT_UNRESOLVED, role)
            self.assertEqual(settings["model"], {"mode": "undecided"}, role)
            self.assertEqual(settings["effort"], {"mode": "undecided"}, role)
        self.assertEqual(config["policy"]["language"], "undecided")
        errors, warnings = devflow.validate_config(config)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_kit_and_managed_material_carry_no_owner_identifiers(self):
        kit = devflow.find_project_kit(self.repo)
        forbidden = ["belkov", "BelkovGB", "belkovgb", "@gmail", "masha", "vibe/automode"]
        checked = 0
        for path in sorted(kit.rglob("*")):
            if not path.is_file():
                continue
            checked += 1
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            for needle in forbidden:
                self.assertNotIn(needle.lower(), text, f"{path.name} carries {needle}")
        self.assertGreater(checked, 5)

    def test_fresh_install_inherits_no_layout_and_stops_setup_at_roles(self):
        self.apply_init()
        matrix = devflow.effective_configuration_from_files(self.repo)
        machine_rows = [row for row in matrix["rows"] if row["owner"] != "human-pm"]
        self.assertTrue(machine_rows)
        for row in machine_rows:
            self.assertEqual(row["agent"], devflow.AGENT_UNRESOLVED, row["node"])
            self.assertIsNone(row["model"], row["node"])
            self.assertIsNone(row["effort"], row["node"])
            self.assertEqual(row["model_mode"], "undecided", row["node"])
            self.assertEqual(row["effort_mode"], "undecided", row["node"])
        pending = devflow.pending_execution_decisions(
            devflow.load_json(self.repo / devflow.CONFIG_PATH),
            devflow.load_json(self.repo / devflow.WORKFLOW_PATH),
        )
        self.assertTrue(any(item["pointer"].endswith(".agent") for item in pending))
        stages = {item["stage"]: item for item in devflow.evaluate_setup(self.repo)}
        self.assertEqual(stages["context"]["status"], "BLOCKED")
        self.assertTrue(any("language" in gap.lower() for gap in stages["context"]["gaps"]))
        self.assertEqual(stages["roles"]["status"], "BLOCKED")
        self.assertTrue(stages["roles"]["requires_user_decision"])
        self.assertTrue(any("roles.implementer.agent" in gap for gap in stages["roles"]["gaps"]))

    def test_setup_reaches_roles_and_clears_it_only_after_explicit_choices(self):
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["project"]["product_stage"] = "development-readiness"
        config["project"]["decision_ref"] = "PM-1"
        config["policy"]["language"] = "en"
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        # The context stage now also holds the scale decision, so clearing it takes one
        # more explicit choice before setup moves on.
        devflow.scale_set(self.repo, "internal-tool", "PM-2")
        step = devflow.next_setup_step(devflow.evaluate_setup(self.repo), self.repo)
        self.assertEqual(step["stage"], "roles")
        self.assertEqual(step["status"], "BLOCKED")
        self.choose_executors(agent="codex", model=None, effort=None)
        stages = {item["stage"]: item for item in devflow.evaluate_setup(self.repo)}
        self.assertEqual(stages["roles"]["status"], "PASS")
        self.assertEqual(
            devflow.pending_execution_decisions(
                devflow.load_json(self.repo / devflow.CONFIG_PATH),
                devflow.load_json(self.repo / devflow.WORKFLOW_PATH),
            ),
            [],
        )

    def test_undecided_execution_cannot_preflight_or_record(self):
        self.apply_init()
        self.resolve_all_skill_decisions()
        preflight = devflow.operate_preflight(self.repo, "implement")
        self.assertEqual(preflight["status"], "BLOCKED")
        self.assertTrue(any("не выбран" in gap for gap in preflight["external_gaps"]))
        head = self.commit_worktree()
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.record_run(
                self.repo, "implement", "PASS", head, "ISSUE-1", "PR-1",
                ["passing targeted tests=ci://run/1", "implementation diff=git://diff",
                 "updated architecture docs when required=n/a"],
                "codex", "some-model", "high", [],
            )
        self.assertIn("не выбран", str(context.exception))

    def test_unresolved_agent_forbids_a_decided_model(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        config["roles"]["qa"]["model"] = {"mode": "explicit", "value": "some-model"}
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("агент не выбран" in item for item in errors))

    # --- session transport -----------------------------------------------------------

    def declare_sessions(self, implementer="impl-chat", reviewer="review-chat", client="claude",
                         extra=None):
        roles = {}
        if implementer is not None:
            roles["implementer"] = {"mode": "explicit", "session": implementer}
        if reviewer is not None:
            roles["reviewer"] = {"mode": "explicit", "session": reviewer}
        roles.update(extra or {})
        return devflow.configure_value(self.repo, "automation.sessions", json.dumps(
            {"mode": "explicit", "client": client, "roles": roles}))

    def commit_fixture(self):
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True,
                       capture_output=True)
        subprocess.run([
            "git", "-C", str(self.repo), "-c", "user.name=VibeCode Control Test",
            "-c", "user.email=devflow@example.invalid", "commit", "-qm", "fixture",
        ], check=True, capture_output=True)
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"],
                              check=True, text=True, encoding="utf-8", capture_output=True)
        return head.stdout.strip()

    def test_kit_names_no_session_and_setup_asks_for_the_transport(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(config["automation"]["sessions"], {"mode": "undecided"})
        self.apply_init()
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "automation")
        self.assertTrue(stage["requires_user_decision"])
        self.assertTrue(any("automation.sessions" in gap for gap in stage["gaps"]))
        self.assertIn("session transport=undecided", stage["evidence"])

    def test_session_transport_requires_a_client_that_declares_the_capability(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError) as context:
            self.declare_sessions(client="codex")
        self.assertIn("session_messaging", str(context.exception))
        # The capability is an adapter fact, so a project extension enables it without
        # touching the engine rule.
        devflow.configure_value(self.repo, "clients", json.dumps(
            {"codex": {"session_messaging": True}}))
        self.declare_sessions(client="codex")
        self.assertEqual(devflow.session_transport_of(
            devflow.load_json(self.repo / devflow.CONFIG_PATH))["client"], "codex")

    def test_session_registry_shape_is_typed(self):
        entry, errors = devflow.parse_session_role({"mode": "explicit"}, "p")
        self.assertTrue(any("p.session обязателен" in item for item in errors))
        del entry
        _, forbidden = devflow.parse_session_role({"mode": "undecided", "session": "x"}, "p")
        self.assertTrue(any("недопустим при mode=undecided" in item for item in forbidden))
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["automation"]["sessions"] = {
            "mode": "explicit", "client": "claude",
            "roles": {"nonexistent": {"mode": "explicit", "session": "s"}},
        }
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("не объявлена в config.roles" in item for item in errors))

    def test_one_session_cannot_both_implement_and_review_independently(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError) as context:
            self.declare_sessions(implementer="one-chat", reviewer="one-chat")
        message = str(context.exception)
        self.assertIn("изоляция контекстов нарушена", message)
        self.assertIn("final_review", message)
        # The write is refused where it happens, not only later by doctor.
        self.assertEqual(
            devflow.session_transport_of(devflow.load_json(self.repo / devflow.CONFIG_PATH))["mode"],
            "undecided")

    def test_self_review_by_the_implementer_session_stays_legal(self):
        self.apply_init()
        self.declare_sessions()
        _, workflow, _ = devflow.load_project_state(self.repo)
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        errors, _ = devflow.validate_workflow(workflow, config)
        self.assertEqual(errors, [])
        report = devflow.session_report(self.repo, config, workflow)
        self.assertEqual(report["bindings"]["implementer_review"], "impl-chat")
        self.assertEqual(report["bindings"]["final_review"], "review-chat")

    def test_a_role_of_another_client_cannot_be_bound_to_a_session(self):
        self.apply_init()
        self.choose_executors(agent="claude-code", implementer_agent="codex")
        with self.assertRaises(devflow.DevflowError) as context:
            self.declare_sessions()
        message = str(context.exception)
        self.assertIn("automation.sessions.roles.implementer", message)
        self.assertIn("принадлежит клиенту codex", message)
        # A non-executing agent is refused for the same reason, one floor earlier than
        # the run record would catch it.
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["automation"]["sessions"] = {
            "mode": "explicit", "client": "claude",
            "roles": {"human-pm": {"mode": "explicit", "session": "pm-chat"}},
        }
        errors, _ = devflow.validate_config(config)
        self.assertTrue(any("не получает постановок" in item for item in errors))

    def test_an_unresolved_role_may_still_be_bound_to_a_session(self):
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(config["roles"]["implementer"]["agent"], "unresolved")
        self.declare_sessions()
        report = devflow.session_report(
            self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH),
            devflow.load_json(self.repo / devflow.WORKFLOW_PATH))
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["bindings"]["implement"], "impl-chat")

    def test_a_non_executing_role_is_not_asked_about_a_session(self):
        self.apply_init()
        self.choose_executors(agent="claude-code")
        self.declare_sessions()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        workflow = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        report = devflow.session_report(self.repo, config, workflow)
        self.assertIn("human-pm", report["derived_not_applicable"])
        self.assertFalse(any(item["pointer"].endswith("human-pm") for item in report["pending"]))
        # Derived, not written: the configuration still holds no entry for the role.
        self.assertNotIn("human-pm", config["automation"]["sessions"].get("roles", {}))

    def test_giving_a_human_role_an_executing_agent_brings_the_question_back(self):
        self.apply_init()
        self.choose_executors(agent="claude-code")
        self.declare_sessions()
        devflow.configure_value(self.repo, "roles.human-pm", json.dumps({
            "agent": "claude-code", "model": {"mode": "explicit", "value": "verified-model"},
            "effort": {"mode": "explicit", "value": "high"}, "permissions": "human-approval",
        }))
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        report = devflow.session_report(
            self.repo, config, devflow.load_json(self.repo / devflow.WORKFLOW_PATH))
        self.assertNotIn("human-pm", report["derived_not_applicable"])
        self.assertTrue(any(item["pointer"].endswith("human-pm") for item in report["pending"]))

    def test_assign_refuses_a_manual_budget_without_a_named_pm_go(self):
        self.apply_init()
        self.declare_sessions()
        self.commit_fixture()
        blocked = devflow.session_assign(self.repo, "implement", "#17")
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertIn("явному го PM", blocked["reason"])
        rendered = devflow.session_assign(self.repo, "implement", "#17", pm_go="PM-77")
        self.assertEqual(rendered["status"], "PASS")
        self.assertEqual(rendered["authorization"], {"kind": "pm-go", "ref": "PM-77",
                                                     "continuation": False})
        self.assertIn("PM-77", rendered["assignment"])

    def test_assign_renders_the_facts_the_coordinator_would_otherwise_retype(self):
        self.apply_init()
        self.declare_sessions()
        head = self.commit_fixture()
        rendered = devflow.session_assign(self.repo, "final_review", "#17", pm_go="PM-77")
        text = rendered["assignment"]
        self.assertEqual(rendered["session"], "review-chat")
        self.assertEqual(rendered["head_sha"], head)
        self.assertIn(head, text)
        self.assertIn("operate --node final_review --issue '#17'", text)
        self.assertIn("run record --node final_review", text)
        # The evidence contract, not a retyped list.
        self.assertIn("review verdict bound to head SHA", text)
        self.assertIn("kind `review`", text)
        # Two rules the transport exists to carry.
        self.assertIn("restarted whole from the last recorded run record", text)
        self.assertIn("does not send it", text)

    def test_assign_refuses_a_new_issue_on_a_spent_budget_but_continues_a_counted_one(self):
        self.apply_init()
        self.declare_sessions()
        self.commit_fixture()
        self.set_pipeline_budget({"mode": "count", "value": 1, "decision_ref": "PM-9"})
        self.consume_chain_task("#17")
        spent = devflow.pipeline_check(self.repo)
        self.assertFalse(spent["allowed"])
        continuation = devflow.session_assign(self.repo, "implement", "#17")
        self.assertEqual(continuation["status"], "PASS")
        self.assertTrue(continuation["authorization"]["continuation"])
        fresh = devflow.session_assign(self.repo, "implement", "#18")
        self.assertEqual(fresh["status"], "BLOCKED")
        self.assertIn("Бюджет цепочки исчерпан", fresh["reason"])

    def test_assign_names_the_command_when_the_role_has_no_session(self):
        self.apply_init()
        self.commit_fixture()
        with self.assertRaises(devflow.DevflowError) as undeclared:
            devflow.session_assign(self.repo, "implement", "#17", pm_go="PM-77")
        self.assertIn("Транспорт сессий не объявлен", str(undeclared.exception))
        self.declare_sessions(implementer=None)
        with self.assertRaises(devflow.DevflowError) as unnamed:
            devflow.session_assign(self.repo, "implement", "#17", pm_go="PM-77")
        self.assertIn("automation.sessions.roles.implementer", str(unnamed.exception))

    def test_preflight_reports_the_session_and_refuses_to_claim_it_is_alive(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        self.declare_sessions(extra={"qa": {"mode": "explicit", "session": "qa-chat"}})
        report = devflow.operate_preflight(self.repo, "implement", "#17")
        self.assertEqual(report["transport"]["session"], "impl-chat")
        self.assertEqual(report["transport"]["kind"], "sessions")
        self.assertIn("CLI сессий не видит", report["transport"]["liveness"])
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["external_gaps"], [])
        # A role without a session is a named gap, not a silent pass.
        devflow.configure_value(self.repo, "automation.sessions.roles.qa",
                                json.dumps({"mode": "undecided"}))
        qa = devflow.operate_preflight(self.repo, "quality_gates", "#17")
        self.assertTrue(any("Сессия для роли qa не названа" in gap for gap in qa["external_gaps"]))

    def test_a_named_session_does_not_replace_verified_background_workers(self):
        self.apply_init()
        self.choose_executors(agent="claude-code")
        self.resolve_all_skill_decisions()
        self.declare_sessions()
        report = devflow.operate_preflight(self.repo, "implement", "#17")
        self.assertEqual(report["transport"]["session"], "impl-chat")
        self.assertIn("Background executor availability is unverified", report["external_gaps"])

    def test_assignment_template_must_not_ask_for_facts_the_cli_does_not_supply(self):
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.render_session_assignment("{{node}} {{invented_fact}}", {"node": "implement"})
        self.assertIn("invented_fact", str(context.exception))

    def test_a_project_installed_before_this_transport_degrades_instead_of_crashing(self):
        self.apply_init()
        # Exactly what an older install looks like: no registry, no prompt home.
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        del config["automation"]["sessions"]
        (self.repo / devflow.CONFIG_PATH).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.repo / devflow.SESSION_ASSIGNMENT_TEMPLATE).unlink()
        _, workflow, _ = devflow.load_project_state(self.repo)
        self.assertEqual(devflow.validate_config(config)[0], [])
        report = devflow.session_report(self.repo, config, workflow)
        self.assertEqual(report["mode"], "undecided")
        sessions = next(item for item in devflow.doctor(self.repo)["diagnosis"]
                        if item["check"] == "sessions")
        self.assertEqual(sessions["status"], "PARTIAL")
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "automation")
        self.assertTrue(any("automation.sessions" in gap for gap in stage["gaps"]))
        # The shipped wording still renders, and upgrade restores the prompt home.
        self.declare_sessions()
        self.commit_fixture()
        self.assertEqual(
            devflow.session_assign(self.repo, "implement", "#17", pm_go="PM-77")["status"], "PASS")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "test-upgrade"))
        self.assertTrue((self.repo / devflow.SESSION_ASSIGNMENT_TEMPLATE).is_file())

    # --- test spec and model routing ---------------------------------------------------

    SPEC = "\n".join([
        "# Test specification",
        "## Criteria",
        "- `FR-001` — the parser rejects an unknown field",
        "## Cases",
        "### CASE-001",
        "- Criterion: `FR-001`",
        "- Type: `unit`",
        "- Given: a config with an unknown field",
        "- When: it is validated",
        "- Then: the error names the field",
        "- Expected failure reason: no validation exists yet",
        "",
    ])

    def route_tdd_red_to_another_model(self, model="fast-model"):
        config, _, _ = devflow.load_project_state(self.repo)
        config["models"]["available"] = sorted(set(config["models"]["available"]) | {model})
        config["node_overrides"] = {
            "tdd_red": {"model": {"mode": "explicit", "value": model}},
        }
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        return config

    def record_design_spec(self, reference, issue="#6"):
        return devflow.record_run(
            self.repo, "design", "PASS", "", issue, "",
            [f"design decision=ADR-1", f"test spec={reference}", "issue draft=#6"],
            "claude-code", "verified-model", "high",
        )

    def test_shipped_spec_template_passes_its_own_checker(self):
        kit = devflow.find_project_kit(self.repo)
        report = devflow.check_test_spec((kit / "managed" / "test-spec.md").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["covered"], report["criteria"])
        self.apply_init()
        self.assertTrue((self.repo / devflow.TEST_SPEC_TEMPLATE).is_file())

    def test_spec_check_requires_the_triple_the_reason_and_the_type(self):
        broken = "\n".join([
            "## Criteria",
            "- `FR-001` — something",
            "## Cases",
            "### CASE-001",
            "- Criterion: `FR-001`",
            "- Type: `smoke`",
            "- Given: a state",
            "- When: an action",
            "",
        ])
        report = devflow.check_test_spec(broken)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("Then обязательно" in item for item in report["errors"]))
        self.assertTrue(any("ожидаемая причина падения" in item for item in report["errors"]))
        self.assertTrue(any("тип теста" in item for item in report["errors"]))

    def test_spec_check_verifies_the_link_in_both_directions(self):
        uncovered = self.SPEC + "\n".join([
            "- `SC-001` — the second criterion nobody covers",
            "",
        ])
        # The extra criterion is declared after the cases section, so re-declare cleanly.
        uncovered = self.SPEC.replace(
            "- `FR-001` — the parser rejects an unknown field",
            "- `FR-001` — the parser rejects an unknown field\n- `SC-001` — nobody covers this",
        )
        report = devflow.check_test_spec(uncovered)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("SC-001 не покрыт" in item for item in report["errors"]))
        dangling = self.SPEC.replace("- Criterion: `FR-001`", "- Criterion: `FR-777`")
        report = devflow.check_test_spec(dangling)
        self.assertTrue(any("FR-777 не объявлен" in item for item in report["errors"]))
        duplicate = self.SPEC.replace(
            "- `FR-001` — the parser rejects an unknown field",
            "- `FR-001` — one\n- `FR-001` — two",
        )
        self.assertTrue(any("объявлен дважды" in item
                            for item in devflow.check_test_spec(duplicate)["errors"]))

    def test_spec_check_states_what_it_does_not_verify(self):
        report = devflow.check_test_spec(self.SPEC)
        self.assertEqual(report["status"], "PASS")
        self.assertIn("ревьюер", report["not_verified"])

    def test_routing_to_another_model_is_detected_from_the_configuration(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        _, workflow, _ = devflow.load_project_state(self.repo)
        node = next(item for item in workflow["nodes"] if item["id"] == "tdd_red")
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertIsNone(devflow.cross_model_routing(node, config))
        config = self.route_tdd_red_to_another_model()
        routing = devflow.cross_model_routing(node, config)
        self.assertEqual(routing["node_model"], "fast-model")
        self.assertEqual(routing["role_model"], "verified-model")
        # The same model on both levels is not routing, whichever way it was written.
        config["node_overrides"]["tdd_red"]["model"] = {"mode": "explicit", "value": "verified-model"}
        self.assertIsNone(devflow.cross_model_routing(node, config))

    def test_an_inherited_role_with_a_pinned_node_is_routing(self):
        """The primary shape: the client resolves the role, the node is pinned."""
        self.apply_init()
        self.choose_executors(agent="claude-code", model=None, effort="high")
        self.resolve_all_skill_decisions()
        config, workflow, _ = devflow.load_project_state(self.repo)
        self.assertEqual(config["roles"]["implementer"]["model"], {"mode": "inherited"})
        config["node_overrides"] = {
            "tdd_red": {"model": {"mode": "explicit", "value": "writer-model"}},
        }
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        node = next(item for item in workflow["nodes"] if item["id"] == "tdd_red")
        routing = devflow.cross_model_routing(
            node, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertIsNotNone(routing)
        self.assertEqual(routing["role_mode"], "inherited")
        self.assertIsNone(routing["role_model"])
        report = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertEqual(report["status"], "BLOCKED")
        # The blocker names the mode instead of pretending the role has a value.
        blocker = next(gap for gap in report["external_gaps"] if "tdd_red" in gap)
        self.assertIn("mode=inherited", blocker)
        self.assertIn("не определена до запуска", blocker)

    def test_an_unresolvable_role_model_never_waives_the_contract(self):
        self.apply_init()
        self.choose_executors(agent="claude-code", model=None, effort=None)
        _, workflow, _ = devflow.load_project_state(self.repo)
        node = next(item for item in workflow["nodes"] if item["id"] == "tdd_red")
        for role_model in ({"mode": "inherited"}, {"mode": "unset"}):
            config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
            config["roles"]["implementer"]["model"] = role_model
            config["node_overrides"] = {
                "tdd_red": {"model": {"mode": "explicit", "value": "writer-model"}},
            }
            routing = devflow.cross_model_routing(node, config)
            self.assertIsNotNone(routing, role_model)
            self.assertEqual(routing["role_mode"], role_model["mode"])
        # An override that is itself not pinned is not routing: there is no second model.
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        config["node_overrides"] = {"tdd_red": {"model": {"mode": "inherited"}}}
        self.assertIsNone(devflow.cross_model_routing(node, config))

    def test_routing_to_another_model_requires_the_spec_and_checks_it_when_local(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        self.route_tdd_red_to_another_model()
        blocked = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["test_spec"]["required_because"], "cross-model-routing")
        self.assertTrue(any("тот же ли это контекст" in gap
                            for gap in blocked["external_gaps"]))
        # A local reference is checked for free, so a broken spec cannot hide behind it.
        (self.repo / "docs").mkdir(exist_ok=True)
        (self.repo / "docs" / "spec.md").write_text(
            self.SPEC.replace("- Expected failure reason: no validation exists yet", ""),
            encoding="utf-8")
        self.record_design_spec("docs/spec.md")
        broken = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertEqual(broken["status"], "BLOCKED")
        self.assertTrue(broken["test_spec"]["spec"]["local"])
        self.assertTrue(any("не проходит проверку структуры" in gap
                            for gap in broken["external_gaps"]))
        (self.repo / "docs" / "spec.md").write_text(self.SPEC, encoding="utf-8")
        passing = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertEqual(passing["test_spec"]["spec"]["status"], "PASS")
        self.assertEqual(passing["status"], "PASS")

    def test_a_non_local_spec_reference_is_stated_in_words_not_blocked(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        self.route_tdd_red_to_another_model()
        self.record_design_spec("https://example.invalid/spec")
        report = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertFalse(report["test_spec"]["spec"]["local"])
        self.assertIn("локально не проверяется", report["test_spec"]["spec"]["note"])
        self.assertEqual(report["status"], "PASS")

    def test_matching_models_need_no_spec_contract(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        report = devflow.operate_preflight(self.repo, "tdd_red", "#6")
        self.assertIsNone(report["test_spec"])
        self.assertEqual(report["status"], "PASS")

    def test_tdd_red_declares_the_spec_and_refuses_improvisation(self):
        kit = devflow.find_project_kit(self.repo)
        node = next(item for item in devflow.load_json(kit / "workflow.json")["nodes"]
                    if item["id"] == "tdd_red")
        self.assertIn("test spec", node["inputs"])
        self.assertTrue(any("never improvised" in check for check in node["checks"]))
        self.assertTrue(any("expected failure reason" in check for check in node["checks"]))
        self.assertIn("test fails for intended reason", node["checks"])

    def test_the_kit_names_no_model_anywhere(self):
        kit = devflow.find_project_kit(self.repo)
        for path in sorted(kit.rglob("*.json")) + sorted(kit.rglob("*.md")):
            text = path.read_text(encoding="utf-8").lower()
            for token in ("gpt-", "claude-opus", "claude-sonnet", "haiku", "o3-", "gemini"):
                self.assertNotIn(token, text, f"{path.name} names a concrete model")

    # --- scale profiles ---------------------------------------------------------------

    def test_kit_chooses_no_scale_and_context_asks_with_the_command(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(config["project"]["scale"], {"mode": "undecided"})
        self.apply_init()
        stage = next(item for item in devflow.evaluate_setup(self.repo)
                     if item["stage"] == "context")
        self.assertEqual(stage["status"], "BLOCKED")
        self.assertTrue(any("project.scale" in gap for gap in stage["gaps"]))
        self.assertIn("scale=undecided", stage["evidence"])
        report = devflow.scale_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertEqual(report["pending"][0]["command"],
                         "devflow scale set <profile> --decision-ref <ref>")

    def test_profiles_are_kit_data_that_upgrade_refreshes(self):
        kit = devflow.find_project_kit(self.repo)
        shipped = devflow.load_json(kit / "scale-profiles.json")["profiles"]
        self.assertEqual(sorted(shipped), [
            "corporate", "internal-tool", "oss-library", "personal", "prototype",
            "regulated", "startup",
        ])
        self.apply_init()
        installed = self.repo / devflow.SCALE_PROFILES_PATH
        self.assertTrue(installed.is_file())
        installed.write_text(json.dumps({"schema_version": 1, "profiles": {}}), encoding="utf-8")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "refresh"))
        self.assertEqual(sorted(devflow.load_json(installed)["profiles"]), sorted(shipped))

    def test_a_project_may_add_and_override_profiles_but_not_reach_further(self):
        self.apply_init()
        devflow.configure_value(self.repo, "project.scale_profiles", json.dumps({
            "throwaway": {
                "audience": "one afternoon",
                "promotion_watch": True,
                "complexity_budget": {"limits": {"services": 1}, "rationale": "One sitting."},
                "gate_defaults": {"policy.tdd_for_behavior_changes": False},
            },
            "startup": {"audience": "our own definition of startup",
                        "complexity_budget": {"limits": {"services": 9}, "rationale": "Ours."},
                        "gate_defaults": {"policy.max_fix_cycles": 3}},
        }))
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        registry = devflow.scale_profile_registry(self.repo, config)
        self.assertIn("throwaway", registry)
        self.assertEqual(registry["startup"]["audience"], "our own definition of startup")
        self.assertEqual(devflow.scale_profile_errors(registry), [])
        # The allowlist applies to the merged registry, so a custom profile reaches no
        # further than a canonical one.
        with self.assertRaises(devflow.DevflowError) as context:
            devflow.configure_value(self.repo, "project.scale_profiles", json.dumps({
                "greedy": {
                    "complexity_budget": {"limits": {"services": 1}, "rationale": "x"},
                    "gate_defaults": {"automation.pipeline": {"mode": "count"}},
                },
            }))
        self.assertIn("не управляет этим параметром", str(context.exception))

    def test_a_scale_profile_cannot_reach_the_non_minimizable_core(self):
        core_pointers = {
            "automation.pipeline", "quality.validation_plan", "github.required_checks",
            "policy.max_fix_cycles_decision_ref",
        }
        self.assertEqual(set(devflow.SCALE_GATE_DEFAULT_KEYS) & core_pointers, set())
        for name in devflow.MERGE_GATE_INVARIANTS | devflow.NON_MINIMIZABLE_GATE_KINDS:
            self.assertFalse(any(name in key for key in devflow.SCALE_GATE_DEFAULT_KEYS), name)
        # Reachability is refused by construction, not by the profiles happening to
        # behave: every key outside the allowlist is a validation error.
        for pointer in sorted(core_pointers):
            registry = {"x": {"complexity_budget": {"limits": {"services": 1}, "rationale": "x"},
                              "gate_defaults": {pointer: True}}}
            self.assertTrue(any("не управляет этим параметром" in item
                                for item in devflow.scale_profile_errors(registry)), pointer)

    def test_choosing_and_changing_the_scale_both_need_a_named_decision(self):
        self.apply_init()
        with self.assertRaises(devflow.DevflowError) as missing:
            devflow.scale_set(self.repo, "startup", "")
        self.assertIn("--decision-ref", str(missing.exception))
        devflow.scale_set(self.repo, "startup", "PM-42")
        self.assertEqual(
            devflow.scale_of(devflow.load_json(self.repo / devflow.CONFIG_PATH)),
            {"mode": "explicit", "value": "startup", "decision_ref": "PM-42"})
        with self.assertRaises(devflow.DevflowError) as silent:
            devflow.scale_set(self.repo, "regulated", "PM-42")
        self.assertIn("без нового решения", str(silent.exception))
        # The identical repeat is not a change, so it is not refused.
        devflow.scale_set(self.repo, "startup", "PM-42")
        devflow.scale_set(self.repo, "regulated", "PM-51")
        self.assertEqual(
            devflow.scale_of(devflow.load_json(self.repo / devflow.CONFIG_PATH))["value"],
            "regulated")
        with self.assertRaises(devflow.DevflowError) as unknown:
            devflow.scale_set(self.repo, "enterprise-grade", "PM-52")
        self.assertIn("неизвестный профиль", str(unknown.exception))

    def test_doctor_reports_a_configuration_weaker_than_the_profile_with_commands(self):
        self.apply_init()
        devflow.scale_set(self.repo, "regulated", "PM-51")
        report = devflow.scale_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertEqual(report["status"], "PARTIAL")
        self.assertTrue(any("quality.baseline_status" in item for item in report["findings"]))
        self.assertIn("devflow config set quality.baseline_status \"measured\"",
                      [item["command"] for item in report["proposals"]])
        finding = next(item for item in devflow.doctor(self.repo)["diagnosis"]
                       if item["check"] == "scale")
        self.assertEqual(finding["profile"], "regulated")

    def test_promotion_watch_is_a_flag_in_the_data_not_a_name_in_the_code(self):
        self.apply_init()
        config, _, _ = devflow.load_project_state(self.repo)
        config["quality"]["baseline_status"] = "measured"
        config["policy"]["tdd_for_behavior_changes"] = True
        config["github"]["required_checks"] = ["unit", "lint"]
        devflow.write_project_json(self.repo, devflow.CONFIG_PATH, config, "config-set")
        devflow.scale_set(self.repo, "prototype", "PM-1")
        watched = devflow.scale_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertTrue(watched["promotion_watch"])
        self.assertTrue(any("перерос профиль" in item for item in watched["findings"]))
        # The very same configuration, the same profile name, the flag turned off:
        # the engine reads the flag, it never compares the name. Clearing it takes an
        # explicit `false` because the override merges key by key, like `clients`.
        devflow.configure_value(self.repo, "project.scale_profiles", json.dumps({
            "prototype": {
                "audience": "the author",
                "promotion_watch": False,
                "complexity_budget": {"limits": {"services": 1}, "rationale": "Throwaway."},
                "gate_defaults": {"quality.baseline_status": "unmeasured",
                                  "policy.tdd_for_behavior_changes": False,
                                  "github.required_checks_minimum": 0},
            },
        }))
        unwatched = devflow.scale_report(self.repo, devflow.load_json(self.repo / devflow.CONFIG_PATH))
        self.assertFalse(unwatched["promotion_watch"])
        self.assertEqual(unwatched["findings"], [])

    def test_the_complexity_budget_reaches_the_node_that_consumes_it(self):
        self.apply_init()
        self.prepare_verified_delivery_state(agent="claude-code")
        devflow.scale_set(self.repo, "personal", "PM-7")
        preflight = devflow.operate_preflight(self.repo, "design", "#30")
        self.assertEqual(preflight["scale"]["profile"], "personal")
        self.assertEqual(preflight["scale"]["budget"]["limits"]["services"], 1)
        self.assertIn("не измеряется CLI", preflight["scale"]["budget_note"])
        self.declare_sessions(extra={"architect": {"mode": "explicit", "session": "arch-chat"}})
        self.commit_fixture()
        rendered = devflow.session_assign(self.repo, "design", "#30", pm_go="PM-7")
        self.assertIn("services ≤ 1", rendered["assignment"])
        self.assertIn("not measured by the CLI", rendered["assignment"])
        review = next(node for node in
                      devflow.load_json(self.repo / devflow.WORKFLOW_PATH)["nodes"]
                      if node["id"] == "final_review")
        self.assertTrue(any("declared project scale" in check for check in review["checks"]))

    def test_a_project_installed_before_scale_degrades_instead_of_crashing(self):
        self.apply_init()
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        del config["project"]["scale"]
        (self.repo / devflow.CONFIG_PATH).write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (self.repo / devflow.SCALE_PROFILES_PATH).unlink()
        self.assertEqual(devflow.validate_config(config)[0], [])
        report = devflow.scale_report(self.repo, config)
        self.assertEqual(report["mode"], "undecided")
        # The shipped data still answers, so nothing crashes before the migration.
        self.assertIn("startup", report["known_profiles"])
        self.assertEqual(next(item for item in devflow.doctor(self.repo)["diagnosis"]
                              if item["check"] == "scale")["mode"], "undecided")
        self.assertEqual(len(devflow.evaluate_setup(self.repo)), 11)
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "restore"))
        self.assertTrue((self.repo / devflow.SCALE_PROFILES_PATH).is_file())

    # --- design node ------------------------------------------------------------------

    def downgrade_to_sixteen_nodes(self):
        """Exactly what a graph installed before the design node looks like."""
        workflow = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        workflow["nodes"] = [node for node in workflow["nodes"] if node["id"] != "design"]
        workflow["edges"] = [edge for edge in workflow["edges"]
                             if edge["from"] != "design" and edge["to"] != "design"]
        workflow["edges"].insert(1, {"from": "product_scope_gate", "to": "prepare_issue",
                                     "condition": "scope.approved", "max_retries": 0,
                                     "on_failure": "human_needed"})
        for node in workflow["nodes"]:
            if node["id"] != "prepare_issue":
                continue
            node["entry_condition"] = "scope.approved"
            node["inputs"] = [item for item in node["inputs"] if item != "design decision"]
            node["checks"] = [item for item in node["checks"]
                              if not item.startswith("architecture impact references")]
        (self.repo / devflow.WORKFLOW_PATH).write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return workflow

    def test_design_node_is_reachable_and_routes_its_two_outcomes(self):
        kit = devflow.find_project_kit(self.repo)
        workflow = devflow.load_json(kit / "workflow.json")
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(len(workflow["nodes"]), 17)
        design = next(node for node in workflow["nodes"] if node["id"] == "design")
        self.assertEqual(design["role"], "architect")
        self.assertEqual(design["stage"], "planning")
        self.assertEqual(design["expected_evidence"], ["design decision", "test spec", "issue draft"])
        routes = {edge["condition"]: (edge["to"], edge["max_retries"], edge["on_failure"])
                  for edge in workflow["edges"] if edge["from"] == "design"}
        self.assertEqual(routes["design.complete"], ("prepare_issue", 1, "human_needed"))
        self.assertEqual(routes["design.decision_required"], ("human_needed", 0, "human_needed"))
        self.assertEqual(
            [edge["to"] for edge in workflow["edges"]
             if edge["from"] == "product_scope_gate" and edge["condition"] == "scope.approved"],
            ["design"])
        # A discovered product choice ends in human_needed, so no planning cycle appears.
        self.assertEqual([cycle["id"] for cycle in workflow["allowed_cycles"]], ["correction-loop"])
        errors, warnings = devflow.validate_workflow(workflow, config)
        self.assertEqual((errors, warnings), ([], []))

    def test_prepare_issue_consumes_the_design_instead_of_repeating_it(self):
        kit = devflow.find_project_kit(self.repo)
        workflow = devflow.load_json(kit / "workflow.json")
        node = next(item for item in workflow["nodes"] if item["id"] == "prepare_issue")
        self.assertEqual(node["entry_condition"], "design.complete")
        self.assertIn("design decision", node["inputs"])
        self.assertTrue(any("references the design decision" in check for check in node["checks"]))
        # #6 owns the test spec format, so it is not an input here yet.
        self.assertNotIn("test spec", node["inputs"])

    def test_the_design_node_adds_no_executor_and_no_isolation_verdict(self):
        kit = devflow.find_project_kit(self.repo)
        config = devflow.load_json(kit / "config.json")
        self.assertEqual(config["roles"]["architect"]["agent"], devflow.AGENT_UNRESOLVED)
        self.assertEqual(config["roles"]["architect"]["model"], {"mode": "undecided"})
        self.apply_init()
        self.choose_executors(agent="claude-code")
        self.declare_sessions(extra={"architect": {"mode": "explicit", "session": "arch-chat"}})
        config, workflow, _ = devflow.load_project_state(self.repo)
        self.assertEqual(devflow.validate_workflow(workflow, config)[0], [])
        report = devflow.session_report(self.repo, config, workflow)
        self.assertEqual(report["bindings"]["design"], "arch-chat")
        # design is a planning node, so binding it to the implementer session is legal.
        devflow.configure_value(self.repo, "automation.sessions.roles.architect",
                                json.dumps({"mode": "explicit", "session": "impl-chat"}))
        config, workflow, _ = devflow.load_project_state(self.repo)
        self.assertEqual(devflow.validate_workflow(workflow, config)[0], [])

    def test_installed_sixteen_node_graph_migrates_with_one_command(self):
        self.apply_init()
        self.downgrade_to_sixteen_nodes()
        config, workflow, _ = devflow.load_project_state(self.repo)
        self.assertEqual(len(workflow["nodes"]), 16)
        # Nothing crashes before the migration: the old graph is still a valid graph.
        self.assertEqual(devflow.validate_workflow(workflow, config)[0], [])
        self.assertEqual(len(devflow.evaluate_setup(self.repo)), 11)
        self.assertIn(devflow.doctor(self.repo)["status"], devflow.STATUS_VALUES)
        plan = devflow.migrate_graph_contracts(self.repo, apply=False)
        self.assertEqual(plan["added_nodes"], ["design"])
        applied = devflow.migrate_graph_contracts(self.repo, apply=True)
        self.assertEqual(applied["status"], "PASS")
        migrated = devflow.load_json(self.repo / devflow.WORKFLOW_PATH)
        self.assertEqual(len(migrated["nodes"]), 17)
        self.assertEqual(
            [edge["to"] for edge in migrated["edges"]
             if edge["from"] == "product_scope_gate" and edge["condition"] == "scope.approved"],
            ["design"])
        successor = next(node for node in migrated["nodes"] if node["id"] == "prepare_issue")
        self.assertEqual(successor["entry_condition"], "design.complete")
        self.assertIn("design decision", successor["inputs"])
        self.assertEqual(devflow.validate_workflow(migrated, config)[0], [])
        self.assertEqual(devflow.migrate_graph_contracts(self.repo, apply=True)["status"],
                         "NOT_APPLICABLE")

    def test_migration_refuses_to_rewire_an_edge_this_project_changed(self):
        self.apply_init()
        workflow = self.downgrade_to_sixteen_nodes()
        for edge in workflow["edges"]:
            if edge["from"] == "product_scope_gate" and edge["condition"] == "scope.approved":
                edge["max_retries"] = 2
        (self.repo / devflow.WORKFLOW_PATH).write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        refused = devflow.migrate_graph_contracts(self.repo, apply=True)
        self.assertEqual(refused["status"], "BLOCKED")
        self.assertEqual(refused["added_nodes"], [])
        self.assertTrue(any("max_retries=2" in item for item in refused["requires_explicit_decision"]))
        self.assertEqual(len(devflow.load_json(self.repo / devflow.WORKFLOW_PATH)["nodes"]), 16)

    def test_migration_refuses_to_rewrite_a_neighbour_this_project_changed(self):
        self.apply_init()
        workflow = self.downgrade_to_sixteen_nodes()
        for node in workflow["nodes"]:
            if node["id"] == "prepare_issue":
                node["checks"].append("our own definition of ready")
        (self.repo / devflow.WORKFLOW_PATH).write_text(
            json.dumps(workflow, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        refused = devflow.migrate_graph_contracts(self.repo, apply=True)
        self.assertEqual(refused["status"], "BLOCKED")
        self.assertEqual(refused["added_nodes"], [])
        self.assertTrue(any("собственные элементы checks" in item
                            for item in refused["requires_explicit_decision"]))
        self.assertEqual(len(devflow.load_json(self.repo / devflow.WORKFLOW_PATH)["nodes"]), 16)

    def test_neutral_template_does_not_replace_a_configured_project_on_upgrade(self):
        self.apply_init()
        self.choose_executors(agent="claude-code", model=None, effort="high")
        devflow.apply_plan(self.repo, devflow.build_setup_plan(self.repo, "upgrade", "keep"))
        config = devflow.load_json(self.repo / devflow.CONFIG_PATH)
        self.assertEqual(config["roles"]["implementer"]["agent"], "claude-code")
        self.assertEqual(config["roles"]["implementer"]["effort"], {"mode": "explicit", "value": "high"})


if __name__ == "__main__":
    unittest.main()
