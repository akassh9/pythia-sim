from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_ROOT = PLUGIN_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import pythia_sim_core as core
import pythia_sim_server as server


def _make_fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "pythia"
    (root / "include" / "Pythia8").mkdir(parents=True)
    (root / "include" / "Pythia8" / "Pythia.h").write_text("// header\n", encoding="utf-8")
    (root / "examples").mkdir()
    (root / "examples" / "Makefile").write_text("all:\n\t@true\n", encoding="utf-8")
    (root / "share" / "Pythia8" / "xmldoc").mkdir(parents=True)
    (root / "lib").mkdir()
    (root / "lib" / "libpythia8.a").write_text("", encoding="utf-8")
    return root


def _write_makefile_inc(root: Path, compiler: str = "g++") -> None:
    payload = f"""
PREFIX_INCLUDE={root / "include"}
PREFIX_LIB={root / "lib"}
CXX={compiler}
CXX_COMMON=-O2 -std=c++11 -Wall
OBJ_COMMON=
"""
    (root / "Makefile.inc").write_text(payload.strip() + "\n", encoding="utf-8")


def _write_examples_makefile(root: Path) -> None:
    payload = """
all:
\t@true

%: $(PYTHIA) %.cc
\t$(CXX) $@.cc -o $@ $(CXX_COMMON)

main141: $(PYTHIA) $$@.cc
ifeq ($(ROOT_USE),true)
\t$(CXX) $@.cc -o $@ -w $(CXX_COMMON) $(ROOT_OPTS)
else
\t$(error Error: $@ requires ROOT)
endif
"""
    (root / "examples" / "Makefile").write_text(payload.strip() + "\n", encoding="utf-8")


