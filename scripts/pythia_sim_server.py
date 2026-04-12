#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

from pythia_sim_core import (
    BOOTSTRAP_PYTHIA_TOOL,
    EXPLAIN_STATUS_CODES_TOOL,
    FIND_DECAY_CHAIN_TOOL,
    LIST_ROOTS_TOOL,
    RUN_SIMULATION_TOOL,
    SEARCH_EXAMPLES_TOOL,
    SUMMARIZE_EVENT_RECORD_TOOL,
    TRACE_PARTICLE_LINEAGE_TOOL,
    PythiaSimError,
    PythiaSimulationRunner,
)


SERVER_NAME = "pythia-sim"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOL_VERSIONS = (    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


def _write_message(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _write_error(message_id: Any, code: int, message: str) -> None:
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
    )

def build_tool_result(summary: str, payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    result = {
        "content": [{"type": "text", "text": summary}],
        "structuredContent": payload,
    }
    if is_error:
        result["isError"] = True
    return result


def _truncate_text_block(text: str, *, limit: int = 1600) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 18].rstrip() + "\n...[truncated]"


def _append_output_block(lines: list[str], title: str, text: Any, *, limit: int = 1600) -> None:
    if not isinstance(text, str):
        return
    trimmed = _truncate_text_block(text, limit=limit)
    if not trimmed:
        return
    lines.append("")
    lines.append(f"{title}:")
    lines.append(trimmed)


def _top_count_summary(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return "none"
    parts: list[str] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        count = item.get("count")
        if key is None or count is None:
            continue
        parts.append(f"{key}={count}")
    return ", ".join(parts) if parts else "none"


def _format_lineage_path(path: Any) -> str:
    if not isinstance(path, list) or not path:
        return ""
    nodes: list[str] = []
    for node in path:
        if not isinstance(node, dict):
            continue
        index = node.get("index")
        pdg_id = node.get("id")
        status = node.get("status")
        nodes.append(f"{index}:{pdg_id}[{status}]")
    return " -> ".join(nodes)


def _format_decay_match_sequence(sequence: Any) -> str:
    if not isinstance(sequence, list) or not sequence:
        return ""
    steps: list[str] = []
    for node in sequence:
        if not isinstance(node, dict):
            continue
        steps.append(f"{node.get('index')}:{node.get('id')}")
    return " -> ".join(steps)


def _summarize_roots(payload: dict[str, Any]) -> str:
    lines = [f"default_alias: {payload['default_alias']}"]
    for root in payload["roots"]:
        status = root["build_status"]
        compiler = root["detected_compiler"] or "unknown"
        ready = "yes" if root["standalone_execution_available"] else "no"
        lines.append(
            f"{root['alias']}: status={status}, compiler={compiler}, standalone_execution_available={ready}, path={root['path']}"
        )
    return "\n".join(lines)

def _summarize_bootstrap(payload: dict[str, Any]) -> str:
    lines = [
        f"ok: {payload.get('ok', False)}",
        f"alias: {payload.get('alias', 'unknown')}",
        f"path: {payload.get('path', 'unknown')}",
        f"registry_path: {payload.get('registry_path', 'unknown')}",
    ]
    _append_output_block(lines, "bootstrap logs", payload.get("logs"), limit=3000)
    return "\n".join(lines)


def _summarize_run(payload: dict[str, Any]) -> str:
    compile_result = payload.get("compile", {})
    run_result = payload.get("run", {})
    lines = [
        f"run_id: {payload['run_id']}",
        f"root_alias: {payload['root_alias']}",
        f"bootstrap_performed: {payload['bootstrap_performed']}",
        f"compile_ok: {compile_result['ok']} (exit_code={compile_result['exit_code']})",
        f"run_ok: {run_result['ok']} (exit_code={run_result['exit_code']}, timed_out={run_result['timed_out']})",
    ]
    command_summary = compile_result.get("command_summary")
    if isinstance(command_summary, str) and command_summary:
        lines.append(f"compile_commands: {command_summary}")
    if payload.get("failure_artifacts_path"):
        lines.append(f"failure_artifacts_path: {payload['failure_artifacts_path']}")
    _append_output_block(lines, "compile stdout", compile_result.get("stdout"), limit=1200)
    _append_output_block(lines, "compile stderr", compile_result.get("stderr"), limit=1200)
    _append_output_block(lines, "run stdout", run_result.get("stdout"), limit=1200)
    _append_output_block(lines, "run stderr", run_result.get("stderr"), limit=1200)
    return "\n".join(lines)


def _summarize_example_search(payload: dict[str, Any]) -> str:
    lines = [
        f"root_alias: {payload['root_alias']}",
        f"examples_path: {payload['examples_path']}",
        f"query: {payload['query']!r}",
        f"safety_mode: {payload['safety_mode']}",
        f"include_cmnd: {payload['include_cmnd']}",
        f"matches: {payload['match_count']}",
        f"filtered_matches: {payload['filtered_match_count']}",
        f"returned: {payload['returned_count']}",
    ]
    if payload.get("truncated"):
        lines.append("truncated: true")
    results = payload.get("results", [])
    if isinstance(results, list) and results:
        lines.append("")
        lines.append("results:")
        for result in results[:5]:
            if not isinstance(result, dict):
                continue
            location = result.get("name", result.get("path", "unknown"))
            line_number = result.get("line_number")
            if line_number is not None:
                location = f"{location}:{line_number}"
            lines.append(
                f"- {location} [{result.get('file_kind', '?')}, {result.get('safety', '?')}]"
            )
            path = result.get("path")
            if isinstance(path, str):
                lines.append(f"  path: {path}")
            snippet = result.get("snippet")
            if isinstance(snippet, str):
                lines.append(f"  snippet: {_truncate_text_block(snippet, limit=300)}")
    return "\n".join(lines)


def _summarize_event_record(payload: dict[str, Any]) -> str:
    if not payload.get("analysis_ok"):
        return _summarize_run(payload)
    record = payload.get("event_record", {})
    lines = [
        f"run_id: {payload['run_id']}",
        f"root_alias: {payload['root_alias']}",
        f"bootstrap_performed: {payload.get('bootstrap_performed')}",
        f"accepted_event_count: {record.get('accepted_event_count')}",
        f"failed_event_count: {record.get('failed_event_count')}",
        f"stored_example_event_count: {record.get('stored_example_event_count')}",
        f"top_particle_pdg_counts: {_top_count_summary(record.get('top_particle_pdg_counts'))}",
        f"top_final_state_pdg_counts: {_top_count_summary(record.get('top_final_state_pdg_counts'))}",
        f"top_status_code_counts: {_top_count_summary(record.get('top_status_code_counts'))}",
        f"top_decay_chain_counts: {_top_count_summary(record.get('top_decay_chain_counts'))}",
    ]
    return "\n".join(lines)


def _summarize_lineage_trace(payload: dict[str, Any]) -> str:
    if not payload.get("analysis_ok"):
        return payload.get("message", _summarize_run(payload))
    particle = payload.get("selected_particle", {})
    selected_event = payload.get("selected_event", {})
    lines = [
        f"run_id: {payload['run_id']}",
        f"root_alias: {payload['root_alias']}",
        f"used_existing_run: {payload.get('used_existing_run')}",
        f"selected_event: accepted_event_index={selected_event.get('accepted_event_index')} score={selected_event.get('score')}",
        f"selected_particle: index={particle.get('index')} id={particle.get('id')} status={particle.get('status')}",
        f"selected_particle_kinematics: pt={particle.get('pt')} energy={particle.get('energy')} eta={particle.get('eta')} charge={particle.get('charge')}",
        f"lineage_paths: {len(payload.get('lineage_paths', []))}",
        f"matched_stop_nodes: {len(payload.get('matched_stop_nodes', []))}",
    ]
    lineage_paths = payload.get("lineage_paths", [])
    if isinstance(lineage_paths, list) and lineage_paths:
        lines.append("")
        lines.append("representative_lineage_paths:")
        for path in lineage_paths[:3]:
            rendered = _format_lineage_path(path)
            if rendered:
                lines.append(f"- {rendered}")
    return "\n".join(lines)


def _summarize_decay_chain(payload: dict[str, Any]) -> str:
    if not payload.get("analysis_ok"):
        return payload.get("message", _summarize_run(payload))
    chain = payload.get("decay_chain", {})
    lines = [
        f"run_id: {payload['run_id']}",
        f"root_alias: {payload['root_alias']}",
        f"used_existing_run: {payload.get('used_existing_run')}",
        f"chain_key: {chain.get('chain_key')}",
        f"match_count: {chain.get('match_count')}",
        f"representative_matches: {len(chain.get('representative_matches', []))}",
    ]
    representative_matches = chain.get("representative_matches", [])
    if isinstance(representative_matches, list) and representative_matches:
        lines.append("")
        lines.append("representative_matches_detail:")
        for item in representative_matches[:3]:
            if not isinstance(item, dict):
                continue
            lines.append(f"- accepted_event_index={item.get('accepted_event_index')}")
            matches = item.get("matches", [])
            if isinstance(matches, list):
                for sequence in matches[:3]:
                    rendered = _format_decay_match_sequence(sequence)
                    if rendered:
                        lines.append(f"  {rendered}")
    return "\n".join(lines)


def _summarize_status_codes(payload: dict[str, Any]) -> str:
    explanations = payload.get("status_code_explanations", [])
    lines = [f"status_codes: {len(explanations)}"]
    for item in explanations[:8]:
        if not isinstance(item, dict) or "code" not in item or "description" not in item:
            continue
        observed_count = item.get("observed_count")
        count_text = "" if observed_count is None else f" (observed_count={observed_count})"
        lines.append(f"{item['code']}: {item['description']}{count_text}")
    return "\n".join(lines)


def _read_messages():
    while True:
        first_line = sys.stdin.buffer.readline()
        if not first_line:
            return
        if not first_line.strip():
            continue
        if first_line.lower().startswith(b"content-length:"):
            try:
                length = int(first_line.split(b":", 1)[1].strip())
            except ValueError:
                raise SystemExit("Invalid Content-Length header")
            while True:
                header_line = sys.stdin.buffer.readline()
                if not header_line or header_line in {b"\n", b"\r\n"}:
                    break
            body = sys.stdin.buffer.read(length)
            yield json.loads(body.decode("utf-8"))
            continue
        yield json.loads(first_line.decode("utf-8"))


def main() -> int:
    runner = PythiaSimulationRunner()
    initialized = False

    for message in _read_messages():
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        message_id = message.get("id")
        params = message.get("params") or {}

        if method == "initialize":
            client_version = params.get("protocolVersion")
            negotiated = (
                client_version
                if isinstance(client_version, str)
                and client_version in SUPPORTED_PROTOCOL_VERSIONS
                else "2025-03-26"
            )
            initialized = True
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": message_id,
                    "result": {
                        "protocolVersion": negotiated,
                        "capabilities": {
                            "tools": {
                                "listChanged": False,
                            },
                        },
                        "serverInfo": {
                            "name": SERVER_NAME,
                            "version": SERVER_VERSION,
                        },
                    },
                }
            )
            continue

        if method == "notifications/initialized":
            continue

        if method == "ping":
            _write_message({"jsonrpc": "2.0", "id": message_id, "result": {}})
            continue

        if method == "tools/list":
            if not initialized:
                _write_error(message_id, -32002, "Server must be initialized before listing tools.")
                continue
            payload = {
                "tools": [
                    LIST_ROOTS_TOOL,
                    BOOTSTRAP_PYTHIA_TOOL,
                    SEARCH_EXAMPLES_TOOL,
                    RUN_SIMULATION_TOOL,
                    SUMMARIZE_EVENT_RECORD_TOOL,
                    TRACE_PARTICLE_LINEAGE_TOOL,
                    FIND_DECAY_CHAIN_TOOL,
                    EXPLAIN_STATUS_CODES_TOOL,
                ]
            }
            _write_message({"jsonrpc": "2.0", "id": message_id, "result": payload})
            continue

        if method == "tools/call":
            if not initialized:
                _write_error(message_id, -32002, "Server must be initialized before calling tools.")
                continue
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if tool_name == "list_pythia_roots":
                try:
                    payload = runner.list_pythia_roots()
                    result = build_tool_result(_summarize_roots(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    if exc.failure_artifacts_path:
                        payload["failure_artifacts_path"] = exc.failure_artifacts_path
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "bootstrap_pythia":
                try:
                    payload = runner.bootstrap_pythia(arguments)
                    result = build_tool_result(_summarize_bootstrap(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "search_pythia_examples":
                try:
                    payload = runner.search_pythia_examples(arguments)
                    result = build_tool_result(_summarize_example_search(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    if exc.failure_artifacts_path:
                        payload["failure_artifacts_path"] = exc.failure_artifacts_path
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "run_pythia_simulation":
                try:
                    payload = runner.run_pythia_simulation(arguments)
                    result = build_tool_result(_summarize_run(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    if exc.failure_artifacts_path:
                        payload["failure_artifacts_path"] = exc.failure_artifacts_path
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "summarize_event_record":
                try:
                    payload = runner.summarize_event_record(arguments)
                    result = build_tool_result(_summarize_event_record(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "trace_particle_lineage":
                try:
                    payload = runner.trace_particle_lineage(arguments)
                    result = build_tool_result(_summarize_lineage_trace(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "find_decay_chain":
                try:
                    payload = runner.find_decay_chain(arguments)
                    result = build_tool_result(_summarize_decay_chain(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            if tool_name == "explain_status_codes":
                try:
                    payload = runner.explain_status_codes(arguments)
                    result = build_tool_result(_summarize_status_codes(payload), payload)
                except PythiaSimError as exc:
                    payload = {"message": str(exc)}
                    result = build_tool_result(str(exc), payload, is_error=True)
                _write_message({"jsonrpc": "2.0", "id": message_id, "result": result})
                continue
            _write_error(message_id, -32602, f"Unknown tool: {tool_name}")
            continue

        if method == "prompts/list":
            key = {
                "prompts/list": "prompts",
            }[method]
            _write_message({"jsonrpc": "2.0", "id": message_id, "result": {key: []}})
            continue

        if method and message_id is not None:
            _write_error(message_id, -32601, f"Method not found: {method}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
 
