import copy
import sys
from pathlib import Path

import pytest

from feynmap.judgment.ai_repair_benchmark import (
    build_agent_input,
    load_json,
    score_manifest,
    validate_manifest,
)
from feynmap.judgment.ai_repair_execution import (
    EXECUTION_SCHEMA,
    AgentRunResult,
    CommandRepairAgent,
    capture_patch,
    execute_run,
    repository_content_hash,
    resolve_source_repository,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "experiments" / "ai_repair_r1_fixture.json"


class RetryCapAgent:
    def run(self, workspace, agent_input, control_directory):
        path = workspace / "backoff.py"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "return base_seconds * (2 ** attempt)",
                "return min(30, base_seconds * (2 ** attempt))",
            ),
            encoding="utf-8",
        )
        return AgentRunResult(
            provider="scripted-fixture",
            model="fixture-v1",
            first_proposed_edit={"path": "backoff.py", "start_line": 5},
            repository_searches=1,
            usage={"input_tokens": 20, "output_tokens": 8},
        )


class VerifierEditingAgent(RetryCapAgent):
    def run(self, workspace, agent_input, control_directory):
        result = super().run(workspace, agent_input, control_directory)
        (workspace / "verify.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        return result


class NoOpAgent:
    def run(self, workspace, agent_input, control_directory):
        return AgentRunResult(provider="no-op", model="fixture-v1")


class SealedFileEditingAgent:
    def run(self, workspace, agent_input, control_directory):
        sealed = control_directory.parent / "sealed" / "verify.py"
        sealed.write_text("raise SystemExit(0)\n", encoding="utf-8")
        return AgentRunResult(provider="malicious-fixture", model="fixture-v1")


def _spec():
    return load_json(SPEC_PATH)


def _input(arm="unassisted"):
    context = None
    if arm != "unassisted":
        context = {
            "schema": "feynmap.context_fixture.v1",
            "candidates": [{"id": "backoff", "path": "backoff.py"}],
        }
    return build_agent_input(_spec(), "bounded-retry-delay", arm, context)


def test_execute_run_repairs_disposable_copy_and_scores_success(tmp_path):
    source = ROOT / "tests" / "fixtures" / "ai_repair_r1" / "bounded_retry_delay"
    original = (source / "backoff.py").read_bytes()

    result = execute_run(
        _spec(),
        _input("dual_channel"),
        RetryCapAgent(),
        project_root=ROOT,
        workspace_parent=tmp_path,
    )

    assert result["schema"] == EXECUTION_SCHEMA
    assert result["source_repository_modified"] is False
    assert (source / "backoff.py").read_bytes() == original
    assert list(tmp_path.iterdir()) == []
    assert result["manifest"]["outcome"]["baseline_tests"] == [
        {"id": "bounded-retry-delay-check", "status": "failed"}
    ]
    assert result["manifest"]["outcome"]["tests"] == [
        {"id": "bounded-retry-delay-check", "status": "passed"}
    ]
    assert result["manifest"]["outcome"]["changed_files"] == ["backoff.py"]
    assert "min(30" in result["patch"]
    validate_manifest(_spec(), result["manifest"])
    score = score_manifest(_spec(), result["manifest"])
    assert score["oracle_passed"] is True
    assert score["strict_success"] is True


def test_sealed_oracle_is_used_and_verifier_edit_is_forbidden(tmp_path):
    result = execute_run(
        _spec(),
        _input(),
        VerifierEditingAgent(),
        project_root=ROOT,
        workspace_parent=tmp_path,
    )

    assert result["manifest"]["outcome"]["tests"][0]["status"] == "passed"
    score = score_manifest(_spec(), result["manifest"])
    assert score["forbidden_changed_files"] == ["verify.py"]
    assert score["oracle_passed"] is False
    assert score["strict_success"] is False


def test_sealed_oracle_integrity_is_verified_after_agent_run(tmp_path):
    with pytest.raises(RuntimeError, match="modified sealed oracle"):
        execute_run(
            _spec(),
            _input(),
            SealedFileEditingAgent(),
            project_root=ROOT,
            workspace_parent=tmp_path,
        )


def test_test_timeout_is_bounded_and_recorded_as_error(tmp_path):
    spec = copy.deepcopy(_spec())
    task = spec["tasks"][0]
    task["oracle"]["required_tests"][0]["command"] = [
        "python",
        "-c",
        "import time; time.sleep(2)",
    ]
    task["oracle"]["sealed_files"] = []
    agent_input = build_agent_input(spec, task["id"], "unassisted")

    result = execute_run(
        spec,
        agent_input,
        NoOpAgent(),
        project_root=ROOT,
        test_timeout_seconds=0.05,
        workspace_parent=tmp_path,
    )

    assert result["manifest"]["outcome"]["baseline_tests"][0]["status"] == "error"
    assert result["manifest"]["outcome"]["tests"][0]["status"] == "error"
    assert result["final_test_diagnostics"][0]["returncode"] is None


def test_source_resolution_rejects_nonlocal_and_escaping_locators(tmp_path):
    with pytest.raises(ValueError, match="only fixture: and path"):
        resolve_source_repository(ROOT, "https://example.com/repository.git")
    with pytest.raises(ValueError, match="escapes the project root"):
        resolve_source_repository(ROOT, "fixture:../outside")
    with pytest.raises(ValueError, match="does not exist"):
        resolve_source_repository(ROOT, "path:" + str(tmp_path / "missing"))


def test_execution_rejects_repository_content_drift(tmp_path):
    spec = copy.deepcopy(_spec())
    spec["tasks"][0]["repository"]["content_hash"] = "0" * 64
    agent_input = build_agent_input(spec, "bounded-retry-delay", "unassisted")
    with pytest.raises(ValueError, match="content hash mismatch"):
        execute_run(
            spec,
            agent_input,
            NoOpAgent(),
            project_root=ROOT,
            workspace_parent=tmp_path,
        )


def test_fixture_repository_hash_is_deterministic():
    source = ROOT / "tests" / "fixtures" / "ai_repair_r1" / "bounded_retry_delay"
    expected = _spec()["tasks"][0]["repository"]["content_hash"]
    assert repository_content_hash(source) == expected


def test_repository_hash_ignores_text_checkout_line_endings(tmp_path):
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    lf.mkdir()
    crlf.mkdir()
    (lf / "module.py").write_bytes(b"first\nsecond\n")
    (crlf / "module.py").write_bytes(b"first\r\nsecond\r\n")

    assert repository_content_hash(lf) == repository_content_hash(crlf)


def test_repository_hash_preserves_binary_line_ending_bytes(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "payload.bin").write_bytes(b"\x00first\n")
    (second / "payload.bin").write_bytes(b"\x00first\r\n")

    assert repository_content_hash(first) != repository_content_hash(second)


def test_repository_hash_rejects_unknown_policy(tmp_path):
    with pytest.raises(ValueError, match="unsupported repository content hash policy"):
        repository_content_hash(tmp_path, policy="raw_bytes_v1")


def test_capture_patch_handles_added_deleted_and_binary_files(tmp_path):
    baseline = tmp_path / "baseline"
    workspace = tmp_path / "workspace"
    baseline.mkdir()
    workspace.mkdir()
    (baseline / "deleted.txt").write_text("old\n", encoding="utf-8")
    (baseline / "binary.bin").write_bytes(b"\xff\x00")
    (workspace / "binary.bin").write_bytes(b"\xfe\x00")
    (workspace / "added.txt").write_text("new\n", encoding="utf-8")

    changed, patch, digest = capture_patch(baseline, workspace)

    assert changed == ["added.txt", "binary.bin", "deleted.txt"]
    assert "Binary files a/binary.bin and b/binary.bin differ" in patch
    assert len(digest) == 64


def test_command_agent_requires_argv_and_positive_timeout():
    with pytest.raises(ValueError, match="non-empty argv"):
        CommandRepairAgent([], provider="agent", model="model")
    with pytest.raises(ValueError, match="timeout must be positive"):
        CommandRepairAgent(
            [sys.executable, "agent.py"],
            provider="agent",
            model="model",
            timeout_seconds=0,
        )


def test_command_agent_json_protocol_repairs_temporary_workspace(tmp_path):
    script = tmp_path / "fixture_agent.py"
    script.write_text(
        """import json
import sys
from pathlib import Path

workspace = Path(sys.argv[1])
output = Path(sys.argv[3])
path = workspace / "backoff.py"
text = path.read_text(encoding="utf-8")
path.write_text(text.replace(
    "return base_seconds * (2 ** attempt)",
    "return min(30, base_seconds * (2 ** attempt))",
), encoding="utf-8")
output.write_text(json.dumps({
    "first_proposed_edit": {"path": "backoff.py", "start_line": 5},
    "repository_searches": 1,
    "usage": {"input_tokens": 12, "output_tokens": 5},
}), encoding="utf-8")
""",
        encoding="utf-8",
    )
    agent = CommandRepairAgent(
        [
            sys.executable,
            str(script),
            "{workspace}",
            "{input}",
            "{output}",
        ],
        provider="command-fixture",
        model="fixture-v1",
        timeout_seconds=5,
    )

    result = execute_run(
        _spec(),
        _input(),
        agent,
        project_root=ROOT,
        workspace_parent=tmp_path,
    )

    assert score_manifest(_spec(), result["manifest"])["strict_success"] is True
    assert result["manifest"]["agent"] == {
        "provider": "command-fixture",
        "model": "fixture-v1",
    }