def _write_registry(tmp_path: Path, root_path: Path) -> Path:
    registry_path = tmp_path / "roots.json"
    registry_path.write_text(
        json.dumps(
            {
                "default_alias": "local",
                "roots": [{"alias": "local", "path": str(root_path)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return registry_path


def _write_fake_cxx(path: Path, *, executable_body: str) -> None:
    payload = f"""#!/bin/sh
set -eu
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then
    out="$arg"
    break
  fi
  prev="$arg"
done
if [ -z "$out" ]; then
  echo "missing -o output path" >&2
  exit 1
fi
cat > "$out" <<'EOF'
#!/bin/sh
{executable_body}
EOF
chmod +x "$out"
"""
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o755)


def _make_runner(tmp_path: Path) -> core.PythiaSimulationRunner:
    root = _make_fake_root(tmp_path)
    _write_makefile_inc(root)
    registry_path = _write_registry(tmp_path, root)
    plugin_root = tmp_path / "plugin"
    plugin_root.mkdir()
    state_root = tmp_path / "state"
    return core.PythiaSimulationRunner(
        plugin_root=plugin_root, registry_path=registry_path, state_root=state_root
    )


def _terminal_output_block(name: str, kind: str, text: str) -> str:
    return (
        f"{core.TERMINAL_OUTPUT_BEGIN_PREFIX}name={name} kind={kind}>>\n"
        f"{text}"
        f"{'' if text.endswith(chr(10)) else chr(10)}"
        f"{core.TERMINAL_OUTPUT_END_PREFIX}name={name} kind={kind}>>\n"
    )


def _write_event_record_bundle(
    plugin_root: Path,
    run_id: str = "trace123",
    *,
    decay_chain_counts: dict[str, int] | None = None,
) -> Path:
    completed_dir = plugin_root / ".runs" / "completed" / run_id
    completed_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": 1,
        "requested_event_count": 10,
        "accepted_event_count": 8,
        "failed_event_count": 2,
        "particle_pdg_counts": {"23": 4, "13": 4, "-13": 4, "2": 8, "-2": 8},
        "final_state_pdg_counts": {"13": 4, "-13": 4},
        "status_code_counts": {"-23": 1, "-21": 2, "1": 2},
        "final_state_multiplicity_counts": {"2": 4},
        "decay_chain_counts": (
            {"23>13": 4, "23>-13": 4}
            if decay_chain_counts is None
            else decay_chain_counts
        ),
    }
    examples = {
        "version": 1,
        "stored_event_count": 1,
        "events": [
            {
                "accepted_event_index": 0,
                "score": 42.0,
                "selected_particle_indices": [6],
                "particles": [
                    {
                        "index": 1,
                        "id": 2,
                        "status": -21,
                        "mother1": 0,
                        "mother2": 0,
                        "daughter1": 5,
                        "daughter2": 5,
                        "pt": 0.0,
                        "energy": 4000.0,
                        "eta": 0.0,
                        "charge": 0.6666667,
                        "is_final": False,
                    },
                    {
                        "index": 2,
                        "id": -2,
                        "status": -21,
                        "mother1": 0,
                        "mother2": 0,
                        "daughter1": 5,
                        "daughter2": 5,
                        "pt": 0.0,
                        "energy": 4000.0,
                        "eta": 0.0,
                        "charge": -0.6666667,
                        "is_final": False,
                    },
                    {
                        "index": 5,
                        "id": 23,
                        "status": -23,
                        "mother1": 1,
                        "mother2": 2,
                        "daughter1": 6,
                        "daughter2": 7,
                        "pt": 12.0,
                        "energy": 90.0,
                        "eta": 0.1,
                        "charge": 0.0,
                        "is_final": False,
                    },
                    {
                        "index": 6,
                        "id": 13,
                        "status": 1,
                        "mother1": 5,
                        "mother2": 5,
                        "daughter1": 0,
                        "daughter2": 0,
                        "pt": 42.0,
                        "energy": 43.0,
                        "eta": 0.2,
                        "charge": -1.0,
                        "is_final": True,
                    },
                    {
                        "index": 7,
                        "id": -13,
                        "status": 1,
                        "mother1": 5,
                        "mother2": 5,
                        "daughter1": 0,
                        "daughter2": 0,
                        "pt": 38.0,
                        "energy": 39.0,
                        "eta": -0.2,
                        "charge": 1.0,
                        "is_final": True,
                    },
                ],
            }
        ],
    }
    metadata = {
        "run_id": run_id,
        "root_alias": "local",
        "bootstrap_performed": False,
        "compile": {"ok": True, "exit_code": 0, "stdout": "", "stderr": ""},
        "run": {"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "timed_out": False},
        "created_at_epoch_sec": 1,
    }
    (completed_dir / core.EVENT_RECORD_SUMMARY_ARTIFACT).write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (completed_dir / core.EVENT_RECORD_EXAMPLES_ARTIFACT).write_text(
        json.dumps(examples, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (completed_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return completed_dir


def test_load_registry_defaults_build_command(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    registry_path = _write_registry(tmp_path, root)
    registry = core.load_registry(registry_path)
    assert registry.default_alias == "local"
    assert registry.roots["local"].build_command == core.DEFAULT_BUILD_COMMAND


def test_load_registry_from_env_root(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)

    registry = core.load_registry(
        None,
        plugin_root=tmp_path / "plugin",
        env={
            core.PYTHIA_SIM_ROOT_ENV: str(root),
            core.PYTHIA_SIM_ROOT_ALIAS_ENV: "env-root",
        },
        platform="linux",
    )

    assert registry.default_alias == "env-root"
    assert registry.roots["env-root"].path == root.resolve()
    assert registry.roots["env-root"].build_command == core.DEFAULT_BUILD_COMMAND


def test_load_registry_prefers_explicit_registry_path_env_over_root_env(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path / "from-registry")
    registry_path = _write_registry(tmp_path, root)

    registry = core.load_registry(
        None,
        plugin_root=tmp_path / "plugin",
        env={
            core.PYTHIA_SIM_REGISTRY_PATH_ENV: str(registry_path),
            core.PYTHIA_SIM_ROOT_ENV: str(tmp_path / "ignored"),
            core.PYTHIA_SIM_ROOT_ALIAS_ENV: "ignored",
        },
        platform="linux",
    )

    assert registry.default_alias == "local"
    assert registry.roots["local"].path == root.resolve()


def test_load_registry_falls_back_to_legacy_repo_config_when_xdg_file_missing(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path / "legacy-root")
    plugin_root = tmp_path / "plugin"
    (plugin_root / "config").mkdir(parents=True)
    registry_path = plugin_root / "config" / "roots.json"
    registry_path.write_text(
        json.dumps(
            {
                "default_alias": "legacy",
                "roots": [{"alias": "legacy", "path": str(root)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = core.load_registry(
        None,
        plugin_root=plugin_root,
        env={"XDG_CONFIG_HOME": str(tmp_path / "xdg-config")},
        platform="linux",
    )

    assert registry.default_alias == "legacy"
    assert registry.roots["legacy"].path == root.resolve()


def test_load_registry_uses_macos_fallback_after_missing_xdg_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setattr(core.Path, "home", lambda: home)
    root = _make_fake_root(tmp_path / "mac-root")
    registry_path = (
        home / ".pythia-sim" / "roots.json"
    )
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "default_alias": "mac",
                "roots": [{"alias": "mac", "path": str(root)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    registry = core.load_registry(
        None,
        plugin_root=tmp_path / "plugin",
        env={"XDG_CONFIG_HOME": str(tmp_path / "missing-xdg")},
        platform="darwin",
    )

    assert registry.default_alias == "mac"
    assert registry.roots["mac"].path == root.resolve()


def test_resolve_state_root_prefers_override_and_platform_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = core.resolve_state_root(
        env={core.PYTHIA_SIM_STATE_DIR_ENV: str(tmp_path / "override")},
        platform="linux",
    )
    assert override == (tmp_path / "override").resolve()

    xdg_state = core.resolve_state_root(
        env={"XDG_STATE_HOME": str(tmp_path / "xdg-state")},
        platform="linux",
    )
    assert xdg_state == (tmp_path / "xdg-state" / "pythia-sim").resolve()

    home = tmp_path / "home"
    monkeypatch.setattr(core.Path, "home", lambda: home)
    mac_state = core.resolve_state_root(env={}, platform="darwin")
    assert mac_state == (
        home / ".pythia-sim" / "state"
    ).resolve()


def test_runtime_limits_are_raised_for_common_production_runs() -> None:
    assert core.DEFAULT_COMPILE_TIMEOUT_SEC == 60
    assert core.DEFAULT_RUN_TIMEOUT_SEC == 60
    assert core.DEFAULT_MAX_OUTPUT_BYTES == 500_000
    assert core.MAX_COMPILE_TIMEOUT_SEC == 900
    assert core.MAX_RUN_TIMEOUT_SEC == 600
    assert core.MAX_OUTPUT_BYTES == 2_000_000
    assert core.MAX_INTROSPECTION_EVENT_COUNT == 10_000


def test_tool_schemas_expose_updated_runtime_limit_maxima() -> None:
    introspection_tools = [
        core.SUMMARIZE_EVENT_RECORD_TOOL,
        core.TRACE_PARTICLE_LINEAGE_TOOL,
        core.FIND_DECAY_CHAIN_TOOL,
    ]
    for tool in introspection_tools:
        properties = tool["inputSchema"]["properties"]
        assert properties["event_count"]["maximum"] == core.MAX_INTROSPECTION_EVENT_COUNT
        assert properties["compile_timeout_sec"]["maximum"] == core.MAX_COMPILE_TIMEOUT_SEC
        assert properties["run_timeout_sec"]["maximum"] == core.MAX_RUN_TIMEOUT_SEC
        assert properties["max_output_bytes"]["maximum"] == core.MAX_OUTPUT_BYTES

    run_properties = core.RUN_SIMULATION_TOOL["inputSchema"]["properties"]
    assert run_properties["compile_timeout_sec"]["maximum"] == core.MAX_COMPILE_TIMEOUT_SEC
    assert run_properties["run_timeout_sec"]["maximum"] == core.MAX_RUN_TIMEOUT_SEC
    assert run_properties["max_output_bytes"]["maximum"] == core.MAX_OUTPUT_BYTES


def test_parse_makefile_inc_extracts_required_fields(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    _write_makefile_inc(root)
    parsed = core.parse_makefile_inc(root / "Makefile.inc")
    assert parsed["CXX"] == "g++"
    assert parsed["PREFIX_INCLUDE"] == str(root / "include")
    assert parsed["PREFIX_LIB"] == str(root / "lib")
    assert "-std=c++11" in parsed["CXX_COMMON"]


def test_validate_source_rejects_unsafe_calls() -> None:
    source = """
    #include "Pythia8/Pythia.h"
    int main() {
      system("echo nope");
      return 0;
    }
    """
    with pytest.raises(core.PythiaSimError, match="system"):
        core.validate_source_cpp(source)


def test_build_direct_compile_command_uses_root_fields(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    _write_makefile_inc(root)
    make_vars = core.parse_makefile_inc(root / "Makefile.inc")
    command = core.build_direct_compile_command(
        make_vars, source_path=Path("/tmp/source.cpp"), output_path=Path("/tmp/a.out")
    )
    joined = " ".join(command)
    assert command[0] == "g++"
    assert f"-I{root / 'include'}" in joined
    assert f"-L{root / 'lib'}" in joined
    assert "-lpythia8" in joined


def test_search_examples_returns_standalone_cc_and_cmnd_matches(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    root = core.load_registry(runner.registry_path).roots["local"].path
    _write_examples_makefile(root)
    (root / "examples" / "main101.cc").write_text(
        'pythia.readString("HardQCD:all = on");\n',
        encoding="utf-8",
    )
    (root / "examples" / "main101.cmnd").write_text(
        "HardQCD:all = on\nPhaseSpace:pTHatMin = 20.\n",
        encoding="utf-8",
    )

    payload = runner.search_pythia_examples({"query": "HardQCD", "max_results": 5})

    assert payload["root_alias"] == "local"
    assert payload["returned_count"] == 2
    assert [item["name"] for item in payload["results"]] == ["main101.cc", "main101.cmnd"]
    assert all(item["safety"] == core.EXAMPLE_SAFETY_TAG_STANDALONE for item in payload["results"])
    assert payload["filtered_match_count"] == 0


def test_search_examples_filters_external_dependency_matches_by_default(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    root = core.load_registry(runner.registry_path).roots["local"].path
    _write_examples_makefile(root)
    (root / "examples" / "main141.cc").write_text(
        "// ROOT histogram output example\n",
        encoding="utf-8",
    )

    payload = runner.search_pythia_examples({"query": "ROOT"})

    assert payload["match_count"] == 1
    assert payload["filtered_match_count"] == 1
    assert payload["returned_count"] == 0
    assert payload["results"] == []


def test_search_examples_all_mode_returns_external_dependency_match(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    root = core.load_registry(runner.registry_path).roots["local"].path
    _write_examples_makefile(root)
    (root / "examples" / "main141.cc").write_text(
        "// ROOT histogram output example\n",
        encoding="utf-8",
    )

    payload = runner.search_pythia_examples({"query": "ROOT", "safety_mode": "all"})

    assert payload["returned_count"] == 1
    assert payload["results"][0]["name"] == "main141.cc"
    assert payload["results"][0]["safety"] == core.EXAMPLE_SAFETY_TAG_EXTERNAL


def test_search_examples_empty_query_returns_clean_empty_payload(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    root = core.load_registry(runner.registry_path).roots["local"].path
    (root / "examples" / "main101.cc").write_text(
        'pythia.readString("HardQCD:all = on");\n',
        encoding="utf-8",
    )

    payload = runner.search_pythia_examples({"query": "   "})

    assert payload["results"] == []
    assert payload["match_count"] == 0
    assert payload["returned_count"] == 0
    assert payload["searched_file_count"] >= 1


def test_search_examples_snippet_is_truncated(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    root = core.load_registry(runner.registry_path).roots["local"].path
    _write_examples_makefile(root)
    long_line = "HardQCD " + ("x" * 500)
    (root / "examples" / "main101.cc").write_text(long_line + "\n", encoding="utf-8")

    payload = runner.search_pythia_examples({"query": "HardQCD"})

    assert payload["returned_count"] == 1
    assert len(payload["results"][0]["snippet"]) <= core.MAX_EXAMPLE_SNIPPET_CHARS
    assert payload["results"][0]["snippet"].endswith("...")


def test_search_examples_unknown_root_raises_error(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)

    with pytest.raises(core.PythiaSimError, match="Unknown root alias"):
        runner.search_pythia_examples({"query": "HardQCD", "root_alias": "missing"})


def test_success_cleanup_and_failure_preservation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _make_runner(tmp_path)
    source = """
    #include "Pythia8/Pythia.h"
    #include "pythia_sim_artifacts.h"
    int main() { return 0; }
    """
    run_stdout = (
        "before\n"
        + _terminal_output_block("summary.txt", core.TERMINAL_OUTPUT_KIND_TEXT, "ok\n")
        + "after\n"
    )
    calls = [
        core.CommandExecution(["c++"], 0, "", ""),
        core.CommandExecution(["./simulation.out"], 0, run_stdout, ""),
    ]

    def fake_run(*args: object, **kwargs: object) -> core.CommandExecution:
        return calls.pop(0)

    monkeypatch.setattr(core, "_run_subprocess_capped", fake_run)
    result = runner.run_pythia_simulation({"source_cpp": source})

    assert result["run"]["ok"] is True
    assert "[pythia-sim text output: summary.txt]" in result["run"]["stdout"]
    assert "[end summary.txt]" in result["run"]["stdout"]
    assert "artifacts" not in result
    assert "artifacts_path" not in result
    assert list((runner.runs_tmp_root).glob("run-*")) == []

    failed_dir = tmp_path / "failed-source"
    failed_dir.mkdir()
    (failed_dir / "artifact.txt").write_text("keep\n", encoding="utf-8")
    destination = core.preserve_failure_run(failed_dir, tmp_path / "failed")
    assert destination.exists()
    assert (destination / "artifact.txt").read_text(encoding="utf-8") == "keep\n"


def test_supporting_files_reject_code_extensions() -> None:
    with pytest.raises(core.PythiaSimError, match="looks like code"):
        core.validate_supporting_files([{"name": "helper.hpp", "content": "x"}])


def test_normalize_terminal_outputs_formats_text_json_and_csv() -> None:
    stdout = "".join(
        [
            "hello\n",
            _terminal_output_block("note.txt", core.TERMINAL_OUTPUT_KIND_TEXT, "plain text\n"),
            _terminal_output_block("data.json", core.TERMINAL_OUTPUT_KIND_JSON, '{"b":2,"a":1}'),
            _terminal_output_block("table.csv", core.TERMINAL_OUTPUT_KIND_CSV, "x,y\n1,2\n"),
            "world\n",
        ]
    )
    visible_stdout = core.normalize_terminal_outputs(stdout)

    assert visible_stdout.startswith("hello\n[pythia-sim text output: note.txt]\nplain text\n[end note.txt]\n")
    assert '[pythia-sim json output: data.json]\n{\n  "a": 1,\n  "b": 2\n}\n[end data.json]\n' in visible_stdout
    assert "[pythia-sim csv output: table.csv]\nx,y\n1,2\n[end table.csv]\n" in visible_stdout
    assert visible_stdout.endswith("world\n")


def test_normalize_terminal_outputs_formats_histogram() -> None:
    stdout = _terminal_output_block(
        "multiplicity",
        core.TERMINAL_OUTPUT_KIND_HISTOGRAM,
        "title: Multiplicity\nx_label: n\ny_label: Events\nmax_count: 7\n[0, 1): 3 | #################\n[1, 2): 7 | ########################################\n",
    )
    visible_stdout = core.normalize_terminal_outputs(stdout)

    assert "[pythia-sim histogram output: multiplicity]" in visible_stdout
    assert "title: Multiplicity" in visible_stdout
    assert "[1, 2): 7 | ########################################" in visible_stdout
    assert visible_stdout.endswith("[end multiplicity]\n")


def test_malformed_terminal_output_block_preserves_failure_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _make_runner(tmp_path)
    source = """
    #include "Pythia8/Pythia.h"
    #include "pythia_sim_artifacts.h"
    int main() { return 0; }
    """
    calls = [
        core.CommandExecution(["c++"], 0, "", ""),
        core.CommandExecution(
            ["./simulation.out"],
            0,
            "ok\n<<PYTHIA_SIM_OUTPUT_BEGIN name=oops.txt kind=text",
            "",
        ),
    ]

    def fake_run(*args: object, **kwargs: object) -> core.CommandExecution:
        return calls.pop(0)

    monkeypatch.setattr(core, "_run_subprocess_capped", fake_run)
    result = runner.run_pythia_simulation({"source_cpp": source})

    assert result["run"]["ok"] is False
    assert "Terminal output block begin marker was not terminated" in result["run"]["stderr"]
    failure_dir = Path(result["failure_artifacts_path"])
    assert failure_dir.is_dir()
    assert (failure_dir / "metadata.json").is_file()


def test_removed_max_artifact_bytes_is_rejected(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)

    with pytest.raises(core.PythiaSimError, match="max_artifact_bytes is no longer supported"):
        runner.run_pythia_simulation(
            {
                "source_cpp": '#include "Pythia8/Pythia.h"\nint main() { return 0; }\n',
                "max_artifact_bytes": 16,
            }
        )


def test_server_example_search_result_summary(tmp_path: Path) -> None:
    payload = {
        "root_alias": "local",
        "root_path": "/tmp/pythia",
        "examples_path": "/tmp/pythia/examples",
        "query": "HardQCD",
        "include_cmnd": True,
        "safety_mode": "standalone_only",
        "searched_file_count": 4,
        "match_count": 2,
        "filtered_match_count": 1,
        "returned_count": 1,
        "truncated": False,
        "results": [
            {
                "path": "/tmp/pythia/examples/main101.cc",
                "name": "main101.cc",
                "file_kind": "cc",
                "safety": "standalone_safe",
                "line_number": 12,
                "snippet": 'pythia.readString("HardQCD:all = on");',
            }
        ],
    }

    result = server.build_tool_result(server._summarize_example_search(payload), payload)

    assert "query: 'HardQCD'" in result["content"][0]["text"]
    assert "snippet: pythia.readString" in result["content"][0]["text"]
    assert result["structuredContent"]["returned_count"] == 1
    assert result["structuredContent"]["results"][0]["line_number"] == 12


def test_server_run_summary_includes_outputs_but_not_artifacts() -> None:
    payload = {
        "run_id": "run123",
        "root_alias": "local",
        "bootstrap_performed": False,
        "compile": {
            "ok": True,
            "exit_code": 0,
            "stdout": "compiled successfully\n",
            "stderr": "",
            "command_summary": "direct: g++ source.cpp -o simulation.out",
        },
        "run": {
            "ok": True,
            "exit_code": 0,
            "stdout": "sigmaGen = 12.5\n",
            "stderr": "",
            "timed_out": False,
        },
    }

    summary = server._summarize_run(payload)

    assert "compile_commands: direct: g++ source.cpp -o simulation.out" in summary
    assert "run stdout:" in summary
    assert "sigmaGen = 12.5" in summary


def test_server_run_summary_prefers_head_and_tail_for_long_output() -> None:
    long_stdout = "\n".join(
        [f"banner line {index}: {'x' * 28}" for index in range(80)]
        + [
            "@@@ RESULT: 5000 Z bosons from 5000 events. @@@",
            "@@@ CROSS SECTION: 4.410e-06 +/- 3.665e-08 mb @@@",
        ]
    )
    long_stderr = "\n".join(
        [f"stderr line {index}: {'y' * 32}" for index in range(70)]
        + ["[pythia-sim] Process timed out after 60 seconds."]
    )
    payload = {
        "run_id": "run123",
        "root_alias": "local",
        "bootstrap_performed": False,
        "compile": {
            "ok": True,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "command_summary": "direct: g++ source.cpp -o simulation.out",
        },
        "run": {
            "ok": False,
            "exit_code": 124,
            "stdout": long_stdout,
            "stderr": long_stderr,
            "timed_out": True,
        },
    }

    summary = server._summarize_run(payload)

    assert "banner line 0" in summary
    assert "@@@ RESULT: 5000 Z bosons from 5000 events. @@@" in summary
    assert "@@@ CROSS SECTION: 4.410e-06 +/- 3.665e-08 mb @@@" in summary
    assert "[pythia-sim] Process timed out after 60 seconds." in summary
    assert "output shortened" in summary


def test_build_tool_result_is_text_only() -> None:
    payload = {
        "run_id": "testrun",
        "root_alias": "local",
        "bootstrap_performed": False,
        "compile": {"ok": True, "exit_code": 0},
        "run": {"ok": True, "exit_code": 0, "stdout": "done\n", "stderr": "", "timed_out": False},
    }

    result = server.build_tool_result(server._summarize_run(payload), payload)

    assert result["content"] == [{"type": "text", "text": server._summarize_run(payload)}]


def test_event_record_spec_requires_commands_or_cmnd_text() -> None:
    with pytest.raises(core.PythiaSimError, match="Provide commands, cmnd_text, or both"):
        core.validate_event_record_simulation_spec({})


def test_event_record_spec_accepts_new_introspection_maximum() -> None:
    spec = core.validate_event_record_simulation_spec(
        {
            "commands": ["WeakSingleBoson:ffbar2gmZ = on"],
            "event_count": core.MAX_INTROSPECTION_EVENT_COUNT,
        }
    )

    assert spec.event_count == core.MAX_INTROSPECTION_EVENT_COUNT


def test_event_record_spec_rejects_known_invalid_silencing_settings() -> None:
    with pytest.raises(core.PythiaSimError, match="Main:showBanner"):
        core.validate_event_record_simulation_spec(
            {
                "commands": ["Main:showBanner = off"],
            }
        )

    with pytest.raises(core.PythiaSimError, match="Next:numberShowEvent = 0"):
        core.validate_event_record_simulation_spec(
            {
                "cmnd_text": "Main:showNextStats = off\n",
            }
        )


def test_trace_particle_lineage_reuses_completed_run(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(runner.plugin_root, run_id="trace123")

    payload = runner.trace_particle_lineage(
        {
            "run_id": "trace123",
            "particle_selector": {"pdg_id": 13, "charge": -1, "rank_by": "pt", "rank": 1},
            "trace_options": {"direction": "ancestors", "stop_at": "incoming_partons"},
        }
    )

    assert payload["analysis_ok"] is True
    assert payload["selected_particle"]["id"] == 13
    assert payload["selected_particle"]["pt"] == 42.0
    assert len(payload["lineage_paths"]) == 2
    assert {node["id"] for node in payload["matched_stop_nodes"]} == {2, -2}


def test_find_decay_chain_reuses_summary_and_examples(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(runner.plugin_root, run_id="trace123")

    payload = runner.find_decay_chain(
        {
            "run_id": "trace123",
            "decay_chain": {"parent_pdg_id": 23, "child_pdg_id": 13},
        }
    )

    assert payload["analysis_ok"] is True
    assert payload["decay_chain"]["chain_key"] == "23>13"
    assert payload["decay_chain"]["summary_match_count"] == 4
    assert payload["decay_chain"]["example_snapshot_match_count"] == 1
    assert payload["decay_chain"]["example_snapshot_match_event_count"] == 1
    assert "match_count" not in payload["decay_chain"]
    assert payload["decay_chain"]["representative_matches"]
    assert payload["decay_chain"]["representative_matches"][0]["accepted_event_index"] == 0


def test_find_decay_chain_reports_snapshot_mismatch_without_ambiguous_match_count(
    tmp_path: Path,
) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(
        runner.plugin_root,
        run_id="trace123",
        decay_chain_counts={"23>-13": 4},
    )

    payload = runner.find_decay_chain(
        {
            "run_id": "trace123",
            "decay_chain": {"parent_pdg_id": 23, "child_pdg_id": 13},
        }
    )

    assert payload["analysis_ok"] is True
    assert payload["decay_chain"]["summary_match_count"] == 0
    assert payload["decay_chain"]["example_snapshot_match_count"] == 1
    assert payload["decay_chain"]["representative_matches"]
    assert "match_count" not in payload["decay_chain"]


def test_explain_status_codes_annotates_observed_counts(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(runner.plugin_root, run_id="trace123")

    payload = runner.explain_status_codes({"run_id": "trace123", "status_codes": [1, -23, 41]})

    assert payload["analysis_ok"] is True
    explanations = {item["code"]: item for item in payload["status_code_explanations"]}
    assert explanations[1]["observed_count"] == 2
    assert explanations[-23]["observed_count"] == 1
    assert "Hardest subprocess" in explanations[-23]["description"]
    assert "Initial-state radiation" in explanations[41]["description"]


def test_summarize_event_record_uses_generated_capture_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(runner.plugin_root, run_id="generated123")
    captured: dict[str, object] = {}

    def fake_execute(
        *,
        root: core.RootEntry,
        run_dir: Path,
        source_path: Path,
        compile_timeout_sec: int,
        run_timeout_sec: int,
        max_output_bytes: int,
    ) -> core.SimulationLifecycleResult:
        captured["root_alias"] = root.alias
        captured["source_cpp"] = source_path.read_text(encoding="utf-8")
        captured["supporting_files"] = sorted(path.name for path in run_dir.iterdir() if path.name != "source.cpp")
        (run_dir / core.EVENT_RECORD_SUMMARY_ARTIFACT).write_text(
            (runner.legacy_completed_runs_root / "generated123" / core.EVENT_RECORD_SUMMARY_ARTIFACT).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        (run_dir / core.EVENT_RECORD_EXAMPLES_ARTIFACT).write_text(
            (runner.legacy_completed_runs_root / "generated123" / core.EVENT_RECORD_EXAMPLES_ARTIFACT).read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        return core.SimulationLifecycleResult(
            bootstrap_performed=False,
            compile_result={"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "command_summary": ""},
            run_result={"ok": True, "exit_code": 0, "stdout": "", "stderr": "", "timed_out": False},
        )

    def fake_snapshot(**kwargs: object) -> Path:
        source_dir = Path(kwargs["run_dir"])
        destination = runner.completed_runs_root / str(kwargs["run_id"])
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "metadata.json").write_text(
            json.dumps(
                {
                    "run_id": kwargs["run_id"],
                    "root_alias": "local",
                    "bootstrap_performed": False,
                    "compile": kwargs["compile_result"],
                    "run": kwargs["run_result"],
                    "created_at_epoch_sec": 1,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for name in (core.EVENT_RECORD_SUMMARY_ARTIFACT, core.EVENT_RECORD_EXAMPLES_ARTIFACT):
            (destination / name).write_text((source_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
        return destination

    monkeypatch.setattr(runner, "_execute_run_lifecycle", fake_execute)
    monkeypatch.setattr(runner, "_persist_event_record_snapshot", fake_snapshot)
    payload = runner.summarize_event_record(
        {
            "commands": ["Beams:eCM = 13000.", "WeakSingleBoson:ffbar2gmZ = on"],
            "cmnd_text": "23:onMode = off\n23:onIfAny = 13\n",
            "event_count": 25,
        }
    )

    assert payload["analysis_ok"] is True
    assert payload["event_record"]["accepted_event_count"] == 8
    assert "source_cpp" in captured
    assert 'WeakSingleBoson:ffbar2gmZ = on' in str(captured["source_cpp"])
    assert sorted(captured["supporting_files"]) == ["pythia_sim_artifacts.h", "settings.cmnd"]


def test_server_analysis_summaries_include_representative_details(tmp_path: Path) -> None:
    runner = _make_runner(tmp_path)
    _write_event_record_bundle(runner.plugin_root, run_id="trace123")

    bundle = core._load_event_record_bundle(
        "trace123",
        completed_root=runner.completed_runs_root,
        legacy_completed_root=runner.legacy_completed_runs_root,
    )
    event_record_payload = core._event_record_summary_payload(bundle)
    event_record_payload["analysis_ok"] = True
    lineage_payload = runner.trace_particle_lineage(
        {
            "run_id": "trace123",
            "particle_selector": {"pdg_id": 13, "charge": -1, "rank_by": "pt", "rank": 1},
            "trace_options": {"direction": "ancestors", "stop_at": "incoming_partons"},
        }
    )
    decay_payload = runner.find_decay_chain(
        {
            "run_id": "trace123",
            "decay_chain": {"parent_pdg_id": 23, "child_pdg_id": 13},
        }
    )
    status_payload = runner.explain_status_codes({"run_id": "trace123", "status_codes": [1, -23]})

    event_summary = server._summarize_event_record(event_record_payload)
    lineage_summary = server._summarize_lineage_trace(lineage_payload)
    decay_summary = server._summarize_decay_chain(decay_payload)
    status_summary = server._summarize_status_codes(status_payload)

    assert "top_particle_pdg_counts:" in event_summary
    assert "top_status_code_counts:" in event_summary
    assert "representative_lineage_paths:" in lineage_summary
    assert "6:13[1] -> 5:23[-23] -> 1:2[-21]" in lineage_summary
    assert "representative_matches_detail:" in decay_summary
    assert "summary_match_count: 4" in decay_summary
    assert "example_snapshot_match_count: 1" in decay_summary
    assert "count_scope_note:" in decay_summary
    assert "5:23 -> 6:13" in decay_summary
    assert "-23: Hardest subprocess." in status_summary


def test_server_tool_list_includes_event_record_introspection_tools() -> None:
    tool_names = {
        tool["name"]
        for tool in [
            core.LIST_ROOTS_TOOL,
            core.SEARCH_EXAMPLES_TOOL,
            core.RUN_SIMULATION_TOOL,
            core.SUMMARIZE_EVENT_RECORD_TOOL,
            core.TRACE_PARTICLE_LINEAGE_TOOL,
            core.FIND_DECAY_CHAIN_TOOL,
            core.EXPLAIN_STATUS_CODES_TOOL,
        ]
    }
    assert "summarize_event_record" in tool_names
    assert "trace_particle_lineage" in tool_names
    assert "find_decay_chain" in tool_names
    assert "explain_status_codes" in tool_names


def test_manifest_metadata_matches_server_identity() -> None:
    codex_manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    gemini_manifest = json.loads((PLUGIN_ROOT / "gemini-extension.json").read_text(encoding="utf-8"))

    assert codex_manifest["name"] == server.SERVER_NAME == gemini_manifest["name"]
    assert codex_manifest["version"] == server.SERVER_VERSION == gemini_manifest["version"]
    assert gemini_manifest["description"] == codex_manifest["description"]
    assert gemini_manifest["contextFileName"] == "GEMINI.md"
    assert gemini_manifest["mcpServers"]["pythia-sim"]["command"] == "python3"
    assert gemini_manifest["mcpServers"]["pythia-sim"]["args"] == [
        "${extensionPath}${/}scripts${/}pythia_sim_server.py"
    ]


def test_mcp_config_matches_packaging_entrypoints() -> None:
    codex_manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    gemini_manifest = json.loads((PLUGIN_ROOT / "gemini-extension.json").read_text(encoding="utf-8"))
    mcp_config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))

    assert codex_manifest["mcpServers"] == "./.mcp.json"
    assert "pythia-sim" in gemini_manifest["mcpServers"]
    assert mcp_config["mcpServers"]["pythia-sim"]["command"] == "python3"
    assert mcp_config["mcpServers"]["pythia-sim"]["args"] == ["./scripts/pythia_sim_server.py"]
    assert mcp_config["mcpServers"]["pythia-sim"]["cwd"] == "./"


def test_gemini_manifest_has_no_install_time_settings() -> None:
    gemini_manifest = json.loads((PLUGIN_ROOT / "gemini-extension.json").read_text(encoding="utf-8"))

    assert "settings" not in gemini_manifest


def test_gemini_qualified_tool_names_fit_length_limit() -> None:
    tool_names = [
        core.LIST_ROOTS_TOOL["name"],
        core.SEARCH_EXAMPLES_TOOL["name"],
        core.RUN_SIMULATION_TOOL["name"],
        core.SUMMARIZE_EVENT_RECORD_TOOL["name"],
        core.TRACE_PARTICLE_LINEAGE_TOOL["name"],
        core.FIND_DECAY_CHAIN_TOOL["name"],
        core.EXPLAIN_STATUS_CODES_TOOL["name"],
    ]

    for tool_name in tool_names:
        qualified_name = f"mcp_{server.SERVER_NAME}_{tool_name}"
        assert len(qualified_name) < 64, qualified_name


def test_server_stdio_mcp_smoke_test(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    _write_makefile_inc(root)
    registry_path = _write_registry(tmp_path, root)
    env = os.environ.copy()
    env.update(
        {
            core.PYTHIA_SIM_REGISTRY_PATH_ENV: str(registry_path),
            core.PYTHIA_SIM_STATE_DIR_ENV: str(tmp_path / "state"),
        }
    )

    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_ROOT / "pythia_sim_server.py")],
        cwd=PLUGIN_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        initialize_result = json.loads(process.stdout.readline())
        assert initialize_result["result"]["serverInfo"]["name"] == server.SERVER_NAME
        assert "resources" not in initialize_result["result"]["capabilities"]

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        process.stdin.flush()
        tool_list = json.loads(process.stdout.readline())
        tool_names = {tool["name"] for tool in tool_list["result"]["tools"]}
        assert "list_pythia_roots" in tool_names

        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "list_pythia_roots", "arguments": {}},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        tool_call = json.loads(process.stdout.readline())
        assert tool_call["result"]["structuredContent"]["default_alias"] == "local"
        assert tool_call["result"]["content"][0]["type"] == "text"
        assert "default_alias: local" in tool_call["result"]["content"][0]["text"]
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_server_stdio_rejects_resources_read(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    _write_makefile_inc(root)
    registry_path = _write_registry(tmp_path, root)
    env = os.environ.copy()
    env.update(
        {
            core.PYTHIA_SIM_REGISTRY_PATH_ENV: str(registry_path),
            core.PYTHIA_SIM_STATE_DIR_ENV: str(tmp_path / "state"),
        }
    )

    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_ROOT / "pythia_sim_server.py")],
        cwd=PLUGIN_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        initialize_result = json.loads(process.stdout.readline())
        assert initialize_result["result"]["serverInfo"]["name"] == server.SERVER_NAME

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "resources/read",
                    "params": {"uri": "pythia-sim://runs/run123/plot.svg"},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        response = json.loads(process.stdout.readline())
        assert response["error"]["code"] == -32601
        assert "resources/read" in response["error"]["message"]
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_server_stdio_run_returns_text_only_content(tmp_path: Path) -> None:
    root = _make_fake_root(tmp_path)
    executable_body = (
        "printf '%s' "
        + repr(
            _terminal_output_block(
                "z_mass_resonance",
                core.TERMINAL_OUTPUT_KIND_HISTOGRAM,
                "title: Z mass\nx_label: m_mumu [GeV]\ny_label: Events\nmax_count: 7\n[80, 90): 3 | #################\n[90, 100): 7 | ########################################\n",
            )
        )
    )
    fake_cxx = tmp_path / "fake-cxx.sh"
    _write_fake_cxx(fake_cxx, executable_body=executable_body)
    _write_makefile_inc(root, compiler=str(fake_cxx))
    registry_path = _write_registry(tmp_path, root)
    env = os.environ.copy()
    env.update(
        {
            core.PYTHIA_SIM_REGISTRY_PATH_ENV: str(registry_path),
            core.PYTHIA_SIM_STATE_DIR_ENV: str(tmp_path / "state"),
        }
    )

    process = subprocess.Popen(
        [sys.executable, str(SCRIPTS_ROOT / "pythia_sim_server.py")],
        cwd=PLUGIN_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    try:
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-03-26"},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        _ = json.loads(process.stdout.readline())

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "run_pythia_simulation",
                        "arguments": {
                            "source_cpp": '#include "Pythia8/Pythia.h"\nint main() { return 0; }\n'
                        },
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        tool_call = json.loads(process.stdout.readline())
        result = tool_call["result"]
        assert result["structuredContent"]["run"]["ok"] is True
        assert result["content"][0]["type"] == "text"
        assert len(result["content"]) == 1
        assert "[pythia-sim histogram output: z_mass_resonance]" in result["structuredContent"]["run"]["stdout"]
    finally:
        process.terminate()
        process.wait(timeout=5)


@pytest.mark.integration
def test_integration_run_local_root(tmp_path: Path) -> None:
    integration_root = Path(
        os.environ.get("PYTHIA_SIM_TEST_ROOT", "/Users/akash009/pythia_fresh/pythia8317")
    )
    if not (integration_root / "include" / "Pythia8" / "Pythia.h").is_file():
        pytest.skip("No local Pythia test root available.")

    plugin_root = tmp_path / "plugin"
    (plugin_root / "config").mkdir(parents=True)
    registry_path = plugin_root / "config" / "roots.json"
    registry_path.write_text(
        json.dumps(
            {
                "default_alias": "local",
                "roots": [{"alias": "local", "path": str(integration_root)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runner = core.PythiaSimulationRunner(
        plugin_root=plugin_root, registry_path=registry_path, state_root=tmp_path / "state"
    )
    source = """
    #include "Pythia8/Pythia.h"
    #include "pythia_sim_artifacts.h"
    using namespace Pythia8;
    using namespace PythiaSimArtifacts;

    int main() {
      Pythia pythia;
      pythia.readString("Beams:eCM = 8000.");
      pythia.readString("HardQCD:all = on");
      pythia.readString("PhaseSpace:pTHatMin = 20.");
      if (!pythia.init()) return 1;
      Hist mult("charged multiplicity", 100, -0.5, 799.5);
      std::vector<double> counts(8, 0.0);
      for (int iEvent = 0; iEvent < 25; ++iEvent) {
        if (!pythia.next()) continue;
        int nCharged = 0;
        for (int i = 0; i < pythia.event.size(); ++i) {
          if (pythia.event[i].isFinal() && pythia.event[i].isCharged()) ++nCharged;
        }
        mult.fill(nCharged);
        int bin = nCharged / 20;
        if (bin < 0) bin = 0;
        if (bin > 7) bin = 7;
        counts[bin] += 1.0;
      }
      emit_text("summary.txt", "run complete\\n");
      emit_histogram("charged-multiplicity", "Charged multiplicity", 0.0, 160.0, counts, "N charged", "Events");
      pythia.stat();
      cout << mult;
      return 0;
    }
    """
    result = runner.run_pythia_simulation(
        {
            "source_cpp": source,
            "compile_timeout_sec": 90,
            "run_timeout_sec": 30,
            "max_output_bytes": 160000,
        }
    )
    assert result["compile"]["ok"] is True
    assert result["run"]["ok"] is True
    assert "charged multiplicity" in result["run"]["stdout"]
    assert "[pythia-sim text output: summary.txt]" in result["run"]["stdout"]
    assert "[pythia-sim histogram output: charged-multiplicity]" in result["run"]["stdout"]
    assert "artifacts" not in result
    assert "artifacts_path" not in result

    tool_result = server.build_tool_result(server._summarize_run(result), result)
    assert tool_result["content"][0]["type"] == "text"
    assert len(tool_result["content"]) == 1


@pytest.mark.integration
def test_integration_summarize_event_record(tmp_path: Path) -> None:
    integration_root = Path(
        os.environ.get("PYTHIA_SIM_TEST_ROOT", "/Users/akash009/pythia_fresh/pythia8317")
    )
    if not (integration_root / "include" / "Pythia8" / "Pythia.h").is_file():
        pytest.skip("No local Pythia test root available.")

    plugin_root = tmp_path / "plugin"
    (plugin_root / "config").mkdir(parents=True)
    registry_path = plugin_root / "config" / "roots.json"
    registry_path.write_text(
        json.dumps(
            {
                "default_alias": "local",
                "roots": [{"alias": "local", "path": str(integration_root)}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runner = core.PythiaSimulationRunner(
        plugin_root=plugin_root, registry_path=registry_path, state_root=tmp_path / "state"
    )

    payload = runner.summarize_event_record(
        {
            "commands": [
                "Beams:eCM = 13000.",
                "WeakSingleBoson:ffbar2gmZ = on",
                "23:onMode = off",
                "23:onIfAny = 13",
            ],
            "event_count": 12,
            "random_seed": 7,
        }
    )

    assert payload["analysis_ok"] is True
    assert payload["event_record"]["accepted_event_count"] >= 1
    snapshot_dir = runner.completed_runs_root / payload["run_id"]
    assert (snapshot_dir / core.EVENT_RECORD_SUMMARY_ARTIFACT).is_file()
    assert (snapshot_dir / core.EVENT_RECORD_EXAMPLES_ARTIFACT).is_file()
    assert list((runner.runs_tmp_root).glob("run-*")) == []
