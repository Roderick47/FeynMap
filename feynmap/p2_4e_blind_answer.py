"""Oracle-isolated downstream answer runner for frozen P2.4d model packets.

This module intentionally has no imports from FeynMap. It accepts only an input
folder of already-exported ``feynmap.p2_4d_model_input.v1`` packets and writes
answer JSON plus model-run metadata. The scoring oracle and source fixture are
not inputs to this process.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

PACKET_SCHEMA = "feynmap.p2_4d_model_input.v1"
RUN_SCHEMA = "feynmap.p2_4d_model_run.v1"
DEFAULT_MODEL = "gpt-6-luna"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class BlindAnswerError(RuntimeError):
    """The isolated provider run could not produce a valid grounded answer."""


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def answer_json_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["answer", "need_more_context"]},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "evidence_refs"],
                    "additionalProperties": False,
                },
            },
            "missing_identifiers": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["status", "claims", "missing_identifiers"],
        "additionalProperties": False,
    }


def _all_packet_refs(packet: Mapping[str, Any]) -> Set[str]:
    refs = packet.get("evidence_refs")
    if not isinstance(refs, Mapping):
        raise BlindAnswerError("packet evidence_refs must be an object")
    result: Set[str] = set()
    for values in refs.values():
        if not isinstance(values, list):
            raise BlindAnswerError("packet evidence ref groups must be lists")
        result.update(str(item) for item in values)
    return result


def validate_packet(packet: Mapping[str, Any], *, path: Optional[Path] = None) -> None:
    label = str(path) if path is not None else "packet"
    if packet.get("schema") != PACKET_SCHEMA:
        raise BlindAnswerError(label + ": unexpected packet schema")
    packet_id = packet.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id:
        raise BlindAnswerError(label + ": packet_id must be a non-empty string")
    if not isinstance(packet.get("question"), str) or not packet["question"].strip():
        raise BlindAnswerError(label + ": question must be a non-empty string")
    if not isinstance(packet.get("context"), Mapping):
        raise BlindAnswerError(label + ": context must be an object")
    _all_packet_refs(packet)
    forbidden = {
        "arm",
        "expected_status",
        "expected_missing_identifiers",
        "required_claims",
        "required_behavior_patterns",
        "support_symbols",
        "support_index",
        "unsupported_traps",
    }
    leaked = forbidden & set(packet)
    if leaked:
        raise BlindAnswerError(label + ": scorer-only fields leaked: " + ", ".join(sorted(leaked)))


def validate_answer(answer: Mapping[str, Any], packet: Mapping[str, Any]) -> Dict[str, Any]:
    status = answer.get("status")
    if status not in {"answer", "need_more_context"}:
        raise BlindAnswerError("provider answer status must be answer or need_more_context")
    claims = answer.get("claims")
    missing = answer.get("missing_identifiers")
    if not isinstance(claims, list):
        raise BlindAnswerError("provider answer claims must be a list")
    if not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
        raise BlindAnswerError("provider answer missing_identifiers must be a list of strings")
    allowed = _all_packet_refs(packet)
    normalized_claims: List[Dict[str, Any]] = []
    for position, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            raise BlindAnswerError("claim %d must be an object" % position)
        text = claim.get("text")
        refs = claim.get("evidence_refs")
        if not isinstance(text, str) or not text.strip():
            raise BlindAnswerError("claim %d text must be non-empty" % position)
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise BlindAnswerError("claim %d evidence_refs must be strings" % position)
        invalid = sorted(set(refs) - allowed)
        if invalid:
            raise BlindAnswerError(
                "claim %d cites refs absent from packet: %s" % (position, ", ".join(invalid))
            )
        normalized_claims.append({"text": text, "evidence_refs": list(refs)})
    if status == "answer" and not normalized_claims:
        raise BlindAnswerError("answer status requires at least one cited claim")
    if status == "need_more_context" and normalized_claims:
        raise BlindAnswerError("need_more_context must not contain factual claims")
    return {
        "status": str(status),
        "claims": normalized_claims,
        "missing_identifiers": [str(item) for item in missing],
    }


def _response_output_text(response: Mapping[str, Any]) -> str:
    parts: List[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, Mapping) and content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    if not parts:
        raise BlindAnswerError("provider response did not contain output_text")
    return "\n".join(parts)


def _usage(response: Mapping[str, Any]) -> Dict[str, int]:
    raw = response.get("usage")
    if not isinstance(raw, Mapping):
        return {}
    result: Dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = raw.get(key)
        if value is not None:
            result[key] = int(value)
    return result


def openai_responses_answer(
    packet: Mapping[str, Any],
    *,
    api_key: str,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 120.0,
    max_output_tokens: int = 1200,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not api_key:
        raise BlindAnswerError("OpenAI API key is required")
    validate_packet(packet)
    system = (
        "You are an oracle-blind code-evidence answerer. You receive exactly one "
        "FeynMap model packet. Use only facts explicitly present in that packet. "
        "Do not infer absent implementation, runtime, database, network, framework, "
        "or provider behavior. Every factual claim must cite one or more evidence_refs "
        "that appear in the packet. If the requested behavior is unresolved or the "
        "packet is insufficient, return need_more_context with no factual claims."
    )
    request_payload = {
        "model": model,
        "store": False,
        "max_output_tokens": int(max_output_tokens),
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system}]},
            {
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": "Answer this packet exactly under its answer contract:\n" + compact_json(packet),
                }],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "feynmap_grounded_answer",
                "description": "Source-grounded answer using only evidence refs supplied in the packet.",
                "strict": True,
                "schema": answer_json_schema(),
            }
        },
    }
    url = base_url.rstrip("/") + "/responses"
    request = urllib.request.Request(
        url,
        data=json.dumps(request_payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "FeynMap-P2.4e-oracle-blind/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout)) as response_handle:
            raw = response_handle.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise BlindAnswerError("provider HTTP %s: %s" % (exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise BlindAnswerError("provider request failed: %s" % exc) from exc
    try:
        response = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BlindAnswerError("provider returned non-JSON response") from exc
    if response.get("status") not in {"completed", None}:
        raise BlindAnswerError("provider response status was %r" % response.get("status"))
    text = _response_output_text(response)
    try:
        answer_raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BlindAnswerError("provider output_text was not valid JSON") from exc
    if not isinstance(answer_raw, Mapping):
        raise BlindAnswerError("provider structured answer must be a JSON object")
    answer = validate_answer(answer_raw, packet)
    metadata = {
        "response_id": response.get("id"),
        "model": response.get("model") or model,
        "usage": _usage(response),
    }
    return answer, metadata


def _sum_usage(rows: Iterable[Mapping[str, Any]]) -> Dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    seen = False
    for row in rows:
        usage = row.get("usage")
        if not isinstance(usage, Mapping):
            continue
        seen = True
        for key in totals:
            value = usage.get(key)
            if value is not None:
                totals[key] += int(value)
    return totals if seen else {}


def run_blind_answers(
    input_dir: Path,
    output_dir: Path,
    *,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 120.0,
    max_output_tokens: int = 1200,
    delay_seconds: float = 0.0,
) -> Dict[str, Any]:
    input_dir = Path(input_dir).resolve()
    output_dir = Path(output_dir).resolve()
    packet_paths = sorted(input_dir.glob("*.json"))
    if not packet_paths:
        raise BlindAnswerError("no model packets found in %s" % input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("*.json"):
        stale.unlink()
    provider_rows: List[Dict[str, Any]] = []
    actual_models: Set[str] = set()
    for position, path in enumerate(packet_paths):
        packet = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(packet, Mapping):
            raise BlindAnswerError(str(path) + ": packet must be a JSON object")
        validate_packet(packet, path=path)
        packet_id = str(packet["packet_id"])
        if path.stem != packet_id:
            raise BlindAnswerError(str(path) + ": filename does not match packet_id")
        answer, metadata = openai_responses_answer(
            packet,
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=timeout,
            max_output_tokens=max_output_tokens,
        )
        (output_dir / (packet_id + ".json")).write_text(
            json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        provider_rows.append({"packet_id": packet_id, **metadata})
        if metadata.get("model"):
            actual_models.add(str(metadata["model"]))
        if delay_seconds > 0 and position + 1 < len(packet_paths):
            time.sleep(float(delay_seconds))
    run_model = next(iter(actual_models)) if len(actual_models) == 1 else model
    run = {
        "schema": RUN_SCHEMA,
        "provider": "openai_responses",
        "model": run_model,
        "requested_model": model,
        "oracle_exposure": False,
        "eligible_for_shipping_decision": True,
        "provider_usage": _sum_usage(provider_rows),
        "packet_count": len(packet_paths),
        "isolation": {
            "runner_input": "oracle-free model_inputs directory only",
            "source_fixture_available_to_model_process": False,
            "scoring_oracle_available_to_model_process": False,
            "provider_tools_enabled": False,
            "provider_storage_requested": False,
        },
        "responses": provider_rows,
        "notes": (
            "Generated by the P2.4e oracle-isolated runner. The model process receives "
            "only frozen model packets and no source fixture, scorer index, or gold labels."
        ),
    }
    (output_dir / "run.json").write_text(
        json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return run


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default=os.environ.get("FEYNMAP_BLIND_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-output-tokens", type=int, default=1200)
    parser.add_argument("--delay-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    api_key = os.environ.get(args.api_key_env, "")
    if not api_key:
        raise SystemExit("missing provider credential in environment variable %s" % args.api_key_env)
    run = run_blind_answers(
        Path(args.input),
        Path(args.output),
        api_key=api_key,
        model=str(args.model),
        base_url=str(args.base_url),
        timeout=float(args.timeout),
        max_output_tokens=int(args.max_output_tokens),
        delay_seconds=float(args.delay_seconds),
    )
    print(json.dumps({
        "provider": run["provider"],
        "model": run["model"],
        "packet_count": run["packet_count"],
        "oracle_exposure": run["oracle_exposure"],
        "eligible_for_shipping_decision": run["eligible_for_shipping_decision"],
        "provider_usage": run["provider_usage"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
