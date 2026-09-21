"""Isolated execution adapter for R1 AI repair benchmark trials.

The adapter copies a fixture/local repository into a disposable workspace,
keeps oracle verification files in a separate sealed directory, delegates the
repair to an explicit agent adapter, runs argv-based tests without a shell and
with timeouts, captures a deterministic patch, and emits an immutable manifest.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from .ai_repair_benchmark import (
    AGENT_INPUT_SCHEMA,
    content_hash,
    create_run_manifest,
    load_json,
    validate_agent_input,
    validate_spec,
)

EXECUTION_SCHEMA = "feynmap.ai_repair_execution.v1"
EXCLUDED_PARTS = {
    ".git",
    ".feynmap",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class AgentRunResult:
    provider: str
    model: str
    first_proposed_edit: Optional[Mapping[str, Any]] = None
    unsupported_claims: Sequence[str] = field(default_factory=tuple)
    repository_searches: int = 0
    extra_context_requests: int = 0
    usage: Mapping[str, Any] = field(default_factory=dict)


class RepairAgent(Protocol):
    def run(
        self,
        workspace: Path,
        agent_input: Mapping[str, Any],
        control_directory: Path,
    ) -> AgentRunResult: ...


class CommandRepairAgent:
    """Invoke an explicitly configured argv command using a JSON file protocol."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        provider: str,
        model: str,
        timeout_seconds: float = 900.0,
        environment: Optional[Mapping[str, str]] = None,
    ):
        if not command or any(not str(value) for value in command):
            raise ValueError("agent command requires non-empty argv values")
        if timeout_seconds <= 0:
            raise ValueError("agent timeout must be positive")
        self.command = tuple(str(value) for value in command)
        self.provider = str(provider)
        self.model = str(model)
        self.timeout_seconds = float(timeout_seconds)
        self.environment = dict(environment or {})

    def run(
        self,
        workspace: Path,
        agent_input: Mapping[str, Any],
        control_directory: Path,
    ) -> AgentRunResult:
        input_path = control_directory / "agent-input.json"
        output_path = control_directory / "agent-output.json"
        input_path.write_text(
            json.dumps(agent_input, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        substitutions = {
            "{workspace}": str(workspace),
            "{input}": str(input_path),
            "{output}": str(output_path),
        }
        argv = [substitutions.get(value, value) for value in self.command]
        env = _base_environment()
        env.update(self.environment)
        completed = subprocess.run(
            argv,
            cwd=str(workspace),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout_seconds,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "agent command failed with exit code %d" % completed.returncode
            )
        if not output_path.is_file():
            raise RuntimeError("agent command did not create its JSON output")
        with output_path.open("rb") as handle:
            result = json.load(handle)
        if not isinstance(result, Mapping):
            raise ValueError("agent command output must be a JSON object")
        return AgentRunResult(
            provider=self.provider,
            model=self.model,
            first_proposed_edit=result.get("first_proposed_edit"),
            unsupported_claims=tuple(result.get("unsupported_claims") or []),
            repository_searches=int(result.get("repository_searches") or 0),
            extra_context_requests=int(result.get("extra_context_requests") or 0),
            usage=dict(result.get("usage") or {}),
        )


def _base_environment() -> Dict[str, str]:
    keep = ("SYSTEMROOT", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _task(spec: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    for task in spec["tasks"]:
        if str(task["id"]) == task_id:
            return task
    raise ValueError("unknown repair benchmark task: %s" % task_id)


def resolve_source_repository(project_root: Path, locator: str) -> Path:
    """Resolve only explicit local fixture/path locators; never clone implicitly."""
    if locator.startswith("fixture:"):
        candidate = project_root / locator.split(":", 1)[1]
    elif locator.startswith("path:"):
        candidate = Path(locator.split(":", 1)[1])
    else:
        raise ValueError("execution supports only fixture: and path: repositories")
    resolved = candidate.resolve()
    if locator.startswith("fixture:"):
        root = project_root.resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            raise ValueError("fixture repository escapes the project root")
    if not resolved.is_dir():
        raise ValueError("repair benchmark repository does not exist: %s" % resolved)
    return resolved


def _copy_repository(source: Path, destination: Path) -> None:
    shutil.copytree(
        str(source),
        str(destination),
        ignore=shutil.ignore_patterns(*sorted(EXCLUDED_PARTS)),
    )


def _files(root: Path) -> Dict[str, bytes]:
    result = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        result[relative.as_posix()] = path.read_bytes()
    return result


def repository_content_hash(root: Path) -> str:
    inventory = [
        {
            "path": path,
            "sha256": hashlib.sha256(value).hexdigest(),
            "size": len(value),
        }
        for path, value in sorted(_files(root).items())
    ]
    return content_hash(inventory)


def _text_lines(value: bytes) -> Optional[List[str]]:
    try:
        return value.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None


def capture_patch(baseline: Path, workspace: Path) -> Tuple[List[str], str, str]:
    """Return changed paths, deterministic unified diff text, and SHA-256."""
    before = _files(baseline)
    after = _files(workspace)
    changed = sorted(
        path for path in set(before) | set(after) if before.get(path) != after.get(path)
    )
    chunks = []
    for path in changed:
        old = before.get(path, b"")
        new = after.get(path, b"")
        old_lines = _text_lines(old)
        new_lines = _text_lines(new)
        if old_lines is None or new_lines is None:
            chunks.append("Binary files a/%s and b/%s differ\n" % (path, path))
            continue
        chunks.extend(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile="a/%s" % path,
                tofile="b/%s" % path,
            )
        )
    patch = "".join(chunks)
    digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
    return changed, patch, digest


def _safe_relative(path: str) -> Path:
    value = Path(path)
    if value.is_absolute() or ".." in value.parts:
        raise ValueError("benchmark command path must stay repository-relative")
    return value


def _seal_files(source: Path, sealed: Path, paths: Sequence[str]) -> None:
    for raw in paths:
        relative = _safe_relative(raw)
        source_path = source / relative
        if not source_path.is_file():
            raise ValueError("sealed oracle file does not exist: %s" % raw)
        target = sealed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(source_path), str(target))


def _test_argv(
    raw: Sequence[str], workspace: Path, sealed: Path
) -> Tuple[List[str], Dict[str, str]]:
    if not raw:
        raise ValueError("test command cannot be empty")
    executable = str(raw[0])
    if executable not in {"python", "python3"}:
        raise ValueError("initial R1 executor allows only Python test commands")
    argv = [sys.executable]
    for index, value in enumerate(raw[1:], 1):
        if index == 1 and value.endswith(".py"):
            relative = _safe_relative(value)
            sealed_script = sealed / relative
            if not sealed_script.is_file():
                raise ValueError("Python oracle script must be declared sealed")
            argv.append(str(sealed_script))
        else:
            argv.append(str(value))
    env = _base_environment()
    env["PYTHONPATH"] = str(workspace)
    return argv, env


def run_oracle_tests(
    tests: Sequence[Mapping[str, Any]],
    workspace: Path,
    sealed: Path,
    *,
    timeout_seconds: float,
) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    if timeout_seconds <= 0:
        raise ValueError("test timeout must be positive")
    statuses = []
    diagnostics = []
    for test in tests:
        test_id = str(test["id"])
        argv, env = _test_argv(test["command"], workspace, sealed)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                cwd=str(workspace),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            status = "passed" if completed.returncode == 0 else "failed"
            returncode = completed.returncode
            stdout = completed.stdout.decode("utf-8", errors="replace")[-4000:]
            stderr = completed.stderr.decode("utf-8", errors="replace")[-4000:]
        except subprocess.TimeoutExpired as error:
            status = "error"
            returncode = None
            stdout = (error.stdout or b"").decode("utf-8", errors="replace")[-4000:]
            stderr = (error.stderr or b"").decode("utf-8", errors="replace")[-4000:]
        statuses.append({"id": test_id, "status": status})
        diagnostics.append(
            {
                "id": test_id,
                "status": status,
                "returncode": returncode,
                "elapsed_seconds": round(time.perf_counter() - started, 6),
                "stdout_tail": stdout,
                "stderr_tail": stderr,
            }
        )
    return statuses, diagnostics


def execute_run(
    spec: Mapping[str, Any],
    agent_input: Mapping[str, Any],
    agent: RepairAgent,
    *,
    project_root: Path,
    attempt: int = 1,
    test_timeout_seconds: float = 60.0,
    workspace_parent: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute one repair trial entirely inside a disposable copied workspace."""
    validate_spec(spec)
    validate_agent_input(spec, agent_input)
    if agent_input.get("schema") != AGENT_INPUT_SCHEMA:
        raise ValueError("execution requires an R1 agent input")
    task_id = str(agent_input["task"]["id"])
    task = _task(spec, task_id)
    oracle = task["oracle"]
    source = resolve_source_repository(project_root, str(task["repository"]["locator"]))
    actual_content_hash = repository_content_hash(source)
    if actual_content_hash != str(task["repository"]["content_hash"]):
        raise ValueError("repair benchmark repository content hash mismatch")
    parent = str(workspace_parent.resolve()) if workspace_parent else None
    started_at = _utc_now()
    with tempfile.TemporaryDirectory(prefix="feynmap-r1-", dir=parent) as raw:
        execution_root = Path(raw)
        baseline = execution_root / "baseline"
        workspace = execution_root / "workspace"
        sealed = execution_root / "sealed"
        control = execution_root / "control"
        sealed.mkdir()
        control.mkdir()
        _copy_repository(source, baseline)
        _copy_repository(source, workspace)
        _seal_files(source, sealed, oracle.get("sealed_files") or [])
        sealed_identity = _files(sealed)

        baseline_tests, baseline_diagnostics = run_oracle_tests(
            oracle["required_tests"],
            baseline,
            sealed,
            timeout_seconds=test_timeout_seconds,
        )
        expectation = str(oracle["baseline_expectation"])
        all_baseline_passed = all(test["status"] == "passed" for test in baseline_tests)
        if expectation == "at_least_one_failure" and all_baseline_passed:
            raise ValueError("baseline unexpectedly passes every required test")
        if expectation == "all_pass" and not all_baseline_passed:
            raise ValueError("baseline unexpectedly fails a required test")

        started = time.perf_counter()
        agent_result = agent.run(workspace, agent_input, control)
        agent_elapsed = time.perf_counter() - started
        if _files(sealed) != sealed_identity:
            raise RuntimeError("agent modified sealed oracle files")
        final_tests, final_diagnostics = run_oracle_tests(
            oracle["required_tests"],
            workspace,
            sealed,
            timeout_seconds=test_timeout_seconds,
        )
        changed_files, patch, patch_sha256 = capture_patch(baseline, workspace)
        finished_at = _utc_now()
        outcome = {
            "patch_produced": bool(changed_files),
            "patch_sha256": patch_sha256 if changed_files else None,
            "changed_files": changed_files,
            "baseline_tests": baseline_tests,
            "tests": final_tests,
            "first_proposed_edit": agent_result.first_proposed_edit,
            "unsupported_claims": list(agent_result.unsupported_claims),
            "repository_searches": agent_result.repository_searches,
            "extra_context_requests": agent_result.extra_context_requests,
            "elapsed_seconds": agent_elapsed,
            "usage": dict(agent_result.usage),
        }
        manifest = create_run_manifest(
            spec,
            agent_input,
            attempt=attempt,
            agent={"provider": agent_result.provider, "model": agent_result.model},
            outcome=outcome,
            started_at=started_at,
            finished_at=finished_at,
        )
        return {
            "schema": EXECUTION_SCHEMA,
            "manifest": manifest,
            "patch": patch,
            "baseline_test_diagnostics": baseline_diagnostics,
            "final_test_diagnostics": final_diagnostics,
            "source_repository": str(source),
            "source_repository_modified": _files(source) != _files(baseline),
        }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute one isolated R1 AI repair benchmark run"
    )
    parser.add_argument("spec")
    parser.add_argument("agent_input")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--attempt", type=int, default=1)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--test-timeout", type=float, default=60.0)
    parser.add_argument("--agent-timeout", type=float, default=900.0)
    parser.add_argument(
        "--pass-env",
        action="append",
        default=[],
        help="Explicit environment variable name to pass to the agent command",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "agent_command",
        nargs=argparse.REMAINDER,
        help=(
            "argv after --; exact tokens {workspace}, {input}, and {output} "
            "are replaced with adapter paths"
        ),
    )
    args = parser.parse_args(argv)
    command = list(args.agent_command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("an agent command must follow --")
    environment = {}
    for name in args.pass_env:
        if name not in os.environ:
            parser.error("requested environment variable is not set: %s" % name)
        environment[name] = os.environ[name]
    agent = CommandRepairAgent(
        command,
        provider=args.provider,
        model=args.model,
        timeout_seconds=args.agent_timeout,
        environment=environment,
    )
    result = execute_run(
        load_json(Path(args.spec)),
        load_json(Path(args.agent_input)),
        agent,
        project_root=Path(args.project_root),
        attempt=args.attempt,
        test_timeout_seconds=args.test_timeout,
    )
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
