import json
from unittest.mock import patch

import pytest

from feynmap.p2_4e_blind_answer import (
    BlindAnswerError,
    openai_responses_answer,
    run_blind_answers,
    validate_answer,
)


def _packet(packet_id="packet1"):
    return {
        "schema": "feynmap.p2_4d_model_input.v1",
        "packet_id": packet_id,
        "question": "What does the function return?",
        "delivery_sufficient": True,
        "unresolved_query_identifiers": [],
        "context": {"nodes": [{"id": "node:1", "name": "example"}]},
        "evidence_refs": {
            "nodes": ["node:1"],
            "edges": [],
            "observations": ["behavior:1"],
        },
        "answer_instruction": "Use only supplied evidence.",
        "answer_schema": {
            "status": "answer|need_more_context",
            "claims": [{"text": "string", "evidence_refs": ["ref"]}],
            "missing_identifiers": ["string"],
        },
    }


class _FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _provider_response(model="gpt-test"):
    answer = {
        "status": "answer",
        "claims": [
            {
                "text": "The packet supports this claim.",
                "evidence_refs": ["node:1"],
            }
        ],
        "missing_identifiers": [],
    }
    return {
        "id": "resp_test",
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "content": [
                    {"type": "output_text", "text": json.dumps(answer)}
                ],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 20,
            "total_tokens": 120,
        },
    }


def test_openai_responses_request_uses_structured_output_and_no_tools():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _FakeHTTPResponse(_provider_response())

    with patch("feynmap.p2_4e_blind_answer.urllib.request.urlopen", fake_urlopen):
        answer, metadata = openai_responses_answer(
            _packet(),
            api_key="test-key",
            model="gpt-test",
            base_url="https://example.invalid/v1",
        )

    assert captured["url"] == "https://example.invalid/v1/responses"
    assert captured["payload"]["store"] is False
    assert "tools" not in captured["payload"]
    assert captured["payload"]["text"]["format"]["type"] == "json_schema"
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert answer["status"] == "answer"
    assert metadata["usage"]["total_tokens"] == 120


def test_validate_answer_rejects_ref_not_present_in_packet():
    answer = {
        "status": "answer",
        "claims": [
            {"text": "Unsupported citation", "evidence_refs": ["node:missing"]}
        ],
        "missing_identifiers": [],
    }
    with pytest.raises(BlindAnswerError, match="absent from packet"):
        validate_answer(answer, _packet())


def test_run_blind_answers_writes_oracle_blind_shipping_eligible_metadata(tmp_path):
    inputs = tmp_path / "inputs"
    outputs = tmp_path / "answers"
    inputs.mkdir()
    (inputs / "packet1.json").write_text(
        json.dumps(_packet()) + "\n", encoding="utf-8"
    )

    def fake_urlopen(request, timeout):
        return _FakeHTTPResponse(_provider_response(model="gpt-test"))

    with patch("feynmap.p2_4e_blind_answer.urllib.request.urlopen", fake_urlopen):
        run = run_blind_answers(
            inputs,
            outputs,
            api_key="test-key",
            model="gpt-test",
            base_url="https://example.invalid/v1",
        )

    saved = json.loads((outputs / "run.json").read_text(encoding="utf-8"))
    answer = json.loads((outputs / "packet1.json").read_text(encoding="utf-8"))
    assert run == saved
    assert saved["oracle_exposure"] is False
    assert saved["eligible_for_shipping_decision"] is True
    assert saved["isolation"]["scoring_oracle_available_to_model_process"] is False
    assert saved["provider_usage"] == {
        "input_tokens": 100,
        "output_tokens": 20,
        "total_tokens": 120,
    }
    assert answer["claims"][0]["evidence_refs"] == ["node:1"]
