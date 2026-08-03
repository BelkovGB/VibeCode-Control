#!/usr/bin/env python3
"""VibeCode Control project inspector, configurator, graph validator, and skill manager.

The CLI intentionally uses only the Python standard library. Ordinary audit
commands are read-only. Mutating setup commands produce a plan first and write
only when the caller explicitly requests apply.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import copy
import datetime as dt
import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


VERSION = "0.1.0"
META_DIR = ".agent-flow"
LOCAL_DIR = f"{META_DIR}/.local"
CONFIG_PATH = f"{META_DIR}/config.json"
WORKFLOW_PATH = f"{META_DIR}/workflow.json"
SKILLS_LOCK_PATH = f"{META_DIR}/skills.lock.json"
SETUP_STATE_PATH = f"{META_DIR}/setup-state.json"
SETUP_STAGES_PATH = f"{META_DIR}/setup-stages.json"
MANAGED_START = "<!-- devflow:managed:start -->"
MANAGED_END = "<!-- devflow:managed:end -->"
GITIGNORE_START = "# devflow:managed:start"
GITIGNORE_END = "# devflow:managed:end"
STATUS_VALUES = {"PASS", "PARTIAL", "BLOCKED", "NOT_APPLICABLE"}
DECISION_VALUES = {"unresolved", "zero-skill", "assigned", "blocked"}
RECOMMENDATION_VALUES = {"REQUIRED", "RECOMMENDED", "OPTIONAL", "NOT_NEEDED", "REJECT", "EVALUATE"}

# Typed execution-configuration contract.  A model or effort parameter carries a
# mode, never a bare string that hides whether the value was chosen, inherited,
# or deliberately left out.  `unset` must never be materialized into a concrete
# value by a resolver, a renderer, or a run record.
MODE_EXPLICIT = "explicit"
MODE_INHERITED = "inherited"
MODE_UNSET = "unset"
MODE_NOT_APPLICABLE = "not-applicable"
# `undecided` and `unset` both carry no value, and neither may be materialized, but they
# are different facts: `undecided` means nobody has chosen yet and the shipped template
# supplies it, while `unset` is the project owner's decision that the parameter is
# absent.  Only `undecided` holds setup and execution.
MODE_UNDECIDED = "undecided"
CONFIG_MODES = {MODE_EXPLICIT, MODE_INHERITED, MODE_UNSET, MODE_NOT_APPLICABLE, MODE_UNDECIDED}
# The reserved agent identifier for "no executor has been chosen".  It is not an agent,
# so it never resolves to a client and never satisfies a delivery gate.
AGENT_UNRESOLVED = "unresolved"
TYPED_PROFILE_FIELDS = ("model", "effort")
PROFILE_FIELDS = ("agent", "model", "effort", "permissions")
# Agents that never execute a model, so an executable model/effort is a lie for them.
NON_EXECUTING_AGENTS = {"human", "script", "deterministic"}
# Legacy scalar spellings accepted on read so existing projects normalize without
# losing semantics.  They are never written back.
LEGACY_MODE_TOKENS = {
    "inherit": MODE_INHERITED,
    "inherited": MODE_INHERITED,
    "not-applicable": MODE_NOT_APPLICABLE,
    "not_applicable": MODE_NOT_APPLICABLE,
    "n/a": MODE_NOT_APPLICABLE,
    "unset": MODE_UNSET,
    "unconfigured": MODE_UNDECIDED,
    "undecided": MODE_UNDECIDED,
}
# Check conclusions that a remote adapter can report.  Only `success` proves a check.
CHECK_CONCLUSIONS = {
    "success", "failure", "cancelled", "skipped", "neutral",
    "timed_out", "action_required", "stale",
}
PROVEN_CHECK_CONCLUSIONS = {"success"}
# Statuses that consume a cycle budget.  BLOCKED and HUMAN_NEEDED are stops, not
# attempts: a stop-check must never eat the budget it reports on.
COUNTED_RUN_STATUSES = {"PASS", "PARTIAL", "FAIL"}
# The ceiling on declared cycle traversals.  Anything above it needs a named PM decision.
MAX_FIX_CYCLES_CEILING = 3
MAX_FIX_CYCLES_ABSOLUTE = 10
# Stages where every reported check must be green.  Implementation nodes record their
# conclusions as evidence instead: a RED node proves a test that legitimately fails.
CHECK_GATED_STAGES = {"verification", "review", "release"}
# Artifact kinds a review node can be required to produce.
REVIEW_ARTIFACT_KINDS = {"review", "comment", "findings", "report", "check-run"}
GATE_ORIGINS = {"skill", "repository-policy", "risk-escalation"}
IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "vendor",
    ".venv", "venv", "dist", "build", "coverage", ".next", ".turbo",
    "target", "__pycache__", ".pytest_cache", ".mypy_cache",
}
TEXT_EXTENSIONS = {
    ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt",
    ".cs", ".php", ".rb", ".sh", ".ps1", ".sql", ".xml", ".gradle",
}
SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic-secret-assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"\s]{12,}")),
]
DANGEROUS_SKILL_PATTERNS = [
    ("critical", "destructive recursive delete", re.compile(r"\brm\s+-rf\b|Remove-Item\s+.*-Recurse.*-Force", re.I)),
    ("critical", "force push", re.compile(r"git\s+push\s+[^\n]*--force|git\s+push\s+-f\b", re.I)),
    ("high", "download piped to shell", re.compile(r"(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash|zsh|powershell)", re.I)),
    ("high", "credential or env access", re.compile(r"\.env\b|os\.environ|process\.env|credentials?", re.I)),
    ("high", "guardrail weakening", re.compile(r"disable\s+(?:tests?|lint|security|checks?)|skip\s+(?:tests?|checks?)|bypass", re.I)),
    ("high", "privilege escalation", re.compile(r"\bsudo\b|chmod\s+777|runas\b", re.I)),
    ("medium", "dynamic execution", re.compile(r"\beval\s*\(|\bexec\s*\(|Invoke-Expression|shell\s*=\s*True", re.I)),
    ("medium", "network access", re.compile(r"https?://|\bcurl\b|\bwget\b|Invoke-WebRequest", re.I)),
]


class DevflowError(RuntimeError):
    """Expected user-facing failure."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_id(prefix: str = "run") -> str:
    return f"{prefix}-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def safe_run_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", identifier) or ".." in identifier:
        raise DevflowError(f"Некорректный идентификатор запуска: {identifier}")
    return identifier


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False) + "\n").encode("utf-8")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DevflowError(f"Не найден файл: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DevflowError(f"Некорректный JSON в {path}: {exc}") from exc


def deep_get(value: Any, dotted: str) -> Any:
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            raise DevflowError(f"Путь конфигурации не найден: {dotted}")
        current = current[part]
    return current


def deep_set(value: dict[str, Any], dotted: str, new_value: Any) -> None:
    parts = dotted.split(".")
    current: dict[str, Any] = value
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise DevflowError(f"Нельзя записать внутрь скалярного значения: {dotted}")
        current = child
    current[parts[-1]] = new_value


def parse_jsonish(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def ensure_within(repo: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise DevflowError(f"Небезопасный путь вне репозитория: {relative}")
    candidate = repo / rel
    repo_resolved = repo.resolve()
    parent = candidate.parent
    while parent != repo and parent != parent.parent:
        if parent.exists() and parent.is_symlink():
            raise DevflowError(f"Запись через символьную ссылку запрещена: {relative}")
        parent = parent.parent
    resolved_parent = candidate.parent.resolve()
    if resolved_parent != repo_resolved and repo_resolved not in resolved_parent.parents:
        raise DevflowError(f"Путь выходит за репозиторий: {relative}")
    if candidate.exists() and candidate.is_symlink():
        raise DevflowError(f"Запись в символьную ссылку запрещена: {relative}")
    return candidate


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.devflow-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def run_process(args: list[str], cwd: Path, timeout: int = 10) -> tuple[int, str, str]:
    effective_args = list(args)
    if effective_args and effective_args[0] == "git":
        # Read-only Git inspection must not invoke a repository-controlled
        # fsmonitor or hook program. Fixed subcommands also avoid aliases.
        effective_args = [
            "git",
            "-c", "core.fsmonitor=false",
            "-c", f"core.hooksPath={os.devnull}",
            "-c", "diff.external=",
            "-c", "core.pager=cat",
            *effective_args[1:],
        ]
    try:
        completed = subprocess.run(
            effective_args,
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, "", str(exc)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def expand_devflow_command(repo: Path, command: str | None) -> tuple[str | None, list[str] | None]:
    if not command:
        return command, None
    tokens = shlex.split(command)
    if not tokens or tokens[0] != "devflow":
        return command, tokens
    installed = repo / META_DIR / "devflow.py"
    cli = installed if installed.is_file() else Path(__file__).resolve()
    argv = [sys.executable, str(cli), "--repo", str(repo.resolve()), *tokens[1:]]
    return shlex.join(argv), argv


def sanitize_remote(remote: str) -> str:
    remote = re.sub(r"([a-z][a-z0-9+.-]*://)[^/@\s]+@", r"\1***@", remote, flags=re.I)
    remote = re.sub(r"\b[^/@\s]+@(?=[A-Za-z0-9.-]+[:/])", "***@", remote)
    remote = re.sub(r"([?&][A-Za-z0-9_.~-]+=)[^&\s]+", r"\1***", remote)
    return redact_sensitive_text(remote)


def redact_sensitive_text(text: str) -> str:
    text = re.sub(
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        "<redacted:private-key>", text, flags=re.S,
    )
    for kind, pattern in SECRET_PATTERNS:
        text = pattern.sub(f"<redacted:{kind}>", text)
    return text


def iter_files(root: Path, include_agent_flow: bool = False) -> Iterable[Path]:
    for current, dirs, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        filtered = []
        for name in dirs:
            if name in IGNORED_DIRS:
                continue
            if name == META_DIR and not include_agent_flow:
                continue
            child = current_path / name
            if child.is_symlink():
                continue
            filtered.append(name)
        dirs[:] = filtered
        for name in files:
            path = current_path / name
            if not path.is_symlink():
                yield path


def iter_skill_files(root: Path) -> list[Path] | None:
    if not root.exists() or not root.is_dir() or root.is_symlink():
        return None
    files: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            return None
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                return None
            if entry.is_dir(follow_symlinks=False):
                pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                files.append(path)
            else:
                return None
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def hash_tree(root: Path) -> str:
    files = iter_skill_files(root)
    if files is None:
        return ""
    digest = hashlib.sha256()
    for path in files:
        rel = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def hash_file_map(files: dict[str, Path]) -> str:
    """Checksum an explicit relative-path -> file map, framed exactly like `hash_tree`."""
    digest = hashlib.sha256()
    for relative in sorted(files):
        raw = relative.encode("utf-8")
        digest.update(len(raw).to_bytes(4, "big"))
        digest.update(raw)
        data = files[relative].read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def find_project_kit(repo: Path) -> Path:
    override = os.environ.get("DEVFLOW_SKILL_ROOT")
    candidates = []
    if override:
        candidates.append(Path(override) / "assets" / "project-kit")
    script = Path(__file__).resolve()
    candidates.extend([
        script.parent.parent / "assets" / "project-kit",
        repo / META_DIR / "toolkit",
    ])
    for candidate in candidates:
        if (candidate / "config.json").is_file() and (candidate / "workflow.json").is_file():
            return candidate
    raise DevflowError(
        "Проектный комплект VibeCode Control недоступен. Запустите init/adopt/upgrade через установленный скилл devflow."
    )


def replace_managed_block(existing: str, block: str, start: str = MANAGED_START, end: str = MANAGED_END) -> str:
    if start not in block or end not in block:
        raise DevflowError("Управляемый блок не содержит обязательные маркеры")
    block = block.strip() + "\n"
    if start in existing or end in existing:
        if existing.count(start) != 1 or existing.count(end) != 1:
            raise DevflowError("Повреждены или продублированы маркеры управляемого блока")
        before, tail = existing.split(start, 1)
        _, after = tail.split(end, 1)
        prefix = before.rstrip()
        suffix = after.lstrip("\r\n")
        return (prefix + "\n\n" if prefix else "") + block + suffix
    if existing and not existing.endswith("\n"):
        existing += "\n"
    return existing + ("\n" if existing.strip() else "") + block


def read_optional(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def make_operation(repo: Path, relative: str, content: bytes | None) -> dict[str, Any] | None:
    target = ensure_within(repo, relative)
    previous = read_optional(target)
    if content is not None and previous == content:
        return None
    if content is None and previous is None:
        return None
    return {
        "path": relative,
        "action": "delete" if content is None else ("create" if previous is None else "update"),
        "pre_hash": sha256_bytes(previous) if previous is not None else None,
        "post_hash": sha256_bytes(content) if content is not None else None,
        "content_b64": base64.b64encode(content).decode("ascii") if content is not None else None,
    }


def plan_path_allowed(mode: str, relative: str) -> bool:
    if not relative or "\\" in relative:
        return False
    parts = Path(relative).parts
    if any(part.lower() == ".git" for part in parts):
        return False
    setup_exact = {
        CONFIG_PATH, WORKFLOW_PATH, SKILLS_LOCK_PATH, SETUP_STAGES_PATH,
        f"{META_DIR}/config.schema.json", f"{META_DIR}/workflow.schema.json",
        f"{META_DIR}/devflow.py", "AGENTS.md", "CLAUDE.md", ".gitignore",
        ".github/pull_request_template.md", ".github/ISSUE_TEMPLATE/devflow-task.yml",
        ".agents/skills/devflow-node/SKILL.md", ".claude/skills/devflow-node/SKILL.md",
    }
    if mode in {"init", "adopt", "upgrade", "repair"}:
        return relative in setup_exact or relative.startswith(f"{META_DIR}/toolkit/") or relative.startswith(".github/devflow/prompts/")
    if mode in {"config-set", "role-set", "model-set", "permissions-set"}:
        return relative in {CONFIG_PATH, SKILLS_LOCK_PATH}
    if mode == "graph-migrate":
        return relative == WORKFLOW_PATH
    if mode == "setup-mark":
        return relative == SETUP_STATE_PATH
    if mode in {"skills-decision", "skills-unassign"}:
        return relative == SKILLS_LOCK_PATH
    if mode in {"skills-register", "skills-sync", "skills-remove"}:
        if relative == SKILLS_LOCK_PATH:
            return True
        if relative.startswith((f"{META_DIR}/vendor-skills/", ".agents/skills/", ".claude/skills/")):
            return not relative.startswith((
                ".agents/skills/devflow-node/", ".claude/skills/devflow-node/",
            ))
    return False


def validate_plan(repo: Path, plan: Any) -> None:
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise DevflowError("План не соответствует поддерживаемой schema_version=1")
    safe_run_identifier(str(plan.get("run_id", "")))
    mode = plan.get("mode")
    if not isinstance(mode, str):
        raise DevflowError("План не содержит корректный mode")
    if Path(str(plan.get("repo", ""))).resolve() != repo.resolve():
        raise DevflowError("План создан для другого репозитория")
    fingerprint = plan.get("fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise DevflowError("План не содержит корректный fingerprint")
    operations = plan.get("operations")
    if not isinstance(operations, list) or len(operations) > 10_000:
        raise DevflowError("План содержит некорректный список операций")
    seen: set[str] = set()
    total_bytes = 0
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise DevflowError(f"Операция {index} должна быть объектом")
        relative = operation.get("path")
        action = operation.get("action")
        if not isinstance(relative, str) or not plan_path_allowed(mode, relative):
            raise DevflowError(f"Путь операции не разрешён для mode={mode}: {relative}")
        ensure_within(repo, relative)
        if relative in seen:
            raise DevflowError(f"План содержит повторную операцию для {relative}")
        seen.add(relative)
        if action not in {"create", "update", "delete"}:
            raise DevflowError(f"Некорректное действие операции: {action}")
        pre_hash = operation.get("pre_hash")
        post_hash = operation.get("post_hash")
        if pre_hash is not None and not isinstance(pre_hash, str):
            raise DevflowError(f"Некорректный pre_hash для {relative}")
        if isinstance(pre_hash, str) and not re.fullmatch(r"[0-9a-f]{64}", pre_hash):
            raise DevflowError(f"Некорректный pre_hash для {relative}")
        encoded = operation.get("content_b64")
        if action == "delete":
            if pre_hash is None or post_hash is not None or encoded is not None:
                raise DevflowError(f"Некорректная delete-операция для {relative}")
            continue
        if action == "create" and pre_hash is not None:
            raise DevflowError(f"Create-операция содержит pre_hash для {relative}")
        if action == "update" and pre_hash is None:
            raise DevflowError(f"Update-операция не содержит pre_hash для {relative}")
        if not isinstance(encoded, str) or not isinstance(post_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", post_hash):
            raise DevflowError(f"Операция записи некорректна для {relative}")
        try:
            content = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise DevflowError(f"Некорректный base64 для {relative}") from exc
        total_bytes += len(content)
        if len(content) > 50_000_000 or total_bytes > 200_000_000:
            raise DevflowError("План превышает безопасный размер")
        if sha256_bytes(content) != post_hash:
            raise DevflowError(f"post_hash не соответствует содержимому {relative}")


def validate_manifest(repo: Path, manifest: Any, identifier: str) -> None:
    """Validate a mutable local apply manifest before verify or rollback."""
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise DevflowError("Apply manifest не соответствует schema_version=1")
    if manifest.get("run_id") != identifier:
        raise DevflowError("Apply manifest не соответствует запрошенному run-id")
    if Path(str(manifest.get("repo", ""))).resolve() != repo.resolve():
        raise DevflowError("Apply manifest создан для другого репозитория")
    operations = manifest.get("operations")
    if not isinstance(operations, list):
        raise DevflowError("Apply manifest не содержит корректный список операций")
    synthetic_plan = {
        "schema_version": 1,
        "run_id": identifier,
        "mode": manifest.get("mode"),
        "repo": manifest.get("repo"),
        "fingerprint": "0" * 64,
        "operations": [
            {key: operation.get(key) for key in ["path", "action", "pre_hash", "post_hash", "content_b64"]}
            if isinstance(operation, dict) else operation
            for operation in operations
        ],
    }
    validate_plan(repo, synthetic_plan)
    total_previous = 0
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise DevflowError(f"Операция manifest {index} должна быть объектом")
        encoded = operation.get("previous_b64")
        if encoded is None:
            previous = None
        elif isinstance(encoded, str):
            try:
                previous = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise DevflowError(f"Некорректный previous_b64 для {operation.get('path')}") from exc
            total_previous += len(previous)
            if len(previous) > 50_000_000 or total_previous > 200_000_000:
                raise DevflowError("Apply manifest превышает безопасный размер")
        else:
            raise DevflowError(f"Некорректный previous_b64 для {operation.get('path')}")
        expected_pre = operation.get("pre_hash")
        actual_pre = sha256_bytes(previous) if previous is not None else None
        if actual_pre != expected_pre:
            raise DevflowError(f"previous_b64 не соответствует pre_hash для {operation.get('path')}")
        if operation.get("action") == "create" and previous is not None:
            raise DevflowError(f"Create manifest содержит предыдущее значение для {operation.get('path')}")
        if operation.get("action") in {"update", "delete"} and previous is None:
            raise DevflowError(f"Manifest не содержит предыдущее значение для {operation.get('path')}")


def plan_diff(repo: Path, operation: dict[str, Any]) -> str:
    path = ensure_within(repo, operation["path"])
    old = path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True) if path.exists() else []
    content = base64.b64decode(operation["content_b64"]) if operation["content_b64"] else b""
    new = content.decode("utf-8", errors="replace").splitlines(keepends=True) if operation["action"] != "delete" else []
    rendered = "".join(difflib.unified_diff(old, new, fromfile=f"a/{operation['path']}", tofile=f"b/{operation['path']}"))
    return redact_sensitive_text(rendered)


def repo_fingerprint(repo: Path) -> str:
    pieces: list[str] = [str(repo.resolve())]
    code, head, _ = run_process(["git", "rev-parse", "HEAD"], repo)
    pieces.append(head if code == 0 else "no-head")
    code, status, _ = run_process(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo)
    if code == 0:
        # Saved plans and local evidence are deliberately outside the project
        # state used to invalidate a plan.
        status = "\n".join(
            line for line in status.splitlines()
            if not line[3:].strip('"').startswith(f"{LOCAL_DIR}/")
        )
    pieces.append(status if code == 0 else "no-status")
    return sha256_bytes("\n".join(pieces).encode("utf-8"))


def initialize_skill_decisions(lock: dict[str, Any], workflow: dict[str, Any]) -> None:
    decisions = lock.setdefault("node_decisions", {})
    deterministic = {"inspect_project", "product_scope_gate", "prepare_issue", "skill_preflight", "quality_gates", "merge_gate", "merge", "post_merge", "done", "blocked", "human_needed"}
    evaluation = {"tdd_red", "implement", "fix_findings", "implementer_review", "final_review"}
    for node in workflow["nodes"]:
        node_id = node["id"]
        if node_id in decisions:
            continue
        if node_id in deterministic:
            recommendation = "NOT_NEEDED"
            reason = "VibeCode Control, project rules, scripts, or objective gates cover this node; confirm zero-skill or choose a justified exception."
        elif node_id in evaluation:
            recommendation = "EVALUATE"
            reason = "A narrow stack or review skill may help, but benefit must be compared with the current model and zero-skill."
        else:
            recommendation = "EVALUATE"
            reason = "Assess the concrete execution profile before adding context."
        decisions[node_id] = {
            "status": "unresolved",
            "recommendation": recommendation,
            "evidence_level": "heuristic",
            "reason": reason,
            "assigned": [],
            "reviewed_at": None,
            "revalidation_required": False
        }


def extract_managed_block(text: str, start: str = MANAGED_START, end: str = MANAGED_END) -> str | None:
    """Return the managed block exactly as `replace_managed_block` would have written it."""
    if text.count(start) != 1 or text.count(end) != 1:
        return None
    _, tail = text.split(start, 1)
    body, _ = tail.split(end, 1)
    return (start + body + end).strip() + "\n"


def client_role_assignments(config: Any, workflow: Any, client: str) -> list[dict[str, Any]]:
    """List the roles this client actually owns, with the nodes it would execute."""
    roles = config.get("roles") if isinstance(config, dict) else {}
    roles = roles if isinstance(roles, dict) else {}
    nodes = workflow.get("nodes") if isinstance(workflow, dict) else []
    nodes = nodes if isinstance(nodes, list) else []
    # Ownership is decided per node on the resolved agent, so a node routed to this client
    # by a node override is neither missed nor wrongly claimed.
    owned: dict[tuple[str, str, str], list[str]] = {}
    for node in nodes:
        if not isinstance(node, dict):
            continue
        resolution = resolve_execution_profile(node, config if isinstance(config, dict) else {})
        agent = resolution["agent"].get("value")
        if not agent or expected_target_for_agent(agent) != client:
            continue
        role = str(node.get("role"))
        permissions = resolution["permissions"].get("value") or "unset"
        owned.setdefault((role, agent, permissions), []).append(str(node.get("id")))
    assignments = [
        {"role": role, "agent": agent, "permissions": permissions, "nodes": sorted(node_ids)}
        for (role, agent, permissions), node_ids in owned.items()
    ]
    covered = {item["role"] for item in assignments}
    for role in sorted(roles):
        settings = roles[role]
        if not isinstance(settings, dict) or role in covered:
            continue
        agent = settings.get("agent")
        if not isinstance(agent, str) or expected_target_for_agent(agent) != client:
            continue
        assignments.append({
            "role": role,
            "agent": agent,
            "permissions": settings.get("permissions") if isinstance(settings.get("permissions"), str) else "unset",
            "nodes": [],
        })
    assignments.sort(key=lambda item: (item["role"], item["permissions"], item["agent"]))
    return assignments


def render_client_role_block(config: Any, workflow: Any, client: str, title: str) -> str:
    """Build the managed instruction block from the roles actually configured.

    The block never claims an authority the configuration does not grant and never
    withholds one it does; `doctor` verifies this generated variant, not a fixed text.
    """
    assignments = client_role_assignments(config, workflow, client)
    owned = {item["role"] for item in assignments}
    lines = [MANAGED_START, f"## {title}", ""]
    if not assignments:
        lines += [
            f"No workflow role in this project is assigned to {title.split(' ')[0]}. Do not act as a background "
            f"executor here. If this is wrong, the owner assigns the role in `{CONFIG_PATH}` and reruns "
            "`devflow upgrade`; do not assume a role that the configuration does not grant.",
            "",
            MANAGED_END,
        ]
        return "\n".join(lines) + "\n"
    lines.append("Configured roles and permission profiles, resolved from `" + CONFIG_PATH + "`:")
    lines.append("")
    for item in assignments:
        nodes = ", ".join(item["nodes"]) if item["nodes"] else "no workflow node"
        lines.append(f"- `{item['role']}` (`{item['permissions']}`) — nodes: {nodes}")
    lines += [
        "",
        "Act only inside the permissions of the workflow node you were given, and only in a role listed "
        "above. Do not change product scope, roadmap, priorities, or architecture trade-offs outside the "
        "approved scope.",
        "",
        "Never combine implementation and independent final review in the same session: a change you "
        "implemented must be reviewed by a different context.",
        "",
        "Before acting:",
        "",
        f"1. Read `AGENTS.md`, `{CONFIG_PATH}`, `{WORKFLOW_PATH}`, `{SKILLS_LOCK_PATH}`, and every document named by the Issue.",
        "2. Identify the current workflow node and run "
        "`python3 .agent-flow/devflow.py --repo . operate --node <node>` (`py` instead of `python3` on Windows).",
        "3. Stop as `BLOCKED` if an assigned required skill is missing, changed, or unavailable in this environment.",
        "4. Use the effective configuration, not a guess: "
        "`python3 .agent-flow/devflow.py --repo . config effective`. A parameter whose mode is "
        f"`{MODE_UNSET}` stays absent; a parameter whose mode is `{MODE_INHERITED}` is observed at run time "
        "and recorded, never invented.",
    ]
    if "implementer" in owned:
        lines += [
            "",
            "As `implementer`: establish the baseline, prove the failing test for a behavior change, make the "
            "smallest complete change, add risk-based tests, preserve guardrails, update architecture "
            "documentation in the same PR when architecture changes, and fix the full verified class of any "
            "review finding.",
        ]
    if owned & {"reviewer", "qa"}:
        lines += [
            "",
            "As `reviewer` or `qa`: a successful job is not a passed check. Publish the artifact the node "
            "requires — review, comment, or findings — and record it with "
            "`devflow run record --evidence '<name>=<kind>:<reference>'`. A green `skipped` conclusion is not "
            "a completed check.",
        ]
    if "release-operator" in owned:
        lines += [
            "",
            "As `release-operator`: merge only the exact verified head SHA after the merge gate passes, and "
            "never re-dispatch a post-merge check against a closed PR that needs `refs/pull/<N>/merge`.",
        ]
    else:
        lines += ["", "Do not merge the PR: no role assigned here grants merge authority."]
    lines += [
        "",
        "Report commands, results, evidence, and the current head SHA. Never claim a test or CI status that "
        "was not freshly observed.",
        "",
        MANAGED_END,
    ]
    return "\n".join(lines) + "\n"


def managed_text(repo: Path, relative: str, block: str, start: str = MANAGED_START, end: str = MANAGED_END) -> bytes:
    path = ensure_within(repo, relative)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    return replace_managed_block(existing, block, start, end).encode("utf-8")


def build_setup_plan(repo: Path, mode: str, purpose: str = "setup") -> dict[str, Any]:
    if mode not in {"init", "adopt", "upgrade", "repair"}:
        raise DevflowError(f"Неизвестный режим плана: {mode}")
    kit = find_project_kit(repo)
    inspection = inspect_repository(repo)
    if mode == "init" and inspection["project"]["looks_existing"]:
        raise DevflowError("Репозиторий уже содержит проектные файлы. Используйте adopt вместо init.")
    if mode in {"upgrade", "repair"} and not (repo / CONFIG_PATH).is_file():
        recommended = inspection["project"]["recommended_mode"]
        raise DevflowError(
            f"VibeCode Control ещё не установлен. Используйте dry-run режима {recommended}, а не {mode}."
        )
    config_template = load_json(kit / "config.json")
    workflow_template = load_json(kit / "workflow.json")
    lock_template = load_json(kit / "skills.lock.json")
    config_template["project"]["name"] = repo.name
    config_template["project"]["mode"] = "adopt" if mode in {"adopt", "repair"} else "init"
    config_template["project"]["repository_type"] = "monorepo" if inspection["project"]["monorepo"] else "single-repository"
    initialize_skill_decisions(lock_template, workflow_template)

    # Upgrade/repair may refresh only VibeCode Control-managed material around a valid
    # project control plane.  Never use a template refresh to silently replace
    # or normalize an invalid config, graph, or lock file: that needs a
    # separately reviewed migration with project-specific intent.
    if mode in {"upgrade", "repair"}:
        guarded_config = load_json(repo / CONFIG_PATH) if (repo / CONFIG_PATH).is_file() else config_template
        guarded_workflow = load_json(repo / WORKFLOW_PATH) if (repo / WORKFLOW_PATH).is_file() else workflow_template
        guarded_lock = load_json(repo / SKILLS_LOCK_PATH) if (repo / SKILLS_LOCK_PATH).is_file() else lock_template
        config_errors, _ = validate_config(guarded_config)
        workflow_errors, _ = validate_workflow(guarded_workflow, guarded_config)
        lock_errors = validate_skills_lock(guarded_lock)
        guarded_errors = config_errors + workflow_errors + lock_errors
        if guarded_errors:
            raise DevflowError(
                "Автоматический upgrade/repair заблокирован: требуется отдельный проверенный migration plan. "
                + " | ".join(guarded_errors)
            )

    operations: list[dict[str, Any]] = []

    def add(relative: str, data: bytes | None) -> None:
        operation = make_operation(repo, relative, data)
        if operation:
            operations.append(operation)

    create_only = {
        CONFIG_PATH: json_bytes(config_template),
        WORKFLOW_PATH: json_bytes(workflow_template),
        SKILLS_LOCK_PATH: json_bytes(lock_template),
    }
    for relative, data in create_only.items():
        target = ensure_within(repo, relative)
        if not target.exists():
            add(relative, data)
    for relative, data in {
        SETUP_STAGES_PATH: (kit / "setup-stages.json").read_bytes(),
        f"{META_DIR}/config.schema.json": (kit / "config.schema.json").read_bytes(),
        f"{META_DIR}/workflow.schema.json": (kit / "workflow.schema.json").read_bytes(),
    }.items():
        add(relative, data)
    if mode in {"upgrade", "repair"} and (repo / CONFIG_PATH).is_file():
        existing_config = load_json(repo / CONFIG_PATH)
        if existing_config.get("schema_version") != 1:
            raise DevflowError("Автомиграция неизвестной версии config запрещена; требуется отдельный проверенный migration plan")
        existing_config["devflow_version"] = VERSION
        add(CONFIG_PATH, json_bytes(existing_config))

    # Keep an exact project-local toolkit so the copied CLI remains self-contained.
    for source in sorted(iter_files(kit, include_agent_flow=True), key=lambda p: p.relative_to(kit).as_posix()):
        rel = source.relative_to(kit).as_posix()
        add(f"{META_DIR}/toolkit/{rel}", source.read_bytes())
    add(f"{META_DIR}/devflow.py", Path(__file__).read_bytes())

    managed = kit / "managed"
    # Role-aware managed instructions are generated from the configuration that is
    # actually installed, never from the kit default, so `adopt` over a project that
    # reassigned roles does not overwrite it with the shipped role split.
    role_config = load_json(repo / CONFIG_PATH) if (repo / CONFIG_PATH).is_file() else config_template
    role_workflow = load_json(repo / WORKFLOW_PATH) if (repo / WORKFLOW_PATH).is_file() else workflow_template
    add("AGENTS.md", managed_text(repo, "AGENTS.md", (managed / "AGENTS.block.md").read_text(encoding="utf-8")))
    add("CLAUDE.md", managed_text(
        repo, "CLAUDE.md", render_client_role_block(role_config, role_workflow, "claude", "Claude roles in this project")
    ))
    add(
        ".github/pull_request_template.md",
        managed_text(repo, ".github/pull_request_template.md", (managed / "pull_request_template.block.md").read_text(encoding="utf-8")),
    )
    add(".github/ISSUE_TEMPLATE/devflow-task.yml", (managed / "devflow-task.yml").read_bytes())
    add(".github/devflow/prompts/claude-implement.md", (managed / "claude-implement.md").read_bytes())
    add(".github/devflow/prompts/codex-review.md", (managed / "codex-review.md").read_bytes())
    background = (managed / "background-skill" / "SKILL.template.md").read_bytes()
    add(".agents/skills/devflow-node/SKILL.md", background)
    add(".claude/skills/devflow-node/SKILL.md", background)
    gitignore_block = textwrap.dedent(f"""
        {GITIGNORE_START}
        {LOCAL_DIR}/
        {GITIGNORE_END}
    """).strip() + "\n"
    add(".gitignore", managed_text(repo, ".gitignore", gitignore_block, GITIGNORE_START, GITIGNORE_END))

    return attach_effective_configuration(repo, {
        "schema_version": 1,
        "devflow_version": VERSION,
        "run_id": run_id(purpose),
        "mode": mode,
        "created_at": iso_now(),
        "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo),
        "operations": operations,
        "warnings": [
            "Remote GitHub settings, models, CI results, and background-agent availability remain unverified until their adapters are checked.",
            "Third-party skills are not installed; every workflow node remains awaiting an explicit skill or zero-skill decision."
        ]
    })


def apply_plan(repo: Path, plan: dict[str, Any]) -> dict[str, Any]:
    validate_plan(repo, plan)
    if plan.get("fingerprint") != repo_fingerprint(repo):
        raise DevflowError("Репозиторий изменился после построения плана; постройте и проверьте новый план")
    lock_path = ensure_within(repo, f"{LOCAL_DIR}/apply.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, plan["run_id"].encode("utf-8"))
        os.close(fd)
    except FileExistsError as exc:
        raise DevflowError(f"Другой apply уже выполняется: {lock_path}") from exc

    applied: list[dict[str, Any]] = []
    try:
        for operation in plan.get("operations", []):
            target = ensure_within(repo, operation["path"])
            previous = read_optional(target)
            actual_pre = sha256_bytes(previous) if previous is not None else None
            if actual_pre != operation.get("pre_hash"):
                raise DevflowError(f"Файл изменился после построения плана: {operation['path']}")
            record = copy.deepcopy(operation)
            record["previous_b64"] = base64.b64encode(previous).decode("ascii") if previous is not None else None
            if operation["action"] == "delete":
                target.unlink()
            else:
                atomic_write(target, base64.b64decode(operation["content_b64"]))
            applied.append(record)
        manifest = {
            "schema_version": 1,
            "run_id": plan["run_id"],
            "mode": plan.get("mode"),
            "applied_at": iso_now(),
            "repo": str(repo.resolve()),
            "operations": applied,
        }
        expected_matrix = plan.get("effective_configuration")
        if isinstance(expected_matrix, dict):
            manifest["effective_configuration"] = expected_matrix
            # Rebuild the matrix from the files that were just written and compare it
            # cell by cell with the approved plan.  A mismatch rolls the write back
            # instead of being reconciled by a hidden fallback.
            try:
                actual_matrix = effective_configuration_from_files(repo)
            except DevflowError as exc:
                raise DevflowError(
                    f"Эффективная конфигурация не читается из файлов после записи: {exc}"
                ) from exc
            differences = compare_effective_configuration(expected_matrix, actual_matrix)
            if differences:
                raise DevflowError(
                    "Эффективная конфигурация после записи не совпала с утверждённым планом: "
                    + "; ".join(differences[:20])
                )
        identifier = safe_run_identifier(str(plan.get("run_id", "")))
        manifest_path = ensure_within(repo, f"{LOCAL_DIR}/runs/{identifier}.json")
        atomic_write(manifest_path, json_bytes(manifest))
        return {
            "status": "PASS",
            "run_id": plan["run_id"],
            "changed": len(applied),
            "manifest": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
        }
    except Exception:
        # Best-effort transactional rollback of only operations applied in this run.
        for operation in reversed(applied):
            target = ensure_within(repo, operation["path"])
            previous = base64.b64decode(operation["previous_b64"]) if operation["previous_b64"] is not None else None
            if previous is None:
                if target.exists() and not target.is_dir():
                    target.unlink()
            else:
                atomic_write(target, previous)
        raise
    finally:
        if lock_path.exists():
            lock_path.unlink()


def load_trusted_manifest(repo: Path, identifier: str, expected_sha256: str) -> dict[str, Any]:
    identifier = safe_run_identifier(identifier)
    manifest_path = ensure_within(repo, f"{LOCAL_DIR}/runs/{identifier}.json")
    if not manifest_path.is_file():
        raise DevflowError(f"Apply manifest не найден: {identifier}")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise DevflowError("Требуется SHA-256 исходного apply manifest")
    if sha256_file(manifest_path) != expected_sha256:
        raise DevflowError("Apply manifest изменился после создания; verify/rollback запрещён")
    manifest = load_json(manifest_path)
    validate_manifest(repo, manifest, identifier)
    return manifest


def verify_run(repo: Path, identifier: str, expected_sha256: str) -> dict[str, Any]:
    identifier = safe_run_identifier(identifier)
    manifest = load_trusted_manifest(repo, identifier, expected_sha256)
    drift = manifest_drift(repo, manifest)
    # Rebuild the effective configuration from the files that were actually written and
    # compare it cell by cell with the approved plan.  A mismatch blocks; it is never
    # reconciled by a fallback.
    matrix_drift: list[str] = []
    expected_matrix = manifest.get("effective_configuration")
    if isinstance(expected_matrix, dict):
        try:
            actual_matrix = effective_configuration_from_files(repo)
        except DevflowError as exc:
            matrix_drift = [f"Не удалось перечитать эффективную конфигурацию из файлов: {exc}"]
        else:
            matrix_drift = compare_effective_configuration(expected_matrix, actual_matrix)
    return {
        "status": "PASS" if not drift and not matrix_drift else "BLOCKED",
        "run_id": identifier,
        "drift": drift,
        "effective_configuration_drift": matrix_drift,
    }


def manifest_drift(repo: Path, manifest: dict[str, Any]) -> list[str]:
    drift = []
    for operation in manifest["operations"]:
        target = ensure_within(repo, operation["path"])
        current = read_optional(target)
        actual = sha256_bytes(current) if current is not None else None
        if actual != operation.get("post_hash"):
            drift.append(operation["path"])
    return drift


def rollback_run(repo: Path, identifier: str, expected_sha256: str) -> dict[str, Any]:
    identifier = safe_run_identifier(identifier)
    manifest = load_trusted_manifest(repo, identifier, expected_sha256)
    drift = manifest_drift(repo, manifest)
    if drift:
        raise DevflowError("Rollback остановлен: после apply изменены файлы: " + ", ".join(drift))
    restored = 0
    for operation in reversed(manifest["operations"]):
        target = ensure_within(repo, operation["path"])
        previous = base64.b64decode(operation["previous_b64"]) if operation.get("previous_b64") is not None else None
        if previous is None:
            if target.exists() and not target.is_dir():
                target.unlink()
        else:
            atomic_write(target, previous)
        restored += 1
    rollback_record = ensure_within(repo, f"{LOCAL_DIR}/runs/{identifier}.rollback.json")
    atomic_write(rollback_record, json_bytes({"run_id": identifier, "rolled_back_at": iso_now(), "restored": restored}))
    return {"status": "PASS", "run_id": identifier, "restored": restored}


def read_small_text(path: Path, limit: int = 2_000_000) -> str:
    try:
        if path.stat().st_size > limit:
            return ""
        data = path.read_bytes()
        if b"\x00" in data:
            return ""
        return data.decode("utf-8", errors="replace")
    except (OSError, UnicodeError):
        return ""


def detect_stacks(repo: Path, paths: set[str]) -> list[str]:
    stacks: set[str] = set()
    if "package.json" in paths:
        stacks.add("node")
        try:
            package = load_json(repo / "package.json")
            deps = {}
            deps.update(package.get("dependencies", {}) if isinstance(package.get("dependencies"), dict) else {})
            deps.update(package.get("devDependencies", {}) if isinstance(package.get("devDependencies"), dict) else {})
            mapping = {
                "@nestjs/core": "nestjs", "next": "nextjs", "react": "react",
                "vue": "vue", "@angular/core": "angular", "express": "express",
                "vitest": "vitest", "jest": "jest", "playwright": "playwright",
            }
            for dependency, label in mapping.items():
                if dependency in deps:
                    stacks.add(label)
        except DevflowError:
            stacks.add("node-invalid-package-json")
    if any(name in paths for name in {"pyproject.toml", "requirements.txt", "setup.py", "Pipfile"}):
        stacks.add("python")
        combined = "\n".join(
            read_small_text(repo / name, 500_000)
            for name in ["pyproject.toml", "requirements.txt"]
            if (repo / name).exists()
        ).lower()
        for token, label in [("django", "django"), ("fastapi", "fastapi"), ("flask", "flask"), ("pytest", "pytest")]:
            if token in combined:
                stacks.add(label)
    if "go.mod" in paths:
        stacks.add("go")
    if "Cargo.toml" in paths:
        stacks.add("rust")
    if "pom.xml" in paths or "build.gradle" in paths or "build.gradle.kts" in paths:
        stacks.add("jvm")
    if any(name.endswith(".csproj") or name.endswith(".sln") for name in paths):
        stacks.add("dotnet")
    if "pubspec.yaml" in paths:
        stacks.add("flutter-dart")
    if "Dockerfile" in paths or any(name.endswith("/Dockerfile") for name in paths):
        stacks.add("docker")
    if "docker-compose.yml" in paths or "docker-compose.yaml" in paths or "compose.yml" in paths or "compose.yaml" in paths:
        stacks.add("docker-compose")
    return sorted(stacks)


def detect_test_files(relative_paths: list[str]) -> list[str]:
    patterns = [
        re.compile(r"(^|/)(tests?|specs?)/", re.I),
        re.compile(r"(?:^|/)[^/]+\.(?:test|spec)\.[^/]+$", re.I),
        re.compile(r"(?:^|/)test_[^/]+\.py$", re.I),
        re.compile(r"(?:^|/)[^/]+_test\.go$", re.I),
    ]
    return [path for path in relative_paths if any(pattern.search(path) for pattern in patterns)]


def detect_monorepo(paths: set[str]) -> bool:
    markers = {"pnpm-workspace.yaml", "turbo.json", "nx.json", "lerna.json", "rush.json"}
    if paths.intersection(markers):
        return True
    top_packages = {path.split("/", 2)[0] for path in paths if "/" in path}
    return "packages" in top_packages and "apps" in top_packages


def inspect_git(repo: Path) -> dict[str, Any]:
    code, _, _ = run_process(["git", "rev-parse", "--is-inside-work-tree"], repo)
    if code != 0:
        return {
            "is_repository": False,
            "branch": None,
            "head": None,
            "dirty": None,
            "remotes": [],
            "default_branch": "unverified",
            "github_remote_settings": "unverified",
        }
    _, branch, _ = run_process(["git", "branch", "--show-current"], repo)
    head_code, head, _ = run_process(["git", "rev-parse", "HEAD"], repo)
    _, status, _ = run_process(["git", "status", "--porcelain=v1", "--untracked-files=normal"], repo)
    _, remotes_raw, _ = run_process(["git", "remote", "-v"], repo)
    remotes = sorted({sanitize_remote(line) for line in remotes_raw.splitlines() if line.strip()})
    _, remote_head, _ = run_process(["git", "symbolic-ref", "refs/remotes/origin/HEAD"], repo)
    default_branch = remote_head.rsplit("/", 1)[-1] if remote_head else "unverified"
    return {
        "is_repository": True,
        "branch": branch or "detached-or-unborn",
        "head": head if head_code == 0 else None,
        "dirty": bool(status),
        "dirty_entries": len(status.splitlines()) if status else 0,
        "remotes": remotes,
        "default_branch": default_branch,
        "github_remote_settings": "unverified",
    }


def scan_suspected_secrets(repo: Path, files: list[Path]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in files:
        rel = path.relative_to(repo).as_posix()
        lower_name = path.name.lower()
        if lower_name.startswith(".env") and lower_name not in {".env.example", ".env.sample", ".env.template"}:
            findings.append({"path": rel, "kind": "sensitive-env-file"})
            continue
        if path.suffix.lower() not in TEXT_EXTENSIONS and path.name not in {"Dockerfile", "Makefile"}:
            continue
        text = read_small_text(path)
        if not text:
            continue
        for kind, pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append({"path": rel, "kind": kind})
                break
    return findings


def inspect_repository(repo: Path, deep: bool = False) -> dict[str, Any]:
    repo = repo.resolve()
    files = list(iter_files(repo))
    relative = sorted(path.relative_to(repo).as_posix() for path in files)
    path_set = set(relative)
    tests = detect_test_files(relative)
    workflows = [path for path in relative if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))]
    docs = {
        "readme": next((name for name in ["README.md", "README.rst", "README.txt"] if name in path_set), None),
        "architecture": "docs/ARCHITECTURE.md" if "docs/ARCHITECTURE.md" in path_set else None,
        "roadmap": "docs/ROADMAP.md" if "docs/ROADMAP.md" in path_set else None,
        "product_strategy": next((name for name in ["docs/PRODUCT_STRATEGY.md", "PRODUCT_STRATEGY.md", "docs/PRODUCT_RULES.md"] if name in path_set), None),
        "agents": "AGENTS.md" if "AGENTS.md" in path_set else None,
        "claude": "CLAUDE.md" if "CLAUDE.md" in path_set else None,
        "adrs": len([name for name in relative if re.match(r"docs/(?:adr|decisions)/.+\.md$", name, re.I)]),
    }
    large_files = []
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size >= 10 * 1024 * 1024:
            large_files.append({"path": path.relative_to(repo).as_posix(), "bytes": size})
    secret_findings = scan_suspected_secrets(repo, files)
    project_markers = {
        "package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml",
        "pom.xml", "build.gradle", "build.gradle.kts", "pubspec.yaml", "Dockerfile",
        "README.md", "src", "app", "apps", "packages",
    }
    looks_existing = bool(path_set.intersection(project_markers)) or len(files) > 3
    package_scripts: dict[str, Any] = {}
    if (repo / "package.json").is_file():
        try:
            package_scripts = load_json(repo / "package.json").get("scripts", {})
        except DevflowError:
            package_scripts = {"status": "invalid-package-json"}
    report = {
        "schema_version": 1,
        "generated_at": iso_now(),
        "read_only": True,
        "repo": str(repo),
        "project": {
            "name": repo.name,
            "file_count": len(files),
            "looks_existing": looks_existing,
            "recommended_mode": "adopt" if looks_existing else "init",
            "monorepo": detect_monorepo(path_set),
            "stacks": detect_stacks(repo, path_set),
        },
        "git": inspect_git(repo),
        "documentation": docs,
        "quality": {
            "test_files": len(tests),
            "test_examples": tests[:10],
            "package_scripts": package_scripts,
            "ci_workflows": workflows,
            "baseline_execution": "not-run-by-read-only-inspection",
        },
        "skills": {
            "codex_project_skills": len([name for name in relative if name.startswith(".agents/skills/") and name.endswith("/SKILL.md")]),
            "claude_project_skills": len([name for name in relative if name.startswith(".claude/skills/") and name.endswith("/SKILL.md")]),
        },
        "security": {
            "suspected_secret_paths": secret_findings,
            "large_files": large_files,
            "history_scan": "not-run" if not deep else "requires-dedicated-approved-tooling",
        },
        "remote": {
            "github_rulesets": "unverified",
            "required_checks": "unverified",
            "open_prs_and_issues": "unverified",
            "models_and_agents": "unverified",
        },
        "limits": {"usage": "нет доступной телеметрии"},
    }
    return report


def parse_profile_value(raw: Any, pointer: str) -> tuple[dict[str, Any], list[str]]:
    """Parse one model/effort parameter into a typed {mode, value} pair.

    Accepts the legacy scalar spelling so an installed project can be normalized
    without losing semantics, and rejects any shape that would let an absent
    parameter masquerade as a concrete one.
    """
    errors: list[str] = []
    if isinstance(raw, dict):
        mode = raw.get("mode")
        value = raw.get("value")
        unknown = sorted(set(raw) - {"mode", "value"})
        if unknown:
            errors.append(f"{pointer} содержит неизвестные ключи: {', '.join(unknown)}")
        if mode not in CONFIG_MODES:
            errors.append(f"{pointer}.mode должен быть одним из: {', '.join(sorted(CONFIG_MODES))}")
            return {"mode": MODE_UNSET}, errors
        if mode == MODE_EXPLICIT:
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{pointer}.value обязателен и непуст при mode={MODE_EXPLICIT}")
                return {"mode": MODE_UNSET}, errors
            return {"mode": MODE_EXPLICIT, "value": value.strip()}, errors
        if value is not None:
            errors.append(
                f"{pointer}.value недопустим при mode={mode}: значение не должно материализоваться"
            )
        # A non-explicit parameter carries no value key at all, so nothing can later be
        # mistaken for a configured one.
        return {"mode": mode}, errors
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            errors.append(f"{pointer} не задан")
            return {"mode": MODE_UNSET}, errors
        legacy = LEGACY_MODE_TOKENS.get(text.lower())
        if legacy:
            return {"mode": legacy}, errors
        return {"mode": MODE_EXPLICIT, "value": text}, errors
    errors.append(f"{pointer} должен быть строкой или объектом с полем mode")
    return {"mode": MODE_UNSET}, errors


def profile_display(entry: dict[str, Any]) -> str:
    """Render one typed parameter as the single token shown in tables and graphs."""
    mode = entry.get("mode", MODE_UNSET)
    if mode == MODE_EXPLICIT:
        return str(entry.get("value") or "")
    if mode == MODE_INHERITED:
        return "inherit"
    return str(mode)


def normalize_profile_settings(settings: Any, pointer: str) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(settings, dict):
        return {}, [f"{pointer} должен быть объектом"]
    errors: list[str] = []
    result = copy.deepcopy(settings)
    for field in TYPED_PROFILE_FIELDS:
        if field not in settings:
            continue
        entry, field_errors = parse_profile_value(settings[field], f"{pointer}.{field}")
        errors.extend(field_errors)
        result[field] = entry
    return result, errors


def normalize_config(config: Any) -> tuple[dict[str, Any], list[str]]:
    """Return the config with every model/effort parameter in canonical typed form."""
    if not isinstance(config, dict):
        return {}, ["config должен быть объектом"]
    errors: list[str] = []
    result = copy.deepcopy(config)
    for section in ["roles", "node_overrides"]:
        block = config.get(section)
        if not isinstance(block, dict):
            continue
        normalized: dict[str, Any] = {}
        for name, settings in block.items():
            entry, section_errors = normalize_profile_settings(settings, f"{section}.{name}")
            errors.extend(section_errors)
            normalized[name] = entry if entry else settings
        result[section] = normalized
    return result, errors


def pending_execution_decisions(config: Any, workflow: Any = None) -> list[dict[str, str]]:
    """List the execution parameters nobody has chosen yet.

    This is the typed marker the setup stage blocks on.  It is deliberately not a
    validation warning: an owner who declares `unset` has decided, and that decision must
    not hold the stage, while a template default must.
    """
    pending: list[dict[str, str]] = []
    if not isinstance(config, dict):
        return pending
    roles = config.get("roles")
    roles = roles if isinstance(roles, dict) else {}
    used_roles = None
    if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list):
        used_roles = {
            node.get("role") for node in workflow["nodes"]
            if isinstance(node, dict) and node.get("role")
        }
    for role in sorted(roles):
        settings = roles[role]
        if not isinstance(settings, dict):
            continue
        if used_roles is not None and role not in used_roles:
            continue
        agent = settings.get("agent")
        if not isinstance(agent, str) or not agent.strip() or agent.strip() == AGENT_UNRESOLVED:
            pending.append({
                "pointer": f"roles.{role}.agent",
                "decision": "Выберите исполнителя роли",
                "command": f"devflow role set {role} <agent>",
            })
        for field in TYPED_PROFILE_FIELDS:
            entry, _ = parse_profile_value(settings.get(field, {"mode": MODE_UNDECIDED}), f"roles.{role}.{field}")
            if entry.get("mode") == MODE_UNDECIDED:
                pending.append({
                    "pointer": f"roles.{role}.{field}",
                    "decision": f"Выберите {field} или явно объявите отсутствие параметра",
                    "command": f"devflow model set {role} <model|inherit|unset|not-applicable>",
                })
    overrides = config.get("node_overrides")
    if isinstance(overrides, dict):
        for node_id in sorted(overrides):
            settings = overrides[node_id]
            if not isinstance(settings, dict):
                continue
            for field in TYPED_PROFILE_FIELDS:
                if field not in settings:
                    continue
                entry, _ = parse_profile_value(settings[field], f"node_overrides.{node_id}.{field}")
                if entry.get("mode") == MODE_UNDECIDED:
                    pending.append({
                        "pointer": f"node_overrides.{node_id}.{field}",
                        "decision": f"Выберите {field} для узла или снимите override",
                        "command": f"devflow model set {node_id} <model|inherit|unset|not-applicable>",
                    })
    return pending


def config_uses_legacy_profile(config: Any) -> list[str]:
    """List the pointers still using the untyped scalar spelling."""
    legacy: list[str] = []
    if not isinstance(config, dict):
        return legacy
    for section in ["roles", "node_overrides"]:
        block = config.get(section)
        if not isinstance(block, dict):
            continue
        for name, settings in block.items():
            if not isinstance(settings, dict):
                continue
            for field in TYPED_PROFILE_FIELDS:
                if field in settings and not isinstance(settings[field], dict):
                    legacy.append(f"{section}.{name}.{field}")
    return legacy


def resolve_execution_profile(node: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Resolve agent, model, effort and permissions for one node, with provenance.

    Every field reports where its value came from, so a cross-client transfer can
    be reviewed before it is written and rebuilt from the files afterwards.
    """
    node_id = node.get("id")
    role_name = node.get("role")
    roles = config.get("roles") if isinstance(config, dict) else {}
    roles = roles if isinstance(roles, dict) else {}
    role = roles.get(role_name)
    role = role if isinstance(role, dict) else {}
    overrides = config.get("node_overrides") if isinstance(config, dict) else {}
    overrides = overrides if isinstance(overrides, dict) else {}
    override = overrides.get(node_id)
    override = override if isinstance(override, dict) else {}

    def source(level: str, pointer: str | None, file: str | None) -> dict[str, Any]:
        return {"level": level, "pointer": pointer, "file": file}

    resolution: dict[str, Any] = {}
    for field in TYPED_PROFILE_FIELDS:
        if field in override:
            entry, _ = parse_profile_value(override[field], f"node_overrides.{node_id}.{field}")
            origin = source("node-override", f"node_overrides.{node_id}.{field}", CONFIG_PATH)
        elif field in role:
            entry, _ = parse_profile_value(role[field], f"roles.{role_name}.{field}")
            origin = source("role", f"roles.{role_name}.{field}", CONFIG_PATH)
        else:
            entry = {"mode": MODE_UNDECIDED}
            origin = source("absent", None, None)
        item = dict(entry)
        item["source"] = origin
        if item["mode"] == MODE_INHERITED:
            # A role inherits from the client runtime; a node override inherits from its role.
            item["inherited_from"] = "client" if origin["level"] == "role" else "role"
        resolution[field] = item

    if "agent" in override:
        raw_agent, agent_origin = override["agent"], source("node-override", f"node_overrides.{node_id}.agent", CONFIG_PATH)
    elif "agent" in role:
        raw_agent, agent_origin = role["agent"], source("role", f"roles.{role_name}.agent", CONFIG_PATH)
    else:
        raw_agent, agent_origin = None, source("absent", None, None)
    agent_value = raw_agent.strip() if isinstance(raw_agent, str) and raw_agent.strip() else None
    resolution["agent"] = {
        "mode": MODE_EXPLICIT if agent_value else MODE_UNSET,
        "value": agent_value,
        "source": agent_origin,
    }

    if "permissions" in override:
        raw_permissions = override["permissions"]
        permissions_origin = source("node-override", f"node_overrides.{node_id}.permissions", CONFIG_PATH)
    elif isinstance(node.get("permissions"), str) and node["permissions"].strip():
        raw_permissions = node["permissions"]
        permissions_origin = source("node", f"nodes.{node_id}.permissions", WORKFLOW_PATH)
    elif "permissions" in role:
        raw_permissions = role["permissions"]
        permissions_origin = source("role", f"roles.{role_name}.permissions", CONFIG_PATH)
    else:
        raw_permissions, permissions_origin = None, source("absent", None, None)
    permissions_value = raw_permissions.strip() if isinstance(raw_permissions, str) and raw_permissions.strip() else None
    resolution["permissions"] = {
        "mode": MODE_EXPLICIT if permissions_value else MODE_UNSET,
        "value": permissions_value,
        "source": permissions_origin,
    }
    resolution["executes_model"] = agent_value not in NON_EXECUTING_AGENTS if agent_value else True
    return resolution


def validate_config(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(config, dict):
        return ["config должен быть объектом"], warnings
    if config.get("schema_version") != 1:
        errors.append("config.schema_version должен быть 1")
    if not isinstance(config.get("project"), dict):
        errors.append("config.project отсутствует")
    policy = config.get("policy", {})
    if not isinstance(policy, dict):
        errors.append("config.policy должен быть объектом")
        policy = {}
    max_fix_cycles = policy.get("max_fix_cycles", 2)
    decision_ref = policy.get("max_fix_cycles_decision_ref")
    named_decision = isinstance(decision_ref, str) and bool(decision_ref.strip())
    if not isinstance(max_fix_cycles, int) or max_fix_cycles < 1 or max_fix_cycles > MAX_FIX_CYCLES_ABSOLUTE:
        errors.append(f"policy.max_fix_cycles должен быть целым числом от 1 до {MAX_FIX_CYCLES_ABSOLUTE}")
    elif max_fix_cycles > MAX_FIX_CYCLES_CEILING and not named_decision:
        # A higher ceiling is a product decision, not a quietly raised number.
        errors.append(
            f"policy.max_fix_cycles={max_fix_cycles} превышает потолок {MAX_FIX_CYCLES_CEILING}; "
            "укажите policy.max_fix_cycles_decision_ref — непустую ссылку на решение PM "
            f"(Issue, PR или документ), чтобы разрешить до {MAX_FIX_CYCLES_ABSOLUTE}"
        )
    roles = config.get("roles")
    if not isinstance(roles, dict) or not roles:
        errors.append("config.roles отсутствует или пуст")
        roles = {}
    typed_roles: dict[str, dict[str, Any]] = {}
    for role, settings in roles.items():
        if not isinstance(settings, dict):
            errors.append(f"roles.{role} должен быть объектом")
            continue
        for field in ["agent", "permissions"]:
            if not isinstance(settings.get(field), str) or not settings[field].strip():
                errors.append(f"roles.{role}.{field} не задан")
        parsed: dict[str, Any] = {}
        for field in TYPED_PROFILE_FIELDS:
            if field not in settings:
                errors.append(
                    f"roles.{role}.{field} не задан; отсутствующий параметр записывается как "
                    f'{{"mode": "{MODE_UNSET}"}}, а не подставляется значением'
                )
                parsed[field] = {"mode": MODE_UNSET}
                continue
            entry, field_errors = parse_profile_value(settings[field], f"roles.{role}.{field}")
            errors.extend(field_errors)
            parsed[field] = entry
        typed_roles[role] = parsed
        agent = settings.get("agent").strip() if isinstance(settings.get("agent"), str) else ""
        if agent == AGENT_UNRESOLVED:
            # No executor has been chosen, so neither may its model or effort be:
            # anything else would be a value decided on behalf of the owner.
            for field in TYPED_PROFILE_FIELDS:
                if parsed[field]["mode"] != MODE_UNDECIDED:
                    errors.append(
                        f"roles.{role}.{field}: агент не выбран (`{AGENT_UNRESOLVED}`), "
                        f"поэтому требуется mode={MODE_UNDECIDED}"
                    )
            continue
        executes = bool(agent) and agent not in NON_EXECUTING_AGENTS
        for field in TYPED_PROFILE_FIELDS:
            mode = parsed[field]["mode"]
            if mode == MODE_UNDECIDED:
                continue
            if agent and not executes and mode != MODE_NOT_APPLICABLE:
                errors.append(
                    f"roles.{role}.{field}: агент {agent} не исполняет модель, "
                    f"требуется mode={MODE_NOT_APPLICABLE} без исполняемого значения"
                )
            if executes and mode == MODE_NOT_APPLICABLE:
                errors.append(
                    f"roles.{role}.{field}: mode={MODE_NOT_APPLICABLE} недопустим для исполняющего агента {agent}"
                )
    legacy_pointers = config_uses_legacy_profile(config)
    if legacy_pointers:
        warnings.append(
            "Нетипизированные model/effort требуют нормализации через `devflow config normalize`: "
            + ", ".join(legacy_pointers)
        )
    models = config.get("models", {})
    if not isinstance(models, dict):
        errors.append("config.models должен быть объектом")
        models = {}
    available = models.get("available", [])
    if not isinstance(available, list) or not all(isinstance(item, str) for item in available):
        errors.append("models.available должен быть массивом строк")
        available = []
    checked = models.get("availability_checked_at")
    for role, parsed in typed_roles.items():
        entry = parsed.get("model", {"mode": MODE_UNSET})
        mode = entry.get("mode")
        # A declared `inherited` or `unset` mode is a decision, not a gap: there is no
        # value to verify against a model list.  Honesty is enforced when evidence is
        # recorded, where the actually observed value must be supplied.
        if mode != MODE_EXPLICIT:
            continue
        model = entry.get("value")
        if available and model not in available:
            errors.append(f"Модель {model} для роли {role} не входит в проверенный список доступных")
        elif not checked:
            warnings.append(f"Доступность модели {model} для роли {role} не проверена")
    if policy.get("allow_paid_fallback"):
        warnings.append("Включён платный fallback; VibeCode Control по умолчанию его запрещает")
    overrides = config.get("node_overrides", {})
    if not isinstance(overrides, dict):
        errors.append("config.node_overrides должен быть объектом")
    else:
        for node_id, settings in overrides.items():
            if not isinstance(node_id, str) or not isinstance(settings, dict):
                errors.append(f"Некорректная настройка node_overrides.{node_id}")
                continue
            for field in ["agent", "permissions"]:
                if field in settings and (not isinstance(settings[field], str) or not settings[field].strip()):
                    errors.append(f"node_overrides.{node_id}.{field} должен быть непустой строкой")
            for field in TYPED_PROFILE_FIELDS:
                if field in settings:
                    _, field_errors = parse_profile_value(settings[field], f"node_overrides.{node_id}.{field}")
                    errors.extend(field_errors)
    for field in ["quality", "github", "automation", "telemetry"]:
        if field in config and not isinstance(config[field], dict):
            errors.append(f"config.{field} должен быть объектом")
    return errors, warnings


def validate_workflow(workflow: dict[str, Any], config: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(workflow, dict):
        return ["workflow должен быть объектом"], warnings
    if not isinstance(config, dict):
        return ["config должен быть объектом"], warnings
    if workflow.get("schema_version") != 1:
        errors.append("workflow.schema_version должен быть 1")
    policy = config.get("policy", {}) if isinstance(config.get("policy", {}), dict) else {}
    max_fix_cycles = policy.get("max_fix_cycles", 2)
    if not isinstance(max_fix_cycles, int):
        max_fix_cycles = 2
    configured_roles = config.get("roles", {}) if isinstance(config.get("roles", {}), dict) else {}
    nodes_list = workflow.get("nodes")
    edges = workflow.get("edges")
    if not isinstance(nodes_list, list) or not nodes_list:
        return ["workflow.nodes отсутствует или пуст"], warnings
    if not isinstance(edges, list):
        return ["workflow.edges отсутствует"], warnings
    nodes: dict[str, dict[str, Any]] = {}
    required_node_fields = {
        "id", "stage", "state", "entry_condition", "action", "role", "permissions",
        "competencies", "inputs", "expected_evidence", "checks", "timeout_minutes",
    }
    for node in nodes_list:
        if not isinstance(node, dict):
            errors.append("Каждый узел должен быть объектом")
            continue
        missing = sorted(required_node_fields - set(node))
        if missing:
            errors.append(f"Узел {node.get('id', '?')} не содержит: {', '.join(missing)}")
        node_id = node.get("id")
        if not isinstance(node_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", node_id):
            errors.append(f"Некорректный id узла: {node_id}")
            continue
        if node_id in nodes:
            errors.append(f"Повторяющийся узел: {node_id}")
        nodes[node_id] = node
        if node.get("role") not in configured_roles:
            errors.append(f"Узел {node_id} ссылается на неизвестную роль {node.get('role')}")
        if not node.get("expected_evidence"):
            errors.append(f"Узел {node_id} не задаёт expected_evidence")
        for field in ["competencies", "inputs", "expected_evidence", "checks"]:
            value = node.get(field)
            if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
                errors.append(f"Узел {node_id} имеет некорректный массив {field}")
        for field in ["stage", "state", "entry_condition", "action", "role", "permissions"]:
            if not isinstance(node.get(field), str) or not node[field].strip():
                errors.append(f"Узел {node_id} не задаёт корректное поле {field}")
        if not isinstance(node.get("timeout_minutes"), int) or node["timeout_minutes"] < 0:
            errors.append(f"Узел {node_id} имеет некорректный timeout_minutes")
    entry = workflow.get("entry_node")
    terminal_list = workflow.get("terminal_nodes", [])
    if not isinstance(terminal_list, list) or not all(isinstance(item, str) for item in terminal_list):
        errors.append("workflow.terminal_nodes должен быть массивом строк")
        terminal_list = []
    terminals = set(terminal_list)
    if entry not in nodes:
        errors.append("entry_node не существует")
    for terminal in terminals:
        if terminal not in nodes:
            errors.append(f"Терминальный узел не существует: {terminal}")

    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    outgoing: dict[str, int] = {node: 0 for node in nodes}
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("Каждое ребро должно быть объектом")
            continue
        source, target = edge.get("from"), edge.get("to")
        if source not in nodes or target not in nodes:
            errors.append(f"Ребро ссылается на неизвестный узел: {source} -> {target}")
            continue
        retries = edge.get("max_retries")
        if not isinstance(retries, int) or retries < 0 or retries > 10:
            errors.append(f"Ребро {source}->{target} имеет неограниченный или некорректный max_retries")
        failure = edge.get("on_failure")
        if failure not in nodes:
            errors.append(f"Ребро {source}->{target} имеет неизвестный on_failure: {failure}")
        elif failure == source:
            errors.append(f"Ребро {source}->{target} возвращает on_failure в тот же узел")
        if not isinstance(edge.get("condition"), str) or not re.fullmatch(r"[a-z0-9_.-]+", edge["condition"]):
            errors.append(f"Ребро {source}->{target} содержит небезопасное условие")
        adjacency[source].append(target)
        if failure in nodes and failure != target:
            adjacency[source].append(failure)
        outgoing[source] += 1
    for node_id in nodes:
        if node_id in terminals and outgoing[node_id]:
            errors.append(f"Терминальный узел {node_id} имеет исходящее ребро")
        if node_id not in terminals and not outgoing[node_id]:
            errors.append(f"Нет выхода из нетерминального узла {node_id}")
    reachable: set[str] = set()
    if entry in nodes:
        stack = [entry]
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(adjacency.get(current, []))
        for node_id in sorted(set(nodes) - reachable):
            errors.append(f"Недостижимый узел: {node_id}")
    if not terminals.intersection(reachable):
        errors.append("Из entry_node недостижим ни один терминальный узел")
    reverse: dict[str, list[str]] = {node: [] for node in nodes}
    for source, targets in adjacency.items():
        for target in targets:
            reverse[target].append(source)
    can_reach_terminal: set[str] = set()
    stack = [terminal for terminal in terminals if terminal in nodes]
    while stack:
        current = stack.pop()
        if current in can_reach_terminal:
            continue
        can_reach_terminal.add(current)
        stack.extend(reverse.get(current, []))
    for node_id in sorted(reachable - can_reach_terminal):
        errors.append(f"Из узла {node_id} нет пути к терминальному состоянию")

    # Success and failure transitions both form the executable graph. A retry
    # loop that exists only through on_failure must be declared and bounded too.
    main_adjacency: dict[str, list[str]] = {
        node: list(dict.fromkeys(targets)) for node, targets in adjacency.items()
    }
    def path_exists(start: str, target: str) -> bool:
        seen: set[str] = set()
        pending = [start]
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(main_adjacency.get(current, []))
        return False
    declared_cycles = workflow.get("allowed_cycles", [])
    if not isinstance(declared_cycles, list):
        errors.append("workflow.allowed_cycles должен быть массивом")
        declared_cycles = []
    declarations: dict[frozenset[str], dict[str, Any]] = {}
    for declaration in declared_cycles:
        if not isinstance(declaration, dict) or not isinstance(declaration.get("nodes"), list):
            errors.append("Каждый allowed_cycle должен быть объектом с массивом nodes")
            continue
        component = frozenset(declaration["nodes"])
        if not component or not component.issubset(nodes):
            errors.append(f"allowed_cycle содержит неизвестные узлы: {sorted(component - set(nodes))}")
            continue
        budget = declaration.get("max_traversals")
        if not isinstance(budget, int) or budget < 1 or budget > max_fix_cycles:
            errors.append(f"allowed_cycle {declaration.get('id', '?')} имеет некорректный max_traversals")
        exhausted = declaration.get("on_exhausted")
        if exhausted not in nodes or exhausted in component:
            errors.append(f"allowed_cycle {declaration.get('id', '?')} имеет некорректный on_exhausted")
        declarations[component] = declaration
    seen_components: set[frozenset[str]] = set()
    for node_id in nodes:
        component = frozenset(
            other for other in nodes
            if path_exists(node_id, other) and path_exists(other, node_id)
        )
        self_loop = node_id in main_adjacency.get(node_id, [])
        if len(component) < 2 and not self_loop:
            continue
        if component in seen_components:
            continue
        seen_components.add(component)
        internal_edges = [
            edge for edge in edges
            if isinstance(edge, dict)
            and edge.get("from") in component
            and (edge.get("to") in component or edge.get("on_failure") in component)
        ]
        if not any(isinstance(edge.get("max_retries"), int) and edge["max_retries"] > 0 for edge in internal_edges):
            errors.append(
                "Цикл не имеет положительного лимита проходов: " + ", ".join(sorted(component))
            )
        if component not in declarations:
            errors.append("Цикл не объявлен в allowed_cycles: " + ", ".join(sorted(component)))
    for declared in declarations:
        if declared not in seen_components:
            warnings.append("allowed_cycle не соответствует фактическому циклу: " + ", ".join(sorted(declared)))
    merge_gates = [node for node in nodes.values() if node.get("state") == "MERGE_GATE"]
    if not merge_gates:
        errors.append("Workflow не содержит MERGE_GATE")
    for node in merge_gates:
        evidence = set(node.get("expected_evidence", []))
        if not {"verified_head_sha", "required_checks_green"}.issubset(evidence):
            errors.append(f"Merge gate {node.get('id')} не требует verified_head_sha и required_checks_green вместе")
    # A review node must declare which artifact proves it ran: a successful job without
    # the configured review, comment, or findings artifact is not a passed check.
    for node_id, node in nodes.items():
        contract = node.get("evidence_contract")
        if contract is not None and not isinstance(contract, dict):
            errors.append(f"Узел {node_id}: evidence_contract должен быть объектом")
            contract = None
        contract = contract or {}
        declared = node.get("expected_evidence")
        declared = set(declared) if isinstance(declared, list) else set()
        for name, requirement in contract.items():
            if not isinstance(requirement, dict):
                errors.append(f"Узел {node_id}: контракт артефакта {name} должен быть объектом")
                continue
            if name not in declared:
                errors.append(f"Узел {node_id}: контракт артефакта {name} не объявлен в expected_evidence")
            kind = requirement.get("kind")
            if kind not in REVIEW_ARTIFACT_KINDS:
                errors.append(
                    f"Узел {node_id}: вид артефакта {kind} неизвестен; допустимы: "
                    + ", ".join(sorted(REVIEW_ARTIFACT_KINDS))
                )
            if "required" in requirement and not isinstance(requirement["required"], bool):
                errors.append(f"Узел {node_id}: поле required контракта {name} должно быть булевым")
        if node.get("stage") == "review" and not any(
            isinstance(requirement, dict) and requirement.get("required", True)
            for requirement in contract.values()
        ):
            # A graph written before this contract existed stays valid so the project can
            # still run doctor, upgrade and the migration.  The gate is enforced where it
            # matters instead: such a node cannot record a PASS.
            warnings.append(
                f"Review-узел {node_id} не требует ни одного обязательного артефакта; "
                "PASS для него запрещён до миграции графа командой `devflow graph --migrate --apply`"
            )
        for field in TYPED_PROFILE_FIELDS:
            if field in node:
                errors.append(
                    f"Узел {node_id}: {field} задаётся в config.json через roles или node_overrides, "
                    "а не в графе; значение внутри узла молча игнорировалось бы"
                )
        # The executing-agent rule has to hold for the value that actually resolves, not
        # only for the role default: a node override can pair an executing agent with
        # `not-applicable`, or a non-executing agent with a real model.
        resolution = resolve_execution_profile(node, config if isinstance(config, dict) else {})
        agent = resolution["agent"].get("value")
        executes = resolution.get("executes_model")
        if agent == AGENT_UNRESOLVED:
            # Nothing to cross-check until an executor is chosen; the roles setup stage
            # reports the pending decision.
            continue
        for field in TYPED_PROFILE_FIELDS:
            mode = resolution[field].get("mode")
            pointer = resolution[field].get("source", {}).get("pointer") or field
            if mode == MODE_UNDECIDED:
                continue
            if agent and not executes and mode != MODE_NOT_APPLICABLE:
                errors.append(
                    f"Узел {node_id}: агент {agent} не исполняет модель, но {pointer} имеет mode={mode}; "
                    f"требуется mode={MODE_NOT_APPLICABLE}"
                )
            if agent and executes and mode == MODE_NOT_APPLICABLE:
                errors.append(
                    f"Узел {node_id}: {pointer} объявлен mode={MODE_NOT_APPLICABLE}, "
                    f"хотя агент {agent} исполняет модель; фактическое значение было бы нечем проверить"
                )
    return errors, warnings


def load_project_state(repo: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return load_json(repo / CONFIG_PATH), load_json(repo / WORKFLOW_PATH), load_json(repo / SKILLS_LOCK_PATH)


def validate_skills_lock(lock: Any) -> list[str]:
    if not isinstance(lock, dict):
        return ["skills.lock должен быть объектом"]
    errors: list[str] = []
    if lock.get("schema_version") != 1:
        errors.append("skills.lock.schema_version должен быть 1")

    allowed = lock.get("allowed_sources")
    if not isinstance(allowed, dict):
        errors.append("skills.lock.allowed_sources должен быть объектом")
    else:
        for field in ["registries", "official_repositories", "official_documentation", "extra"]:
            values = allowed.get(field, [])
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                errors.append(f"skills.lock.allowed_sources.{field} должен быть массивом строк")

    policy = lock.get("review_policy")
    if not isinstance(policy, dict):
        errors.append("skills.lock.review_policy должен быть объектом")
    else:
        review_days = policy.get("review_interval_days")
        if not isinstance(review_days, int) or review_days < 1 or review_days > 3650:
            errors.append("skills.lock.review_policy.review_interval_days должен быть целым числом от 1 до 3650")
        max_skills = policy.get("max_third_party_skills_per_node")
        if not isinstance(max_skills, int) or max_skills < 0 or max_skills > 20:
            errors.append("skills.lock.review_policy.max_third_party_skills_per_node должен быть целым числом от 0 до 20")
        triggers = policy.get("reevaluate_on", [])
        if not isinstance(triggers, list) or not all(isinstance(item, str) for item in triggers):
            errors.append("skills.lock.review_policy.reevaluate_on должен быть массивом строк")

    decisions = lock.get("node_decisions")
    if not isinstance(decisions, dict):
        errors.append("skills.lock.node_decisions должен быть объектом")
    else:
        for node_id, decision in decisions.items():
            if not isinstance(node_id, str) or not isinstance(decision, dict):
                errors.append(f"Некорректное решение skills.lock.node_decisions.{node_id}")
                continue
            if decision.get("status") not in DECISION_VALUES:
                errors.append(f"Некорректный status решения по скиллам для узла {node_id}")
            assigned = decision.get("assigned", [])
            if not isinstance(assigned, list):
                errors.append(f"skills.lock.node_decisions.{node_id}.assigned должен быть массивом")
            else:
                for assignment in assigned:
                    if not isinstance(assignment, dict) or not isinstance(assignment.get("name"), str):
                        errors.append(f"Некорректное назначение скилла для узла {node_id}")
                        continue
                    if assignment.get("level", "required") not in {"required", "recommended", "optional"}:
                        errors.append(f"Некорректный level скилла {assignment.get('name')} для узла {node_id}")

    skills = lock.get("skills")
    if not isinstance(skills, list):
        errors.append("skills.lock.skills должен быть массивом")
    else:
        seen_names: set[str] = set()
        for index, skill in enumerate(skills):
            if not isinstance(skill, dict):
                errors.append(f"skills.lock.skills[{index}] должен быть объектом")
                continue
            name = skill.get("name")
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
                errors.append(f"skills.lock.skills[{index}].name некорректен")
            elif name in seen_names:
                errors.append(f"Повторяющийся скилл в lock: {name}")
            else:
                seen_names.add(name)
            if not isinstance(skill.get("source"), str) or not skill.get("source"):
                errors.append(f"skills.lock.skills[{index}].source должен быть непустой строкой")
            if not isinstance(skill.get("commit_sha"), str):
                errors.append(f"skills.lock.skills[{index}].commit_sha должен быть строкой")
            if not isinstance(skill.get("checksum"), str):
                errors.append(f"skills.lock.skills[{index}].checksum должен быть строкой")
            if not isinstance(skill.get("license"), str) or not skill.get("license"):
                errors.append(f"skills.lock.skills[{index}].license должен быть непустой строкой")
            targets = skill.get("targets")
            if not isinstance(targets, list) or not targets or any(target not in {"claude", "codex"} for target in targets):
                errors.append(f"skills.lock.skills[{index}].targets некорректен")
            if not isinstance(skill.get("provenance"), dict):
                errors.append(f"skills.lock.skills[{index}].provenance должен быть объектом")
            if skill.get("review_after") is not None and not isinstance(skill.get("review_after"), str):
                errors.append(f"skills.lock.skills[{index}].review_after должен быть строкой")
    return errors


def load_project_or_proposed_state(repo: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    if all((repo / path).is_file() for path in [CONFIG_PATH, WORKFLOW_PATH, SKILLS_LOCK_PATH]):
        config, workflow, lock = load_project_state(repo)
        return config, workflow, lock, "installed"
    kit = find_project_kit(repo)
    config = load_json(kit / "config.json")
    workflow = load_json(kit / "workflow.json")
    lock = load_json(kit / "skills.lock.json")
    inspection = inspect_repository(repo)
    config["project"]["name"] = repo.name
    config["project"]["mode"] = inspection["project"]["recommended_mode"]
    config["project"]["repository_type"] = "monorepo" if inspection["project"]["monorepo"] else "single-repository"
    initialize_skill_decisions(lock, workflow)
    return config, workflow, lock, "proposed-not-installed"


def effective_node(node: dict[str, Any], config: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(node)
    resolution = resolve_execution_profile(node, config if isinstance(config, dict) else {})
    for field in PROFILE_FIELDS:
        result[field] = profile_display(resolution[field])
    result["resolution"] = resolution
    decisions = lock.get("node_decisions", {}) if isinstance(lock, dict) else {}
    decisions = decisions if isinstance(decisions, dict) else {}
    decision = decisions.get(node.get("id"), {"status": "unresolved", "assigned": []})
    decision = decision if isinstance(decision, dict) else {"status": "unresolved", "assigned": []}
    result["skill_decision"] = decision.get("status", "unresolved")
    result["skills"] = decision.get("assigned", [])
    return result


def mermaid_escape(value: Any) -> str:
    return str(value).replace('"', "'").replace("\n", " ")


def render_graph(workflow: dict[str, Any], config: dict[str, Any], lock: dict[str, Any], output_format: str,
                 configuration_status: str = "installed") -> str:
    nodes = [effective_node(node, config, lock) for node in workflow["nodes"]]
    if output_format == "json":
        effective = copy.deepcopy(workflow)
        effective["nodes"] = nodes
        effective["configuration_status"] = configuration_status
        return json.dumps(effective, ensure_ascii=False, indent=2)
    if output_format == "table":
        lines = [
            f"> configuration_status: {configuration_status}",
            "",
            "| Узел | Состояние | Действие | Роль | Агент | Модель | Effort | Скиллы |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for node in nodes:
            skills = node["skill_decision"] if not node["skills"] else ", ".join(item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in node["skills"])
            lines.append(
                f"| {node['id']} | {node['state']} | {node['action']} | {node['role']} | "
                f"{node['agent']} | {node['model']} | {node['effort']} | {skills} |"
            )
        return "\n".join(lines)
    lines = [f"%% configuration_status: {configuration_status}", "flowchart TD"]
    terminal = set(workflow.get("terminal_nodes", []))
    for node in nodes:
        skills = node["skill_decision"] if not node["skills"] else ", ".join(item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in node["skills"])
        label = " · ".join([
            mermaid_escape(node["state"]),
            mermaid_escape(node["action"]),
            mermaid_escape(f"{node['role']} · {node['agent']}"),
            mermaid_escape(f"{node['model']} · {node['effort']}"),
            mermaid_escape(f"skills: {skills}"),
        ])
        shape_open, shape_close = ("([", "])") if node["id"] in terminal else ("[", "]")
        lines.append(f"  {node['id']}{shape_open}\"{label}\"{shape_close}")
    for edge in workflow["edges"]:
        condition = mermaid_escape(edge["condition"])
        lines.append(f"  {edge['from']} -->|\"{condition}\"| {edge['to']}")
        failure = edge.get("on_failure")
        if failure and failure != edge["to"] and not any(
            other.get("from") == edge["from"] and other.get("to") == failure
            for other in workflow["edges"]
        ):
            lines.append(f"  {edge['from']} -.->|\"on failure / retries exhausted\"| {failure}")
    return "\n".join(lines)


EFFECTIVE_MATRIX_CELLS = (
    "stage", "state", "owner", "agent", "agent_mode",
    "model", "model_mode", "effort", "effort_mode", "permissions",
)


def effective_configuration(workflow: dict[str, Any], config: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    """Build the stage/owner/agent/model/effort matrix with per-cell provenance."""
    rows: list[dict[str, Any]] = []
    for node in workflow.get("nodes", []) if isinstance(workflow, dict) else []:
        if not isinstance(node, dict):
            continue
        resolution = resolve_execution_profile(node, config if isinstance(config, dict) else {})
        row: dict[str, Any] = {
            "node": node.get("id"),
            "stage": node.get("stage"),
            "state": node.get("state"),
            "owner": node.get("role"),
            "executes_model": resolution.get("executes_model"),
        }
        for field in PROFILE_FIELDS:
            entry = resolution[field]
            origin = entry.get("source", {})
            row[field] = entry.get("value")
            row[f"{field}_mode"] = entry.get("mode")
            row[f"{field}_source"] = origin.get("pointer")
            row[f"{field}_source_file"] = origin.get("file")
            row[f"{field}_source_level"] = origin.get("level")
        rows.append(row)
    return {
        "schema_version": 1,
        "sources": {"config": CONFIG_PATH, "workflow": WORKFLOW_PATH, "lock": SKILLS_LOCK_PATH},
        "rows": rows,
    }


def effective_configuration_from_files(repo: Path) -> dict[str, Any]:
    """Rebuild the matrix from what is actually on disk, never from an in-memory plan."""
    config, workflow, lock = load_project_state(repo)
    return effective_configuration(workflow, config, lock)


def render_effective_configuration(matrix: dict[str, Any], output_format: str = "table") -> str:
    if output_format == "json":
        return json.dumps(matrix, ensure_ascii=False, indent=2)
    lines = [
        "| Узел | Этап | Владелец | Agent | Model | Model mode | Model источник | Effort | Effort mode | Effort источник |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in matrix.get("rows", []):
        lines.append(
            f"| {row.get('node')} | {row.get('stage')} | {row.get('owner')} | "
            f"{row.get('agent') or row.get('agent_mode')} | "
            f"{row.get('model') or '—'} | {row.get('model_mode')} | {row.get('model_source') or '—'} | "
            f"{row.get('effort') or '—'} | {row.get('effort_mode')} | {row.get('effort_source') or '—'} |"
        )
    return "\n".join(lines)


def projected_project_state(repo: Path, plan: dict[str, Any]) -> tuple[Any, Any, Any]:
    """Read the control plane the plan would produce: planned bytes first, disk second."""
    payload = {
        operation.get("path"): operation
        for operation in plan.get("operations", [])
        if isinstance(operation, dict) and operation.get("action") != "delete"
    }

    def read(relative: str) -> Any:
        operation = payload.get(relative)
        if operation is not None and isinstance(operation.get("content_b64"), str):
            try:
                return json.loads(base64.b64decode(operation["content_b64"]).decode("utf-8"))
            except (ValueError, binascii.Error, UnicodeDecodeError):
                return None
        path = repo / relative
        if path.is_file():
            try:
                return load_json(path)
            except DevflowError:
                return None
        return None

    return read(CONFIG_PATH), read(WORKFLOW_PATH), read(SKILLS_LOCK_PATH)


def attach_effective_configuration(repo: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Record the matrix the plan promises, so verify can rebuild it from the files.

    Only plans that actually rewrite the control plane carry it: stamping the whole-repo
    matrix onto an unrelated run would make that run verify BLOCKED after any later
    authorized configuration change.
    """
    touched = {
        operation.get("path") for operation in plan.get("operations", [])
        if isinstance(operation, dict)
    }
    if not touched.intersection({CONFIG_PATH, WORKFLOW_PATH}):
        return plan
    config, workflow, lock = projected_project_state(repo, plan)
    if not isinstance(config, dict) or not isinstance(workflow, dict):
        return plan
    plan["effective_configuration"] = effective_configuration(workflow, config, lock if isinstance(lock, dict) else {})
    return plan


def compare_effective_configuration(expected: Any, actual: Any) -> list[str]:
    """Compare two matrices cell by cell.  Any difference must block, never fall back."""
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return ["Матрица эффективной конфигурации недоступна для сравнения"]
    expected_rows = {row.get("node"): row for row in expected.get("rows", []) if isinstance(row, dict)}
    actual_rows = {row.get("node"): row for row in actual.get("rows", []) if isinstance(row, dict)}
    differences: list[str] = []
    for node in sorted(set(expected_rows) - set(actual_rows), key=str):
        differences.append(f"{node}: узел отсутствует в фактических файлах")
    for node in sorted(set(actual_rows) - set(expected_rows), key=str):
        differences.append(f"{node}: узел появился в файлах, но отсутствовал в утверждённом плане")
    for node in sorted(set(expected_rows) & set(actual_rows), key=str):
        for cell in EFFECTIVE_MATRIX_CELLS:
            want = expected_rows[node].get(cell)
            got = actual_rows[node].get(cell)
            if want != got:
                differences.append(f"{node}.{cell}: план={want!r}, файлы={got!r}")
    return differences


def source_allowed(source: str, lock: dict[str, Any]) -> bool:
    if source.startswith("internal:devflow"):
        return True
    try:
        parsed = urlparse(source)
    except ValueError:
        return False
    canonical = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
    allowed = lock.get("allowed_sources", {})
    # Documentation can recommend a repository, but it is not itself an
    # installable package source. Only canonical repositories and explicit
    # user additions may enter the lock file; skills.sh remains discovery-only.
    prefixes = allowed.get("official_repositories", []) + allowed.get("extra", [])
    for prefix in prefixes:
        normalized = prefix.rstrip("/")
        if canonical == normalized or canonical.startswith(normalized + "/"):
            return True
    return False


def canonical_git_remote(remote: str) -> str:
    value = remote.strip()
    scp = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", value)
    if scp and "://" not in value:
        host, path = scp.groups()
        return f"https://{host.lower()}/{path.removesuffix('.git').strip('/')}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.hostname:
        return ""
    path = parsed.path.removesuffix(".git").rstrip("/")
    return f"https://{parsed.hostname.lower()}{path}"


def verify_skill_provenance(source_path: Path, source_url: str, commit_sha: str) -> dict[str, Any]:
    code, top_raw, _ = run_process(["git", "rev-parse", "--show-toplevel"], source_path)
    if code != 0:
        raise DevflowError("Каталог кандидата не принадлежит проверяемому Git checkout")
    top = Path(top_raw).resolve()
    try:
        relative_root = source_path.relative_to(top).as_posix()
    except ValueError as exc:
        raise DevflowError("Каталог кандидата выходит за Git checkout") from exc
    code, head, _ = run_process(["git", "rev-parse", "HEAD"], top)
    if code != 0 or head != commit_sha:
        raise DevflowError("Байты кандидата не привязаны к указанному HEAD commit SHA")
    code, remote, _ = run_process(["git", "remote", "get-url", "origin"], top)
    canonical_remote = canonical_git_remote(remote) if code == 0 else ""
    if not canonical_remote or not (source_url == canonical_remote or source_url.startswith(canonical_remote + "/")):
        raise DevflowError("Origin checkout не совпадает с каноническим source URL")
    pathspec = relative_root if relative_root != "." else "."
    code, status, _ = run_process(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "--", pathspec], top
    )
    if code != 0 or status:
        raise DevflowError("Каталог кандидата содержит незакоммиченные или untracked изменения")
    code, tracked_raw, _ = run_process(["git", "ls-files", "--", pathspec], top)
    if code != 0:
        raise DevflowError("Не удалось подтвердить tracked-файлы кандидата")
    prefix = "" if relative_root == "." else relative_root.rstrip("/") + "/"
    tracked = {
        line[len(prefix):] if prefix and line.startswith(prefix) else line
        for line in tracked_raw.splitlines() if line and (not prefix or line.startswith(prefix))
    }
    entries = iter_skill_files(source_path)
    if entries is None:
        raise DevflowError("Каталог кандидата содержит symlink, special file или недоступный entry")
    actual = {path.relative_to(source_path).as_posix() for path in entries}
    if tracked != actual:
        raise DevflowError("Состав локальных файлов кандидата не совпадает с tracked tree указанного commit")
    return {
        "status": "verified-local-checkout",
        "canonical_repository": canonical_remote,
        "repository_subpath": relative_root,
        "commit_sha": commit_sha,
        "tracked_files": len(tracked),
        "verified_at": iso_now(),
    }


def audit_skill_directory(path: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if not path.is_dir():
        return {"status": "BLOCKED", "checksum": "", "declared_name": None, "findings": [{"severity": "critical", "message": "Каталог скилла не найден"}]}
    skill_md = path / "SKILL.md"
    declared_name: str | None = None
    if not skill_md.is_file():
        findings.append({"severity": "critical", "path": "SKILL.md", "message": "Отсутствует SKILL.md"})
    else:
        skill_text = read_small_text(skill_md)
        frontmatter = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", skill_text, re.S)
        if not frontmatter:
            findings.append({"severity": "critical", "path": "SKILL.md", "message": "Отсутствует корректный YAML frontmatter"})
        else:
            name_match = re.search(r"(?m)^name:\s*['\"]?([^'\"\r\n]+)['\"]?\s*$", frontmatter.group(1))
            description_match = re.search(r"(?m)^description:\s*\S.+$", frontmatter.group(1))
            if not name_match:
                findings.append({"severity": "critical", "path": "SKILL.md", "message": "Frontmatter не содержит name"})
            else:
                declared_name = name_match.group(1).strip()
                if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", declared_name):
                    findings.append({"severity": "high", "path": "SKILL.md", "message": "Frontmatter name имеет небезопасный формат"})
            if not description_match:
                findings.append({"severity": "high", "path": "SKILL.md", "message": "Frontmatter не содержит непустой description"})
    for current, dirs, files in os.walk(path, followlinks=False):
        current_path = Path(current)
        for name in list(dirs):
            child = current_path / name
            if child.is_symlink():
                findings.append({"severity": "high", "path": child.relative_to(path).as_posix(), "message": "Символьная ссылка запрещена"})
                dirs.remove(name)
        for name in files:
            file_path = current_path / name
            rel = file_path.relative_to(path).as_posix()
            if file_path.is_symlink():
                findings.append({"severity": "high", "path": rel, "message": "Символьная ссылка запрещена"})
                continue
            try:
                size = file_path.stat().st_size
            except OSError:
                findings.append({"severity": "high", "path": rel, "message": "Файл невозможно прочитать"})
                continue
            if size > 2_000_000:
                findings.append({"severity": "medium", "path": rel, "message": "Файл больше 2 MB требует ручной проверки"})
            data = file_path.read_bytes() if size <= 2_000_000 else b""
            if b"\x00" in data:
                findings.append({"severity": "high", "path": rel, "message": "Бинарный файл требует отдельного подтверждения"})
                continue
            text = data.decode("utf-8", errors="replace")
            for secret_kind, secret_pattern in SECRET_PATTERNS:
                if secret_pattern.search(text):
                    findings.append({"severity": "critical", "path": rel, "message": f"Обнаружен возможный секрет: {secret_kind}"})
                    break
            for severity, message, pattern in DANGEROUS_SKILL_PATTERNS:
                if pattern.search(text):
                    findings.append({"severity": severity, "path": rel, "message": message})
    severity = {item["severity"] for item in findings}
    status = "BLOCKED" if severity.intersection({"critical", "high"}) else ("PARTIAL" if findings else "PASS")
    return {"status": status, "checksum": hash_tree(path), "declared_name": declared_name, "findings": findings}


def target_skill_path(repo: Path, name: str, target: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise DevflowError(f"Некорректное имя скилла: {name}")
    if target == "codex":
        return ensure_within(repo, f".agents/skills/{name}")
    if target == "claude":
        return ensure_within(repo, f".claude/skills/{name}")
    raise DevflowError(f"Неизвестная цель скилла: {target}")


def vendor_skill_path(repo: Path, skill: dict[str, Any]) -> Path:
    name = skill.get("name", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise DevflowError(f"Некорректное имя скилла в lock: {name}")
    expected = f"{META_DIR}/vendor-skills/{name}"
    if skill.get("vendor_path", expected) != expected:
        raise DevflowError(f"vendor_path скилла {name} должен быть {expected}")
    return ensure_within(repo, expected)


def find_locked_skill(lock: dict[str, Any], name: str) -> dict[str, Any]:
    for skill in lock.get("skills", []):
        if skill.get("name") == name:
            return skill
    raise DevflowError(f"Скилл {name} не зарегистрирован в lock-файле")


def expected_target_for_agent(agent: str) -> str | None:
    lowered = agent.lower()
    if "claude" in lowered:
        return "claude"
    if "codex" in lowered or "openai" in lowered:
        return "codex"
    return None


SKILL_PUBLIC_NAME = "vibecode-control"
# Where each client loads a personal skill from.  The project-scoped roots live in
# `target_skill_path`; these are the user-level ones.
PERSONAL_SKILL_ROOTS = {
    "codex": (".agents", "skills"),
    "claude": (".claude", "skills"),
}


def skill_source_root() -> Path:
    """The root of this skill: the directory that holds SKILL.md, scripts and assets."""
    override = os.environ.get("DEVFLOW_SKILL_ROOT")
    root = Path(override).resolve() if override else Path(__file__).resolve().parent.parent
    if not (root / "SKILL.md").is_file() or not (root / "assets" / "project-kit").is_dir():
        raise DevflowError(f"Каталог не выглядит корнем скилла VibeCode Control: {root}")
    return root


def personal_skill_target(client: str, home: Path | None = None) -> Path:
    if client not in PERSONAL_SKILL_ROOTS:
        raise DevflowError(
            f"Неизвестный клиент: {client}; поддерживаются " + ", ".join(sorted(PERSONAL_SKILL_ROOTS))
        )
    base = home.resolve() if home is not None else Path.home()
    return base.joinpath(*PERSONAL_SKILL_ROOTS[client], SKILL_PUBLIC_NAME)


def install_skill(client: str, apply: bool = False, home: Path | None = None,
                  force: bool = False) -> dict[str, Any]:
    """Install or update this skill as a personal skill for one client.

    The plan is shown before anything is written, the target is confined to that
    client's own skills directory, and the result is verified by re-hashing the
    installed tree against the source.
    """
    source = skill_source_root()
    target = personal_skill_target(client, home)
    root = target.parent
    if target.exists() and target.is_symlink():
        raise DevflowError(f"Целевой путь — symlink, установка запрещена: {target}")
    if target.exists() and not target.is_dir():
        raise DevflowError(f"Целевой путь занят файлом: {target}")
    existing_marker = target / "SKILL.md"
    if target.is_dir() and existing_marker.is_file():
        declared = read_small_text(existing_marker)
        if f"name: {SKILL_PUBLIC_NAME}" not in declared and not force:
            raise DevflowError(
                f"В {target} уже установлен другой скилл; повторите с --force, чтобы заменить его"
            )
    elif target.is_dir() and any(target.iterdir()) and not force:
        raise DevflowError(
            f"Каталог {target} не пуст и не содержит SKILL.md; повторите с --force, чтобы заменить его"
        )

    source_files = {
        path.relative_to(source).as_posix(): path
        for path in iter_files(source)
    }
    installed = iter_skill_files(target) if target.is_dir() else []
    if installed is None:
        raise DevflowError(f"Установленная копия содержит symlink или недоступный файл: {target}")
    existing = {path.relative_to(target).as_posix(): path for path in installed}

    create = sorted(name for name in source_files if name not in existing)
    update = sorted(
        name for name in source_files
        if name in existing and existing[name].read_bytes() != source_files[name].read_bytes()
    )
    remove = sorted(name for name in existing if name not in source_files)
    total_bytes = sum(path.stat().st_size for path in source_files.values())
    report: dict[str, Any] = {
        "client": client,
        "skill": SKILL_PUBLIC_NAME,
        "source": str(source),
        "target": str(target),
        "file_count": len(source_files),
        "total_bytes": total_bytes,
        # Checksum the installable file set, not the raw tree: the source is a git
        # checkout and must not have `.git` folded into its identity.
        "source_checksum": hash_file_map(source_files),
        "installed_checksum": hash_file_map(existing),
        "create": create,
        "update": update,
        "remove": remove,
    }
    report["up_to_date"] = not (create or update or remove)
    if not apply:
        report["status"] = "PASS" if report["up_to_date"] else "PARTIAL"
        report["applied"] = False
        report["dry_run"] = True
        report["next_command"] = f"devflow install --client {client} --apply"
        return report
    root.mkdir(parents=True, exist_ok=True)
    for name in remove:
        existing[name].unlink()
    for name in sorted(source_files):
        destination = target / name
        if root.resolve() not in destination.resolve().parents:
            raise DevflowError(f"Операция установки вышла за пределы каталога клиента: {destination}")
        atomic_write(destination, source_files[name].read_bytes())
    for current, _, _ in os.walk(target, topdown=False):
        path = Path(current)
        if path != target and not any(path.iterdir()):
            path.rmdir()
    reinstalled = iter_skill_files(target) or []
    report["installed_checksum"] = hash_file_map(
        {path.relative_to(target).as_posix(): path for path in reinstalled}
    )
    report["applied"] = True
    report["dry_run"] = False
    verified = report["installed_checksum"] == report["source_checksum"] and bool(report["source_checksum"])
    report["status"] = "PASS" if verified else "BLOCKED"
    if not verified:
        report["error"] = "Контрольная сумма установленной копии не совпала с источником"
    report["invocation"] = (
        f"$ {SKILL_PUBLIC_NAME} ..." if client == "codex" else f"Skill: {SKILL_PUBLIC_NAME}"
    )
    return report


def skills_audit(repo: Path, node: str | None = None, deep: bool = False) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    config_errors, _ = validate_config(config)
    workflow_errors, _ = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    if config_errors or workflow_errors or lock_errors:
        return {
            "status": "BLOCKED",
            "errors": ["Нельзя проверять скиллы поверх невалидной конфигурации, графа или lock", *config_errors, *workflow_errors, *lock_errors],
            "warnings": [],
            "details": [],
        }
    initialize_skill_decisions(lock, workflow)
    errors: list[str] = []
    warnings: list[str] = []
    details: list[dict[str, Any]] = []
    nodes = {item["id"]: item for item in workflow["nodes"]}
    selected_nodes = [node] if node else list(nodes)
    for skill in lock.get("skills", []):
        name = skill.get("name", "<unnamed>")
        if not source_allowed(skill.get("source", ""), lock):
            errors.append(f"Источник скилла {name} не входит в allowlist")
        if not re.fullmatch(r"[0-9a-f]{40}", skill.get("commit_sha", "")):
            errors.append(f"Скилл {name} не закреплён полным commit SHA")
        if skill.get("approved_by_user") is not True:
            errors.append(f"Для скилла {name} нет зафиксированного явного пользовательского одобрения")
        if skill.get("audit_status") not in {"PASS", "PARTIAL"}:
            errors.append(f"Скилл {name} имеет блокирующий или неизвестный audit_status")
        provenance = skill.get("provenance", {})
        if provenance.get("status") != "verified-local-checkout" or provenance.get("commit_sha") != skill.get("commit_sha"):
            errors.append(f"Provenance скилла {name} не подтверждает закреплённый commit")
        canonical_repository = provenance.get("canonical_repository", "")
        if not canonical_repository or not (
            skill.get("source") == canonical_repository or str(skill.get("source", "")).startswith(canonical_repository + "/")
        ):
            errors.append(f"Provenance скилла {name} не совпадает с source URL")
        targets = skill.get("targets")
        if not isinstance(targets, list) or not targets or any(target not in {"claude", "codex"} for target in targets):
            errors.append(f"Скилл {name} не имеет корректных target-платформ")
        if not skill.get("license"):
            warnings.append(f"Для скилла {name} не зафиксирована лицензия")
        try:
            vendor = vendor_skill_path(repo, skill)
        except DevflowError as exc:
            errors.append(str(exc))
            continue
        vendor_checksum = hash_tree(vendor)
        if not vendor_checksum or vendor_checksum != skill.get("checksum"):
            errors.append(f"Pinned vendor copy скилла {name} отсутствует или не совпадает с lock")
        target_results = []
        for target in skill.get("targets", []):
            try:
                path = target_skill_path(repo, name, target)
            except DevflowError as exc:
                errors.append(str(exc))
                continue
            actual = hash_tree(path)
            expected = skill.get("checksum", "")
            state = "PASS" if actual and actual == expected else "BLOCKED"
            if state == "BLOCKED":
                errors.append(f"Checksum или наличие {target}-копии скилла {name} не подтверждены")
            target_results.append({"target": target, "path": str(path.relative_to(repo)), "status": state, "checksum": actual})
        details.append({"node": None, "skill": name, "level": "locked", "targets": target_results})
        if deep:
            static = audit_skill_directory(vendor)
            if static["status"] == "BLOCKED":
                errors.append(f"Статический аудит скилла {name} обнаружил блокирующие признаки")
            elif static["status"] == "PARTIAL":
                warnings.append(f"Статический аудит скилла {name} требует ручной проверки")
    for node_id in selected_nodes:
        if node_id not in nodes:
            errors.append(f"Неизвестный узел: {node_id}")
            continue
        decision = lock["node_decisions"].get(node_id)
        if not decision or decision.get("status") not in DECISION_VALUES:
            errors.append(f"Для узла {node_id} нет корректного решения по скиллам")
            continue
        if decision["status"] == "unresolved":
            errors.append(f"Для узла {node_id} решение по скиллам не принято")
        if decision["status"] == "blocked":
            errors.append(f"Для узла {node_id} зафиксировано блокирующее решение по скиллам")
        if decision["status"] == "zero-skill" and not str(decision.get("reason", "")).strip():
            errors.append(f"Для zero-skill узла {node_id} не зафиксирована причина")
        if decision.get("revalidation_required"):
            warnings.append(f"Для узла {node_id} требуется повторная оценка скиллов")
        assigned = decision.get("assigned", [])
        if decision["status"] == "assigned" and not assigned:
            errors.append(f"Узел {node_id} имеет status=assigned без назначенных скиллов")
        limit = lock.get("review_policy", {}).get("max_third_party_skills_per_node", 2)
        if len(assigned) > limit:
            errors.append(f"Узел {node_id} превышает лимит {limit} сторонних скиллов")
        role = nodes[node_id].get("role")
        overrides = config.get("node_overrides", {}) if isinstance(config.get("node_overrides", {}), dict) else {}
        roles = config.get("roles", {}) if isinstance(config.get("roles", {}), dict) else {}
        override = overrides.get(node_id, {}) if isinstance(overrides.get(node_id, {}), dict) else {}
        role_settings = roles.get(role, {}) if isinstance(roles.get(role, {}), dict) else {}
        agent = override.get("agent", role_settings.get("agent", ""))
        needed_target = expected_target_for_agent(agent)
        for assignment in assigned:
            name = assignment.get("name") if isinstance(assignment, dict) else str(assignment)
            level = assignment.get("level", "required") if isinstance(assignment, dict) else "required"
            try:
                skill = find_locked_skill(lock, name)
            except DevflowError as exc:
                errors.append(str(exc))
                continue
            targets = skill.get("targets", [])
            if needed_target and level == "required" and needed_target not in targets:
                errors.append(f"Обязательный скилл {name} не доставляется агенту {agent}")
            details.append({"node": node_id, "skill": name, "level": level, "targets": targets})
    core_paths = [repo / ".agents/skills/devflow-node", repo / ".claude/skills/devflow-node"]
    canonical_core = repo / META_DIR / "toolkit" / "managed" / "background-skill" / "SKILL.template.md"
    canonical_hash = sha256_file(canonical_core) if canonical_core.is_file() else ""
    if not canonical_hash:
        errors.append("Каноническая toolkit-копия devflow-node отсутствует или повреждена")
    if any(not (path / "SKILL.md").is_file() for path in core_paths):
        errors.append("Проектный devflow-node не доставлен обоим фоновым агентам")
    else:
        core_entries = [iter_skill_files(path) for path in core_paths]
        valid_layout = all(
            entries is not None
            and len(entries) == 1
            and entries[0].relative_to(path).as_posix() == "SKILL.md"
            for path, entries in zip(core_paths, core_entries)
        )
        core_hashes = [sha256_file(path / "SKILL.md") for path in core_paths]
        if not valid_layout or any(value != canonical_hash for value in core_hashes):
            errors.append("Копии devflow-node не совпадают с канонической toolkit-копией")
    status = "BLOCKED" if errors else ("PARTIAL" if warnings else "PASS")
    return {"status": status, "errors": errors, "warnings": warnings, "details": details}


def skill_recommendations(repo: Path, node: str | None = None) -> dict[str, Any]:
    config, workflow, lock, configuration_status = load_project_or_proposed_state(repo)
    config_errors, _ = validate_config(config)
    workflow_errors, _ = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    if config_errors or workflow_errors or lock_errors:
        raise DevflowError(
            "Нельзя рекомендовать скиллы поверх невалидного control plane: "
            + " | ".join(config_errors + workflow_errors + lock_errors)
        )
    initialize_skill_decisions(lock, workflow)
    inspection = inspect_repository(repo)
    stack_label = ", ".join(inspection["project"]["stacks"]) or "stack unclassified"
    rows = []
    for raw_node in workflow["nodes"]:
        if node and raw_node["id"] != node:
            continue
        effective = effective_node(raw_node, config, lock)
        decision = lock["node_decisions"][raw_node["id"]]
        if decision["recommendation"] == "NOT_NEEDED":
            gap = "No capability gap identified: project rules, VibeCode Control, scripts, CI, or objective checks cover the node."
        else:
            competency = ", ".join(raw_node.get("competencies", [])[:2]) or raw_node["action"]
            gap = f"Evaluate whether a narrow {stack_label} procedure measurably improves {competency}; no project comparison exists yet."
        query = None
        if decision["recommendation"] == "EVALUATE":
            stack = " ".join(inspection["project"]["stacks"][:3]) or "software engineering"
            query = f"{stack} {raw_node['action'].replace('_', ' ')}"
        rows.append({
            "node": raw_node["id"],
            "action": raw_node["action"],
            "agent": effective["agent"],
            "model": effective["model"],
            "effort": effective["effort"],
            "permissions": effective["permissions"],
            "stack": stack_label,
            "stack_versions": "unverified",
            "risk": config.get("quality", {}).get("risk_profile", "unclassified"),
            "competencies": raw_node.get("competencies", []),
            "identified_gap": gap,
            "recommendation": decision["recommendation"],
            "evidence_level": decision["evidence_level"],
            "empirical_status": "эмпирически не проверено" if decision["evidence_level"] != "project-tested" else "проверено на сценариях проекта",
            "reason": decision["reason"],
            "search_query_if_needed": query,
            "user_decision": decision["status"],
        })
    return {
        "status": "BLOCKED" if any(row["user_decision"] == "unresolved" for row in rows) else "PASS",
        "configuration_status": configuration_status,
        "principle": "Compare zero-skill, incumbent, and at most three allowlisted candidates under the same model, effort, permissions, and scenarios.",
        "rows": rows,
    }


def copy_tree_operations(repo: Path, source: Path, relative_target: str, delete_extras: bool = False) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    source_entries = iter_skill_files(source)
    if source_entries is None:
        raise DevflowError(f"Дерево скилла содержит symlink, special file или недоступный entry: {source}")
    source_files = {path.relative_to(source).as_posix(): path for path in source_entries}
    target_root = ensure_within(repo, relative_target)
    if delete_extras and target_root.exists():
        target_entries = iter_skill_files(target_root)
        if target_entries is None:
            raise DevflowError(f"Целевое дерево скилла повреждено или содержит symlink: {target_root}")
        for existing in target_entries:
            rel = existing.relative_to(target_root).as_posix()
            if rel not in source_files:
                operation = make_operation(repo, f"{relative_target}/{rel}", None)
                if operation:
                    operations.append(operation)
    for rel, path in source_files.items():
        operation = make_operation(repo, f"{relative_target}/{rel}", path.read_bytes())
        if operation:
            operations.append(operation)
    return operations


def one_file_plan(repo: Path, relative: str, data: bytes, purpose: str) -> dict[str, Any]:
    operation = make_operation(repo, relative, data)
    return attach_effective_configuration(repo, {
        "schema_version": 1,
        "devflow_version": VERSION,
        "run_id": run_id(purpose),
        "mode": purpose,
        "created_at": iso_now(),
        "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo),
        "operations": [operation] if operation else [],
        "warnings": [],
    })


def write_project_json(repo: Path, relative: str, value: Any, purpose: str) -> dict[str, Any]:
    plan = one_file_plan(repo, relative, json_bytes(value), purpose)
    if not plan["operations"]:
        return {"status": "PASS", "changed": 0, "run_id": None}
    return apply_plan(repo, plan)


def load_setup_state(repo: Path) -> dict[str, Any]:
    path = repo / SETUP_STATE_PATH
    if not path.exists():
        return {"schema_version": 1, "manual": {}}
    value = load_json(path)
    value.setdefault("manual", {})
    return value


def stage_result(stage: str, status: str, evidence: list[str], gaps: list[str], recommendation: str,
                 next_stage: str | None, next_command: str | None, requires_user_decision: bool = False) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise DevflowError(f"Некорректный статус этапа {stage}: {status}")
    return {
        "stage": stage,
        "status": status,
        "evidence": evidence,
        "gaps": gaps,
        "recommendation": recommendation,
        "next_stage": next_stage,
        "next_command": next_command,
        "requires_user_decision": requires_user_decision,
    }


def finalize_stage_commands(repo: Path, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for result in results:
        command, argv = expand_devflow_command(repo, result.get("next_command"))
        result["next_command"] = command
        if argv:
            result["next_argv"] = argv
    return results


def evaluate_setup(repo: Path) -> list[dict[str, Any]]:
    stages_path = repo / SETUP_STAGES_PATH
    if stages_path.exists():
        stages_def = load_json(stages_path)
    else:
        stages_def = load_json(find_project_kit(repo) / "setup-stages.json")
    stage_ids = [stage["id"] for stage in stages_def["stages"]]
    next_for = {stage_ids[index]: stage_ids[index + 1] if index + 1 < len(stage_ids) else None for index in range(len(stage_ids))}
    command_for = {stage["id"]: stage.get("next_command") for stage in stages_def["stages"]}
    inspection = inspect_repository(repo)
    results: list[dict[str, Any]] = []
    results.append(stage_result(
        "inspection", "PASS",
        [f"Read-only inspection completed; {inspection['project']['file_count']} files; mode {inspection['project']['recommended_mode']}"],
        [], "Proceed with the detected init/adopt mode.", next_for["inspection"], command_for["inspection"]
    ))
    if not (repo / CONFIG_PATH).is_file() or not (repo / WORKFLOW_PATH).is_file() or not (repo / SKILLS_LOCK_PATH).is_file():
        mode = inspection["project"]["recommended_mode"]
        results.append(stage_result(
            "context", "BLOCKED", [], ["VibeCode Control project configuration is not installed"],
            f"Review the proposed graph, skill matrix, and {mode} dry-run; apply only after explicit approval.",
            "context", f"devflow {mode}", True
        ))
        for stage in stage_ids[2:]:
            results.append(stage_result(
                stage, "BLOCKED", [], ["Previous configuration stage is incomplete"],
                "Complete the reviewed VibeCode Control installation first.", stage, f"devflow {mode}", True
            ))
        return finalize_stage_commands(repo, results)

    config, workflow, lock = load_project_state(repo)
    config_errors, config_warnings = validate_config(config)
    graph_errors, graph_warnings = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    guarded_errors = config_errors + graph_errors + lock_errors
    if guarded_errors:
        for stage in stage_ids[1:]:
            results.append(stage_result(
                stage, "BLOCKED", [], guarded_errors,
                "Prepare an explicit reviewed migration for the invalid guarded control-plane file.",
                stage, "devflow doctor --repair-plan", True,
            ))
        return finalize_stage_commands(repo, results)
    manual = load_setup_state(repo).get("manual", {})
    context_evidence = [f"product_stage={config.get('project', {}).get('product_stage', 'missing')}"]
    context_gaps = []
    product_stage = config.get("project", {}).get("product_stage")
    if product_stage in {None, "unassessed"}:
        context_gaps.append("Product stage and approved scope reference are not configured")
    if product_stage in {"development-readiness", "development", "maintenance"} and not config.get("project", {}).get("decision_ref"):
        context_gaps.append("Development stage lacks an explicit PM decision reference")
    language = config.get("policy", {}).get("language") if isinstance(config.get("policy"), dict) else None
    context_evidence.append(f"report_language={language or 'missing'}")
    if not isinstance(language, str) or not language.strip() or language.strip() == MODE_UNDECIDED:
        context_gaps.append(
            "Report language is not chosen; the template ships no default: "
            "devflow config set policy.language <language>"
        )
    context_status = "BLOCKED" if context_gaps else "PASS"
    results.append(stage_result(
        "context", context_status, context_evidence, context_gaps,
        "Record the current product stage and the explicit PM decision; do not infer approval.",
        next_for["context"], "devflow config set project.product_stage <stage>", bool(context_gaps)
    ))

    # An undecided parameter blocks this stage through an explicit typed marker, not
    # through a validation warning: the shipped template chooses nothing, and a project
    # that has not chosen yet must not look configured.
    pending = pending_execution_decisions(config, workflow)
    roles_status = "BLOCKED" if config_errors or pending else ("PARTIAL" if config_warnings else "PASS")
    results.append(stage_result(
        "roles", roles_status,
        [f"Configured logical roles: {len(config.get('roles', {}))}",
         f"Pending execution decisions: {len(pending)}"],
        config_errors + config_warnings + [
            f"{item['pointer']}: {item['decision']} — `{item['command']}`" for item in pending
        ],
        "Verify concrete agents, models, effort, and permissions for the next runs; never use silent fallback.",
        next_for["roles"],
        pending[0]["command"] if pending else "devflow config effective",
        bool(pending),
    ))

    graph_status = "BLOCKED" if graph_errors else ("PARTIAL" if graph_warnings else "PASS")
    results.append(stage_result(
        "graph", graph_status,
        [f"Nodes: {len(workflow.get('nodes', []))}; edges: {len(workflow.get('edges', []))}"],
        graph_errors + graph_warnings,
        "Fix unreachable nodes, unbounded retries, unknown roles, or an unsafe merge path before automation.",
        next_for["graph"], "devflow graph --format table", False
    ))

    docs = inspection["documentation"]
    doc_gaps = []
    if inspection["project"]["looks_existing"] and not docs["readme"]:
        doc_gaps.append("README is missing")
    if product_stage in {"development-readiness", "development", "maintenance"} and not docs["architecture"]:
        doc_gaps.append("docs/ARCHITECTURE.md is missing for a development-stage project")
    documentation_status = "PARTIAL" if doc_gaps else "PASS"
    results.append(stage_result(
        "documentation", documentation_status,
        [f"README={docs['readme'] or 'missing'}", f"architecture={docs['architecture'] or 'missing'}", f"ADRs={docs['adrs']}"],
        doc_gaps,
        "Create or repair canonical documents from verified project facts; update architecture docs in the same PR as architectural changes.",
        next_for["documentation"], "devflow audit docs", False
    ))

    git_info = inspection["git"]
    git_gaps = []
    if not git_info["is_repository"]:
        git_gaps.append("Local Git repository is not initialized")
    if not git_info["remotes"]:
        git_gaps.append("Git remote is not configured or not observable")
    if config.get("github", {}).get("remote_settings") != "verified":
        git_gaps.append("Remote GitHub rulesets, required checks, and merge policy are unverified")
    git_status = "BLOCKED" if not git_info["is_repository"] else ("PARTIAL" if git_gaps else "PASS")
    results.append(stage_result(
        "git-github", git_status,
        [f"branch={git_info['branch']}", f"dirty={git_info['dirty']}", f"remotes={len(git_info['remotes'])}"],
        git_gaps,
        "Audit local Git and remote GitHub separately. Do not claim remote protection without API evidence. Follow references/github-preparation.md step by step.",
        next_for["git-github"], "devflow audit git", False
    ))

    quality = config.get("quality", {})
    quality_gaps = []
    if quality.get("baseline_status") != "measured":
        quality_gaps.append("Quality baseline is not measured")
    commands = quality.get("commands", {})
    if not any(commands.get(key) for key in ["unit", "integration", "e2e"]):
        quality_gaps.append("No project test command is configured")
    if not inspection["quality"]["ci_workflows"]:
        quality_gaps.append("No CI workflow was detected")
    quality_status = "PARTIAL" if quality_gaps else "PASS"
    results.append(stage_result(
        "quality", quality_status,
        [f"test files={inspection['quality']['test_files']}", f"CI workflows={len(inspection['quality']['ci_workflows'])}"],
        quality_gaps,
        "Measure the existing baseline before setting thresholds; use risk-based tests and evidence bound to head SHA.",
        next_for["quality"], "devflow audit quality", False
    ))

    skill_report = skills_audit(repo)
    results.append(stage_result(
        "skills", skill_report["status"],
        [f"Locked skills: {len(lock.get('skills', []))}", f"Node decisions: {len(lock.get('node_decisions', {}))}"],
        skill_report["errors"] + skill_report["warnings"],
        "Review one matrix for all nodes; explicitly accept assigned skills or zero-skill. Search only allowlisted sources.",
        next_for["skills"], "devflow skills recommend", bool(skill_report["errors"])
    ))

    automation_gaps = []
    if config.get("automation", {}).get("background_workers") != "verified":
        automation_gaps.append("Background Claude/Codex runners are unverified")
    core_skills = [repo / ".agents/skills/devflow-node/SKILL.md", repo / ".claude/skills/devflow-node/SKILL.md"]
    if not all(path.is_file() for path in core_skills):
        automation_gaps.append("devflow-node is not present for both background agents")
    if not inspection["quality"]["ci_workflows"]:
        automation_gaps.append("CI executor is not configured")
    automation_status = "PARTIAL" if automation_gaps else "PASS"
    results.append(stage_result(
        "automation", automation_status,
        [f"core background skills present={all(path.is_file() for path in core_skills)}"],
        automation_gaps,
        "Verify runner checkout, explicit node prompt, model/effort inputs, permissions, required checks, and state-change notifications.",
        next_for["automation"], "devflow doctor --deep", False
    ))

    pilot = manual.get("pilot", {})
    pilot_status = pilot.get("status") if pilot.get("status") in STATUS_VALUES else "PARTIAL"
    pilot_evidence = pilot.get("evidence", []) if isinstance(pilot.get("evidence"), list) else []
    pilot_gaps = [] if pilot_status == "PASS" else ["No successful small real Issue has been recorded through the complete flow"]
    results.append(stage_result(
        "pilot", pilot_status, pilot_evidence, pilot_gaps,
        "Run one low-risk Issue end to end and record Issue, branch, PR, checks, skills, head SHA, review, merge, and post-merge evidence.",
        None, "devflow setup mark pilot PASS --evidence <reference>", pilot_status != "PASS"
    ))

    for result in results:
        override = manual.get(result["stage"])
        if isinstance(override, dict):
            evidence = override.get("evidence", [])
            if isinstance(evidence, list):
                result["evidence"].extend(str(item) for item in evidence)
            if override.get("status") == "BLOCKED":
                result["status"] = "BLOCKED"
                result["gaps"].append(override.get("note", "Manual blocker recorded"))
    return finalize_stage_commands(repo, results)


def next_setup_step(results: list[dict[str, Any]], repo: Path | None = None) -> dict[str, Any]:
    for index, result in enumerate(results):
        if result["status"] not in {"PASS", "NOT_APPLICABLE"}:
            response = copy.deepcopy(result)
            response["position"] = f"{index + 1}/{len(results)}"
            return response
    complete = {
        "stage": "complete",
        "status": "PASS",
        "position": f"{len(results)}/{len(results)}",
        "evidence": ["All setup stages pass or are not applicable"],
        "gaps": [],
        "recommendation": "Operate the workflow and run periodic doctor checks after material changes or failures.",
        "next_stage": None,
        "next_command": "devflow doctor",
        "requires_user_decision": False,
    }
    if repo is not None:
        command, argv = expand_devflow_command(repo, complete["next_command"])
        complete["next_command"] = command
        complete["next_argv"] = argv
    return complete


def mark_setup_stage(repo: Path, stage: str, status: str, evidence: list[str], note: str) -> dict[str, Any]:
    if status not in STATUS_VALUES:
        raise DevflowError("Статус должен быть PASS, PARTIAL, BLOCKED или NOT_APPLICABLE")
    definitions = load_json(repo / SETUP_STAGES_PATH)
    valid = {item["id"] for item in definitions["stages"]}
    if stage not in valid:
        raise DevflowError(f"Неизвестный этап: {stage}")
    state = load_setup_state(repo)
    state["manual"][stage] = {"status": status, "evidence": evidence, "note": note, "recorded_at": iso_now()}
    return write_project_json(repo, SETUP_STATE_PATH, state, "setup-mark")


def apply_json_updates(repo: Path, values: dict[str, Any], purpose: str) -> dict[str, Any]:
    operations = []
    for relative, value in values.items():
        operation = make_operation(repo, relative, json_bytes(value))
        if operation:
            operations.append(operation)
    if not operations:
        return {"status": "PASS", "changed": 0, "run_id": None}
    plan = attach_effective_configuration(repo, {
        "schema_version": 1,
        "devflow_version": VERSION,
        "run_id": run_id(purpose),
        "mode": purpose,
        "created_at": iso_now(),
        "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo),
        "operations": operations,
        "warnings": [],
    })
    result = apply_plan(repo, plan)
    if isinstance(plan.get("effective_configuration"), dict):
        result["effective_configuration"] = plan["effective_configuration"]
    return result


def mark_skill_revalidation(config: dict[str, Any], workflow: dict[str, Any], lock: dict[str, Any], target: str) -> None:
    initialize_skill_decisions(lock, workflow)
    if target in config.get("roles", {}):
        affected = [node["id"] for node in workflow["nodes"] if node.get("role") == target]
    else:
        affected = [target]
    for node_id in affected:
        if node_id in lock["node_decisions"]:
            lock["node_decisions"][node_id]["revalidation_required"] = True


def configure_value(repo: Path, dotted: str, raw: str) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    deep_set(config, dotted, parse_jsonish(raw))
    errors, _ = validate_config(config)
    if errors:
        raise DevflowError("Конфигурация после изменения невалидна: " + "; ".join(errors))
    if dotted.startswith("roles.") or dotted.startswith("node_overrides.") or dotted.startswith("models."):
        parts = dotted.split(".")
        target = parts[1] if len(parts) > 1 else ""
        mark_skill_revalidation(config, workflow, lock, target)
    return apply_json_updates(repo, {CONFIG_PATH: config, SKILLS_LOCK_PATH: lock}, "config-set")


def configure_role(repo: Path, role: str, agent: str) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    if role not in config.get("roles", {}):
        raise DevflowError(f"Неизвестная роль: {role}")
    config["roles"][role]["agent"] = agent
    errors, _ = validate_config(config)
    if errors:
        raise DevflowError("Конфигурация после изменения невалидна: " + "; ".join(errors))
    mark_skill_revalidation(config, workflow, lock, role)
    return apply_json_updates(repo, {CONFIG_PATH: config, SKILLS_LOCK_PATH: lock}, "role-set")


def configure_model(repo: Path, target: str, model: str, effort: str | None) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    node_ids = {node["id"] for node in workflow["nodes"]}
    parsed_model, model_errors = parse_profile_value(model, f"{target}.model")
    if model_errors:
        raise DevflowError("; ".join(model_errors))
    parsed_effort = None
    if effort:
        parsed_effort, effort_errors = parse_profile_value(effort, f"{target}.effort")
        if effort_errors:
            raise DevflowError("; ".join(effort_errors))
    if target in config.get("roles", {}):
        config["roles"][target]["model"] = parsed_model
        if parsed_effort is not None:
            config["roles"][target]["effort"] = parsed_effort
    elif target in node_ids:
        override = config.setdefault("node_overrides", {}).setdefault(target, {})
        override["model"] = parsed_model
        if parsed_effort is not None:
            override["effort"] = parsed_effort
    else:
        raise DevflowError(f"Неизвестная роль или узел: {target}")
    errors, _ = validate_config(config)
    if errors:
        raise DevflowError("Конфигурация после изменения невалидна: " + "; ".join(errors))
    mark_skill_revalidation(config, workflow, lock, target)
    return apply_json_updates(repo, {CONFIG_PATH: config, SKILLS_LOCK_PATH: lock}, "model-set")


def migrate_graph_contracts(repo: Path, apply: bool = False, full_diff: bool = False) -> dict[str, Any]:
    """Add the missing review-artifact contracts to a graph written before this contract.

    Only node ids that exist in the canonical kit graph are migrated, and only by copying
    that graph's declaration.  A review node this tool does not ship is reported for an
    explicit decision instead of being given a guessed artifact kind.
    """
    workflow = load_json(repo / WORKFLOW_PATH)
    template = load_json(find_project_kit(repo) / "workflow.json")
    canonical = {
        node.get("id"): node.get("evidence_contract")
        for node in template.get("nodes", []) if isinstance(node, dict)
    }
    migrated: list[str] = []
    undecided: list[str] = []
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict) or node.get("stage") != "review":
            continue
        contract = node.get("evidence_contract")
        if isinstance(contract, dict) and any(
            isinstance(item, dict) and item.get("required", True) for item in contract.values()
        ):
            continue
        proposed = canonical.get(node.get("id"))
        declared = node.get("expected_evidence") if isinstance(node.get("expected_evidence"), list) else []
        if isinstance(proposed, dict) and set(proposed).issubset(set(declared)):
            node["evidence_contract"] = copy.deepcopy(proposed)
            migrated.append(str(node.get("id")))
        else:
            undecided.append(str(node.get("id")))
    if not migrated:
        return {
            "status": "BLOCKED" if undecided else "NOT_APPLICABLE",
            "migrated": [],
            "requires_explicit_decision": undecided,
            "note": (
                "Для этих review-узлов нет канонического контракта: добавьте evidence_contract "
                "в .agent-flow/workflow.json явно, указав имя из expected_evidence и вид артефакта "
                + ", ".join(sorted(REVIEW_ARTIFACT_KINDS))
                if undecided else "Граф уже объявляет обязательные артефакты review-узлов"
            ),
        }
    errors, _ = validate_workflow(workflow, load_json(repo / CONFIG_PATH))
    if errors:
        return {"status": "BLOCKED", "errors": errors, "migrated": migrated}
    plan = one_file_plan(repo, WORKFLOW_PATH, json_bytes(workflow), "graph-migrate")
    if not apply:
        return {
            "status": "PARTIAL",
            "applied": False,
            "migrated": migrated,
            "requires_explicit_decision": undecided,
            "plan": summarize_plan(repo, plan, full_diff=full_diff),
            "next_command": "devflow graph --migrate --apply",
        }
    result = apply_plan(repo, plan)
    result["migrated"] = migrated
    result["requires_explicit_decision"] = undecided
    result["applied"] = True
    if undecided:
        result["status"] = "PARTIAL"
    return result


def normalize_project_config(repo: Path, apply: bool = False, full_diff: bool = False) -> dict[str, Any]:
    """Migrate an installed project to the typed model/effort contract."""
    config = load_json(repo / CONFIG_PATH)
    legacy = config_uses_legacy_profile(config)
    normalized, errors = normalize_config(config)
    if errors:
        return {"status": "BLOCKED", "errors": errors, "legacy": legacy}
    plan = one_file_plan(repo, CONFIG_PATH, json_bytes(normalized), "config-set")
    if not plan["operations"]:
        return {
            "status": "NOT_APPLICABLE",
            "legacy": legacy,
            "note": "Конфигурация уже записана в типизированной форме",
        }
    validation_errors, validation_warnings = validate_config(normalized)
    if validation_errors:
        return {"status": "BLOCKED", "errors": validation_errors, "legacy": legacy}
    summary = summarize_plan(repo, plan, full_diff=full_diff)
    if not apply:
        return {
            "status": "PARTIAL",
            "applied": False,
            "legacy": legacy,
            "warnings": validation_warnings,
            "plan": summary,
            "next_command": "devflow config normalize --apply",
        }
    result = apply_plan(repo, plan)
    result["legacy"] = legacy
    result["warnings"] = validation_warnings
    result["applied"] = True
    return result


def configure_permissions(repo: Path, target: str, profile: str) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    node_ids = {node["id"] for node in workflow["nodes"]}
    if target in config.get("roles", {}):
        config["roles"][target]["permissions"] = profile
    elif target in node_ids:
        config.setdefault("node_overrides", {}).setdefault(target, {})["permissions"] = profile
    else:
        raise DevflowError(f"Неизвестная роль или узел: {target}")
    errors, _ = validate_config(config)
    if errors:
        raise DevflowError("Конфигурация после изменения невалидна: " + "; ".join(errors))
    mark_skill_revalidation(config, workflow, lock, target)
    return apply_json_updates(repo, {CONFIG_PATH: config, SKILLS_LOCK_PATH: lock}, "permissions-set")


def skill_decision(repo: Path, node: str, status: str, skill: str | None = None,
                   level: str = "required", reason: str = "") -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    del config
    initialize_skill_decisions(lock, workflow)
    if node not in lock["node_decisions"]:
        raise DevflowError(f"Неизвестный узел: {node}")
    decision = lock["node_decisions"][node]
    if status == "zero-skill":
        if not reason:
            raise DevflowError("Для zero-skill укажите причину через --reason")
        decision.update({
            "status": "zero-skill", "assigned": [], "reason": reason,
            "recommendation": "NOT_NEEDED", "evidence_level": "user-approved",
            "reviewed_at": iso_now(), "revalidation_required": False,
        })
    elif status == "assigned":
        if level not in {"required", "recommended", "optional"}:
            raise DevflowError("level должен быть required, recommended или optional")
        find_locked_skill(lock, skill or "")
        assigned = [item for item in decision.get("assigned", []) if item.get("name") != skill]
        assigned.append({"name": skill, "level": level})
        limit = lock.get("review_policy", {}).get("max_third_party_skills_per_node", 2)
        if len(assigned) > limit:
            raise DevflowError(f"На узел разрешено не более {limit} сторонних скиллов")
        decision.update({
            "status": "assigned", "assigned": assigned,
            "reason": reason or "User selected an audited pinned skill for this node.",
            "evidence_level": "user-approved", "reviewed_at": iso_now(),
            "revalidation_required": False,
        })
    elif status == "unresolved":
        decision.update({"status": "unresolved", "assigned": [], "reviewed_at": None})
    else:
        raise DevflowError(f"Неподдерживаемое решение: {status}")
    return write_project_json(repo, SKILLS_LOCK_PATH, lock, "skills-decision")


def skill_unassign(repo: Path, node: str, skill_name: str) -> dict[str, Any]:
    _, workflow, lock = load_project_state(repo)
    initialize_skill_decisions(lock, workflow)
    if node not in lock["node_decisions"]:
        raise DevflowError(f"Неизвестный узел: {node}")
    decision = lock["node_decisions"][node]
    assigned = [item for item in decision.get("assigned", []) if item.get("name") != skill_name]
    decision["assigned"] = assigned
    decision["status"] = "assigned" if assigned else "unresolved"
    decision["revalidation_required"] = True
    return write_project_json(repo, SKILLS_LOCK_PATH, lock, "skills-unassign")


def register_skill(repo: Path, name: str, source_path: Path, source_url: str, commit_sha: str,
                   license_name: str, targets: list[str], apply: bool, approved: bool) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        raise DevflowError("Имя скилла должно содержать lowercase letters, digits, and hyphens")
    if name in {"devflow", "devflow-node"}:
        raise DevflowError(f"Имя {name} зарезервировано VibeCode Control")
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise DevflowError("Требуется полный 40-символьный Git commit SHA")
    if not license_name.strip():
        raise DevflowError("Укажите лицензию скилла")
    if source_path.is_symlink():
        raise DevflowError("Корневой symlink кандидата запрещён")
    source_path = source_path.resolve()
    static = audit_skill_directory(source_path)
    if static.get("declared_name") and static["declared_name"] != name:
        raise DevflowError(f"Имя {name} не совпадает с frontmatter name={static['declared_name']}")
    _, workflow, lock = load_project_state(repo)
    if not source_allowed(source_url, lock):
        raise DevflowError("Источник не входит в allowlist. Добавьте его явно в allowed_sources.extra или используйте разрешённый источник.")
    provenance = verify_skill_provenance(source_path, source_url, commit_sha)
    if static["status"] == "BLOCKED":
        return {
            "status": "BLOCKED",
            "reason": "Static audit found high or critical signals; explicit approval cannot bypass a blocking audit.",
            "audit": static,
            "next_command": "Review every finding. Do not approve merely to bypass the audit."
        }
    if any(target not in {"claude", "codex"} for target in targets) or not targets:
        raise DevflowError("targets должны содержать claude и/или codex")
    checksum = static["checksum"]
    vendor_rel = f"{META_DIR}/vendor-skills/{name}"
    previous = next((item for item in lock.get("skills", []) if item.get("name") == name), None)
    operations = copy_tree_operations(repo, source_path, vendor_rel, delete_extras=True)
    previous_targets = set(previous.get("targets", [])) if isinstance(previous, dict) else set()
    for removed_target in sorted(previous_targets - set(targets)):
        removed_rel = target_skill_path(repo, name, removed_target).relative_to(repo).as_posix()
        operations.extend(delete_tree_operations(repo, removed_rel))
    for target in targets:
        target_rel = target_skill_path(repo, name, target).relative_to(repo).as_posix()
        operations.extend(copy_tree_operations(repo, source_path, target_rel, delete_extras=True))
    review_days = int(lock.get("review_policy", {}).get("review_interval_days", 60))
    review_after = (utc_now() + dt.timedelta(days=review_days)).date().isoformat()
    entry = {
        "name": name,
        "source": source_url,
        "source_type": "allowlisted-repository",
        "commit_sha": commit_sha,
        "checksum": checksum,
        "license": license_name,
        "targets": sorted(set(targets)),
        "vendor_path": vendor_rel,
        "audit_status": static["status"],
        "audit_findings": static["findings"],
        "audited_at": iso_now(),
        "review_after": review_after,
        "approved_by_user": bool(approved),
        "provenance": provenance,
    }
    lock["skills"] = [item for item in lock.get("skills", []) if item.get("name") != name] + [entry]
    if previous and (previous.get("commit_sha") != commit_sha or previous.get("checksum") != checksum):
        for decision in lock.get("node_decisions", {}).values():
            assigned_names = {
                item.get("name") if isinstance(item, dict) else str(item)
                for item in decision.get("assigned", [])
            }
            if name in assigned_names:
                decision["revalidation_required"] = True
    lock_operation = make_operation(repo, SKILLS_LOCK_PATH, json_bytes(lock))
    if lock_operation:
        operations.append(lock_operation)
    plan = {
        "schema_version": 1, "devflow_version": VERSION, "run_id": run_id("skills-register"),
        "mode": "skills-register", "created_at": iso_now(), "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo), "operations": operations,
        "warnings": ["Registering a skill does not assign it to any node. Use skills assign after reviewing the node matrix."],
    }
    if not apply:
        return {"status": "PARTIAL", "dry_run": True, "plan": summarize_plan(repo, plan), "audit": static}
    if not approved:
        raise DevflowError("Для копирования стороннего скилла требуется --approved-by-user после просмотра аудита")
    return {"status": "PASS", "apply": apply_plan(repo, plan), "audit": static}


def delete_tree_operations(repo: Path, relative_root: str) -> list[dict[str, Any]]:
    root = ensure_within(repo, relative_root)
    if not root.exists():
        return []
    if not root.is_dir():
        raise DevflowError(f"Ожидался каталог: {relative_root}")
    operations: list[dict[str, Any]] = []
    entries = iter_skill_files(root)
    if entries is None:
        raise DevflowError(f"Дерево скилла повреждено или содержит symlink: {relative_root}")
    for path in reversed(entries):
        operation = make_operation(repo, path.relative_to(repo).as_posix(), None)
        if operation:
            operations.append(operation)
    return operations


def remove_skill(repo: Path, name: str, apply: bool) -> dict[str, Any]:
    _, workflow, lock = load_project_state(repo)
    initialize_skill_decisions(lock, workflow)
    skill = find_locked_skill(lock, name)
    assigned_nodes = []
    for node_id, decision in lock.get("node_decisions", {}).items():
        assigned_names = {
            item.get("name") if isinstance(item, dict) else str(item)
            for item in decision.get("assigned", [])
        }
        if name in assigned_names:
            assigned_nodes.append(node_id)
    if assigned_nodes:
        raise DevflowError(
            "Сначала снимите назначение скилла с узлов: " + ", ".join(sorted(assigned_nodes))
        )
    operations = delete_tree_operations(repo, vendor_skill_path(repo, skill).relative_to(repo).as_posix())
    for target in skill.get("targets", []):
        target_rel = target_skill_path(repo, name, target).relative_to(repo).as_posix()
        operations.extend(delete_tree_operations(repo, target_rel))
    lock["skills"] = [item for item in lock.get("skills", []) if item.get("name") != name]
    lock_operation = make_operation(repo, SKILLS_LOCK_PATH, json_bytes(lock))
    if lock_operation:
        operations.append(lock_operation)
    plan = {
        "schema_version": 1,
        "devflow_version": VERSION,
        "run_id": run_id("skills-remove"),
        "mode": "skills-remove",
        "created_at": iso_now(),
        "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo),
        "operations": operations,
        "warnings": ["Only files are tracked; empty untracked directories may remain on disk."],
    }
    if not apply:
        return {"status": "PARTIAL" if operations else "PASS", "dry_run": True, "plan": summarize_plan(repo, plan)}
    return {"status": "PASS", "apply": apply_plan(repo, plan)}


def sync_skills(repo: Path, apply: bool) -> dict[str, Any]:
    _, _, lock = load_project_state(repo)
    operations: list[dict[str, Any]] = []
    missing_vendor = []
    for skill in lock.get("skills", []):
        name = skill["name"]
        vendor = vendor_skill_path(repo, skill)
        if hash_tree(vendor) != skill.get("checksum"):
            missing_vendor.append(name)
            continue
        for target in skill.get("targets", []):
            target_rel = target_skill_path(repo, name, target).relative_to(repo).as_posix()
            operations.extend(copy_tree_operations(repo, vendor, target_rel, delete_extras=True))
    if missing_vendor:
        raise DevflowError("Pinned vendor copy is missing or changed: " + ", ".join(missing_vendor))
    plan = {
        "schema_version": 1, "devflow_version": VERSION, "run_id": run_id("skills-sync"),
        "mode": "skills-sync", "created_at": iso_now(), "repo": str(repo.resolve()),
        "fingerprint": repo_fingerprint(repo), "operations": operations, "warnings": [],
    }
    if not apply:
        return {"status": "PASS" if not operations else "PARTIAL", "dry_run": True, "plan": summarize_plan(repo, plan)}
    return apply_plan(repo, plan)


def skills_search_request(repo: Path, node: str | None) -> dict[str, Any]:
    _, _, lock, _ = load_project_or_proposed_state(repo)
    recommendations = skill_recommendations(repo, node)
    queries = [row["search_query_if_needed"] for row in recommendations["rows"] if row.get("search_query_if_needed")]
    return {
        "status": "ONLINE_SEARCH_REQUIRED",
        "allowed_sources": lock.get("allowed_sources", {}),
        "queries": queries,
        "rules": [
            "Do not use general GitHub or web discovery outside the allowlist.",
            "Shortlist no more than three candidates for a problem node.",
            "Compare candidate, incumbent, and zero-skill under the same model, effort, permissions, and scenarios.",
            "Popularity and recency are signals, not proof of quality or safety.",
            "Do not install or update a candidate without explicit user approval, full commit SHA, static audit, and diff."
        ],
        "recommendations": recommendations["rows"],
    }


def summarize_plan(repo: Path, plan: dict[str, Any], full_diff: bool = False,
                   only_paths: list[str] | None = None) -> dict[str, Any]:
    rendered_operations: list[dict[str, Any]] = []
    remaining = None if full_diff else 20_000
    per_file = None if full_diff else 3_000
    for operation in plan.get("operations", []):
        if only_paths and operation["path"] not in set(only_paths):
            continue
        is_text = operation["path"].endswith((".md", ".json", ".yml", ".yaml", ".py", ".gitignore")) or operation["path"] == ".gitignore"
        raw_diff = plan_diff(repo, operation) if is_text else "binary-or-omitted"
        preview = raw_diff
        truncated = False
        if is_text and remaining is not None:
            allowed = max(0, min(per_file or len(raw_diff), remaining))
            if len(raw_diff) > allowed:
                preview = raw_diff[:allowed] + "\n... diff truncated; rerun with --full-diff for complete output ...\n"
                truncated = True
            remaining -= min(len(raw_diff), allowed)
        rendered_operations.append({
            "path": operation["path"],
            "action": operation["action"],
            "pre_hash": operation.get("pre_hash"),
            "post_hash": operation.get("post_hash"),
            "diff": preview,
            "diff_truncated": truncated,
        })
    return {
        "run_id": plan["run_id"],
        "mode": plan.get("mode"),
        "operation_count": len(plan.get("operations", [])),
        "shown_operation_count": len(rendered_operations),
        "diff_mode": "full" if full_diff else "bounded-preview",
        "operations": rendered_operations,
        "warnings": plan.get("warnings", []),
        "effective_configuration": plan.get("effective_configuration"),
    }


def managed_block_report(repo: Path) -> dict[str, Any]:
    """Check the generated role-aware managed blocks against the current configuration."""
    if not (repo / CONFIG_PATH).is_file() or not (repo / WORKFLOW_PATH).is_file():
        return {"check": "managed-blocks", "status": "NOT_APPLICABLE", "details": []}
    try:
        config = load_json(repo / CONFIG_PATH)
        workflow = load_json(repo / WORKFLOW_PATH)
    except DevflowError as exc:
        return {"check": "managed-blocks", "status": "BLOCKED", "details": [str(exc)]}
    expected_blocks = {
        "CLAUDE.md": render_client_role_block(config, workflow, "claude", "Claude roles in this project"),
    }
    try:
        kit_agents = find_project_kit(repo) / "managed" / "AGENTS.block.md"
    except DevflowError:
        kit_agents = None
    if kit_agents is not None and kit_agents.is_file():
        expected_blocks["AGENTS.md"] = kit_agents.read_text(encoding="utf-8")
    details: list[dict[str, Any]] = []
    status = "PASS"
    for relative, expected in sorted(expected_blocks.items()):
        path = repo / relative
        if not path.is_file():
            details.append({"path": relative, "state": "missing"})
            status = "BLOCKED"
            continue
        current = extract_managed_block(path.read_text(encoding="utf-8", errors="replace"))
        if current is None:
            details.append({"path": relative, "state": "markers-missing-or-duplicated"})
            status = "BLOCKED"
            continue
        if current != expected.strip() + "\n":
            details.append({"path": relative, "state": "stale"})
            if status != "BLOCKED":
                status = "PARTIAL"
    return {
        "check": "managed-blocks",
        "status": status,
        "details": details,
        "recommendation": (
            "Regenerate the managed instructions with `devflow upgrade` so they match the configured roles."
            if details else "Managed instructions match the configured roles."
        ),
    }


def audit_project(repo: Path, area: str, deep: bool = False) -> dict[str, Any]:
    inspection = inspect_repository(repo, deep=deep)
    if area == "git":
        # The inspection can only observe the local worktree, so the remote state comes
        # from what was recorded after an actual API check.  Reading it from the
        # inspection alone left this audit permanently PARTIAL.
        recorded = "unverified"
        if (repo / CONFIG_PATH).is_file():
            github = load_json(repo / CONFIG_PATH).get("github", {})
            if isinstance(github, dict) and isinstance(github.get("remote_settings"), str):
                recorded = github["remote_settings"]
        local = dict(inspection["git"])
        local["github_remote_settings"] = recorded
        gaps = []
        if not local.get("is_repository"):
            gaps.append("Local Git repository is not initialized")
        if not local.get("remotes"):
            gaps.append("Git remote is not configured or not observable")
        if recorded != "verified":
            gaps.append("Remote GitHub rulesets, required checks, and merge policy are unverified")
        status = "BLOCKED" if not local.get("is_repository") else ("PARTIAL" if gaps else "PASS")
        return {"area": area, "status": status, "local": local, "remote": inspection["remote"], "gaps": gaps}
    if area == "code":
        return {"area": area, "status": "PASS", "project": inspection["project"], "note": "Semantic code quality requires an agent review and project commands; this deterministic audit reports structure only."}
    if area == "quality":
        config = load_json(repo / CONFIG_PATH) if (repo / CONFIG_PATH).exists() else {}
        baseline = config.get("quality", {}).get("baseline_status", "unconfigured")
        gaps = []
        if baseline != "measured":
            gaps.append("baseline not measured")
        if not inspection["quality"]["ci_workflows"]:
            gaps.append("CI workflow not detected")
        if inspection["quality"]["test_files"] == 0:
            gaps.append("test files not detected; legacy characterization may be required")
        return {"area": area, "status": "PARTIAL" if gaps else "PASS", "evidence": inspection["quality"], "gaps": gaps}
    if area == "ci":
        gaps = [] if inspection["quality"]["ci_workflows"] else ["No GitHub Actions workflow detected"]
        remote_state = "unverified"
        if (repo / CONFIG_PATH).is_file():
            remote_state = load_json(repo / CONFIG_PATH).get("github", {}).get("remote_settings", "unverified")
        if remote_state != "verified":
            gaps.append("Remote required checks and merge protection are unverified")
        return {
            "area": area,
            "status": "PARTIAL" if gaps else "PASS",
            "workflows": inspection["quality"]["ci_workflows"],
            "remote_required_checks": remote_state,
            "gaps": gaps,
        }
    if area == "docs":
        docs = inspection["documentation"]
        gaps = [name for name in ["readme", "architecture"] if not docs.get(name)]
        return {"area": area, "status": "PARTIAL" if gaps else "PASS", "evidence": docs, "gaps": gaps, "rule": "Update canonical architecture docs in the same PR as architecture changes."}
    if area == "security":
        findings = inspection["security"]
        gaps = []
        if findings["large_files"]:
            gaps.append("Large files require review")
        if deep and findings.get("history_scan") != "complete":
            gaps.append("Git history secret scan was not executed; dedicated approved tooling is required")
        status = "BLOCKED" if findings["suspected_secret_paths"] else ("PARTIAL" if gaps else "PASS")
        return {
            "area": area,
            "status": status,
            "findings": findings,
            "gaps": gaps,
            "note": "Secret values are never printed. Deep history scanning requires dedicated approved tooling.",
        }
    if area == "skills":
        return {"area": area, **skills_audit(repo, deep=deep)}
    if area == "all":
        areas = ["git", "code", "quality", "ci", "docs", "security", "skills"]
        results = []
        for item in areas:
            try:
                results.append(audit_project(repo, item, deep=deep))
            except DevflowError as exc:
                results.append({"area": item, "status": "BLOCKED", "error": str(exc)})
        status = "BLOCKED" if any(item["status"] == "BLOCKED" for item in results) else ("PARTIAL" if any(item["status"] == "PARTIAL" for item in results) else "PASS")
        return {"area": area, "status": status, "results": results}
    raise DevflowError(f"Неизвестная область аудита: {area}")


def doctor(repo: Path, deep: bool = False, refresh_skills: bool = False, repair_plan: bool = False) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    if not (repo / CONFIG_PATH).exists():
        inspection = inspect_repository(repo)
        mode = inspection["project"]["recommended_mode"]
        next_command, next_argv = expand_devflow_command(repo, f"devflow {mode}")
        return {
            "status": "BLOCKED",
            "diagnosis": ["VibeCode Control is not installed in this project"],
            "evidence": inspection,
            "recommendation": f"Review the proposed graph and skill matrix, then run the {mode} dry-run. Apply only after explicit approval.",
            "next_command": next_command,
            "next_argv": next_argv,
        }
    config, workflow, lock = load_project_state(repo)
    config_errors, config_warnings = validate_config(config)
    workflow_errors, workflow_warnings = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    findings.append({"check": "config", "status": "BLOCKED" if config_errors else ("PARTIAL" if config_warnings else "PASS"), "errors": config_errors, "warnings": config_warnings})
    findings.append({"check": "graph", "status": "BLOCKED" if workflow_errors else ("PARTIAL" if workflow_warnings else "PASS"), "errors": workflow_errors, "warnings": workflow_warnings})
    findings.append({"check": "skills-lock", "status": "BLOCKED" if lock_errors else "PASS", "errors": lock_errors, "warnings": []})
    skill_report = skills_audit(repo, deep=deep)
    findings.append({"check": "skills", **skill_report})
    if config_errors or workflow_errors or lock_errors:
        setup = [stage_result(
            "graph", "BLOCKED", [], config_errors + workflow_errors + lock_errors,
            "Prepare an explicit reviewed migration for the invalid guarded file; automatic repair is intentionally blocked.",
            "graph", None, True,
        )]
    else:
        setup = evaluate_setup(repo)
    findings.append({"check": "setup", "status": "BLOCKED" if any(item["status"] == "BLOCKED" for item in setup) else ("PARTIAL" if any(item["status"] == "PARTIAL" for item in setup) else "PASS"), "stages": setup})
    security = audit_project(repo, "security", deep=deep)
    findings.append({"check": "security", **{key: value for key, value in security.items() if key != "area"}})
    toolkit = repo / META_DIR / "toolkit"
    configured_version = config.get("devflow_version") if isinstance(config, dict) else None
    findings.append({"check": "project-cli", "status": "PASS" if (repo / META_DIR / "devflow.py").is_file() and toolkit.is_dir() else "BLOCKED", "version": configured_version, "running_version": VERSION})
    findings.append(managed_block_report(repo))

    due = []
    today = utc_now().date()
    for skill in lock.get("skills", []) if isinstance(lock, dict) and isinstance(lock.get("skills", []), list) else []:
        if not isinstance(skill, dict):
            continue
        raw = skill.get("review_after")
        try:
            if raw and dt.date.fromisoformat(raw) <= today:
                due.append(skill.get("name"))
        except (TypeError, ValueError):
            due.append(skill.get("name"))
    raw_decisions = lock.get("node_decisions", {}) if isinstance(lock, dict) else {}
    raw_decisions = raw_decisions if isinstance(raw_decisions, dict) else {}
    revalidation = [
        node for node, decision in raw_decisions.items()
        if isinstance(decision, dict) and decision.get("revalidation_required")
    ]
    if due or revalidation:
        findings.append({"check": "skill-review-schedule", "status": "PARTIAL", "due_skills": due, "nodes_requiring_revalidation": revalidation})
    else:
        findings.append({"check": "skill-review-schedule", "status": "PASS", "due_skills": [], "nodes_requiring_revalidation": []})

    overall = "BLOCKED" if any(item.get("status") == "BLOCKED" for item in findings) else ("PARTIAL" if any(item.get("status") == "PARTIAL" for item in findings) else "PASS")
    response: dict[str, Any] = {
        "status": overall,
        "mode": "deep" if deep else "fast-offline",
        "diagnosis": findings,
        "next": next_setup_step(setup, repo),
        "repair_policy": "No project changes are made by doctor. Build and review a repair plan, then apply it explicitly.",
        "usage": "нет доступной телеметрии",
    }
    if refresh_skills:
        if config_errors or workflow_errors or lock_errors:
            response["skill_discovery"] = {
                "status": "BLOCKED",
                "reason": "Skill discovery is disabled until the guarded control plane is valid.",
            }
        else:
            response["skill_discovery"] = skills_search_request(repo, None)
    if repair_plan:
        if config_errors or workflow_errors or lock_errors:
            response["repair_plan"] = {
                "status": "BLOCKED",
                "reason": "Invalid guarded state requires an explicit migration; VibeCode Control will not overwrite it automatically.",
            }
        else:
            response["repair_plan"] = summarize_plan(repo, build_setup_plan(repo, "repair", "repair"))
    return response


GUARDED_EXECUTION_PATHS = (
    f"{META_DIR}/",
    "AGENTS.md",
    "CLAUDE.md",
    ".github/workflows/",
    ".github/devflow/prompts/",
    ".agents/skills/devflow-node/",
    ".claude/skills/devflow-node/",
)


def guarded_control_plane_changes(repo: Path) -> dict[str, Any]:
    """Report whether the current branch rewrites the control plane that governs it.

    A PR that edits its own verifier must be reviewed against the version that actually
    executed, so this is surfaced as evidence rather than guessed at.
    """
    candidates: list[str] = []
    code, symbolic, _ = run_process(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo)
    if code == 0 and symbolic.strip():
        candidates.append(symbolic.strip().removeprefix("refs/remotes/"))
    candidates += ["origin/main", "origin/master", "main", "master"]
    for candidate in candidates:
        code, merge_base, _ = run_process(["git", "merge-base", candidate, "HEAD"], repo)
        if code != 0 or not merge_base.strip():
            continue
        code, names, _ = run_process(["git", "diff", "--name-only", merge_base.strip(), "HEAD"], repo)
        if code != 0:
            continue
        changed = [line.strip() for line in names.splitlines() if line.strip()]
        guarded = sorted({path for path in changed if path.startswith(GUARDED_EXECUTION_PATHS)})
        return {
            "base": candidate,
            "merge_base": merge_base.strip(),
            "guarded_paths": guarded,
            "self_modifying": bool(guarded),
        }
    return {
        "base": None,
        "merge_base": None,
        "guarded_paths": [],
        "self_modifying": None,
        "note": "Базовая версия не определена локально; сравнение base/head выполняется на стороне адаптера GitHub",
    }


def operate_preflight(repo: Path, node_id: str, issue: str = "") -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    config_errors, config_warnings = validate_config(config)
    workflow_errors, workflow_warnings = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    if config_errors or workflow_errors or lock_errors:
        return {
            "status": "BLOCKED",
            "node": {"id": node_id},
            "config": {"errors": config_errors, "warnings": config_warnings},
            "workflow": {"errors": workflow_errors, "warnings": workflow_warnings},
            "skills": {
                "status": "BLOCKED",
                "errors": ["Config/graph/lock validation failed before skill preflight", *lock_errors],
                "warnings": [],
                "details": [],
            },
            "external_gaps": [],
            "instruction": "Repair the invalid guarded control-plane file through an explicit reviewed migration before execution.",
        }
    nodes = {item.get("id"): item for item in workflow.get("nodes", []) if isinstance(item, dict)}
    if node_id not in nodes:
        raise DevflowError(f"Неизвестный узел: {node_id}")
    skill_report = skills_audit(repo, node_id)
    external_gaps: list[str] = []
    external_blockers: list[str] = []
    effective = effective_node(nodes[node_id], config, lock)
    # A node whose executor or execution parameters are still undecided cannot run: the
    # template supplied no choice and nobody has made one.
    resolution = effective.get("resolution", {})
    if resolution.get("agent", {}).get("value") in {None, AGENT_UNRESOLVED}:
        external_blockers.append(
            f"Исполнитель узла {node_id} не выбран: задайте `devflow role set {nodes[node_id].get('role')} <agent>`"
        )
    for field in TYPED_PROFILE_FIELDS:
        if resolution.get(field, {}).get("mode") == MODE_UNDECIDED:
            pointer = resolution[field].get("source", {}).get("pointer") or f"roles.{nodes[node_id].get('role')}.{field}"
            external_blockers.append(
                f"Параметр {pointer} не выбран (mode={MODE_UNDECIDED}); "
                "объявите значение, наследование или явное отсутствие"
            )
    # Preventive layer: an exhausted cycle must not start another traversal at all.
    budget = None
    if declared_cycle_for_node(workflow, node_id) is not None:
        if normalize_issue_key(issue):
            budget = cycle_budget(repo, workflow, node_id, issue)
            if budget["exhausted"]:
                external_blockers.append(
                    f"Бюджет цикла {budget['cycle']} исчерпан для Issue {issue}: "
                    f"пройдено {budget['traversals']} из {budget['max_traversals']}. "
                    "Требуется стоп-чек PM из шести пунктов Stall control; продолжение записей — только "
                    "с --human-decision <ref>. Бюджет считается по локальной истории этого checkout."
                )
        else:
            external_gaps.append(
                f"Узел {node_id} входит в цикл, но бюджет не вычислен: передайте --issue <ref>"
            )
    if effective.get("agent") not in {"human", "script", "deterministic"}:
        automation = config.get("automation", {}) if isinstance(config.get("automation", {}), dict) else {}
        if automation.get("background_workers") != "verified":
            external_gaps.append("Background executor availability is unverified")
    stage = nodes[node_id].get("stage")
    if stage in {"review", "release"}:
        github = config.get("github", {}) if isinstance(config.get("github", {}), dict) else {}
        if github.get("remote_settings") != "verified":
            external_blockers.append("GitHub remote settings and adapter access are unverified for review/release")
        if not isinstance(github.get("required_checks"), list) or not github.get("required_checks"):
            external_blockers.append("No remotely verified required-check set is configured")
        if stage == "release" and github.get("ruleset_verified") is not True:
            external_blockers.append("A remote merge ruleset has not been verified")
    if skill_report["status"] == "BLOCKED" or external_blockers:
        status = "BLOCKED"
    elif config_warnings or workflow_warnings or skill_report["status"] == "PARTIAL" or external_gaps:
        status = "PARTIAL"
    else:
        status = "PASS"
    return {
        "status": status,
        "node": effective,
        "effective_configuration": effective_configuration(workflow, config, lock),
        "cycle_budget": budget,
        "self_modification": guarded_control_plane_changes(repo),
        "required_artifacts": evidence_contract_for(nodes[node_id]),
        "config": {"errors": config_errors, "warnings": config_warnings},
        "workflow": {"errors": workflow_errors, "warnings": workflow_warnings},
        "skills": skill_report,
        "external_gaps": external_gaps + external_blockers,
        "instruction": "Load devflow-node and every assigned required skill explicitly, stay inside node permissions, enforce declared cycle budgets, and record fresh evidence bound to the actual head SHA.",
    }


def scheme_check(repo: Path, refresh_skills: bool = True) -> dict[str, Any]:
    diagnosis = doctor(repo, deep=True, refresh_skills=False, repair_plan=False)
    if not (repo / CONFIG_PATH).is_file():
        return diagnosis
    config, workflow, lock = load_project_state(repo)
    config_errors, _ = validate_config(config)
    workflow_errors, _ = validate_workflow(workflow, config)
    lock_errors = validate_skills_lock(lock)
    if config_errors or workflow_errors or lock_errors:
        return {
            "status": "BLOCKED",
            "diagnosis": diagnosis,
            "skill_outcomes": [],
            "discovery": None,
            "rule": "Repair invalid config/graph before skill comparison.",
            "usage": "нет доступной телеметрии",
        }
    initialize_skill_decisions(lock, workflow)
    runs = show_node_run(repo, None)
    runs = sorted(runs, key=lambda item: item.get("recorded_at", ""), reverse=True)
    by_node: dict[str, list[dict[str, Any]]] = {}
    for item in runs:
        by_node.setdefault(item.get("node", "unknown"), []).append(item)
    today = utc_now().date()
    due_skills = set()
    for skill in lock.get("skills", []):
        try:
            if skill.get("review_after") and dt.date.fromisoformat(skill["review_after"]) <= today:
                due_skills.add(skill.get("name"))
        except (TypeError, ValueError):
            due_skills.add(skill.get("name"))
    decisions = []
    problem_nodes = []
    for node in workflow.get("nodes", []):
        node_id = node["id"]
        decision = lock["node_decisions"].get(node_id, {"status": "unresolved", "assigned": []})
        recent = by_node.get(node_id, [])[:3]
        repeated_failure = len(recent) >= 2 and all(
            item.get("status") in {"FAIL", "BLOCKED", "PARTIAL"} for item in recent[:2]
        )
        assigned_names = [
            item.get("name") if isinstance(item, dict) else str(item)
            for item in decision.get("assigned", [])
        ]
        due = bool(due_skills.intersection(assigned_names))
        if decision.get("status") == "unresolved" or decision.get("revalidation_required") or repeated_failure or due:
            outcome = "NEEDS_EVAL"
            problem_nodes.append(node_id)
        elif decision.get("status") == "zero-skill":
            outcome = "ZERO_SKILL"
        elif decision.get("status") == "assigned":
            outcome = "KEEP"
        else:
            outcome = "NEEDS_EVAL"
            problem_nodes.append(node_id)
        decisions.append({
            "node": node_id,
            "outcome": outcome,
            "assigned": assigned_names,
            "revalidation_required": bool(decision.get("revalidation_required")),
            "review_due": due,
            "repeated_recent_failure": repeated_failure,
            "recent_runs": [
                {"run_id": item.get("run_id"), "status": item.get("status"), "head_sha": item.get("head_sha")}
                for item in recent
            ],
            "evidence": (
                sorted({str(item.get("verification_level") or "reported-run-record") for item in recent})
                if recent else "эмпирически не проверено"
            ),
        })
    discovery = None
    if refresh_skills and problem_nodes:
        requests = [skills_search_request(repo, node_id) for node_id in problem_nodes]
        discovery = {
            "status": "ONLINE_SEARCH_REQUIRED",
            "problem_nodes": problem_nodes,
            "allowed_sources": lock.get("allowed_sources", {}),
            "queries": sorted({query for request in requests for query in request.get("queries", [])}),
            "shortlist_limit_per_node": 3,
            "comparison": "zero-skill vs pinned incumbent vs challengers under identical execution profile",
        }
    return {
        "status": diagnosis["status"],
        "diagnosis": diagnosis,
        "recent_run_count": len(runs),
        "skill_outcomes": decisions,
        "allowed_outcomes": ["KEEP", "UPDATE", "REPLACE", "REMOVE", "ZERO_SKILL", "NEEDS_EVAL"],
        "discovery": discovery,
        "repair_plan": summarize_plan(repo, build_setup_plan(repo, "repair", "scheme-repair")),
        "rule": "UPDATE, REPLACE, REMOVE, or a new skill requires evidence and explicit user approval; this check never applies it.",
        "usage": "нет доступной телеметрии",
    }


def normalize_issue_key(issue: Any) -> str:
    """Group run records by the Issue they belong to, however the reference was spelled.

    `#21`, `21` and a GitHub issue URL are the same Issue.  The normalized key is stored
    beside the raw reference so the grouping stays auditable.  A collision such as
    `ISSUE-1` with `PR-1` only tightens the budget, which is the safe direction.
    """
    if not isinstance(issue, str):
        return ""
    text = issue.strip()
    if not text:
        return ""
    url = re.search(r"github\.com/[^/\s]+/[^/\s]+/issues/(\d+)", text, re.I)
    if url:
        return url.group(1)
    numbers = re.findall(r"\d+", text)
    if numbers:
        return numbers[-1]
    return text.lower()


def declared_cycle_for_node(workflow: Any, node_id: str) -> dict[str, Any] | None:
    for cycle in workflow.get("allowed_cycles", []) if isinstance(workflow, dict) else []:
        if isinstance(cycle, dict) and node_id in (cycle.get("nodes") or []):
            return cycle
    return None


def iter_run_records(repo: Path) -> list[dict[str, Any]]:
    """Read every stored run record.  Counting must not use the capped recent view."""
    directory = repo / f"{LOCAL_DIR}/node-runs"
    if not directory.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            value = load_json(path)
        except DevflowError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def cycle_budget(repo: Path, workflow: Any, node_id: str, issue: str) -> dict[str, Any] | None:
    """Report how much of a declared cycle's budget this Issue has already spent.

    A traversal is a re-entry, not a visit: nodes on the main path are recorded once
    before any correction happens, so the first record of each node is free.
    """
    cycle = declared_cycle_for_node(workflow, node_id)
    if cycle is None:
        return None
    issue_key = normalize_issue_key(issue)
    nodes = [str(item) for item in (cycle.get("nodes") or [])]
    counts = {name: 0 for name in nodes}
    for record in iter_run_records(repo):
        if record.get("status") not in COUNTED_RUN_STATUSES:
            continue
        name = record.get("node")
        if name not in counts:
            continue
        recorded_key = record.get("issue_key") or normalize_issue_key(record.get("issue"))
        if issue_key and recorded_key != issue_key:
            continue
        counts[name] += 1
    max_traversals = cycle.get("max_traversals")
    max_traversals = max_traversals if isinstance(max_traversals, int) and max_traversals > 0 else 1
    traversals = max((max(0, value - 1) for value in counts.values()), default=0)
    return {
        "cycle": cycle.get("id"),
        "nodes": nodes,
        "issue": issue,
        "issue_key": issue_key,
        "counts": counts,
        "max_traversals": max_traversals,
        "traversals": traversals,
        "remaining": max(0, max_traversals - traversals),
        "exhausted": traversals >= max_traversals,
        "on_exhausted": cycle.get("on_exhausted"),
        "scope": "локальная история этого checkout",
    }


def parse_check_results(items: list[str] | None) -> dict[str, str]:
    """Parse `--check name=conclusion` pairs.  A job status alone proves nothing."""
    results: dict[str, str] = {}
    for item in items or []:
        if not isinstance(item, str) or "=" not in item:
            raise DevflowError("Проверка записывается как name=conclusion")
        name, conclusion = (part.strip() for part in item.split("=", 1))
        if not name or not conclusion:
            raise DevflowError("Проверка записывается как name=conclusion")
        if conclusion not in CHECK_CONCLUSIONS:
            raise DevflowError(
                f"Неизвестный conclusion {conclusion} для проверки {name}; допустимы: "
                + ", ".join(sorted(CHECK_CONCLUSIONS))
            )
        if name in results:
            raise DevflowError(f"Повторная проверка {name}")
        results[name] = conclusion
    return results


def evidence_contract_for(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    contract = node.get("evidence_contract")
    return contract if isinstance(contract, dict) else {}


def record_run(repo: Path, node: str, status: str, head_sha: str, issue: str, pr: str,
               evidence: list[str], actual_agent: str | None, actual_model: str | None,
               actual_effort: str | None, checks: list[str] | None = None,
               human_decision: str | None = None) -> dict[str, Any]:
    config, workflow, lock = load_project_state(repo)
    nodes = {item["id"]: item for item in workflow["nodes"]}
    if node not in nodes:
        raise DevflowError(f"Неизвестный узел: {node}")
    effective = effective_node(nodes[node], config, lock)
    allowed_statuses = {"PASS", "PARTIAL", "BLOCKED", "HUMAN_NEEDED", "FAIL"}
    if status not in allowed_statuses:
        raise DevflowError("Некорректный статус run record")
    if not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
        raise DevflowError("Run record требует хотя бы одно непустое доказательство")
    check_results = parse_check_results(checks)
    # A record of a node inside a declared cycle has to be attributable to an Issue, or
    # the budget can be spent through unattributed records.
    budget = declared_cycle_for_node(workflow, node)
    issue_key = normalize_issue_key(issue)
    if budget is not None and not issue_key:
        raise DevflowError(
            f"Узел {node} входит в объявленный цикл {budget.get('id')}: запись требует --issue, "
            "иначе бюджет цикла не к чему привязать"
        )
    decision = human_decision.strip() if isinstance(human_decision, str) else ""
    spent = cycle_budget(repo, workflow, node, issue) if budget is not None else None
    if spent is not None and status in COUNTED_RUN_STATUSES:
        # Per-node cap, not a global one: the tail of the last legal traversal must still
        # be recordable after the traversal count has already reached its maximum.
        if spent["counts"].get(node, 0) >= spent["max_traversals"] + 1 and not decision:
            raise DevflowError(
                f"Бюджет цикла {spent['cycle']} исчерпан для Issue {issue}: узел {node} уже записан "
                f"{spent['counts'][node]} раз при max_traversals={spent['max_traversals']}. "
                "Требуется стоп-чек PM из шести пунктов Stall control; продолжение записей — только с "
                "--human-decision <ref>. Бюджет считается по локальной истории этого checkout."
            )
    stage = nodes[node].get("stage")
    evidence_by_name: dict[str, str] = {}
    if status == "PASS" and stage in {"implementation", "verification", "review", "release"}:
        if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            raise DevflowError("PASS для delivery-узла требует полный 40-символьный head SHA")
        code, actual_head, _ = run_process(["git", "rev-parse", "HEAD"], repo)
        if code != 0 or actual_head != head_sha:
            raise DevflowError("PASS требует head SHA, совпадающий с фактическим локальным Git HEAD")
        code, worktree_status, _ = run_process(["git", "status", "--porcelain=v1", "--untracked-files=all"], repo)
        if code != 0 or worktree_status:
            raise DevflowError("PASS требует чистый Git worktree, соответствующий указанному HEAD")
        if not issue or not pr:
            raise DevflowError("PASS для delivery-узла требует Issue и PR reference")
        if not actual_agent:
            raise DevflowError("PASS требует фактически наблюдённого agent")
        for item in evidence:
            if "=" not in item:
                raise DevflowError("PASS требует именованные доказательства в формате expected_evidence=artifact")
            name, reference = (part.strip() for part in item.split("=", 1))
            if not name or not reference or name in evidence_by_name:
                raise DevflowError("PASS содержит пустое или повторяющееся именованное доказательство")
            evidence_by_name[name] = reference
        expected_names = set(nodes[node].get("expected_evidence", []))
        missing = sorted(expected_names - set(evidence_by_name))
        if missing:
            raise DevflowError("PASS не содержит обязательные доказательства: " + ", ".join(missing))
        # A green job is not a passed check: every contracted review artifact must be
        # present and must name its kind, and every required check must actually be
        # concluded `success`.
        contract = evidence_contract_for(nodes[node])
        if stage == "review" and not any(
            isinstance(requirement, dict) and requirement.get("required", True)
            for requirement in contract.values()
        ):
            raise DevflowError(
                f"PASS запрещён: review-узел {node} не объявляет обязательный артефакт, "
                "поэтому успешный запуск ничем не подтверждён; выполните `devflow graph --migrate --apply`"
            )
        for name, requirement in sorted(contract.items()):
            if not isinstance(requirement, dict):
                raise DevflowError(f"Контракт артефакта {name} повреждён")
            if not requirement.get("required", True):
                continue
            kind = requirement.get("kind")
            reference = evidence_by_name.get(name, "")
            if not reference:
                raise DevflowError(
                    f"PASS запрещён: успешный запуск без обязательного артефакта {name} ({kind}) не является пройденной проверкой"
                )
            if not reference.startswith(f"{kind}:") or not reference[len(str(kind)) + 1:].strip():
                raise DevflowError(
                    f"Артефакт {name} должен быть записан как {kind}:<ссылка>, чтобы его вид был доказан"
                )
        # Checks are gated only where green is the expected outcome.  On an implementation
        # stage a failing check can be the point of the node: `tdd_red` must prove a test
        # that fails, so its conclusions are recorded as evidence and not judged here.
        if stage in CHECK_GATED_STAGES:
            for name, conclusion in sorted(check_results.items()):
                if conclusion not in PROVEN_CHECK_CONCLUSIONS:
                    raise DevflowError(
                        f"PASS запрещён: проверка {name} завершилась как {conclusion}; "
                        "зелёный skipped или neutral не считается выполненной проверкой"
                    )
            required_checks = config.get("github", {}).get("required_checks", []) if isinstance(config.get("github"), dict) else []
            if isinstance(required_checks, list) and required_checks:
                unproven = sorted(str(name) for name in required_checks if check_results.get(str(name)) not in PROVEN_CHECK_CONCLUSIONS)
                if unproven:
                    raise DevflowError(
                        "PASS требует conclusion=success для каждой обязательной проверки: " + ", ".join(unproven)
                    )
        if node == "post_merge" or nodes[node].get("state") == "POST_MERGE_VERIFY":
            # A closed PR has no refs/pull/<N>/merge; a control dispatch against it
            # fabricates a result instead of proving one.  This is a post-merge rule only:
            # before the merge the same ref is the canonical merge-gate reference.
            for name, reference in sorted(evidence_by_name.items()):
                if re.search(r"refs/pull/\d+/merge", reference):
                    raise DevflowError(
                        f"Доказательство {name} ссылается на refs/pull/<N>/merge; "
                        "post-merge проверка не запускается на закрытом PR"
                    )
        preflight = operate_preflight(repo, node, issue)
        if preflight["status"] != "PASS":
            reasons = (
                preflight.get("external_gaps", [])
                + preflight.get("skills", {}).get("errors", [])
                + preflight.get("skills", {}).get("warnings", [])
                + preflight.get("config", {}).get("errors", [])
                + preflight.get("config", {}).get("warnings", [])
                + preflight.get("workflow", {}).get("errors", [])
                + preflight.get("workflow", {}).get("warnings", [])
            )
            raise DevflowError(
                f"PASS запрещён: operate preflight вернул {preflight['status']}: "
                + ("; ".join(str(item) for item in reasons) or "причина не сообщена адаптером preflight")
            )
        resolution = effective.get("resolution", {})
        observed = {"agent": actual_agent, "model": actual_model, "effort": actual_effort}
        for field in ("agent", "model", "effort"):
            entry = resolution.get(field, {"mode": MODE_UNSET})
            mode = entry.get("mode")
            actual_value = observed[field]
            if mode == MODE_NOT_APPLICABLE:
                if actual_value:
                    raise DevflowError(
                        f"Для роли {effective['role']} параметр {field} неприменим; "
                        "фиктивное исполняемое значение записывать нельзя"
                    )
            elif mode == MODE_EXPLICIT:
                if actual_value != entry.get("value"):
                    raise DevflowError(
                        f"Фактический {field} не совпадает с явной конфигурацией; silent fallback запрещён"
                    )
            elif mode == MODE_INHERITED:
                if not actual_value:
                    raise DevflowError(
                        f"Параметр {field} наследуется: PASS требует зафиксировать фактически использованное значение"
                    )
            elif mode == MODE_UNDECIDED:
                raise DevflowError(
                    f"Параметр {field} ещё не выбран (mode={MODE_UNDECIDED}): "
                    "нельзя записать PASS для узла, исполнение которого никто не решал"
                )
            elif not actual_value:
                raise DevflowError(
                    f"Параметр {field} намеренно не задан (mode={MODE_UNSET}): "
                    "PASS требует записать фактически использованное значение, но оно не подставляется в конфигурацию"
                )
    identifier = run_id(node)
    record = {
        "schema_version": 1,
        "run_id": identifier,
        "recorded_at": iso_now(),
        "node": node,
        "state": nodes[node]["state"],
        "status": status,
        "issue": issue,
        "issue_key": issue_key,
        "pr": pr,
        "head_sha": head_sha,
        "human_decision": decision or None,
        # The budget as observed before this record was added.
        "cycle_budget": spent,
        "configured": {
            "role": effective["role"],
            "agent": effective["agent"],
            "model": effective["model"],
            "effort": effective["effort"],
            "skills": effective["skills"],
            "modes": {
                field: effective.get("resolution", {}).get(field, {}).get("mode")
                for field in PROFILE_FIELDS
            },
            "sources": {
                field: effective.get("resolution", {}).get(field, {}).get("source", {}).get("pointer")
                for field in PROFILE_FIELDS
            },
        },
        "actual": {"agent": actual_agent, "model": actual_model, "effort": actual_effort},
        "evidence": evidence,
        "evidence_by_name": evidence_by_name,
        "checks": check_results,
        "verification_level": (
            "local-head-and-preflight-verified; artifact references recorded, remote artifacts remain enforced by their adapters"
            if status == "PASS" and stage in {"implementation", "verification", "review", "release"}
            else "reported-run-record"
        ),
        "usage": "нет доступной телеметрии",
    }
    path = ensure_within(repo, f"{LOCAL_DIR}/node-runs/{safe_run_identifier(identifier)}.json")
    atomic_write(path, json_bytes(record))
    return {"status": "PASS", "run_id": identifier, "path": str(path)}


HELP_TOPICS = {
    "overview": """
VibeCode Control настраивает и проверяет управляемую AI-разработку в отдельном репозитории.

Начните с `devflow inspect`. Для пустого проекта используйте `devflow init`, для существующего — `devflow adopt`. Обе команды сначала показывают dry-run; запись выполняется только с `--apply`.

После установки выполняйте `devflow setup next`: команда покажет первый незавершённый этап, доказательства, пробел, рекомендацию и точную следующую команду. `devflow doctor` выполняет быструю офлайн-проверку всей схемы. `devflow scheme check` запускает полную проверку и формирует ограниченное задание поиска альтернативных скиллов.
""",
    "modes": """
Режимы:
- `install` — установка самого скилла пользователю Codex и/или Claude; тема справки `install`.
- `inspect` — только чтение; стек, Git, документы, CI, тесты, скиллы и риски.
- `init` — установка VibeCode Control в новый репозиторий.
- `adopt` — безопасное подключение существующего проекта без массового переписывания.
- `operate --node <id>` — preflight конкретного фонового узла.
- `upgrade` — dry-run обновления управляемых файлов и project CLI.
- `doctor` — диагностика без изменений.
- `scheme check` — глубокая переоценка схемы и скиллов по разрешённым источникам.

Статусы: PASS — подтверждено; PARTIAL — есть пробел или непроверенный внешний слой; BLOCKED — продолжать нельзя; NOT_APPLICABLE — этап обоснованно не нужен.
""",
    "setup": """
Этапы настройки: инспекция → контекст продукта → роли/модели → граф → документация → Git/GitHub → качество → скиллы → автоматизация → пилот.

Команды:
- `devflow setup check`
- `devflow setup check --stage skills`
- `devflow setup next`
- `devflow setup mark pilot PASS --evidence <Issue/PR reference>`

Setup-этапы не равны этапам продукта. Подсказка следующего этапа не утверждает scope, бюджет, архитектурный компромисс или приоритет вместо PM.
""",
    "configuration": """
Настройка следующих запусков:
- `devflow config effective` — матрица «узел → этап → владелец → agent → model → effort» с режимом и источником каждой ячейки
- `devflow config show --effective`
- `devflow config normalize` затем `--apply` — миграция нетипизированных model/effort установленного проекта
- `devflow role set implementer claude-code`
- `devflow model set reviewer inherit --effort unset`
- `devflow permissions set merge merge-verified-sha`
- `devflow config set quality.baseline_status measured`

Каждый параметр model и effort имеет режим:
- `explicit` — значение выбрано явно и записано;
- `inherited` — значение определяет клиент во время запуска; его нужно наблюдать и зафиксировать, а не придумывать;
- `unset` — параметр намеренно отсутствует и никогда не материализуется в конкретное значение;
- `not-applicable` — роль не исполняет модель (например, `human-pm`), фиктивное значение записывать нельзя.

Перед межклиентским переносом посмотрите матрицу; после записи VibeCode Control перечитывает её из фактических файлов и сравнивает ячейка в ячейку. Несовпадение блокирует запись и verify, fallback не подставляется.

Смена значения не переключает уже выполняющуюся модель. Если доступность модели не проверена, VibeCode Control показывает PARTIAL/BLOCKED и не выбирает fallback молча.
""",
    "install": """
Установка скилла пользователю:
- `devflow install` — dry-run для обоих клиентов
- `devflow install --apply` — установить и обновить копии для Codex и Claude
- `devflow install --client claude --apply`
- `devflow install --client codex --apply`

Каталоги: Codex — `~/.agents/skills/vibecode-control`, Claude — `~/.claude/skills/vibecode-control`. Команда пишет только внутрь каталога скиллов выбранного клиента, удаляет устаревшие файлы прежней установки и проверяет контрольную сумму установленной копии против источника. Чужой скилл по этому пути не перезаписывается без `--force`.
""",
    "skills": """
Для каждого узла требуется одно явное решение: назначить проверенный закреплённый скилл, выбрать `zero-skill` с причиной или оставить узел BLOCKED до оценки.

Команды:
- `devflow skills recommend`
- `devflow skills search --node implement`
- `devflow skills register <name> --path <folder> --source <url> --commit <40-char-sha> --license <name> --approved-by-user --apply`
- `devflow skills assign <name> --node implement --level required`
- `devflow skills none --node quality_gates --reason "CI закрывает задачу"`
- `devflow skills audit --deep`
- `devflow skills verify --node implement`
- `devflow skills sync` затем `--apply`
- `devflow skills remove <name>` затем `--apply` после снятия всех назначений

Поиск ограничен skills.sh, openai/skills, anthropics/skills и официальными/явно разрешёнными источниками. Популярность, новизна и аудит площадки не доказывают пользу или безопасность. Обычный фоновый run никогда не обновляет скиллы из сети.
""",
    "safety": """
`init`, `adopt`, `upgrade`, `repair`, `skills register` и `skills sync` сначала показывают план. Сохранённый план применяется только с показанным при сохранении `--expected-sha256`. `--apply` проверяет schema, allowlist путей, content hash и pre-hash каждого файла, пишет атомарно и сохраняет локальный rollback manifest. `devflow rollback <run-id>` останавливается, если файл изменён после apply.

`inspect --output` и `plan --output` могут только создать новый JSON внутри `.agent-flow/.local/reports/` или `.agent-flow/.local/plans/`. Apply возвращает `manifest_sha256`; передайте его как `--expected-manifest-sha256` в verify/rollback. Эти команды заново проверяют mutable manifest, включая repo/run ID, allowlist путей, хэши и payload.

VibeCode Control не меняет удалённые GitHub rulesets, required checks, production или платные настройки без отдельного адаптера и полномочия. Он не печатает значения предполагаемых секретов и не исполняет скрипты непроверенного стороннего скилла во время аудита.
""",
    "windows": r"""
Windows PowerShell:
  py .agent-flow\devflow.py setup next
  py .agent-flow\devflow.py graph --format table
  py .agent-flow\devflow.py doctor

Linux/macOS:
  python3 .agent-flow/devflow.py setup next
  python3 .agent-flow/devflow.py graph --format table
  python3 .agent-flow/devflow.py doctor

Если команда `devflow` не добавлена в PATH, всегда используйте один из вариантов выше.
""",
}


def help_text(topic: str | None, repo: Path | None = None) -> str:
    if not topic:
        body = textwrap.dedent(HELP_TOPICS["overview"]).strip() + "\n\nТемы: " + ", ".join(sorted(HELP_TOPICS))
    elif topic not in HELP_TOPICS:
        raise DevflowError(f"Неизвестная тема справки: {topic}. Доступно: {', '.join(sorted(HELP_TOPICS))}")
    else:
        body = textwrap.dedent(HELP_TOPICS[topic]).strip()
    if repo is None:
        return body
    installed = repo / META_DIR / "devflow.py"
    cli = installed if installed.is_file() else Path(__file__).resolve()
    prefix = shlex.join([sys.executable, str(cli), "--repo", str(repo.resolve())])
    return (
        f"Точный префикс команды для этого репозитория: `{prefix}`. "
        "Записи `devflow …` ниже — только краткое обозначение аргументов после этого префикса.\n\n"
        + body
    )


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def add_register_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name")
    parser.add_argument("--path", required=True, type=Path, help="Local audited skill directory")
    parser.add_argument("--source", required=True, help="Allowlisted canonical source URL")
    parser.add_argument("--commit", required=True, help="Full 40-character Git commit SHA")
    parser.add_argument("--license", required=True, dest="license_name")
    parser.add_argument("--targets", default="claude,codex", help="Comma-separated claude,codex")
    parser.add_argument("--approved-by-user", action="store_true")
    parser.add_argument("--apply", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devflow", description="Управляемая настройка и аудит AI-разработки")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Repository root (default: current directory)")
    parser.add_argument("--version", action="version", version=f"devflow {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    help_parser = sub.add_parser("help", help="Пользовательская справка")
    help_parser.add_argument("topic", nargs="?")

    inspect_parser = sub.add_parser("inspect", help="Read-only project inspection")
    inspect_parser.add_argument("--deep", action="store_true")
    inspect_parser.add_argument("--output", type=str)

    for mode in ["init", "adopt", "upgrade"]:
        mode_parser = sub.add_parser(mode, help=f"Dry-run/apply {mode}")
        mode_parser.add_argument("--apply", action="store_true")
        mode_parser.add_argument("--full-diff", action="store_true")
        mode_parser.add_argument("--diff-path", action="append", default=[])

    plan_parser = sub.add_parser("plan", help="Build a typed change plan")
    plan_parser.add_argument("mode", choices=["init", "adopt", "upgrade", "repair"])
    plan_parser.add_argument("--output", type=str)
    plan_parser.add_argument("--full-diff", action="store_true")
    plan_parser.add_argument("--diff-path", action="append", default=[])

    apply_parser = sub.add_parser("apply", help="Apply a previously saved plan")
    apply_parser.add_argument("--plan", required=True, type=str)
    apply_parser.add_argument("--expected-sha256", required=True, help="SHA-256 printed when the reviewed plan was saved")

    verify_parser = sub.add_parser("verify", help="Verify one apply run")
    verify_parser.add_argument("run_id")
    verify_parser.add_argument("--expected-manifest-sha256", required=True)

    rollback_parser = sub.add_parser("rollback", help="Rollback one unchanged apply run")
    rollback_parser.add_argument("run_id")
    rollback_parser.add_argument("--expected-manifest-sha256", required=True)

    setup = sub.add_parser("setup", help="Setup stage checks and hints")
    setup_sub = setup.add_subparsers(dest="setup_command", required=True)
    setup_check = setup_sub.add_parser("check")
    setup_check.add_argument("--stage")
    setup_sub.add_parser("next")
    setup_mark = setup_sub.add_parser("mark")
    setup_mark.add_argument("stage")
    setup_mark.add_argument("status")
    setup_mark.add_argument("--evidence", action="append", default=[])
    setup_mark.add_argument("--note", default="")

    sub.add_parser("status", help="Show setup status and next step")
    sub.add_parser("next", help="Show only the next setup step")

    graph = sub.add_parser("graph", help="Generate graph from the state machine")
    graph.add_argument("--format", choices=["mermaid", "json", "table"], default="mermaid")
    graph.add_argument("--migrate", action="store_true", help="Add missing review-artifact contracts to an older graph")
    graph.add_argument("--apply", action="store_true", help="Apply the graph migration")
    graph.add_argument("--full-diff", action="store_true")

    config = sub.add_parser("config", help="Project configuration")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_show = config_sub.add_parser("show")
    config_show.add_argument("--effective", action="store_true")
    config_set = config_sub.add_parser("set")
    config_set.add_argument("path")
    config_set.add_argument("value")
    config_effective = config_sub.add_parser("effective", help="Effective configuration matrix with provenance")
    config_effective.add_argument("--format", choices=["table", "json"], default="table")
    config_normalize = config_sub.add_parser("normalize", help="Rewrite untyped model/effort into the typed contract")
    config_normalize.add_argument("--apply", action="store_true")
    config_normalize.add_argument("--full-diff", action="store_true")

    role = sub.add_parser("role", help="Logical role assignment")
    role_sub = role.add_subparsers(dest="role_command", required=True)
    role_set = role_sub.add_parser("set")
    role_set.add_argument("role")
    role_set.add_argument("agent")

    model = sub.add_parser("model", help="Model and effort assignment")
    model_sub = model.add_subparsers(dest="model_command", required=True)
    model_set = model_sub.add_parser("set")
    model_set.add_argument("target", help="Role or node")
    model_set.add_argument("model")
    model_set.add_argument("--effort")

    permissions = sub.add_parser("permissions", help="Permission profile assignment")
    permissions_sub = permissions.add_subparsers(dest="permissions_command", required=True)
    permissions_set = permissions_sub.add_parser("set")
    permissions_set.add_argument("target", help="Role or node")
    permissions_set.add_argument("profile")

    skills = sub.add_parser("skills", help="Skill dependency manager")
    skills_sub = skills.add_subparsers(dest="skills_command", required=True)
    skills_sub.add_parser("list")
    skills_recommend = skills_sub.add_parser("recommend", aliases=["plan"])
    skills_recommend.add_argument("--node")
    skills_explain = skills_sub.add_parser("explain")
    skills_explain.add_argument("node")
    skills_search = skills_sub.add_parser("search")
    skills_search.add_argument("--node")
    skills_register = skills_sub.add_parser("register")
    add_register_arguments(skills_register)
    skills_update = skills_sub.add_parser("update")
    add_register_arguments(skills_update)
    skills_assign = skills_sub.add_parser("assign")
    skills_assign.add_argument("name")
    skills_assign.add_argument("--node", required=True)
    skills_assign.add_argument("--level", choices=["required", "recommended", "optional"], default="required")
    skills_assign.add_argument("--reason", default="")
    skills_none = skills_sub.add_parser("none")
    skills_none.add_argument("--node", required=True)
    skills_none.add_argument("--reason", required=True)
    skills_unassign_parser = skills_sub.add_parser("unassign")
    skills_unassign_parser.add_argument("name")
    skills_unassign_parser.add_argument("--node", required=True)
    skills_remove = skills_sub.add_parser("remove")
    skills_remove.add_argument("name")
    skills_remove.add_argument("--apply", action="store_true")
    skills_audit_parser = skills_sub.add_parser("audit")
    skills_audit_parser.add_argument("--node")
    skills_audit_parser.add_argument("--deep", action="store_true")
    skills_verify_parser = skills_sub.add_parser("verify")
    skills_verify_parser.add_argument("--node")
    skills_sync_parser = skills_sub.add_parser("sync")
    skills_sync_parser.add_argument("--apply", action="store_true")
    skills_eval = skills_sub.add_parser("evaluate")
    skills_eval.add_argument("node")

    doctor_parser = sub.add_parser("doctor", help="Check the whole scheme without changing it")
    doctor_parser.add_argument("--deep", action="store_true")
    doctor_parser.add_argument("--refresh-skills", action="store_true")
    doctor_parser.add_argument("--repair-plan", action="store_true")

    scheme = sub.add_parser("scheme", help="Deep scheme check and repair planning")
    scheme_sub = scheme.add_subparsers(dest="scheme_command", required=True)
    scheme_check = scheme_sub.add_parser("check")
    scheme_check.add_argument("--no-refresh-skills", action="store_true")
    scheme_repair = scheme_sub.add_parser("repair")
    scheme_repair.add_argument("--apply", action="store_true")

    audit = sub.add_parser("audit", help="Audit one project layer")
    audit.add_argument("area", choices=["git", "code", "quality", "ci", "docs", "security", "skills", "all"])
    audit.add_argument("--deep", action="store_true")

    install = sub.add_parser("install", help="Install or update this skill for Codex and Claude")
    install.add_argument("--client", choices=["codex", "claude", "both"], default="both")
    install.add_argument("--apply", action="store_true")
    install.add_argument("--home", type=Path, help="Override the home directory (testing and non-standard setups)")
    install.add_argument("--force", action="store_true", help="Replace an unrelated directory at the target path")

    operate = sub.add_parser("operate", help="Preflight one configured workflow node")
    operate.add_argument("--node", required=True)
    operate.add_argument("--issue", default="", help="Issue reference; required to evaluate a cycle budget")

    run = sub.add_parser("run", help="Record or inspect background run evidence")
    run_sub = run.add_subparsers(dest="run_command", required=True)
    run_record = run_sub.add_parser("record")
    run_record.add_argument("--node", required=True)
    run_record.add_argument("--status", required=True)
    run_record.add_argument("--head-sha", default="")
    run_record.add_argument("--issue", default="")
    run_record.add_argument("--pr", default="")
    run_record.add_argument("--evidence", action="append", default=[])
    run_record.add_argument("--actual-agent")
    run_record.add_argument("--actual-model")
    run_record.add_argument("--actual-effort")
    run_record.add_argument(
        "--human-decision",
        default="",
        metavar="REF",
        help="Reference to the PM decision that extends an exhausted cycle budget",
    )
    run_record.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="NAME=CONCLUSION",
        help="Observed check conclusion; only success proves a check",
    )
    run_show = run_sub.add_parser("show")
    run_show.add_argument("run_id", nargs="?")
    return parser


def local_output_path(repo: Path, relative: str, category: str) -> Path:
    if category not in {"plans", "reports"}:
        raise DevflowError(f"Неизвестная категория локального вывода: {category}")
    normalized = Path(relative).as_posix()
    prefix = f"{LOCAL_DIR}/{category}/"
    if not normalized.startswith(prefix) or not normalized.endswith(".json"):
        raise DevflowError(f"Вывод разрешён только в {prefix}<name>.json")
    target = ensure_within(repo, normalized)
    if target.exists():
        raise DevflowError(f"Файл вывода уже существует; выберите новое имя: {normalized}")
    return target


def save_plan(repo: Path, relative: str, plan: dict[str, Any]) -> str:
    target = local_output_path(repo, relative, "plans")
    atomic_write(target, json_bytes(plan))
    return str(target)


def show_node_run(repo: Path, identifier: str | None) -> Any:
    directory = ensure_within(repo, f"{LOCAL_DIR}/node-runs")
    if identifier:
        return load_json(directory / f"{safe_run_identifier(identifier)}.json")
    if not directory.exists():
        return []
    return [load_json(path) for path in sorted(directory.glob("*.json"), reverse=True)[:20]]


def execute(args: argparse.Namespace) -> int:
    repo = args.repo.resolve()
    if not repo.exists() or not repo.is_dir():
        raise DevflowError(f"Каталог репозитория не найден: {repo}")

    if args.command == "help":
        print(help_text(args.topic, repo))
        return 0
    if args.command == "inspect":
        report = inspect_repository(repo, args.deep)
        if args.output:
            target = local_output_path(repo, args.output, "reports")
            atomic_write(target, json_bytes(report))
            report["saved_to"] = str(target)
        print_json(report)
        return 0
    if args.command in {"init", "adopt", "upgrade"}:
        plan = build_setup_plan(repo, args.command, args.command)
        if args.apply:
            applied = apply_plan(repo, plan)
            verified = verify_run(repo, applied["run_id"], applied["manifest_sha256"])
            response = {"apply": applied, "verify": verified, "next": next_setup_step(evaluate_setup(repo), repo)}
            print_json(response)
            return 0 if verified["status"] == "PASS" else 1
        next_command, next_argv = expand_devflow_command(repo, f"devflow {args.command} --apply")
        print_json({
            "status": "PARTIAL" if plan["operations"] else "PASS",
            "dry_run": True,
            "plan": summarize_plan(repo, plan, args.full_diff, args.diff_path),
            "requires_user_decision": bool(plan["operations"]),
            "next_command": next_command,
            "next_argv": next_argv,
        })
        return 0
    if args.command == "plan":
        plan = build_setup_plan(repo, args.mode, "plan")
        response: dict[str, Any] = {"status": "PASS", "plan": summarize_plan(repo, plan, args.full_diff, args.diff_path)}
        if args.output:
            response["saved_to"] = save_plan(repo, args.output, plan)
            response["plan_sha256"] = sha256_file(Path(response["saved_to"]))
        print_json(response)
        return 0
    if args.command == "apply":
        plan_path = ensure_within(repo, args.plan)
        plan_bytes = plan_path.read_bytes()
        actual_plan_sha = sha256_bytes(plan_bytes)
        if not re.fullmatch(r"[0-9a-f]{64}", args.expected_sha256) or actual_plan_sha != args.expected_sha256:
            raise DevflowError("SHA-256 сохранённого плана не совпадает с просмотренной версией")
        try:
            saved_plan = json.loads(plan_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DevflowError("Сохранённый план не является корректным UTF-8 JSON") from exc
        result = apply_plan(repo, saved_plan)
        print_json({"apply": result, "verify": verify_run(repo, result["run_id"], result["manifest_sha256"]), "next": next_setup_step(evaluate_setup(repo), repo)})
        return 0
    if args.command == "verify":
        result = verify_run(repo, args.run_id, args.expected_manifest_sha256)
        print_json(result)
        return 0 if result["status"] == "PASS" else 1
    if args.command == "rollback":
        print_json(rollback_run(repo, args.run_id, args.expected_manifest_sha256))
        return 0
    if args.command == "setup":
        if args.setup_command == "check":
            results = evaluate_setup(repo)
            if args.stage:
                selected = [item for item in results if item["stage"] == args.stage]
                if not selected:
                    raise DevflowError(f"Неизвестный этап: {args.stage}")
                print_json(selected[0])
            else:
                print_json({"stages": results, "next": next_setup_step(results, repo)})
            selected_status = selected[0]["status"] if args.stage else next_setup_step(results, repo)["status"]
            return 1 if selected_status == "BLOCKED" else 0
        if args.setup_command == "next":
            result = next_setup_step(evaluate_setup(repo), repo)
            print_json(result)
            return 0 if result["status"] == "PASS" else 1
        if args.setup_command == "mark":
            print_json(mark_setup_stage(repo, args.stage, args.status, args.evidence, args.note))
            return 0
    if args.command in {"status", "next"}:
        results = evaluate_setup(repo)
        if args.command == "next":
            print_json(next_setup_step(results, repo))
        else:
            print_json({"stages": results, "next": next_setup_step(results, repo)})
        return 1 if next_setup_step(results, repo)["status"] == "BLOCKED" else 0
    if args.command == "graph" and args.migrate:
        result = migrate_graph_contracts(repo, apply=args.apply, full_diff=args.full_diff)
        print_json(result)
        return 0 if result["status"] in {"PASS", "NOT_APPLICABLE"} else 1
    if args.command == "graph":
        config, workflow, lock, configuration_status = load_project_or_proposed_state(repo)
        config_errors, _ = validate_config(config)
        workflow_errors, _ = validate_workflow(workflow, config)
        lock_errors = validate_skills_lock(lock)
        errors = config_errors + workflow_errors + lock_errors
        if errors:
            print_json({"status": "BLOCKED", "errors": errors})
            return 1
        print(render_graph(workflow, config, lock, args.format, configuration_status))
        return 0
    if args.command == "config":
        if args.config_command == "show":
            config, workflow, lock = load_project_state(repo)
            if args.effective:
                print_json({"config": config, "nodes": [effective_node(node, config, lock) for node in workflow["nodes"]]})
            else:
                print_json(config)
            return 0
        if args.config_command == "set":
            print_json(configure_value(repo, args.path, args.value))
            return 0
        if args.config_command == "effective":
            config, workflow, lock = load_project_state(repo)
            config_errors, _ = validate_config(config)
            workflow_errors, _ = validate_workflow(workflow, config)
            if config_errors or workflow_errors:
                print_json({"status": "BLOCKED", "errors": config_errors + workflow_errors})
                return 1
            matrix = effective_configuration(workflow, config, lock)
            if args.format == "json":
                print_json(matrix)
            else:
                print(render_effective_configuration(matrix, "table"))
            return 0
        if args.config_command == "normalize":
            result = normalize_project_config(repo, apply=args.apply, full_diff=args.full_diff)
            print_json(result)
            return 0 if result["status"] in {"PASS", "NOT_APPLICABLE"} else 1
    if args.command == "role" and args.role_command == "set":
        print_json(configure_role(repo, args.role, args.agent))
        return 0
    if args.command == "model" and args.model_command == "set":
        print_json(configure_model(repo, args.target, args.model, args.effort))
        return 0
    if args.command == "permissions" and args.permissions_command == "set":
        print_json(configure_permissions(repo, args.target, args.profile))
        return 0
    if args.command == "skills":
        if args.skills_command == "list":
            _, workflow, lock = load_project_state(repo)
            initialize_skill_decisions(lock, workflow)
            print_json(lock)
            return 0
        if args.skills_command in {"recommend", "plan"}:
            result = skill_recommendations(repo, args.node)
            print_json(result)
            return 0 if result["status"] == "PASS" else 1
        if args.skills_command == "explain":
            print_json(skill_recommendations(repo, args.node))
            return 0
        if args.skills_command == "search":
            print_json(skills_search_request(repo, args.node))
            return 0
        if args.skills_command in {"register", "update"}:
            targets = [item.strip() for item in args.targets.split(",") if item.strip()]
            result = register_skill(repo, args.name, args.path, args.source, args.commit, args.license_name, targets, args.apply, args.approved_by_user)
            print_json(result)
            return 0 if result["status"] != "BLOCKED" else 1
        if args.skills_command == "assign":
            print_json(skill_decision(repo, args.node, "assigned", args.name, args.level, args.reason))
            return 0
        if args.skills_command == "none":
            print_json(skill_decision(repo, args.node, "zero-skill", reason=args.reason))
            return 0
        if args.skills_command == "unassign":
            print_json(skill_unassign(repo, args.node, args.name))
            return 0
        if args.skills_command == "remove":
            print_json(remove_skill(repo, args.name, args.apply))
            return 0
        if args.skills_command in {"audit", "verify"}:
            deep = getattr(args, "deep", False)
            result = skills_audit(repo, getattr(args, "node", None), deep=deep)
            print_json(result)
            return 0 if result["status"] == "PASS" else 1
        if args.skills_command == "sync":
            print_json(sync_skills(repo, args.apply))
            return 0
        if args.skills_command == "evaluate":
            print_json({
                "status": "EVAL_RUNNER_REQUIRED",
                "node": args.node,
                "method": "Run fixed normal, edge, and failure scenarios under identical model, effort, permissions, code, and tools for zero-skill, incumbent, and challenger.",
                "metrics": ["correctness", "policy compliance", "critical defects", "guardrail interference", "time/cost only when telemetry exists"],
                "rule": "If comparison cannot be executed, keep candidate-unverified; do not claim improvement."
            })
            return 0
    if args.command == "doctor":
        result = doctor(repo, args.deep, args.refresh_skills, args.repair_plan)
        print_json(result)
        return 0 if result["status"] == "PASS" else 1
    if args.command == "scheme":
        if args.scheme_command == "check":
            result = scheme_check(repo, refresh_skills=not args.no_refresh_skills)
            print_json(result)
            return 0 if result["status"] == "PASS" else 1
        if args.scheme_command == "repair":
            plan = build_setup_plan(repo, "repair", "scheme-repair")
            if args.apply:
                result = apply_plan(repo, plan)
                print_json({"apply": result, "verify": verify_run(repo, result["run_id"], result["manifest_sha256"]), "next": next_setup_step(evaluate_setup(repo), repo)})
            else:
                next_command, next_argv = expand_devflow_command(repo, "devflow scheme repair --apply")
                print_json({
                    "status": "PARTIAL",
                    "dry_run": True,
                    "plan": summarize_plan(repo, plan),
                    "requires_user_decision": True,
                    "next_command": next_command,
                    "next_argv": next_argv,
                })
            return 0
    if args.command == "audit":
        result = audit_project(repo, args.area, args.deep)
        print_json(result)
        return 0 if result["status"] == "PASS" else 1
    if args.command == "install":
        clients = ["codex", "claude"] if args.client == "both" else [args.client]
        reports = [install_skill(client, args.apply, args.home, args.force) for client in clients]
        status = "BLOCKED" if any(item["status"] == "BLOCKED" for item in reports) else (
            "PARTIAL" if any(item["status"] == "PARTIAL" for item in reports) else "PASS"
        )
        print_json({"status": status, "applied": bool(args.apply), "clients": reports})
        return 0 if status == "PASS" else 1
    if args.command == "operate":
        result = operate_preflight(repo, args.node, args.issue)
        print_json(result)
        return 0 if result["status"] == "PASS" else 1
    if args.command == "run":
        if args.run_command == "record":
            print_json(record_run(
                repo, args.node, args.status, args.head_sha, args.issue, args.pr, args.evidence,
                args.actual_agent, args.actual_model, args.actual_effort, args.check,
                args.human_decision,
            ))
            return 0
        if args.run_command == "show":
            print_json(show_node_run(repo, args.run_id))
            return 0
    raise DevflowError("Команда не реализована")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return execute(parser.parse_args(argv))
    except DevflowError as exc:
        print_json({"status": "BLOCKED", "error": str(exc)})
        return 2
    except KeyboardInterrupt:
        print_json({"status": "BLOCKED", "error": "Операция отменена пользователем"})
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
