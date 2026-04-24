#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Mapping, cast

from pythia_sim_core import (
    AnalysisPayloadBase,
    BOOTSTRAP_PYTHIA_TOOL,
    BootstrapPayload,
    CountEntry,
    EXPLAIN_STATUS_CODES_TOOL,
    FIND_DECAY_CHAIN_TOOL,
    DecayChainResult,
    ExampleSearchPayload,
    EventRecordAnalysisPayload,
    LineageNode,
    LIST_ROOTS_TOOL,
    RootListPayload,
    StatusCodeResult,
    RUN_SIMULATION_TOOL,
    SEARCH_EXAMPLES_TOOL,
    SUMMARIZE_EVENT_RECORD_TOOL,
    PythiaSimError,
    TraceLineageAnalysis,
    TRACE_PARTICLE_LINEAGE_TOOL,
    PythiaSimulationRunner,
)


SERVER_NAME = "pythia-sim"
SERVER_VERSION = "0.1.0"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


def _write_message(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _write_error(message_id: object, code: int, message: str) -> None:
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


def build_tool_result(
    summary: str, payload: Mapping[str, object], *, is_error: bool = False
) -> dict[str, object]:
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
    if limit <= 32:
        return normalized[:limit]
    return normalized[: limit - 18].rstrip() + "\n...[truncated]"


def _truncate_line(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 20:
        return text[:limit]
    return text[: limit - 15].rstrip() + " ...[truncated]"


def _collect_lines_with_budget(
    lines: list[str], *, max_lines: int, max_chars: int, from_end: bool
) -> list[str]:
    if max_lines <= 0 or max_chars <= 0:
        return []
    selected: list[str] = []
    total_chars = 0
    iterable = reversed(lines) if from_end else iter(lines)
    for raw_line in iterable:
        line = raw_line
        if not selected and len(line) > max_chars:
            line = _truncate_line(line, limit=max_chars)
        line_cost = len(line) + (1 if selected else 0)
        if selected and total_chars + line_cost > max_chars:
            break
        if not selected and len(line) > max_chars:
            break
        selected.append(line)
        total_chars += line_cost
        if len(selected) >= max_lines:
            break
    if from_end:
        selected.reverse()
    return selected


def _head_tail_text_block(
    text: str,
    *,
    limit: int,
    head_lines: int = 8,
    tail_lines: int = 20,
    head_fraction: float = 0.3,
) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized

    lines = normalized.splitlines()
    notice_template = "...[output shortened; omitted {omitted_lines} middle lines and {omitted_chars} chars]..."
    head_budget = max(160, int(limit * head_fraction))
    head = _collect_lines_with_budget(lines, max_lines=head_lines, max_chars=head_budget, from_end=False)
    remaining_lines = lines[len(head) :] if head else lines
    tail_budget = max(160, limit - sum(len(line) for line in head) - max(len(head) - 1, 0) - 120)
    tail = _collect_lines_with_budget(
        remaining_lines, max_lines=tail_lines, max_chars=tail_budget, from_end=True
    )
    if not tail:
        tail = _collect_lines_with_budget(lines, max_lines=tail_lines, max_chars=tail_budget, from_end=True)
    omitted_lines = max(0, len(lines) - len(head) - len(tail))
    visible_chars = sum(len(line) for line in head) + sum(len(line) for line in tail)
    omitted_chars = max(0, len(normalized) - visible_chars)
    notice = notice_template.format(
        omitted_lines=omitted_lines,
        omitted_chars=omitted_chars,
    )

    parts: list[str] = []
    if head:
        parts.append("\n".join(head))
    parts.append(notice)
    if tail:
        parts.append("\n".join(tail))
    rendered = "\n".join(parts)
    if len(rendered) <= limit:
        return rendered
    tail_only_notice = (
        f"[output shortened; showing last {len(tail)} of {len(lines)} lines, "
        f"omitted {max(0, len(lines) - len(tail))} earlier lines]"
    )
    tail_only_budget = max(120, limit - len(tail_only_notice) - 1)
    tail_only = _collect_lines_with_budget(lines, max_lines=tail_lines, max_chars=tail_only_budget, from_end=True)
    return tail_only_notice + "\n" + "\n".join(tail_only)


def _append_output_block(
    lines: list[str],
    title: str,
    text: object,
    *,
    limit: int = 1600,
    strategy: str = "head",
) -> None:
    if not isinstance(text, str):
        return
    if strategy == "head_tail":
        trimmed = _head_tail_text_block(text, limit=limit)
    elif strategy == "tail":
        trimmed = _head_tail_text_block(text, limit=limit, head_lines=0, tail_lines=24, head_fraction=0.0)
    else:
        trimmed = _truncate_text_block(text, limit=limit)
    if not trimmed:
        return
    lines.append("")
    lines.append(f"{title}:")
    lines.append(trimmed)


def _top_count_summary(items: list[CountEntry] | None) -> str:
    if not items:
        return "none"
    parts = [f"{item['key']}={item['count']}" for item in items[:5]]
    return ", ".join(parts) if parts else "none"


def _format_lineage_path(path: list[LineageNode] | None) -> str:
    if not path:
        return ""
    return " -> ".join(f"{node['index']}:{node['id']}[{node['status']}]" for node in path)


def _format_decay_match_sequence(sequence: list[LineageNode] | None) -> str:
    if not sequence:
        return ""
    return " -> ".join(f"{node['index']}:{node['id']}" for node in sequence)


def _analysis_header_lines(payload: AnalysisPayloadBase) -> list[str]:
    lines = [
        f"run_id: {payload['run_id']}",
        f"root_alias: {payload['root_alias']}",
    ]
    if "bootstrap_performed" in payload:
        lines.append(f"bootstrap_performed: {payload.get('bootstrap_performed')}")
    if "used_existing_run" in payload:
        lines.append(f"used_existing_run: {payload.get('used_existing_run')}")
    return lines


def _summarize_roots(payload: RootListPayload) -> str:
    lines = [f"default_alias: {payload['default_alias']}"]
    for root in payload["roots"]:
        status = root["build_status"]
        compiler = root["detected_compiler"] or "unknown"
        ready = "yes" if root["standalone_execution_available"] else "no"
        lines.append(
            f"{root['alias']}: status={status}, compiler={compiler}, standalone_execution_available={ready}, path={root['path']}"
        )
    return "\n".join(lines)

def _summarize_bootstrap(payload: BootstrapPayload) -> str:
    lines = [
        f"ok: {payload.get('ok', False)}",
        f"alias: {payload.get('alias', 'unknown')}",
        f"path: {payload.get('path', 'unknown')}",
        f"registry_path: {payload.get('registry_path', 'unknown')}",
    ]
    _append_output_block(lines, "bootstrap logs", payload.get("logs"), limit=3000)
    return "\n".join(lines)


def _summarize_run(payload: AnalysisPayloadBase) -> str:
    compile_result = payload["compile"]
    run_result = payload["run"]
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
    _append_output_block(
        lines,
        "compile stdout",
        compile_result.get("stdout"),
        limit=1600,
        strategy="head_tail",
    )
    _append_output_block(
        lines,
        "compile stderr",
        compile_result.get("stderr"),
        limit=1600,
        strategy="head_tail",
    )
    _append_output_block(
        lines,
        "run stdout",
        run_result.get("stdout"),
        limit=2800,
        strategy="head_tail",
    )
    _append_output_block(
        lines,
        "run stderr",
        run_result.get("stderr"),
        limit=2200,
        strategy="head_tail",
    )
    return "\n".join(lines)


def _summarize_example_search(payload: ExampleSearchPayload) -> str:
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
    results = payload["results"]
    if results:
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


def _summarize_event_record(payload: EventRecordAnalysisPayload) -> str:
    if not payload.get("analysis_ok"):
        return _summarize_run(payload)
    record = payload["event_record"]
    lines = _analysis_header_lines(payload)
    lines.extend(
        [
        f"accepted_event_count: {record['accepted_event_count']}",
        f"failed_event_count: {record['failed_event_count']}",
        f"stored_example_event_count: {record['stored_example_event_count']}",
        f"top_particle_pdg_counts: {_top_count_summary(record['top_particle_pdg_counts'])}",
        f"top_final_state_pdg_counts: {_top_count_summary(record['top_final_state_pdg_counts'])}",
        f"top_status_code_counts: {_top_count_summary(record['top_status_code_counts'])}",
        f"top_decay_chain_counts: {_top_count_summary(record['top_decay_chain_counts'])}",
        ]
    )
    return "\n".join(lines)


def _summarize_lineage_trace(payload: TraceLineageAnalysis) -> str:
    if not payload.get("analysis_ok"):
        return payload.get("message", _summarize_run(payload))
    particle = payload["selected_particle"]
    selected_event = payload["selected_event"]
    lines = _analysis_header_lines(payload)
    lines.extend([
        f"selected_event: accepted_event_index={selected_event.get('accepted_event_index')} score={selected_event.get('score')}",
        f"selected_particle: index={particle.get('index')} id={particle.get('id')} status={particle.get('status')}",
        f"selected_particle_kinematics: pt={particle.get('pt')} energy={particle.get('energy')} eta={particle.get('eta')} charge={particle.get('charge')}",
        f"lineage_paths: {len(payload['lineage_paths'])}",
        f"matched_stop_nodes: {len(payload['matched_stop_nodes'])}",
    ])
    lineage_paths = payload["lineage_paths"]
    if lineage_paths:
        lines.append("")
        lines.append("representative_lineage_paths:")
        for path in lineage_paths[:3]:
            rendered = _format_lineage_path(path)
            if rendered:
                lines.append(f"- {rendered}")
    return "\n".join(lines)


def _summarize_decay_chain(payload: DecayChainResult) -> str:
    if not payload.get("analysis_ok"):
        return payload.get("message", _summarize_run(payload))
    chain = payload["decay_chain"]
    summary_match_count = chain.get("summary_match_count")
    example_snapshot_match_count = chain.get("example_snapshot_match_count")
    lines = _analysis_header_lines(payload)
    lines.extend([
        f"chain_key: {chain.get('chain_key')}",
        f"match_semantics: {chain.get('match_semantics')}",
        f"summary_histogram_complete: {chain.get('summary_histogram_complete')}",
        f"summary_count_source: {chain.get('summary_count_source')}",
        f"summary_match_count: {summary_match_count}",
        f"example_snapshot_match_count: {example_snapshot_match_count}",
        f"example_snapshot_match_event_count: {chain.get('example_snapshot_match_event_count')}",
        f"stored_example_event_count: {chain.get('stored_example_event_count')}",
        f"representative_matches: {len(chain.get('representative_matches', []))}",
    ])
    if summary_match_count != example_snapshot_match_count:
        lines.append(
            "count_scope_note: summary_match_count comes from the stored full-run histogram; "
            "example_snapshot_match_count comes from the stored example snapshots used for representatives."
        )
    representative_matches = chain["representative_matches"]
    if representative_matches:
        lines.append("")
        lines.append("representative_matches_detail:")
        for item in representative_matches[:3]:
            lines.append(f"- accepted_event_index={item['accepted_event_index']}")
            for sequence in item["matches"][:3]:
                rendered = _format_decay_match_sequence(sequence)
                if rendered:
                    lines.append(f"  {rendered}")
    return "\n".join(lines)


def _summarize_status_codes(payload: StatusCodeResult) -> str:
    explanations = payload["status_code_explanations"]
    lines = [f"status_codes: {len(explanations)}"]
    for item in explanations[:8]:
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
        message = cast(dict[str, object], message)
        method = message.get("method")
        message_id = message.get("id")
        params_obj = message.get("params")
        params = cast(dict[str, object], params_obj) if isinstance(params_obj, dict) else {}

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
            arguments_obj = params.get("arguments")
            arguments = cast(Mapping[str, object], arguments_obj) if isinstance(arguments_obj, dict) else {}
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
 
