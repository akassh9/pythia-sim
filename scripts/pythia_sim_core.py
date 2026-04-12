from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PYTHIA_SIM_REGISTRY_PATH_ENV = "PYTHIA_SIM_REGISTRY_PATH"
PYTHIA_SIM_ROOT_ENV = "PYTHIA_SIM_ROOT"
PYTHIA_SIM_ROOT_ALIAS_ENV = "PYTHIA_SIM_ROOT_ALIAS"
PYTHIA_SIM_STATE_DIR_ENV = "PYTHIA_SIM_STATE_DIR"
DEFAULT_ENV_ROOT_ALIAS = "default"


def _current_platform(platform: str | None = None) -> str:
    return platform or sys.platform


def _expand_user_path(raw_path: str) -> Path:
    return Path(raw_path).expanduser().resolve()


def _resolve_state_home(*, env: Mapping[str, str], platform: str) -> Path | None:
    xdg_state_home = env.get("XDG_STATE_HOME")
    if xdg_state_home:
        return _expand_user_path(xdg_state_home)
    if platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path.home() / ".local" / "state"


def resolve_state_root(
    *, env: Mapping[str, str] | None = None, platform: str | None = None
) -> Path:
    env_map = os.environ if env is None else env
    override = env_map.get(PYTHIA_SIM_STATE_DIR_ENV)
    if override:
        return _expand_user_path(override)

    platform_name = _current_platform(platform)
    state_home = _resolve_state_home(env=env_map, platform=platform_name)
    if state_home is None:  # pragma: no cover - defensive; current logic always returns a path.
        return (PLUGIN_ROOT / ".state").resolve()
    if platform_name == "darwin" and "XDG_STATE_HOME" not in env_map:
        return (state_home / "pythia-sim" / "state").resolve()
    return (state_home / "pythia-sim").resolve()


def _legacy_registry_path(plugin_root: Path) -> Path:
    return plugin_root / "config" / "roots.json"


def _legacy_runs_tmp_root(plugin_root: Path) -> Path:
    return plugin_root / ".runs" / "tmp"


def _legacy_failed_runs_root(plugin_root: Path) -> Path:
    return plugin_root / ".runs" / "failed"


def _legacy_completed_runs_root(plugin_root: Path) -> Path:
    return plugin_root / ".runs" / "completed"


def _legacy_locks_root(plugin_root: Path) -> Path:
    return plugin_root / ".locks"


DEFAULT_REGISTRY_PATH = _legacy_registry_path(PLUGIN_ROOT)
DEFAULT_STATE_ROOT = resolve_state_root()
RUNS_TMP_ROOT = DEFAULT_STATE_ROOT / "runs" / "tmp"
FAILED_RUNS_ROOT = DEFAULT_STATE_ROOT / "runs" / "failed"
COMPLETED_RUNS_ROOT = DEFAULT_STATE_ROOT / "runs" / "completed"
LOCKS_ROOT = DEFAULT_STATE_ROOT / "locks"
LEGACY_RUNS_TMP_ROOT = _legacy_runs_tmp_root(PLUGIN_ROOT)
LEGACY_FAILED_RUNS_ROOT = _legacy_failed_runs_root(PLUGIN_ROOT)
LEGACY_COMPLETED_RUNS_ROOT = _legacy_completed_runs_root(PLUGIN_ROOT)
LEGACY_LOCKS_ROOT = _legacy_locks_root(PLUGIN_ROOT)

DEFAULT_BUILD_COMMAND = ["make", "-j2"]
DEFAULT_COMPILE_TIMEOUT_SEC = 30
DEFAULT_RUN_TIMEOUT_SEC = 15
DEFAULT_MAX_OUTPUT_BYTES = 120_000
MAX_COMPILE_TIMEOUT_SEC = 300
MAX_RUN_TIMEOUT_SEC = 120
MAX_OUTPUT_BYTES = 200_000
MIN_OUTPUT_BYTES = 4_096
AUTO_BUILD_TIMEOUT_SEC = 1_200
MAX_SOURCE_BYTES = 160_000
MAX_SUPPORTING_FILES = 8
MAX_SUPPORTING_FILE_BYTES = 64_000
MAX_TOTAL_SUPPORTING_FILE_BYTES = 256_000
MAX_COMPLETED_RUNS = 25
DEFAULT_EXAMPLE_SEARCH_RESULTS = 8
MAX_EXAMPLE_SEARCH_RESULTS = 20
MAX_EXAMPLE_SNIPPET_CHARS = 320
EXAMPLE_SAFETY_MODE_STANDALONE_ONLY = "standalone_only"
EXAMPLE_SAFETY_MODE_ALL = "all"
EXAMPLE_SAFETY_TAG_STANDALONE = "standalone_safe"
EXAMPLE_SAFETY_TAG_EXTERNAL = "requires_external_dep"
DEFAULT_INTROSPECTION_EVENT_COUNT = 200
MAX_INTROSPECTION_EVENT_COUNT = 2_000
DEFAULT_INTROSPECTION_EXAMPLE_EVENTS = 6
MAX_INTROSPECTION_EXAMPLE_EVENTS = 12
MAX_TRACE_DEPTH = 24
MAX_CHAIN_INTERMEDIATES = 4
MAX_STATUS_CODES_QUERY = 32
EVENT_RECORD_SUMMARY_ARTIFACT = "event_record_summary.json"
EVENT_RECORD_EXAMPLES_ARTIFACT = "event_record_examples.json"
TRACE_DIRECTION_ANCESTORS = "ancestors"
TRACE_DIRECTION_DESCENDANTS = "descendants"
TRACE_STOP_AT_HARD_PROCESS_BOSON = "hard_process_boson"
TRACE_STOP_AT_INCOMING_PARTONS = "incoming_partons"
TRACE_STOP_AT_BEAM = "beam"
TRACE_RANK_BY_PT = "pt"
TRACE_RANK_BY_ENERGY = "energy"
TRACE_RANK_BY_ETA_ABS = "eta_abs"

ARTIFACT_HELPER_HEADER = "pythia_sim_artifacts.h"
TERMINAL_OUTPUT_BEGIN_PREFIX = "<<PYTHIA_SIM_OUTPUT_BEGIN "
TERMINAL_OUTPUT_END_PREFIX = "<<PYTHIA_SIM_OUTPUT_END "
TERMINAL_OUTPUT_KIND_TEXT = "text"
TERMINAL_OUTPUT_KIND_JSON = "json"
TERMINAL_OUTPUT_KIND_CSV = "csv"
TERMINAL_OUTPUT_KIND_HISTOGRAM = "histogram"
TERMINAL_OUTPUT_KINDS = {
    TERMINAL_OUTPUT_KIND_TEXT,
    TERMINAL_OUTPUT_KIND_JSON,
    TERMINAL_OUTPUT_KIND_CSV,
    TERMINAL_OUTPUT_KIND_HISTOGRAM,
}

SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TERMINAL_OUTPUT_BEGIN_RE = re.compile(
    r"^<<PYTHIA_SIM_OUTPUT_BEGIN name=(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,127}) kind=(?P<kind>[a-z]+)>>$"
)
TERMINAL_OUTPUT_END_RE = re.compile(
    r"^<<PYTHIA_SIM_OUTPUT_END name=(?P<name>[A-Za-z0-9][A-Za-z0-9._-]{0,127}) kind=(?P<kind>[a-z]+)>>$"
)
DISALLOWED_SUPPORTING_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".o",
    ".obj",
    ".so",
    ".dylib",
    ".a",
    ".py",
    ".sh",
    ".mk",
    ".cmake",
}
DISALLOWED_HEADER_PREFIXES = (
    "fastjet",
    "FastJet",
    "HepMC",
    "LHAPDF",
    "Pythia8Plugins/",
    "Rivet",
    "EvtGen",
    "TFile",
    "TTree",
    "TROOT",
    "TRandom",
    "ROOT/",
)
DISALLOWED_HEADERS = {
    "filesystem",
    "fstream",
    "thread",
    "future",
    "mutex",
    "condition_variable",
    "semaphore",
    "unistd.h",
    "sys/socket.h",
    "netinet/in.h",
    "arpa/inet.h",
    "netdb.h",
    "signal.h",
    "spawn.h",
    "dirent.h",
    "dlfcn.h",
    "fcntl.h",
    "sys/stat.h",
    "sys/wait.h",
}
BANNED_SOURCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:std::)?system\s*\("), "system() is not allowed."),
    (re.compile(r"\bpopen\s*\("), "popen() is not allowed."),
    (re.compile(r"\b(?:fork|vfork)\s*\("), "fork() is not allowed."),
    (
        re.compile(r"\bexec(?:l|le|lp|v|ve|vp|vpe)?\s*\("),
        "exec*() calls are not allowed.",
    ),
    (
        re.compile(r"\b(?:posix_spawn|posix_spawnp)\s*\("),
        "Process spawning is not allowed.",
    ),
    (
        re.compile(r"\b(?:socket|connect|accept|bind|listen|send|sendto|recv|recvfrom|getaddrinfo)\s*\("),
        "Network APIs are not allowed.",
    ),
    (
        re.compile(
            r"\b(?:fopen|freopen|open|creat|opendir|readdir|scandir|mkdir|rmdir|unlink|rename|remove|chmod|chown|symlink|link|chdir)\s*\("
        ),
        "Filesystem APIs are not allowed in standalone runs.",
    ),
    (
        re.compile(r"\b(?:ifstream|ofstream|fstream)\b"),
        "C++ filesystem streams are not allowed.",
    ),
    (
        re.compile(r"\b(?:std::filesystem|filesystem::)"),
        "std::filesystem is not allowed.",
    ),
    (
        re.compile(r"\b(?:std::thread|pthread_)"),
        "Threading APIs are not allowed.",
    ),
    (
        re.compile(r"\b(?:dlopen|dlsym|dlclose)\s*\("),
        "Dynamic loader APIs are not allowed.",
    ),
    (
        re.compile(r"\b(?:setenv|putenv|unsetenv|getenv)\s*\("),
        "Environment mutation is not allowed.",
    ),
    (
        re.compile(r"\b(?:asm|__asm__)\b"),
        "Inline assembly is not allowed.",
    ),
)
EXAMPLE_TARGET_PREFIX_RE = re.compile(r"^(main\d+)")
EXAMPLE_RULE_MARKERS = (
    "root_use",
    "root_opts",
    "fastjet3_use",
    "fastjet3_opts",
    "hepmc2_use",
    "hepmc2_opts",
    "hepmc3_use",
    "hepmc3_opts",
    "evtgen_use",
    "evtgen_opts",
    "hdf5_use",
    "hdf5_opts",
    "highfive_use",
    "yoda_use",
    "yoda_opts",
)
ALLOWED_EXAMPLE_FILE_SUFFIXES = {".cc", ".cmnd"}


class PythiaSimError(Exception):
    def __init__(self, message: str, *, failure_artifacts_path: str | None = None) -> None:
        super().__init__(message)
        self.failure_artifacts_path = failure_artifacts_path


@dataclass(frozen=True)
class RootEntry:
    alias: str
    path: Path
    build_command: list[str]


@dataclass(frozen=True)
class RootRegistry:
    default_alias: str
    roots: dict[str, RootEntry]


@dataclass
class SupportingFile:
    name: str
    content: str


@dataclass
class CommandExecution:
    command: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    output_capped: bool = False


@dataclass(frozen=True)
class EventRecordSimulationSpec:
    root_alias: str | None
    commands: list[str]
    cmnd_text: str | None
    event_count: int
    random_seed: int | None
    example_event_limit: int
    compile_timeout_sec: int
    run_timeout_sec: int
    max_output_bytes: int


@dataclass(frozen=True)
class SimulationLifecycleResult:
    bootstrap_performed: bool
    compile_result: dict[str, Any]
    run_result: dict[str, Any]


@dataclass(frozen=True)
class ParticleSelector:
    pdg_id: int | None
    final_state: bool
    charge: int | None
    status_codes: list[int]
    rank_by: str
    rank: int


@dataclass(frozen=True)
class TraceOptions:
    direction: str
    stop_at: str | list[int] | None
    max_depth: int


@dataclass(frozen=True)
class DecayChainQuery:
    parent_pdg_id: int
    child_pdg_id: int
    intermediate_pdg_ids: list[int]


def _strip_comments_and_strings(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//.*", "", source)
    source = re.sub(r'"(?:\\.|[^"\\])*"', '""', source)
    source = re.sub(r"'(?:\\.|[^'\\])*'", "''", source)
    return source


def _format_stage_output(stage_name: str, text: str) -> str:
    if not text:
        return ""
    suffix = "" if text.endswith("\n") else "\n"
    return f"[{stage_name}]\n{text}{suffix}"


def _shell_join(command: list[str]) -> str:
    return shlex.join(command)


def _coerce_timeout(value: Any, *, name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError(f"{name} must be an integer.")
    if value <= 0:
        raise PythiaSimError(f"{name} must be positive.")
    if value > maximum:
        raise PythiaSimError(f"{name} must be <= {maximum}.")
    return value


def _coerce_output_cap(value: Any) -> int:
    if value is None:
        return DEFAULT_MAX_OUTPUT_BYTES
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError("max_output_bytes must be an integer.")
    if value < MIN_OUTPUT_BYTES:
        raise PythiaSimError(f"max_output_bytes must be >= {MIN_OUTPUT_BYTES}.")
    if value > MAX_OUTPUT_BYTES:
        raise PythiaSimError(f"max_output_bytes must be <= {MAX_OUTPUT_BYTES}.")
    return value


def _reject_removed_artifact_cap(arguments: dict[str, Any]) -> None:
    if "max_artifact_bytes" in arguments:
        raise PythiaSimError(
            "max_artifact_bytes is no longer supported; artifact output has been removed. "
            "Use terminal text output instead."
        )


def _coerce_example_search_results(value: Any) -> int:
    if value is None:
        return DEFAULT_EXAMPLE_SEARCH_RESULTS
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError("max_results must be an integer.")
    if value <= 0:
        raise PythiaSimError("max_results must be positive.")
    if value > MAX_EXAMPLE_SEARCH_RESULTS:
        raise PythiaSimError(f"max_results must be <= {MAX_EXAMPLE_SEARCH_RESULTS}.")
    return value


def _coerce_optional_bool(value: Any, *, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise PythiaSimError(f"{name} must be a boolean.")
    return value


def _coerce_example_safety_mode(value: Any) -> str:
    if value is None:
        return EXAMPLE_SAFETY_MODE_STANDALONE_ONLY
    if not isinstance(value, str) or not value:
        raise PythiaSimError("safety_mode must be a non-empty string.")
    if value not in {EXAMPLE_SAFETY_MODE_STANDALONE_ONLY, EXAMPLE_SAFETY_MODE_ALL}:
        raise PythiaSimError(
            f"safety_mode must be one of: {EXAMPLE_SAFETY_MODE_STANDALONE_ONLY}, {EXAMPLE_SAFETY_MODE_ALL}."
        )
    return value


def _coerce_introspection_event_count(value: Any) -> int:
    if value is None:
        return DEFAULT_INTROSPECTION_EVENT_COUNT
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError("event_count must be an integer.")
    if value <= 0:
        raise PythiaSimError("event_count must be positive.")
    if value > MAX_INTROSPECTION_EVENT_COUNT:
        raise PythiaSimError(f"event_count must be <= {MAX_INTROSPECTION_EVENT_COUNT}.")
    return value


def _coerce_example_event_limit(value: Any) -> int:
    if value is None:
        return DEFAULT_INTROSPECTION_EXAMPLE_EVENTS
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError("example_event_limit must be an integer.")
    if value <= 0:
        raise PythiaSimError("example_event_limit must be positive.")
    if value > MAX_INTROSPECTION_EXAMPLE_EVENTS:
        raise PythiaSimError(
            f"example_event_limit must be <= {MAX_INTROSPECTION_EXAMPLE_EVENTS}."
        )
    return value


def _coerce_optional_seed(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PythiaSimError("random_seed must be an integer.")
    if value <= 0:
        raise PythiaSimError("random_seed must be positive.")
    return value


def _coerce_int_list(
    value: Any,
    *,
    name: str,
    maximum_length: int | None = None,
    allow_empty: bool = True,
) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PythiaSimError(f"{name} must be an array of integers.")
    if not allow_empty and not value:
        raise PythiaSimError(f"{name} must not be empty.")
    if maximum_length is not None and len(value) > maximum_length:
        raise PythiaSimError(f"{name} must contain at most {maximum_length} integers.")
    items: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise PythiaSimError(f"{name}[{index}] must be an integer.")
        items.append(item)
    return items


def _validate_commands(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise PythiaSimError("commands must be an array of strings.")
    if len(value) > 64:
        raise PythiaSimError("commands may contain at most 64 entries.")
    commands: list[str] = []
    total_bytes = 0
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise PythiaSimError(f"commands[{index}] must be a string.")
        command = item.strip()
        if not command:
            raise PythiaSimError(f"commands[{index}] must be non-empty.")
        encoded = command.encode("utf-8")
        if len(encoded) > 512:
            raise PythiaSimError(f"commands[{index}] exceeds 512 bytes.")
        total_bytes += len(encoded)
        commands.append(command)
    if total_bytes > 8_192:
        raise PythiaSimError("commands exceed 8192 total bytes.")
    return commands


def _validate_cmnd_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PythiaSimError("cmnd_text must be a string when provided.")
    cmnd_text = value.strip()
    if not cmnd_text:
        raise PythiaSimError("cmnd_text must be non-empty when provided.")
    if len(cmnd_text.encode("utf-8")) > MAX_SUPPORTING_FILE_BYTES:
        raise PythiaSimError(f"cmnd_text exceeds {MAX_SUPPORTING_FILE_BYTES} bytes.")
    return cmnd_text + ("\n" if not cmnd_text.endswith("\n") else "")


def validate_event_record_simulation_spec(arguments: dict[str, Any]) -> EventRecordSimulationSpec:
    _reject_removed_artifact_cap(arguments)
    root_alias = arguments.get("root_alias")
    if root_alias is not None and (not isinstance(root_alias, str) or not root_alias):
        raise PythiaSimError("root_alias must be a non-empty string when provided.")
    commands = _validate_commands(arguments.get("commands"))
    cmnd_text = _validate_cmnd_text(arguments.get("cmnd_text"))
    if not commands and cmnd_text is None:
        raise PythiaSimError("Provide commands, cmnd_text, or both.")
    return EventRecordSimulationSpec(
        root_alias=root_alias,
        commands=commands,
        cmnd_text=cmnd_text,
        event_count=_coerce_introspection_event_count(arguments.get("event_count")),
        random_seed=_coerce_optional_seed(arguments.get("random_seed")),
        example_event_limit=_coerce_example_event_limit(arguments.get("example_event_limit")),
        compile_timeout_sec=_coerce_timeout(
            arguments.get("compile_timeout_sec"),
            name="compile_timeout_sec",
            default=DEFAULT_COMPILE_TIMEOUT_SEC,
            maximum=MAX_COMPILE_TIMEOUT_SEC,
        ),
        run_timeout_sec=_coerce_timeout(
            arguments.get("run_timeout_sec"),
            name="run_timeout_sec",
            default=DEFAULT_RUN_TIMEOUT_SEC,
            maximum=MAX_RUN_TIMEOUT_SEC,
        ),
        max_output_bytes=_coerce_output_cap(arguments.get("max_output_bytes")),
    )


def validate_particle_selector(value: Any) -> ParticleSelector:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise PythiaSimError("particle_selector must be an object.")
    pdg_id = value.get("pdg_id")
    if pdg_id is not None and (isinstance(pdg_id, bool) or not isinstance(pdg_id, int)):
        raise PythiaSimError("particle_selector.pdg_id must be an integer when provided.")
    final_state = _coerce_optional_bool(
        value.get("final_state"), name="particle_selector.final_state", default=True
    )
    charge = value.get("charge")
    if charge is not None:
        if isinstance(charge, bool) or not isinstance(charge, int):
            raise PythiaSimError("particle_selector.charge must be an integer when provided.")
        if charge not in {-1, 0, 1}:
            raise PythiaSimError("particle_selector.charge must be one of -1, 0, 1.")
    status_codes = _coerce_int_list(
        value.get("status_codes"), name="particle_selector.status_codes", maximum_length=16
    )
    rank_by = value.get("rank_by", TRACE_RANK_BY_PT)
    if rank_by not in {TRACE_RANK_BY_PT, TRACE_RANK_BY_ENERGY, TRACE_RANK_BY_ETA_ABS}:
        raise PythiaSimError(
            f"particle_selector.rank_by must be one of: {TRACE_RANK_BY_PT}, {TRACE_RANK_BY_ENERGY}, {TRACE_RANK_BY_ETA_ABS}."
        )
    rank = value.get("rank", 1)
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise PythiaSimError("particle_selector.rank must be an integer.")
    if rank <= 0:
        raise PythiaSimError("particle_selector.rank must be positive.")
    return ParticleSelector(
        pdg_id=pdg_id,
        final_state=final_state,
        charge=charge,
        status_codes=status_codes,
        rank_by=rank_by,
        rank=rank,
    )


def validate_trace_options(value: Any) -> TraceOptions:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise PythiaSimError("trace_options must be an object.")
    direction = value.get("direction", TRACE_DIRECTION_ANCESTORS)
    if direction not in {TRACE_DIRECTION_ANCESTORS, TRACE_DIRECTION_DESCENDANTS}:
        raise PythiaSimError(
            f"trace_options.direction must be one of: {TRACE_DIRECTION_ANCESTORS}, {TRACE_DIRECTION_DESCENDANTS}."
        )
    raw_stop_at = value.get("stop_at")
    stop_at: str | list[int] | None
    if raw_stop_at is None:
        stop_at = None
    elif isinstance(raw_stop_at, str):
        if raw_stop_at not in {
            TRACE_STOP_AT_HARD_PROCESS_BOSON,
            TRACE_STOP_AT_INCOMING_PARTONS,
            TRACE_STOP_AT_BEAM,
        }:
            raise PythiaSimError(
                "trace_options.stop_at must be hard_process_boson, incoming_partons, beam, or an array of PDG ids."
            )
        stop_at = raw_stop_at
    else:
        stop_at = _coerce_int_list(
            raw_stop_at, name="trace_options.stop_at", maximum_length=16, allow_empty=False
        )
    max_depth = value.get("max_depth", 12)
    if isinstance(max_depth, bool) or not isinstance(max_depth, int):
        raise PythiaSimError("trace_options.max_depth must be an integer.")
    if max_depth <= 0:
        raise PythiaSimError("trace_options.max_depth must be positive.")
    if max_depth > MAX_TRACE_DEPTH:
        raise PythiaSimError(f"trace_options.max_depth must be <= {MAX_TRACE_DEPTH}.")
    return TraceOptions(direction=direction, stop_at=stop_at, max_depth=max_depth)


def validate_decay_chain_query(value: Any) -> DecayChainQuery:
    if not isinstance(value, dict):
        raise PythiaSimError("decay_chain must be an object.")
    parent_pdg_id = value.get("parent_pdg_id")
    child_pdg_id = value.get("child_pdg_id")
    if isinstance(parent_pdg_id, bool) or not isinstance(parent_pdg_id, int):
        raise PythiaSimError("decay_chain.parent_pdg_id must be an integer.")
    if isinstance(child_pdg_id, bool) or not isinstance(child_pdg_id, int):
        raise PythiaSimError("decay_chain.child_pdg_id must be an integer.")
    intermediate_pdg_ids = _coerce_int_list(
        value.get("intermediate_pdg_ids"),
        name="decay_chain.intermediate_pdg_ids",
        maximum_length=MAX_CHAIN_INTERMEDIATES,
    )
    return DecayChainQuery(
        parent_pdg_id=parent_pdg_id,
        child_pdg_id=child_pdg_id,
        intermediate_pdg_ids=intermediate_pdg_ids,
    )


def _normalize_status_code_list(value: Any) -> list[int]:
    codes = _coerce_int_list(value, name="status_codes", maximum_length=MAX_STATUS_CODES_QUERY)
    if not codes:
        raise PythiaSimError("status_codes must contain at least one integer.")
    return codes


def _build_decay_chain_key(chain_query: DecayChainQuery) -> str:
    return ">".join(
        str(item)
        for item in [chain_query.parent_pdg_id, *chain_query.intermediate_pdg_ids, chain_query.child_pdg_id]
    )


def _artifact_helper_header_source() -> str:
    begin_prefix = json.dumps(TERMINAL_OUTPUT_BEGIN_PREFIX)
    end_prefix = json.dumps(TERMINAL_OUTPUT_END_PREFIX)
    return f'''#pragma once
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace PythiaSimArtifacts {{

namespace detail {{

inline bool valid_name(const std::string& name) {{
  if (name.empty() || name.size() > 128) return false;
  const unsigned char first = static_cast<unsigned char>(name[0]);
  if (!((first >= 'A' && first <= 'Z') || (first >= 'a' && first <= 'z') || (first >= '0' && first <= '9'))) return false;
  for (std::size_t i = 0; i < name.size(); ++i) {{
    const unsigned char ch = static_cast<unsigned char>(name[i]);
    const bool ok = (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '.' || ch == '_' || ch == '-';
    if (!ok) return false;
  }}
  return true;
}}

inline std::string json_escape(const std::string& input) {{
  std::ostringstream out;
  for (std::size_t i = 0; i < input.size(); ++i) {{
    const unsigned char ch = static_cast<unsigned char>(input[i]);
    switch (ch) {{
      case '\\\\': out << "\\\\\\\\"; break;
      case '"': out << "\\\\\\""; break;
      case '\\b': out << "\\\\b"; break;
      case '\\f': out << "\\\\f"; break;
      case '\\n': out << "\\\\n"; break;
      case '\\r': out << "\\\\r"; break;
      case '\\t': out << "\\\\t"; break;
      default:
        if (ch < 0x20) {{
          static const char* digits = "0123456789abcdef";
          out << "\\\\u00" << digits[(ch >> 4) & 0xF] << digits[ch & 0xF];
        }} else {{
          out << static_cast<char>(ch);
        }}
    }}
  }}
  return out.str();
}}

inline std::string format_number(const double value) {{
  std::ostringstream out;
  out << std::setprecision(6) << value;
  return out.str();
}}

inline void emit_block(
    const std::string& name,
    const std::string& kind,
    const std::string& payload) {{
  if (!valid_name(name)) {{
    throw std::runtime_error("Output names must match [A-Za-z0-9][A-Za-z0-9._-]{{0,127}}");
  }}
  std::cout << {begin_prefix} << "name=" << name << " kind=" << kind << ">>\\n";
  std::cout << payload;
  if (payload.empty() || payload.back() != '\\n') std::cout << '\\n';
  std::cout << {end_prefix} << "name=" << name << " kind=" << kind << ">>\\n";
  std::cout.flush();
}}

inline std::string histogram_body(
    const std::string& title,
    const std::vector<double>& bin_edges,
    const std::vector<double>& counts,
    const std::string& x_label,
    const std::string& y_label) {{
  if (counts.empty()) {{
    throw std::runtime_error("emit_histogram requires a non-empty counts array");
  }}
  double max_count = 0.0;
  for (std::size_t i = 0; i < counts.size(); ++i) {{
    max_count = std::max(max_count, counts[i]);
  }}
  std::ostringstream body;
  body << "title: " << title << "\\n";
  if (!x_label.empty()) body << "x_label: " << x_label << "\\n";
  if (!y_label.empty()) body << "y_label: " << y_label << "\\n";
  body << "max_count: " << format_number(max_count) << "\\n";
  for (std::size_t i = 0; i < counts.size(); ++i) {{
    const double count = counts[i];
    int bar_count = 0;
    if (max_count > 0.0 && count > 0.0) {{
      bar_count = static_cast<int>(std::llround((count / max_count) * 40.0));
    }}
    body << "[" << format_number(bin_edges[i]) << ", " << format_number(bin_edges[i + 1]) << "): "
         << format_number(count) << " | " << std::string(bar_count, '#') << "\\n";
  }}
  return body.str();
}}

}}  // namespace detail

inline void emit_text(const std::string& name, const std::string& text) {{
  detail::emit_block(name, "text", text);
}}

inline void emit_json(const std::string& name, const std::string& json_text) {{
  detail::emit_block(name, "json", json_text);
}}

inline void emit_csv(const std::string& name, const std::string& csv_text) {{
  detail::emit_block(name, "csv", csv_text);
}}

inline void emit_histogram(
    const std::string& name,
    const std::string& title,
    const std::vector<double>& bin_edges,
    const std::vector<double>& counts,
    const std::string& x_label = "",
    const std::string& y_label = "Count") {{
  if (bin_edges.size() != counts.size() + 1) {{
    throw std::runtime_error("emit_histogram bin_edges must be exactly one longer than counts");
  }}
  detail::emit_block(name, "histogram", detail::histogram_body(title, bin_edges, counts, x_label, y_label));
}}

inline void emit_histogram(
    const std::string& name,
    const std::string& title,
    const double x_min,
    const double x_max,
    const std::vector<double>& counts,
    const std::string& x_label = "",
    const std::string& y_label = "Count") {{
  if (!(x_max > x_min)) {{
    throw std::runtime_error("emit_histogram requires x_max > x_min");
  }}
  if (counts.empty()) {{
    throw std::runtime_error("emit_histogram requires a non-empty counts array");
  }}
  std::vector<double> bin_edges;
  bin_edges.reserve(counts.size() + 1);
  const double width = (x_max - x_min) / static_cast<double>(counts.size());
  for (std::size_t i = 0; i <= counts.size(); ++i) {{
    bin_edges.push_back(x_min + (static_cast<double>(i) * width));
  }}
  detail::emit_block(name, "histogram", detail::histogram_body(title, bin_edges, counts, x_label, y_label));
}}

}}  // namespace PythiaSimArtifacts
'''

def _normalize_terminal_block_content(name: str, kind: str, body: str) -> str:
    if not SAFE_FILENAME_RE.fullmatch(name):
        raise PythiaSimError(
            "Terminal output name must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}."
        )
    if kind not in TERMINAL_OUTPUT_KINDS:
        raise PythiaSimError(f"Unsupported terminal output kind '{kind}'.")
    if "\x00" in body:
        raise PythiaSimError(f"Terminal output '{name}' contains NUL bytes.")
    if kind == TERMINAL_OUTPUT_KIND_JSON:
        try:
            parsed_json = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PythiaSimError(f"JSON output '{name}' is not valid JSON: {exc}") from exc
        body = json.dumps(parsed_json, indent=2, sort_keys=True) + "\n"
    elif body and not body.endswith("\n"):
        body += "\n"
    lines = [f"[pythia-sim {kind} output: {name}]", body.rstrip("\n"), f"[end {name}]"]
    return "\n".join(lines) + "\n"


def normalize_terminal_outputs(stdout_text: str) -> str:
    visible_chunks: list[str] = []
    position = 0

    while True:
        start = stdout_text.find(TERMINAL_OUTPUT_BEGIN_PREFIX, position)
        if start < 0:
            visible_chunks.append(stdout_text[position:])
            break
        visible_chunks.append(stdout_text[position:start])
        begin_end = stdout_text.find(">>", start)
        if begin_end < 0:
            raise PythiaSimError("Terminal output block begin marker was not terminated before process exit.")
        begin_marker = stdout_text[start : begin_end + 2]
        begin_match = TERMINAL_OUTPUT_BEGIN_RE.fullmatch(begin_marker)
        if begin_match is None:
            raise PythiaSimError(f"Invalid terminal output begin marker '{begin_marker}'.")
        name = begin_match.group("name")
        kind = begin_match.group("kind")
        body_start = begin_end + 2
        if body_start < len(stdout_text) and stdout_text[body_start] == "\n":
            body_start += 1
        end_marker = f"{TERMINAL_OUTPUT_END_PREFIX}name={name} kind={kind}>>"
        end = stdout_text.find(end_marker, body_start)
        if end < 0:
            raise PythiaSimError("Terminal output block was not terminated before process exit.")
        body = stdout_text[body_start:end]
        if body.endswith("\n"):
            body = body[:-1]
        visible_chunks.append(_normalize_terminal_block_content(name, kind, body))
        position = end + len(end_marker)
        if position < len(stdout_text) and stdout_text[position] == "\n":
            position += 1

    return "".join(visible_chunks)


def _cxx_bool(value: bool) -> str:
    return "true" if value else "false"


def _cxx_string(value: str) -> str:
    return json.dumps(value)


def _cxx_int_vector(values: list[int]) -> str:
    if not values:
        return "{}"
    return "{" + ", ".join(str(value) for value in values) + "}"


def _build_event_record_source(
    spec: EventRecordSimulationSpec, *, selector: ParticleSelector | None = None
) -> str:
    command_lines = "\n".join(
        f"  pythia.readString({_cxx_string(command)});" for command in spec.commands
    )
    if not command_lines:
        command_lines = "  // No inline commands provided."
    cmnd_line = (
        '  pythia.readFile("settings.cmnd");\n'
        if spec.cmnd_text is not None
        else ""
    )
    seed_lines = ""
    if spec.random_seed is not None:
        seed_lines = (
            '  pythia.readString("Random:setSeed = on");\n'
            f'  pythia.readString("Random:seed = {spec.random_seed}");\n'
        )
    selector = selector or ParticleSelector(
        pdg_id=None,
        final_state=True,
        charge=None,
        status_codes=[],
        rank_by=TRACE_RANK_BY_PT,
        rank=1,
    )
    source = f"""#include "Pythia8/Pythia.h"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

using namespace Pythia8;

namespace {{

const int kRequestedEventCount = {spec.event_count};
const int kExampleEventLimit = {spec.example_event_limit};
const bool kSelectorEnabled = {_cxx_bool(selector.pdg_id is not None or selector.charge is not None or bool(selector.status_codes))};
const bool kSelectorFinalState = {_cxx_bool(selector.final_state)};
const int kSelectorPdgId = {selector.pdg_id if selector.pdg_id is not None else 0};
const bool kSelectorHasPdgId = {_cxx_bool(selector.pdg_id is not None)};
const int kSelectorCharge = {selector.charge if selector.charge is not None else 0};
const bool kSelectorHasCharge = {_cxx_bool(selector.charge is not None)};
const char* kSelectorRankBy = {_cxx_string(selector.rank_by)};
const std::vector<int> kSelectorStatusCodes = {_cxx_int_vector(selector.status_codes)};
const int kMaxChainDepth = {2 + MAX_CHAIN_INTERMEDIATES};
const int kMaxSelectedParticlesPerEvent = 8;
const int kMaxStoredDecayChains = 256;

struct ExampleEntry {{
  double score;
  int acceptedEventIndex;
  std::string payload;
}};

std::string jsonEscape(const std::string& value) {{
  std::ostringstream out;
  for (std::size_t i = 0; i < value.size(); ++i) {{
    const unsigned char ch = static_cast<unsigned char>(value[i]);
    switch (ch) {{
      case '\\\\': out << "\\\\\\\\"; break;
      case '"': out << "\\\\\\""; break;
      case '\\b': out << "\\\\b"; break;
      case '\\f': out << "\\\\f"; break;
      case '\\n': out << "\\\\n"; break;
      case '\\r': out << "\\\\r"; break;
      case '\\t': out << "\\\\t"; break;
      default:
        if (ch < 0x20) {{
          static const char* digits = "0123456789abcdef";
          out << "\\\\u00" << digits[(ch >> 4) & 0xF] << digits[ch & 0xF];
        }} else {{
          out << static_cast<char>(ch);
        }}
    }}
  }}
  return out.str();
}}

std::string quoteJson(const std::string& value) {{
  return std::string("\\"") + jsonEscape(value) + "\\"";
}}

std::string boolJson(const bool value) {{
  return value ? "true" : "false";
}}

std::string intMapJson(const std::map<int, int>& values) {{
  std::ostringstream out;
  out << "{{";
  bool first = true;
  for (std::map<int, int>::const_iterator it = values.begin(); it != values.end(); ++it) {{
    if (!first) out << ",";
    first = false;
    out << quoteJson(std::to_string(it->first)) << ":" << it->second;
  }}
  out << "}}";
  return out.str();
}}

std::string stringIntMapJson(const std::map<std::string, int>& values) {{
  std::ostringstream out;
  out << "{{";
  bool first = true;
  for (std::map<std::string, int>::const_iterator it = values.begin(); it != values.end(); ++it) {{
    if (!first) out << ",";
    first = false;
    out << quoteJson(it->first) << ":" << it->second;
  }}
  out << "}}";
  return out.str();
}}

std::map<std::string, int> pruneDecayChainCounts(const std::map<std::string, int>& values) {{
  std::vector<std::pair<std::string, int> > items;
  for (std::map<std::string, int>::const_iterator it = values.begin(); it != values.end(); ++it) {{
    items.push_back(*it);
  }}
  std::sort(
      items.begin(),
      items.end(),
      [](const std::pair<std::string, int>& left, const std::pair<std::string, int>& right) {{
        if (left.second != right.second) return left.second > right.second;
        return left.first < right.first;
      }});
  std::map<std::string, int> pruned;
  for (std::size_t i = 0; i < items.size() && static_cast<int>(i) < kMaxStoredDecayChains; ++i) {{
    pruned[items[i].first] = items[i].second;
  }}
  return pruned;
}}

std::string selectedIndexListJson(const std::vector<int>& values) {{
  std::ostringstream out;
  out << "[";
  for (std::size_t i = 0; i < values.size(); ++i) {{
    if (i) out << ",";
    out << values[i];
  }}
  out << "]";
  return out.str();
}}

void pushUnique(std::vector<int>& values, const int candidate) {{
  if (candidate <= 0) return;
  for (std::size_t i = 0; i < values.size(); ++i) {{
    if (values[i] == candidate) return;
  }}
  values.push_back(candidate);
}}

void collectNeighborhood(
    const Event& event, const int index, std::vector<int>& retained, const int depth) {{
  if (depth < 0 || index <= 0 || index >= event.size()) return;
  bool alreadyPresent = false;
  for (std::size_t i = 0; i < retained.size(); ++i) {{
    if (retained[i] == index) {{
      alreadyPresent = true;
      break;
    }}
  }}
  if (!alreadyPresent) retained.push_back(index);
  if (depth == 0) return;
  const Particle& particle = event[index];
  if (particle.mother1() > 0) collectNeighborhood(event, particle.mother1(), retained, depth - 1);
  if (particle.mother2() > 0 && particle.mother2() != particle.mother1()) {{
    collectNeighborhood(event, particle.mother2(), retained, depth - 1);
  }}
  const int firstDaughter = particle.daughter1();
  const int lastDaughter = particle.daughter2();
  if (firstDaughter > 0 && lastDaughter >= firstDaughter) {{
    for (int child = firstDaughter; child <= lastDaughter && child < event.size(); ++child) {{
      collectNeighborhood(event, child, retained, depth - 1);
    }}
  }}
}}

std::vector<int> retainedIndices(const Event& event, const std::vector<int>& selectedIndices) {{
  std::vector<int> seeds = selectedIndices;
  if (seeds.empty()) {{
    std::vector<std::pair<double, int> > fallback;
    for (int i = 0; i < event.size(); ++i) {{
      if (!event[i].isFinal()) continue;
      fallback.push_back(std::make_pair(event[i].pT(), i));
    }}
    std::sort(fallback.begin(), fallback.end(), std::greater<std::pair<double, int> >());
    for (std::size_t i = 0; i < fallback.size() && i < 4; ++i) pushUnique(seeds, fallback[i].second);
  }}
  std::vector<int> retained;
  for (std::size_t i = 0; i < seeds.size() && i < 4; ++i) {{
    collectNeighborhood(event, seeds[i], retained, 3);
  }}
  if (retained.empty()) {{
    pushUnique(retained, 1);
    pushUnique(retained, 2);
  }}
  std::sort(retained.begin(), retained.end());
  return retained;
}}

double rankValue(const Particle& particle) {{
  if (std::string(kSelectorRankBy) == "energy") return particle.e();
  if (std::string(kSelectorRankBy) == "eta_abs") return std::abs(particle.eta());
  return particle.pT();
}}

bool matchesSelector(const Particle& particle) {{
  if (!kSelectorEnabled) return particle.isFinal();
  if (kSelectorHasPdgId && particle.id() != kSelectorPdgId) return false;
  if (kSelectorFinalState && !particle.isFinal()) return false;
  if (kSelectorHasCharge) {{
    const double charge = particle.charge();
    if (kSelectorCharge == 0 && std::abs(charge) >= 1e-9) return false;
    if (kSelectorCharge != 0 && charge * static_cast<double>(kSelectorCharge) <= 0.0) return false;
  }}
  if (!kSelectorStatusCodes.empty()) {{
    bool matched = false;
    for (std::size_t i = 0; i < kSelectorStatusCodes.size(); ++i) {{
      if (particle.status() == kSelectorStatusCodes[i]) {{
        matched = true;
        break;
      }}
    }}
    if (!matched) return false;
  }}
  return true;
}}

double eventFallbackScore(const Event& event) {{
  double best = -1.0;
  for (int i = 0; i < event.size(); ++i) {{
    const Particle& particle = event[i];
    if (!particle.isFinal()) continue;
    best = std::max(best, particle.pT());
  }}
  return best;
}}

std::string particleJson(const Particle& particle, const int index) {{
  std::ostringstream out;
  out << "{{"
      << "\\"index\\":" << index << ","
      << "\\"id\\":" << particle.id() << ","
      << "\\"status\\":" << particle.status() << ","
      << "\\"mother1\\":" << particle.mother1() << ","
      << "\\"mother2\\":" << particle.mother2() << ","
      << "\\"daughter1\\":" << particle.daughter1() << ","
      << "\\"daughter2\\":" << particle.daughter2() << ","
      << "\\"pt\\":" << particle.pT() << ","
      << "\\"energy\\":" << particle.e() << ","
      << "\\"eta\\":" << particle.eta() << ","
      << "\\"charge\\":" << particle.charge() << ","
      << "\\"is_final\\":" << boolJson(particle.isFinal())
      << "}}";
  return out.str();
}}

std::string eventJson(
    const Event& event,
    const int acceptedEventIndex,
    const double score,
    const std::vector<int>& selectedIndices) {{
  const std::vector<int> retained = retainedIndices(event, selectedIndices);
  std::ostringstream out;
  out << "{{"
      << "\\"accepted_event_index\\":" << acceptedEventIndex << ","
      << "\\"score\\":" << score << ","
      << "\\"selected_particle_indices\\":" << selectedIndexListJson(selectedIndices) << ","
      << "\\"particles\\":[";
  for (std::size_t i = 0; i < retained.size(); ++i) {{
    if (i) out << ",";
    out << particleJson(event[retained[i]], retained[i]);
  }}
  out << "]}}";
  return out.str();
}}

std::string chainKey(const std::vector<int>& ids) {{
  std::ostringstream out;
  for (std::size_t i = 0; i < ids.size(); ++i) {{
    if (i) out << ">";
    out << ids[i];
  }}
  return out.str();
}}

void collectChainCounts(
    const Event& event,
    const int index,
    std::vector<int>& chain,
    std::map<std::string, int>& counts,
    const int depth) {{
  if (depth >= kMaxChainDepth) return;
  const Particle& particle = event[index];
  const int firstDaughter = particle.daughter1();
  const int lastDaughter = particle.daughter2();
  if (firstDaughter <= 0 || lastDaughter < firstDaughter) return;
  for (int child = firstDaughter; child <= lastDaughter && child < event.size(); ++child) {{
    chain.push_back(event[child].id());
    if (chain.size() >= 2u) counts[chainKey(chain)] += 1;
    collectChainCounts(event, child, chain, counts, depth + 1);
    chain.pop_back();
  }}
}}

void addExample(std::vector<ExampleEntry>& examples, const ExampleEntry& candidate) {{
  if (candidate.score < 0.0) return;
  if (static_cast<int>(examples.size()) < kExampleEventLimit) {{
    examples.push_back(candidate);
    return;
  }}
  std::size_t minIndex = 0;
  for (std::size_t i = 1; i < examples.size(); ++i) {{
    if (examples[i].score < examples[minIndex].score) minIndex = i;
  }}
  if (candidate.score > examples[minIndex].score) examples[minIndex] = candidate;
}}

bool writeTextFile(const std::string& path, const std::string& text) {{
  std::ofstream out(path.c_str(), std::ios::out | std::ios::trunc);
  if (!out) return false;
  out << text;
  if (!text.empty() && text.back() != '\\n') out << '\\n';
  return static_cast<bool>(out);
}}

}}  // namespace

int main() {{
  Pythia pythia;
  pythia.readString("Print:quiet = on");
  pythia.readString("Init:showChangedSettings = off");
  pythia.readString("Init:showChangedParticleData = off");
  pythia.readString("Next:numberShowInfo = 0");
  pythia.readString("Next:numberShowProcess = 0");
  pythia.readString("Next:numberShowEvent = 0");
{command_lines}
{cmnd_line}{seed_lines}  if (!pythia.init()) return 1;

  std::map<int, int> particlePdgCounts;
  std::map<int, int> finalStatePdgCounts;
  std::map<int, int> statusCodeCounts;
  std::map<int, int> finalStateMultiplicityCounts;
  std::map<std::string, int> decayChainCounts;
  std::vector<ExampleEntry> examples;
  int acceptedEvents = 0;
  int failedEvents = 0;

  for (int iEvent = 0; iEvent < kRequestedEventCount; ++iEvent) {{
    if (!pythia.next()) {{
      failedEvents += 1;
      continue;
    }}
    acceptedEvents += 1;
    int finalMultiplicity = 0;
    double bestSelectorScore = -1.0;
    std::vector<std::pair<double, int> > rankedSelectedParticles;
    for (int i = 0; i < pythia.event.size(); ++i) {{
      const Particle& particle = pythia.event[i];
      particlePdgCounts[particle.id()] += 1;
      statusCodeCounts[particle.status()] += 1;
      if (particle.isFinal()) {{
        finalMultiplicity += 1;
        finalStatePdgCounts[particle.id()] += 1;
      }}
      if (matchesSelector(particle)) {{
        const double score = rankValue(particle);
        bestSelectorScore = std::max(bestSelectorScore, score);
        rankedSelectedParticles.push_back(std::make_pair(score, i));
      }}
      std::vector<int> chain(1, particle.id());
      collectChainCounts(pythia.event, i, chain, decayChainCounts, 0);
    }}
    finalStateMultiplicityCounts[finalMultiplicity] += 1;
    std::sort(
        rankedSelectedParticles.begin(),
        rankedSelectedParticles.end(),
        std::greater<std::pair<double, int> >());
    std::vector<int> selectedIndices;
    for (std::size_t i = 0; i < rankedSelectedParticles.size() && i < kMaxSelectedParticlesPerEvent; ++i) {{
      selectedIndices.push_back(rankedSelectedParticles[i].second);
    }}
    const double exampleScore = bestSelectorScore >= 0.0 ? bestSelectorScore : eventFallbackScore(pythia.event);
    addExample(examples, ExampleEntry{{exampleScore, acceptedEvents - 1, eventJson(pythia.event, acceptedEvents - 1, exampleScore, selectedIndices)}});
  }}

  std::sort(
      examples.begin(),
      examples.end(),
      [](const ExampleEntry& left, const ExampleEntry& right) {{
        if (left.score != right.score) return left.score > right.score;
        return left.acceptedEventIndex < right.acceptedEventIndex;
      }});
  const std::map<std::string, int> prunedDecayChainCounts = pruneDecayChainCounts(decayChainCounts);

  std::ostringstream summary;
  summary << "{{"
          << "\\"version\\":1,"
          << "\\"selector_enabled\\":" << boolJson(kSelectorEnabled) << ","
          << "\\"requested_event_count\\":" << kRequestedEventCount << ","
          << "\\"accepted_event_count\\":" << acceptedEvents << ","
          << "\\"failed_event_count\\":" << failedEvents << ","
          << "\\"particle_pdg_counts\\":" << intMapJson(particlePdgCounts) << ","
          << "\\"final_state_pdg_counts\\":" << intMapJson(finalStatePdgCounts) << ","
          << "\\"status_code_counts\\":" << intMapJson(statusCodeCounts) << ","
          << "\\"final_state_multiplicity_counts\\":" << intMapJson(finalStateMultiplicityCounts) << ","
          << "\\"decay_chain_counts\\":" << stringIntMapJson(prunedDecayChainCounts)
          << "}}";
  if (!writeTextFile("{EVENT_RECORD_SUMMARY_ARTIFACT}", summary.str())) return 1;

  std::ostringstream examplePayload;
  examplePayload << "{{"
                 << "\\"version\\":1,"
                 << "\\"selector_rank_by\\":" << quoteJson(kSelectorRankBy) << ","
                 << "\\"stored_event_count\\":" << examples.size() << ","
                 << "\\"events\\":[";
  for (std::size_t i = 0; i < examples.size(); ++i) {{
    if (i) examplePayload << ",";
    examplePayload << examples[i].payload;
  }}
  examplePayload << "]}}";
  if (!writeTextFile("{EVENT_RECORD_EXAMPLES_ARTIFACT}", examplePayload.str())) return 1;
  return 0;
}}
"""
    return source


def _resolve_root_path(raw_path: str, *, registry_path: Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (registry_path.parent / candidate).resolve()
    return candidate.resolve()


def _load_registry_file(registry_path: Path) -> RootRegistry:
    if not registry_path.is_file():
        raise PythiaSimError(f"Registry file not found at {registry_path}.")
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PythiaSimError(f"roots.json is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise PythiaSimError("roots.json must contain a JSON object.")

    default_alias = payload.get("default_alias")
    roots_payload = payload.get("roots")
    if not isinstance(default_alias, str) or not default_alias:
        raise PythiaSimError("roots.json default_alias must be a non-empty string.")
    if not isinstance(roots_payload, list) or not roots_payload:
        raise PythiaSimError("roots.json roots must be a non-empty array.")

    roots: dict[str, RootEntry] = {}
    for index, item in enumerate(roots_payload):
        if not isinstance(item, dict):
            raise PythiaSimError(f"roots[{index}] must be an object.")
        alias = item.get("alias")
        raw_path = item.get("path")
        raw_build_command = item.get("build_command")
        if not isinstance(alias, str) or not alias:
            raise PythiaSimError(f"roots[{index}].alias must be a non-empty string.")
        if alias in roots:
            raise PythiaSimError(f"Duplicate root alias '{alias}' in roots.json.")
        if not isinstance(raw_path, str) or not raw_path:
            raise PythiaSimError(f"roots[{index}].path must be a non-empty string.")
        if raw_build_command is None:
            build_command = list(DEFAULT_BUILD_COMMAND)
        else:
            if (
                not isinstance(raw_build_command, list)
                or not raw_build_command
                or any(not isinstance(part, str) or not part for part in raw_build_command)
            ):
                raise PythiaSimError(
                    f"roots[{index}].build_command must be an array of non-empty strings."
                )
            build_command = list(raw_build_command)
        roots[alias] = RootEntry(
            alias=alias,
            path=_resolve_root_path(raw_path, registry_path=registry_path),
            build_command=build_command,
        )

    if default_alias not in roots:
        raise PythiaSimError(
            f"default_alias '{default_alias}' does not match any configured root."
        )

    return RootRegistry(default_alias=default_alias, roots=roots)


def _load_registry_from_env_root(env: Mapping[str, str]) -> RootRegistry | None:
    raw_root = env.get(PYTHIA_SIM_ROOT_ENV)
    if raw_root is None:
        return None
    root_path = raw_root.strip()
    if not root_path:
        raise PythiaSimError(f"{PYTHIA_SIM_ROOT_ENV} must be a non-empty path.")

    alias = env.get(PYTHIA_SIM_ROOT_ALIAS_ENV, DEFAULT_ENV_ROOT_ALIAS).strip()
    if not alias:
        raise PythiaSimError(f"{PYTHIA_SIM_ROOT_ALIAS_ENV} must be a non-empty string when provided.")

    entry = RootEntry(
        alias=alias,
        path=_expand_user_path(root_path),
        build_command=list(DEFAULT_BUILD_COMMAND),
    )
    return RootRegistry(default_alias=alias, roots={alias: entry})


def _candidate_registry_paths(
    *, plugin_root: Path, env: Mapping[str, str], platform: str
) -> list[Path]:
    candidates: list[Path] = []
    xdg_config_home = env.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        candidates.append(_expand_user_path(xdg_config_home) / "pythia-sim" / "roots.json")
    if platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "pythia-sim" / "roots.json")
    else:
        candidates.append(Path.home() / ".config" / "pythia-sim" / "roots.json")
    candidates.append(_legacy_registry_path(plugin_root))
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_candidates.append(resolved)
    return unique_candidates


def load_registry(
    registry_path: Path | None = None,
    *,
    plugin_root: Path = PLUGIN_ROOT,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> RootRegistry:
    env_map = os.environ if env is None else env
    if registry_path is not None:
        return _load_registry_file(Path(registry_path).expanduser().resolve())

    explicit_registry_path = env_map.get(PYTHIA_SIM_REGISTRY_PATH_ENV)
    if explicit_registry_path is not None:
        return _load_registry_file(_expand_user_path(explicit_registry_path))

    synthetic_registry = _load_registry_from_env_root(env_map)
    if synthetic_registry is not None:
        return synthetic_registry

    platform_name = _current_platform(platform)
    candidates = _candidate_registry_paths(
        plugin_root=plugin_root, env=env_map, platform=platform_name
    )
    for candidate in candidates:
        if candidate.is_file():
            return _load_registry_file(candidate)

    searched = "\n".join(f"- {path}" for path in candidates)
    raise PythiaSimError(
        "Registry file not found. Set "
        f"{PYTHIA_SIM_ROOT_ENV} or {PYTHIA_SIM_REGISTRY_PATH_ENV}, or create one of:\n{searched}"
    )


def parse_makefile_inc(makefile_path: Path) -> dict[str, str]:
    if not makefile_path.is_file():
        raise PythiaSimError(
            f"Missing {makefile_path}. Run ./configure in the Pythia root before using this tool."
        )
    values: dict[str, str] = {}
    for raw_line in makefile_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()

    required = ["CXX", "PREFIX_INCLUDE", "PREFIX_LIB", "CXX_COMMON"]
    missing = [key for key in required if not values.get(key)]
    if missing:
        missing_text = ", ".join(missing)
        raise PythiaSimError(f"{makefile_path} is missing required fields: {missing_text}.")
    return values


def validate_source_cpp(source_cpp: str) -> None:
    if not isinstance(source_cpp, str) or not source_cpp.strip():
        raise PythiaSimError("source_cpp must be a non-empty string.")
    if len(source_cpp.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise PythiaSimError(f"source_cpp exceeds {MAX_SOURCE_BYTES} bytes.")

    include_matches = re.findall(
        r'^\s*#\s*include\s*([<"])([^>"]+)[>"]', source_cpp, flags=re.MULTILINE
    )
    if not include_matches:
        raise PythiaSimError(
            "source_cpp must include standalone Pythia headers such as Pythia8/Pythia.h."
        )

    has_pythia_include = False
    for quote_type, header in include_matches:
        if header.startswith("Pythia8/"):
            has_pythia_include = True
            continue
        if quote_type == '"' and header == ARTIFACT_HELPER_HEADER:
            continue
        if quote_type == '"':
            raise PythiaSimError(
                f"Only Pythia headers may be quoted includes; rejected include '{header}'."
            )
        if header.startswith(DISALLOWED_HEADER_PREFIXES) or header in DISALLOWED_HEADERS:
            raise PythiaSimError(f"Header '{header}' is outside standalone Pythia support.")
        if "/" in header:
            raise PythiaSimError(
                f"External include path '{header}' is outside standalone Pythia support."
            )

    if not has_pythia_include:
        raise PythiaSimError("source_cpp must include at least one Pythia8/... header.")

    sanitized = _strip_comments_and_strings(source_cpp)
    for pattern, message in BANNED_SOURCE_PATTERNS:
        if pattern.search(sanitized):
            raise PythiaSimError(message)


def validate_supporting_files(raw_files: Any) -> list[SupportingFile]:
    if raw_files is None:
        return []
    if not isinstance(raw_files, list):
        raise PythiaSimError("supporting_files must be an array of {name, content} objects.")
    if len(raw_files) > MAX_SUPPORTING_FILES:
        raise PythiaSimError(f"supporting_files may contain at most {MAX_SUPPORTING_FILES} files.")

    files: list[SupportingFile] = []
    total_bytes = 0
    seen_names: set[str] = set()
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise PythiaSimError(f"supporting_files[{index}] must be an object.")
        name = item.get("name")
        content = item.get("content")
        if not isinstance(name, str) or not SAFE_FILENAME_RE.fullmatch(name):
            raise PythiaSimError(
                f"supporting_files[{index}].name must be a simple filename with no path separators."
            )
        if name in seen_names:
            raise PythiaSimError(f"Duplicate supporting file name '{name}'.")
        seen_names.add(name)
        if Path(name).suffix.lower() in DISALLOWED_SUPPORTING_SUFFIXES:
            raise PythiaSimError(f"Supporting file '{name}' looks like code, not text data.")
        if not isinstance(content, str):
            raise PythiaSimError(f"supporting_files[{index}].content must be a string.")
        if "\x00" in content:
            raise PythiaSimError(f"Supporting file '{name}' contains NUL bytes.")
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_SUPPORTING_FILE_BYTES:
            raise PythiaSimError(
                f"Supporting file '{name}' exceeds {MAX_SUPPORTING_FILE_BYTES} bytes."
            )
        total_bytes += len(encoded)
        if total_bytes > MAX_TOTAL_SUPPORTING_FILE_BYTES:
            raise PythiaSimError(
                f"supporting_files exceed {MAX_TOTAL_SUPPORTING_FILE_BYTES} total bytes."
            )
        files.append(SupportingFile(name=name, content=content))
    return files


def _supporting_files_for_event_record(spec: EventRecordSimulationSpec) -> list[dict[str, str]]:
    supporting_files: list[dict[str, str]] = []
    if spec.cmnd_text is not None:
        supporting_files.append({"name": "settings.cmnd", "content": spec.cmnd_text})
    return supporting_files


def _top_counts(mapping: Any, *, limit: int = 10) -> list[dict[str, Any]]:
    if not isinstance(mapping, dict):
        return []
    items: list[tuple[str, int]] = []
    for key, value in mapping.items():
        try:
            if isinstance(value, bool):
                continue
            items.append((str(key), int(value)))
        except (TypeError, ValueError):
            continue
    items.sort(key=lambda item: (-item[1], item[0]))
    return [{"key": key, "count": count} for key, count in items[:limit]]


def _base_payload_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": bundle["run_id"],
        "root_alias": bundle.get("root_alias"),
        "bootstrap_performed": bundle.get("bootstrap_performed", False),
        "compile": bundle.get("compile", {}),
        "run": bundle.get("run", {}),
    }


def _event_record_summary_payload(bundle: dict[str, Any]) -> dict[str, Any]:
    summary = bundle["summary"]
    examples = bundle["examples"]
    payload = _base_payload_from_bundle(bundle)
    payload["event_record"] = {
        "requested_event_count": summary.get("requested_event_count"),
        "accepted_event_count": summary.get("accepted_event_count"),
        "failed_event_count": summary.get("failed_event_count"),
        "stored_example_event_count": examples.get("stored_event_count"),
        "top_particle_pdg_counts": _top_counts(summary.get("particle_pdg_counts")),
        "top_final_state_pdg_counts": _top_counts(summary.get("final_state_pdg_counts")),
        "top_status_code_counts": _top_counts(summary.get("status_code_counts")),
        "top_decay_chain_counts": _top_counts(summary.get("decay_chain_counts")),
    }
    return payload


def inspect_root(root: RootEntry) -> dict[str, Any]:
    makefile_path = root.path / "Makefile.inc"
    root_valid = (
        root.path.is_dir()
        and (root.path / "include" / "Pythia8" / "Pythia.h").is_file()
        and (root.path / "examples" / "Makefile").is_file()
    )
    compiler = None
    build_status = "invalid_root"
    if root_valid:
        if makefile_path.is_file():
            try:
                compiler = parse_makefile_inc(makefile_path).get("CXX")
            except PythiaSimError:
                compiler = None
            libs_present = any((root.path / "lib").glob("libpythia8.*"))
            if libs_present:
                build_status = "ready"
            else:
                build_status = "needs_build"
        else:
            build_status = "needs_bootstrap"
    standalone_execution_available = (
        root_valid
        and build_status == "ready"
        and (root.path / "share" / "Pythia8" / "xmldoc").is_dir()
    )
    return {
        "alias": root.alias,
        "path": str(root.path),
        "build_status": build_status,
        "detected_compiler": compiler,
        "standalone_execution_available": standalone_execution_available,
    }


def _resolve_examples_dir(root: RootEntry) -> Path:
    if not root.path.is_dir():
        raise PythiaSimError(f"Configured root '{root.alias}' does not exist: {root.path}")
    examples_dir = root.path / "examples"
    if not examples_dir.is_dir():
        raise PythiaSimError(
            f"Configured root '{root.alias}' is missing the examples directory: {examples_dir}"
        )
    makefile_path = examples_dir / "Makefile"
    if not makefile_path.is_file():
        raise PythiaSimError(
            f"Configured root '{root.alias}' is missing the examples Makefile: {makefile_path}"
        )
    return examples_dir


def _parse_unsupported_example_targets(makefile_path: Path) -> set[str]:
    unsupported: set[str] = set()
    lines = makefile_path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        if (
            not stripped
            or raw_line[:1].isspace()
            or stripped.startswith("#")
            or ":" not in raw_line
            or stripped.startswith(".")
        ):
            index += 1
            continue

        target_text, _, _ = raw_line.partition(":")
        targets = [token for token in target_text.split() if token and "%" not in token]
        if not targets:
            index += 1
            continue

        block_lines = [stripped]
        next_index = index + 1
        while next_index < len(lines):
            next_line = lines[next_index]
            next_stripped = next_line.strip()
            if (
                next_stripped
                and not next_line[:1].isspace()
                and ":" in next_line
                and not next_stripped.startswith("#")
                and not next_stripped.startswith(("ifeq", "ifneq", "else", "endif"))
            ):
                break
            block_lines.append(next_stripped)
            next_index += 1

        block_text = "\n".join(block_lines).lower()
        if any(marker in block_text for marker in EXAMPLE_RULE_MARKERS):
            unsupported.update(targets)
        index = next_index

    return unsupported


def _example_target_key(filename: str) -> str:
    stem = Path(filename).stem
    match = EXAMPLE_TARGET_PREFIX_RE.match(stem)
    return match.group(1) if match else stem


def _classify_example_file(filename: str, unsupported_targets: set[str]) -> str:
    if _example_target_key(filename) in unsupported_targets:
        return EXAMPLE_SAFETY_TAG_EXTERNAL
    return EXAMPLE_SAFETY_TAG_STANDALONE


def _truncate_example_snippet(text: str) -> str:
    if len(text) <= MAX_EXAMPLE_SNIPPET_CHARS:
        return text
    return text[: MAX_EXAMPLE_SNIPPET_CHARS - 3].rstrip() + "..."


def _build_example_snippet(lines: list[str], match_index: int) -> str:
    start = max(0, match_index - 1)
    end = min(len(lines), match_index + 2)
    snippet = "\n".join(lines[start:end]).strip("\n")
    return _truncate_example_snippet(snippet)


def _find_example_match(text: str, query: str) -> tuple[int | None, str] | None:
    normalized_query = query.strip().lower()
    if not normalized_query:
        return None

    lines = text.splitlines()
    query_terms = [term for term in re.split(r"\s+", normalized_query) if term]
    for index, line in enumerate(lines):
        lowered = line.lower()
        if normalized_query in lowered or all(term in lowered for term in query_terms):
            return index + 1, _build_example_snippet(lines, index)

    lowered_text = text.lower()
    if normalized_query not in lowered_text and not all(term in lowered_text for term in query_terms):
        return None

    for index, line in enumerate(lines):
        lowered = line.lower()
        if normalized_query in lowered or any(term in lowered for term in query_terms):
            return index + 1, _build_example_snippet(lines, index)

    snippet = _truncate_example_snippet(text.strip())
    if not snippet:
        return None
    return None, snippet


def build_direct_compile_command(
    make_vars: dict[str, str], source_path: Path, output_path: Path
) -> list[str]:
    command = [make_vars["CXX"]]
    if make_vars.get("OBJ_COMMON"):
        command.extend(shlex.split(make_vars["OBJ_COMMON"]))
    command.append(f"-I{make_vars['PREFIX_INCLUDE']}")
    command.extend(shlex.split(make_vars["CXX_COMMON"]))
    if make_vars.get("CXX_DTAGS"):
        command.extend(shlex.split(make_vars["CXX_DTAGS"]))
    command.extend(
        [
            str(source_path),
            "-o",
            str(output_path),
            f"-L{make_vars['PREFIX_LIB']}",
            f"-Wl,-rpath,{make_vars['PREFIX_LIB']}",
            "-lpythia8",
            "-ldl",
        ]
    )
    return command


def cleanup_success_run(run_dir: Path) -> None:
    if run_dir.exists():
        shutil.rmtree(run_dir)


def preserve_failure_run(run_dir: Path, failed_root: Path = FAILED_RUNS_ROOT) -> Path:
    failed_root.mkdir(parents=True, exist_ok=True)
    destination = failed_root / run_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(run_dir), str(destination))
    return destination


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


STATUS_CODE_DESCRIPTIONS: tuple[tuple[int, int, str], ...] = (
    (11, 19, "Beam particles."),
    (21, 29, "Hardest subprocess."),
    (31, 39, "Particles from subsequent subprocesses such as multiparton interactions."),
    (41, 49, "Initial-state radiation."),
    (51, 59, "Final-state radiation."),
    (61, 69, "Beam-remnant treatment."),
    (71, 79, "Preparation of hadronization."),
    (81, 89, "Primary hadrons from hadronization."),
    (91, 99, "Decay products."),
)
STATUS_CODE_EXACT_DESCRIPTIONS: dict[int, str] = {
    1: "Final-state particle kept in the event record.",
}


def explain_status_code(code: int) -> dict[str, Any]:
    sign = "negative" if code < 0 else "positive"
    magnitude = abs(code)
    description = STATUS_CODE_EXACT_DESCRIPTIONS.get(code)
    category = "documentation"
    range_text = None
    if description is None:
        for lower, upper, text in STATUS_CODE_DESCRIPTIONS:
            if lower <= magnitude <= upper:
                description = text
                category = f"{lower}-{upper}"
                range_text = f"{lower}-{upper}"
                break
    if description is None:
        description = "No curated explanation is available for this status code in the plugin."
        category = "unknown"
    if range_text is None and category != "unknown":
        range_text = category
    return {
        "code": code,
        "abs_code": magnitude,
        "sign": sign,
        "category": category,
        "range": range_text,
        "description": description,
        "is_final_state": code == 1,
    }


def _load_json_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PythiaSimError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PythiaSimError(f"Invalid JSON in {label}: {path}") from exc
    if not isinstance(payload, dict):
        raise PythiaSimError(f"{label} must contain a JSON object: {path}")
    return payload


def _resolve_completed_run_dir(
    run_id: str,
    *,
    completed_root: Path,
    legacy_completed_root: Path | None = None,
) -> Path:
    candidates = [completed_root / run_id]
    if legacy_completed_root is not None:
        legacy_candidate = legacy_completed_root / run_id
        if legacy_candidate not in candidates:
            candidates.append(legacy_candidate)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise PythiaSimError(f"Completed run not found for run_id '{run_id}'.")


def _load_event_record_bundle(
    run_id: str,
    *,
    completed_root: Path = COMPLETED_RUNS_ROOT,
    legacy_completed_root: Path | None = LEGACY_COMPLETED_RUNS_ROOT,
) -> dict[str, Any]:
    if not isinstance(run_id, str) or not run_id:
        raise PythiaSimError("run_id must be a non-empty string.")
    run_dir = _resolve_completed_run_dir(
        run_id, completed_root=completed_root, legacy_completed_root=legacy_completed_root
    )

    metadata = _load_json_file(run_dir / "metadata.json", label="completed run metadata")
    summary = _load_json_file(run_dir / EVENT_RECORD_SUMMARY_ARTIFACT, label=EVENT_RECORD_SUMMARY_ARTIFACT)
    examples = _load_json_file(
        run_dir / EVENT_RECORD_EXAMPLES_ARTIFACT, label=EVENT_RECORD_EXAMPLES_ARTIFACT
    )
    return {
        "run_id": run_id,
        "root_alias": metadata.get("root_alias"),
        "snapshot_path": str(run_dir),
        "metadata": metadata,
        "summary": summary,
        "examples": examples,
        "compile": metadata.get("compile", {}),
        "run": metadata.get("run", {}),
        "bootstrap_performed": metadata.get("bootstrap_performed", False),
    }

def _particle_rank_value(particle: dict[str, Any], rank_by: str) -> float:
    if rank_by == TRACE_RANK_BY_ENERGY:
        return float(particle.get("energy", 0.0))
    if rank_by == TRACE_RANK_BY_ETA_ABS:
        return abs(float(particle.get("eta", 0.0)))
    return float(particle.get("pt", 0.0))


def _charge_matches(actual_charge: float, requested_charge: int) -> bool:
    if requested_charge == 0:
        return abs(actual_charge) < 1e-9
    return actual_charge * requested_charge > 0.0


def _particle_matches_selector(particle: dict[str, Any], selector: ParticleSelector) -> bool:
    if selector.pdg_id is not None and particle.get("id") != selector.pdg_id:
        return False
    if selector.final_state and not particle.get("is_final", False):
        return False
    if selector.charge is not None and not _charge_matches(
        float(particle.get("charge", 0.0)), selector.charge
    ):
        return False
    if selector.status_codes and particle.get("status") not in selector.status_codes:
        return False
    return True


def _particle_by_index(event: dict[str, Any], particle_index: int) -> dict[str, Any] | None:
    particles = event.get("particles")
    if not isinstance(particles, list):
        return None
    for particle in particles:
        if isinstance(particle, dict) and particle.get("index") == particle_index:
            return particle
    return None


def _neighbor_indices(
    particle: dict[str, Any], *, direction: str
) -> list[int]:
    if direction == TRACE_DIRECTION_DESCENDANTS:
        start = particle.get("daughter1", 0)
        end = particle.get("daughter2", 0)
    else:
        values = [particle.get("mother1", 0), particle.get("mother2", 0)]
        indices: list[int] = []
        seen: set[int] = set()
        for value in values:
            if not isinstance(value, int) or value <= 0 or value in seen:
                continue
            seen.add(value)
            indices.append(int(value))
        return indices
    if not isinstance(start, int) or not isinstance(end, int) or start <= 0 or end < start:
        return []
    return list(range(start, end + 1))


def _is_hard_process_boson(particle: dict[str, Any]) -> bool:
    particle_id = abs(int(particle.get("id", 0)))
    return particle_id in {22, 23, 24, 25, 32, 33, 34, 35, 36, 37, 39}


def _is_incoming_parton(particle: dict[str, Any]) -> bool:
    particle_id = abs(int(particle.get("id", 0)))
    status = int(particle.get("status", 0))
    return status < 0 and (1 <= particle_id <= 9 or particle_id == 21)


def _is_beam_particle(particle: dict[str, Any]) -> bool:
    index = int(particle.get("index", -1))
    return index in {1, 2} or abs(int(particle.get("status", 0))) in range(11, 20)


def _trace_stop_match(particle: dict[str, Any], stop_at: str | list[int] | None) -> bool:
    if stop_at is None:
        return False
    if isinstance(stop_at, list):
        return int(particle.get("id", 0)) in stop_at
    if stop_at == TRACE_STOP_AT_HARD_PROCESS_BOSON:
        return _is_hard_process_boson(particle)
    if stop_at == TRACE_STOP_AT_INCOMING_PARTONS:
        return _is_incoming_parton(particle)
    if stop_at == TRACE_STOP_AT_BEAM:
        return _is_beam_particle(particle)
    return False


def _format_particle_node(particle: dict[str, Any], *, relation: str, depth: int) -> dict[str, Any]:
    return {
        "index": particle.get("index"),
        "id": particle.get("id"),
        "status": particle.get("status"),
        "pt": particle.get("pt"),
        "energy": particle.get("energy"),
        "eta": particle.get("eta"),
        "charge": particle.get("charge"),
        "is_final": particle.get("is_final"),
        "relation": relation,
        "depth": depth,
    }


def _build_lineage_paths(
    event: dict[str, Any],
    particle_index: int,
    trace_options: TraceOptions,
) -> list[list[dict[str, Any]]]:
    start = _particle_by_index(event, particle_index)
    if start is None:
        raise PythiaSimError(f"Particle index {particle_index} was not found in the stored event snapshot.")

    paths: list[list[dict[str, Any]]] = []

    def walk(current: dict[str, Any], depth: int, path: list[dict[str, Any]], visited: set[int]) -> None:
        node_index = int(current.get("index", -1))
        relation = "target" if depth == 0 else trace_options.direction[:-1]
        node = _format_particle_node(current, relation=relation, depth=depth)
        path = [*path, node]
        if depth >= trace_options.max_depth or _trace_stop_match(current, trace_options.stop_at):
            paths.append(path)
            return

        neighbors = []
        for candidate in _neighbor_indices(current, direction=trace_options.direction):
            if candidate in visited:
                continue
            particle = _particle_by_index(event, candidate)
            if particle is not None:
                neighbors.append(particle)
        if not neighbors:
            paths.append(path)
            return
        next_visited = set(visited)
        next_visited.add(node_index)
        for neighbor in neighbors:
            walk(neighbor, depth + 1, path, next_visited)

    walk(start, 0, [], set())
    return paths


def _select_particle_from_examples(
    bundle: dict[str, Any], selector: ParticleSelector
) -> tuple[dict[str, Any], dict[str, Any], int]:
    examples = bundle["examples"]
    events = examples.get("events")
    if not isinstance(events, list):
        raise PythiaSimError("Stored event_record_examples.json does not contain an events array.")
    matches: list[tuple[float, int, int, dict[str, Any], dict[str, Any]]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        particles = event.get("particles")
        if not isinstance(particles, list):
            continue
        for particle in particles:
            if not isinstance(particle, dict):
                continue
            if not _particle_matches_selector(particle, selector):
                continue
            score = _particle_rank_value(particle, selector.rank_by)
            matches.append(
                (
                    score,
                    int(event.get("accepted_event_index", 0)),
                    int(particle.get("index", 0)),
                    event,
                    particle,
                )
            )
    matches.sort(key=lambda item: (-item[0], item[1], item[2]))
    if len(matches) < selector.rank:
        raise PythiaSimError(
            f"No stored particle example satisfied the selector at rank {selector.rank}."
        )
    score, _, _, event, particle = matches[selector.rank - 1]
    return event, particle, selector.rank - 1


def _chain_match_sequences(
    event: dict[str, Any], chain_query: DecayChainQuery
) -> list[list[dict[str, Any]]]:
    target_ids = [
        chain_query.parent_pdg_id,
        *chain_query.intermediate_pdg_ids,
        chain_query.child_pdg_id,
    ]
    matches: list[list[dict[str, Any]]] = []

    def descend(current: dict[str, Any], target_offset: int, path: list[dict[str, Any]]) -> None:
        path = [*path, _format_particle_node(current, relation="chain", depth=target_offset)]
        if target_offset == len(target_ids) - 1:
            matches.append(path)
            return
        for child_index in _neighbor_indices(current, direction=TRACE_DIRECTION_DESCENDANTS):
            child = _particle_by_index(event, child_index)
            if child is None or int(child.get("id", 0)) != target_ids[target_offset + 1]:
                continue
            descend(child, target_offset + 1, path)

    particles = event.get("particles")
    if not isinstance(particles, list):
        return []
    for particle in particles:
        if (
            isinstance(particle, dict)
            and int(particle.get("id", 0)) == chain_query.parent_pdg_id
        ):
            descend(particle, 0, [])
    return matches


def _run_subprocess_capped(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout_sec: int,
    max_output_bytes: int,
) -> CommandExecution:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    selector = selectors.DefaultSelector()
    assert process.stdout is not None
    assert process.stderr is not None
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")

    stdout_chunks: list[bytes] = []
    stderr_chunks: list[bytes] = []
    total_bytes = 0
    timed_out = False
    output_capped = False
    start = time.monotonic()

    while selector.get_map():
        remaining = timeout_sec - (time.monotonic() - start)
        if remaining <= 0:
            timed_out = True
            process.kill()
            break
        events = selector.select(timeout=min(0.1, remaining))
        if not events:
            if process.poll() is not None:
                for key in list(selector.get_map().values()):
                    chunk = key.fileobj.read1(4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    allowed = max_output_bytes - total_bytes
                    if allowed <= 0:
                        output_capped = True
                        selector.unregister(key.fileobj)
                        continue
                    chunk = chunk[:allowed]
                    total_bytes += len(chunk)
                    if key.data == "stdout":
                        stdout_chunks.append(chunk)
                    else:
                        stderr_chunks.append(chunk)
                    if total_bytes >= max_output_bytes:
                        output_capped = True
                break
            continue
        for key, _ in events:
            chunk = key.fileobj.read1(4096)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            allowed = max_output_bytes - total_bytes
            if allowed <= 0:
                output_capped = True
                process.kill()
                break
            if len(chunk) > allowed:
                chunk = chunk[:allowed]
                output_capped = True
            total_bytes += len(chunk)
            if key.data == "stdout":
                stdout_chunks.append(chunk)
            else:
                stderr_chunks.append(chunk)
            if output_capped:
                process.kill()
                break

    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

    stdout_text = b"".join(stdout_chunks).decode("utf-8", errors="replace")
    stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
    if timed_out:
        stderr_text = (
            stderr_text + ("\n" if stderr_text and not stderr_text.endswith("\n") else "")
            + f"[pythia-sim] Process timed out after {timeout_sec} seconds.\n"
        )
    if output_capped:
        stderr_text = (
            stderr_text + ("\n" if stderr_text and not stderr_text.endswith("\n") else "")
            + f"[pythia-sim] Output exceeded {max_output_bytes} bytes and the process was terminated.\n"
        )

    return CommandExecution(
        command=command,
        exit_code=process.returncode,
        stdout=stdout_text,
        stderr=stderr_text,
        timed_out=timed_out,
        output_capped=output_capped,
    )


class PythiaSimulationRunner:
    def __init__(
        self,
        *,
        plugin_root: Path = PLUGIN_ROOT,
        registry_path: Path | None = None,
        state_root: Path | None = None,
    ) -> None:
        self.plugin_root = plugin_root
        self.registry_path = registry_path
        self.state_root = state_root or resolve_state_root()
        self.runs_tmp_root = self.state_root / "runs" / "tmp"
        self.failed_runs_root = self.state_root / "runs" / "failed"
        self.completed_runs_root = self.state_root / "runs" / "completed"
        self.locks_root = self.state_root / "locks"
        self.legacy_runs_tmp_root = _legacy_runs_tmp_root(plugin_root)
        self.legacy_failed_runs_root = _legacy_failed_runs_root(plugin_root)
        self.legacy_completed_runs_root = _legacy_completed_runs_root(plugin_root)
        self.legacy_locks_root = _legacy_locks_root(plugin_root)

    def list_pythia_roots(self) -> dict[str, Any]:
        registry = load_registry(self.registry_path, plugin_root=self.plugin_root)
        roots = [inspect_root(entry) for entry in registry.roots.values()]
        return {
            "default_alias": registry.default_alias,
            "roots": roots,
        }

    def search_pythia_examples(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root_alias = arguments.get("root_alias")
        if root_alias is not None and (not isinstance(root_alias, str) or not root_alias):
            raise PythiaSimError("root_alias must be a non-empty string when provided.")

        query = arguments.get("query")
        if not isinstance(query, str):
            raise PythiaSimError("query must be a string.")
        query = query.strip()
        max_results = _coerce_example_search_results(arguments.get("max_results"))
        include_cmnd = _coerce_optional_bool(
            arguments.get("include_cmnd"), name="include_cmnd", default=True
        )
        safety_mode = _coerce_example_safety_mode(arguments.get("safety_mode"))

        root = self._select_root(root_alias)
        examples_dir = _resolve_examples_dir(root)
        unsupported_targets = _parse_unsupported_example_targets(examples_dir / "Makefile")

        results: list[dict[str, Any]] = []
        match_count = 0
        filtered_match_count = 0
        searched_file_count = 0

        if query:
            for path in sorted(examples_dir.iterdir(), key=lambda candidate: candidate.name):
                if not path.is_file() or path.suffix.lower() not in ALLOWED_EXAMPLE_FILE_SUFFIXES:
                    continue
                if path.suffix.lower() == ".cmnd" and not include_cmnd:
                    continue

                searched_file_count += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                match = _find_example_match(text, query)
                if match is None:
                    continue

                match_count += 1
                safety = _classify_example_file(path.name, unsupported_targets)
                if (
                    safety_mode == EXAMPLE_SAFETY_MODE_STANDALONE_ONLY
                    and safety != EXAMPLE_SAFETY_TAG_STANDALONE
                ):
                    filtered_match_count += 1
                    continue

                if len(results) >= max_results:
                    continue

                line_number, snippet = match
                result = {
                    "path": str(path),
                    "name": path.name,
                    "file_kind": path.suffix.lower().lstrip("."),
                    "safety": safety,
                    "snippet": snippet,
                }
                if line_number is not None:
                    result["line_number"] = line_number
                results.append(result)
        else:
            for path in examples_dir.iterdir():
                if not path.is_file() or path.suffix.lower() not in ALLOWED_EXAMPLE_FILE_SUFFIXES:
                    continue
                if path.suffix.lower() == ".cmnd" and not include_cmnd:
                    continue
                searched_file_count += 1

        eligible_match_count = match_count - filtered_match_count
        return {
            "root_alias": root.alias,
            "root_path": str(root.path),
            "examples_path": str(examples_dir),
            "query": query,
            "include_cmnd": include_cmnd,
            "safety_mode": safety_mode,
            "searched_file_count": searched_file_count,
            "match_count": match_count,
            "filtered_match_count": filtered_match_count,
            "returned_count": len(results),
            "truncated": eligible_match_count > len(results),
            "results": results,
        }

    def _run_event_record_capture(
        self, spec: EventRecordSimulationSpec, *, selector: ParticleSelector | None = None
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        source_cpp = _build_event_record_source(spec, selector=selector)
        supporting_files = validate_supporting_files(_supporting_files_for_event_record(spec))
        root = self._select_root(spec.root_alias)
        run_id = uuid.uuid4().hex
        request_payload = {
            "run_id": run_id,
            "root_alias": root.alias,
            "commands": list(spec.commands),
            "cmnd_text": spec.cmnd_text,
            "event_count": spec.event_count,
            "random_seed": spec.random_seed,
            "example_event_limit": spec.example_event_limit,
            "compile_timeout_sec": spec.compile_timeout_sec,
            "run_timeout_sec": spec.run_timeout_sec,
            "max_output_bytes": max(spec.max_output_bytes, MAX_OUTPUT_BYTES),
        }

        run_dir = self._make_run_dir()
        source_path = run_dir / "source.cpp"
        source_path.write_text(source_cpp, encoding="utf-8")
        self._write_generated_artifact_header(run_dir)
        self._write_supporting_files(run_dir, supporting_files)

        compile_result = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "command_summary": "",
        }
        run_result = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
        }
        bootstrap_performed = False

        try:
            lifecycle = self._execute_run_lifecycle(
                root=root,
                run_dir=run_dir,
                source_path=source_path,
                compile_timeout_sec=spec.compile_timeout_sec,
                run_timeout_sec=spec.run_timeout_sec,
                max_output_bytes=max(spec.max_output_bytes, MAX_OUTPUT_BYTES),
            )
            bootstrap_performed = lifecycle.bootstrap_performed
            compile_result = lifecycle.compile_result
            run_result = lifecycle.run_result
            payload = {
                "run_id": run_id,
                "root_alias": root.alias,
                "bootstrap_performed": bootstrap_performed,
                "compile": compile_result,
                "run": run_result,
            }
            if not compile_result.get("ok") or not run_result.get("ok"):
                failure_dir = self._copy_failed_artifacts(
                    run_dir,
                    run_id=run_id,
                    request_payload=request_payload,
                    root=root,
                    bootstrap_performed=bootstrap_performed,
                    compile_result=compile_result,
                    run_result=run_result,
                )
                payload["failure_artifacts_path"] = str(failure_dir)
                return payload, None

            self._persist_event_record_snapshot(
                run_id=run_id,
                run_dir=run_dir,
                request_payload=request_payload,
                root=root,
                bootstrap_performed=bootstrap_performed,
                compile_result=compile_result,
                run_result=run_result,
            )
            cleanup_success_run(run_dir)
            return payload, _load_event_record_bundle(
                run_id,
                completed_root=self.completed_runs_root,
                legacy_completed_root=self.legacy_completed_runs_root,
            )
        except PythiaSimError:
            raise
        except Exception as exc:  # pragma: no cover - defensive server-side fallback
            compile_result = {
                "ok": False,
                "exit_code": compile_result.get("exit_code"),
                "stdout": str(compile_result.get("stdout", "")),
                "stderr": str(compile_result.get("stderr", ""))
                + _format_stage_output("internal error", str(exc)),
                "command_summary": str(compile_result.get("command_summary", "")),
            }
            failure_dir = self._copy_failed_artifacts(
                run_dir,
                run_id=run_id,
                request_payload=request_payload,
                root=root,
                bootstrap_performed=bootstrap_performed,
                compile_result=compile_result,
                run_result=run_result,
            )
            raise PythiaSimError(
                f"Unexpected internal error. Failure artifacts preserved at {failure_dir}.",
                failure_artifacts_path=str(failure_dir),
            ) from exc

    def summarize_event_record(self, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = validate_event_record_simulation_spec(arguments)
        payload, bundle = self._run_event_record_capture(spec)
        if bundle is None:
            payload["analysis_ok"] = False
            payload["message"] = "Generated event-record capture did not complete successfully."
            return payload
        result = _event_record_summary_payload(bundle)
        result["analysis_ok"] = True
        return result

    def trace_particle_lineage(self, arguments: dict[str, Any]) -> dict[str, Any]:
        selector = validate_particle_selector(arguments.get("particle_selector"))
        trace_options = validate_trace_options(arguments.get("trace_options"))
        run_id = arguments.get("run_id")
        used_existing_run = run_id is not None
        if used_existing_run:
            bundle = _load_event_record_bundle(
                run_id,
                completed_root=self.completed_runs_root,
                legacy_completed_root=self.legacy_completed_runs_root,
            )
        else:
            spec = validate_event_record_simulation_spec(arguments)
            payload, bundle = self._run_event_record_capture(spec, selector=selector)
            if bundle is None:
                payload["analysis_ok"] = False
                payload["message"] = "Generated event-record capture did not complete successfully."
                return payload
        payload = _base_payload_from_bundle(bundle)
        payload["used_existing_run"] = used_existing_run
        try:
            event, particle, rank_offset = _select_particle_from_examples(bundle, selector)
            lineage_paths = _build_lineage_paths(
                event, int(particle["index"]), trace_options
            )
        except PythiaSimError as exc:
            payload["analysis_ok"] = False
            payload["message"] = str(exc)
            return payload
        matched_stop_nodes = [
            path[-1]
            for path in lineage_paths
            if path and _trace_stop_match(path[-1], trace_options.stop_at)
        ]
        payload["analysis_ok"] = True
        payload["selected_event"] = {
            "accepted_event_index": event.get("accepted_event_index"),
            "score": event.get("score"),
        }
        payload["selected_particle"] = {
            "rank_index": rank_offset + 1,
            "index": particle.get("index"),
            "id": particle.get("id"),
            "status": particle.get("status"),
            "pt": particle.get("pt"),
            "energy": particle.get("energy"),
            "eta": particle.get("eta"),
            "charge": particle.get("charge"),
            "is_final": particle.get("is_final"),
        }
        payload["lineage_paths"] = lineage_paths
        payload["matched_stop_nodes"] = matched_stop_nodes
        payload["trace_options"] = dataclasses.asdict(trace_options)
        payload["particle_selector"] = dataclasses.asdict(selector)
        return payload

    def find_decay_chain(self, arguments: dict[str, Any]) -> dict[str, Any]:
        chain_query = validate_decay_chain_query(arguments.get("decay_chain"))
        run_id = arguments.get("run_id")
        used_existing_run = run_id is not None
        if used_existing_run:
            bundle = _load_event_record_bundle(
                run_id,
                completed_root=self.completed_runs_root,
                legacy_completed_root=self.legacy_completed_runs_root,
            )
        else:
            spec = validate_event_record_simulation_spec(arguments)
            payload, bundle = self._run_event_record_capture(spec)
            if bundle is None:
                payload["analysis_ok"] = False
                payload["message"] = "Generated event-record capture did not complete successfully."
                return payload
        payload = _base_payload_from_bundle(bundle)
        payload["used_existing_run"] = used_existing_run
        summary = bundle["summary"]
        chain_key = _build_decay_chain_key(chain_query)
        decay_chain_counts = summary.get("decay_chain_counts", {})
        chain_match_count = 0
        if isinstance(decay_chain_counts, dict):
            try:
                chain_match_count = int(decay_chain_counts.get(chain_key, 0))
            except (TypeError, ValueError):
                chain_match_count = 0
        representative_matches: list[dict[str, Any]] = []
        events = bundle["examples"].get("events")
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue
                matches = _chain_match_sequences(event, chain_query)
                if not matches:
                    continue
                representative_matches.append(
                    {
                        "accepted_event_index": event.get("accepted_event_index"),
                        "matches": matches[:3],
                    }
                )
        payload["analysis_ok"] = True
        payload["decay_chain"] = {
            "query": dataclasses.asdict(chain_query),
            "chain_key": chain_key,
            "match_count": chain_match_count,
            "representative_matches": representative_matches[:3],
        }
        return payload

    def explain_status_codes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        run_id = arguments.get("run_id")
        payload: dict[str, Any]
        status_histogram: dict[str, Any] = {}
        if run_id is not None:
            bundle = _load_event_record_bundle(
                run_id,
                completed_root=self.completed_runs_root,
                legacy_completed_root=self.legacy_completed_runs_root,
            )
            payload = _base_payload_from_bundle(bundle)
            summary = bundle["summary"]
            histogram = summary.get("status_code_counts")
            if isinstance(histogram, dict):
                status_histogram = histogram
        else:
            payload = {}
        explanations = []
        for code in _normalize_status_code_list(arguments.get("status_codes")):
            item = explain_status_code(code)
            observed_count = status_histogram.get(str(code))
            if observed_count is not None:
                try:
                    item["observed_count"] = int(observed_count)
                except (TypeError, ValueError):
                    pass
            explanations.append(item)
        payload["status_code_explanations"] = explanations
        payload["analysis_ok"] = True
        return payload

    @contextmanager
    def _bootstrap_lock(self, alias: str):
        self.locks_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.locks_root / f"{alias}.lock"
        with lock_path.open("w", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _make_run_dir(self) -> Path:
        self.runs_tmp_root.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="run-", dir=self.runs_tmp_root))

    def _write_supporting_files(self, run_dir: Path, supporting_files: list[SupportingFile]) -> None:
        for item in supporting_files:
            (run_dir / item.name).write_text(item.content, encoding="utf-8")

    def _write_generated_artifact_header(self, run_dir: Path) -> None:
        (run_dir / ARTIFACT_HELPER_HEADER).write_text(
            _artifact_helper_header_source(), encoding="utf-8"
        )

    def _assert_valid_root(self, root: RootEntry) -> None:
        if not root.path.is_dir():
            raise PythiaSimError(f"Configured root '{root.alias}' does not exist: {root.path}")
        required_paths = [
            root.path / "include" / "Pythia8" / "Pythia.h",
            root.path / "examples" / "Makefile",
            root.path / "share" / "Pythia8" / "xmldoc",
        ]
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            raise PythiaSimError(
                f"Configured root '{root.alias}' does not look like a standalone Pythia checkout. Missing: {', '.join(missing)}"
            )

    def _select_root(self, root_alias: str | None) -> RootEntry:
        registry = load_registry(self.registry_path, plugin_root=self.plugin_root)
        alias = root_alias or registry.default_alias
        try:
            return registry.roots[alias]
        except KeyError as exc:
            raise PythiaSimError(f"Unknown root alias '{alias}'.") from exc

    def _prepare_root(
        self,
        root: RootEntry,
        *,
        max_output_bytes: int,
    ) -> tuple[dict[str, str], bool, CommandExecution | None]:
        self._assert_valid_root(root)
        makefile_path = root.path / "Makefile.inc"
        make_vars = parse_makefile_inc(makefile_path)
        libs_present = any((root.path / "lib").glob("libpythia8.*"))
        if libs_present:
            return make_vars, False, None

        with self._bootstrap_lock(root.alias):
            libs_present = any((root.path / "lib").glob("libpythia8.*"))
            if libs_present:
                return make_vars, False, None
            build_result = _run_subprocess_capped(
                root.build_command,
                cwd=root.path,
                env=os.environ.copy(),
                timeout_sec=AUTO_BUILD_TIMEOUT_SEC,
                max_output_bytes=max_output_bytes,
            )
            if build_result.exit_code != 0 or build_result.timed_out:
                return make_vars, True, build_result
            if not any((root.path / "lib").glob("libpythia8.*")):
                build_result.stderr = (
                    build_result.stderr
                    + "\n[pythia-sim] Build command completed but lib/libpythia8.* was not produced.\n"
                )
                build_result.exit_code = build_result.exit_code or 1
                return make_vars, True, build_result
        return make_vars, True, None

    def _copy_failed_artifacts(
        self,
        run_dir: Path,
        *,
        run_id: str,
        request_payload: dict[str, Any],
        root: RootEntry,
        bootstrap_performed: bool,
        compile_result: dict[str, Any],
        run_result: dict[str, Any],
    ) -> Path:
        metadata = {
            "run_id": run_id,
            "root_alias": root.alias,
            "root_path": str(root.path),
            "bootstrap_performed": bootstrap_performed,
            "request": request_payload,
            "compile": compile_result,
            "run": run_result,
            "created_at_epoch_sec": int(time.time()),
        }
        _write_json(run_dir / "metadata.json", metadata)
        return preserve_failure_run(run_dir, self.failed_runs_root)

    def _persist_event_record_snapshot(
        self,
        *,
        run_id: str,
        run_dir: Path,
        request_payload: dict[str, Any],
        root: RootEntry,
        bootstrap_performed: bool,
        compile_result: dict[str, Any],
        run_result: dict[str, Any],
    ) -> Path:
        summary = _load_json_file(run_dir / EVENT_RECORD_SUMMARY_ARTIFACT, label=EVENT_RECORD_SUMMARY_ARTIFACT)
        examples = _load_json_file(
            run_dir / EVENT_RECORD_EXAMPLES_ARTIFACT, label=EVENT_RECORD_EXAMPLES_ARTIFACT
        )
        destination = self.completed_runs_root / run_id
        destination.mkdir(parents=True, exist_ok=False)
        try:
            metadata = {
                "run_id": run_id,
                "root_alias": root.alias,
                "root_path": str(root.path),
                "bootstrap_performed": bootstrap_performed,
                "request": request_payload,
                "compile": compile_result,
                "run": run_result,
                "created_at_epoch_sec": int(time.time()),
            }
            _write_json(destination / "metadata.json", metadata)
            _write_json(destination / EVENT_RECORD_SUMMARY_ARTIFACT, summary)
            _write_json(destination / EVENT_RECORD_EXAMPLES_ARTIFACT, examples)
            self._prune_completed_runs(exclude_run_id=run_id)
            return destination
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise

    def _prune_completed_runs(self, *, exclude_run_id: str | None = None) -> None:
        if not self.completed_runs_root.is_dir():
            return
        run_dirs = [path for path in self.completed_runs_root.iterdir() if path.is_dir()]
        if len(run_dirs) <= MAX_COMPLETED_RUNS:
            return
        run_dirs.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for stale_dir in run_dirs[MAX_COMPLETED_RUNS:]:
            if exclude_run_id is not None and stale_dir.name == exclude_run_id:
                continue
            shutil.rmtree(stale_dir, ignore_errors=True)

    def _try_examples_fallback(
        self,
        *,
        root: RootEntry,
        run_dir: Path,
        source_path: Path,
        remaining_compile_timeout: int,
        max_output_bytes: int,
    ) -> tuple[CommandExecution | None, Path | None]:
        examples_dir = root.path / "examples"
        if remaining_compile_timeout <= 1 or not (examples_dir / "Makefile").is_file():
            return None, None
        suffix = hashlib.sha256(
            f"{source_path}:{time.time_ns()}".encode("utf-8")
        ).hexdigest()[:10]
        stem = f"mymain{suffix}"
        fallback_source = examples_dir / f"{stem}.cc"
        fallback_binary = examples_dir / stem
        fallback_header = examples_dir / ARTIFACT_HELPER_HEADER
        fallback_source.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        header_path = run_dir / ARTIFACT_HELPER_HEADER
        if header_path.exists():
            fallback_header.write_text(header_path.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            fallback_result = _run_subprocess_capped(
                ["make", stem],
                cwd=examples_dir,
                env=os.environ.copy(),
                timeout_sec=remaining_compile_timeout,
                max_output_bytes=max_output_bytes,
            )
            if fallback_result.exit_code == 0 and fallback_binary.exists():
                copied_binary = run_dir / stem
                shutil.copy2(fallback_binary, copied_binary)
                return fallback_result, copied_binary
            return fallback_result, None
        finally:
            if fallback_source.exists():
                fallback_source.unlink()
            if fallback_binary.exists():
                fallback_binary.unlink()
            if fallback_header.exists():
                fallback_header.unlink()

    def _execute_run_lifecycle(
        self,
        *,
        root: RootEntry,
        run_dir: Path,
        source_path: Path,
        compile_timeout_sec: int,
        run_timeout_sec: int,
        max_output_bytes: int,
    ) -> SimulationLifecycleResult:
        compile_stdout = ""
        compile_stderr = ""
        compile_command_summaries: list[str] = []
        compile_exit_code: int | None = None
        bootstrap_performed = False
        executable_path: Path | None = None
        run_result = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
        }

        make_vars, bootstrap_performed, bootstrap_result = self._prepare_root(
            root, max_output_bytes=max_output_bytes
        )
        if bootstrap_result is not None:
            compile_command_summaries.append(f"bootstrap: {_shell_join(bootstrap_result.command)}")
            compile_stdout += _format_stage_output("bootstrap stdout", bootstrap_result.stdout)
            compile_stderr += _format_stage_output("bootstrap stderr", bootstrap_result.stderr)
            compile_exit_code = bootstrap_result.exit_code
            compile_result = {
                "ok": False,
                "exit_code": compile_exit_code,
                "stdout": compile_stdout,
                "stderr": compile_stderr,
                "command_summary": " ; ".join(compile_command_summaries),
            }
            return SimulationLifecycleResult(
                bootstrap_performed=bootstrap_performed,
                compile_result=compile_result,
                run_result=run_result,
            )

        executable_path = run_dir / "simulation.out"
        direct_command = build_direct_compile_command(
            make_vars, source_path=source_path, output_path=executable_path
        )
        compile_command_summaries.append(f"direct: {_shell_join(direct_command)}")
        compile_started = time.monotonic()
        direct_result = _run_subprocess_capped(
            direct_command,
            cwd=run_dir,
            env=os.environ.copy(),
            timeout_sec=compile_timeout_sec,
            max_output_bytes=max_output_bytes,
        )
        compile_stdout += _format_stage_output("direct stdout", direct_result.stdout)
        compile_stderr += _format_stage_output("direct stderr", direct_result.stderr)
        compile_exit_code = direct_result.exit_code
        compile_ok = direct_result.exit_code == 0 and not direct_result.timed_out

        if not compile_ok:
            elapsed = int(time.monotonic() - compile_started)
            remaining = max(1, compile_timeout_sec - elapsed)
            fallback_result, fallback_binary = self._try_examples_fallback(
                root=root,
                run_dir=run_dir,
                source_path=source_path,
                remaining_compile_timeout=remaining,
                max_output_bytes=max_output_bytes,
            )
            if fallback_result is not None:
                compile_command_summaries.append(
                    f"fallback: {_shell_join(fallback_result.command)}"
                )
                compile_stdout += _format_stage_output("fallback stdout", fallback_result.stdout)
                compile_stderr += _format_stage_output("fallback stderr", fallback_result.stderr)
                compile_exit_code = fallback_result.exit_code
                if fallback_result.exit_code == 0 and fallback_binary is not None:
                    compile_ok = True
                    executable_path = fallback_binary

        compile_result = {
            "ok": compile_ok,
            "exit_code": compile_exit_code,
            "stdout": compile_stdout,
            "stderr": compile_stderr,
            "command_summary": " ; ".join(compile_command_summaries),
        }

        if not compile_ok or executable_path is None:
            return SimulationLifecycleResult(
                bootstrap_performed=bootstrap_performed,
                compile_result=compile_result,
                run_result=run_result,
            )

        env = os.environ.copy()
        env["PYTHIA8DATA"] = str(root.path / "share" / "Pythia8" / "xmldoc")
        execution = _run_subprocess_capped(
            [str(executable_path)],
            cwd=run_dir,
            env=env,
            timeout_sec=run_timeout_sec,
            max_output_bytes=max_output_bytes,
        )
        run_result = {
            "ok": execution.exit_code == 0 and not execution.timed_out,
            "exit_code": execution.exit_code,
            "stdout": execution.stdout,
            "stderr": execution.stderr,
            "timed_out": execution.timed_out,
        }
        if run_result["ok"]:
            try:
                run_result["stdout"] = normalize_terminal_outputs(execution.stdout)
            except PythiaSimError as exc:
                run_result = {
                    "ok": False,
                    "exit_code": execution.exit_code,
                    "stdout": execution.stdout,
                    "stderr": execution.stderr
                    + ("\n" if execution.stderr and not execution.stderr.endswith("\n") else "")
                    + f"[pythia-sim] {exc}\n",
                    "timed_out": execution.timed_out,
                }

        return SimulationLifecycleResult(
            bootstrap_performed=bootstrap_performed,
            compile_result=compile_result,
            run_result=run_result,
        )

    def run_pythia_simulation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _reject_removed_artifact_cap(arguments)
        root_alias = arguments.get("root_alias")
        if root_alias is not None and (not isinstance(root_alias, str) or not root_alias):
            raise PythiaSimError("root_alias must be a non-empty string when provided.")

        compile_timeout_sec = _coerce_timeout(
            arguments.get("compile_timeout_sec"),
            name="compile_timeout_sec",
            default=DEFAULT_COMPILE_TIMEOUT_SEC,
            maximum=MAX_COMPILE_TIMEOUT_SEC,
        )
        run_timeout_sec = _coerce_timeout(
            arguments.get("run_timeout_sec"),
            name="run_timeout_sec",
            default=DEFAULT_RUN_TIMEOUT_SEC,
            maximum=MAX_RUN_TIMEOUT_SEC,
        )
        max_output_bytes = _coerce_output_cap(arguments.get("max_output_bytes"))
        source_cpp = arguments.get("source_cpp")
        validate_source_cpp(source_cpp)
        supporting_files = validate_supporting_files(arguments.get("supporting_files"))

        root = self._select_root(root_alias)
        run_id = uuid.uuid4().hex
        request_payload = {
            "run_id": run_id,
            "root_alias": root.alias,
            "compile_timeout_sec": compile_timeout_sec,
            "run_timeout_sec": run_timeout_sec,
            "max_output_bytes": max_output_bytes,
            "supporting_files": [dataclasses.asdict(item) for item in supporting_files],
        }

        run_dir = self._make_run_dir()
        source_path = run_dir / "source.cpp"
        source_path.write_text(source_cpp, encoding="utf-8")
        self._write_generated_artifact_header(run_dir)
        self._write_supporting_files(run_dir, supporting_files)

        compile_result = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "command_summary": "",
        }
        run_result = {
            "ok": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "timed_out": False,
        }
        bootstrap_performed = False

        try:
            lifecycle = self._execute_run_lifecycle(
                root=root,
                run_dir=run_dir,
                source_path=source_path,
                compile_timeout_sec=compile_timeout_sec,
                run_timeout_sec=run_timeout_sec,
                max_output_bytes=max_output_bytes,
            )
            bootstrap_performed = lifecycle.bootstrap_performed
            compile_result = lifecycle.compile_result
            run_result = lifecycle.run_result
            if not run_result["ok"]:
                failure_dir = self._copy_failed_artifacts(
                    run_dir,
                    run_id=run_id,
                    request_payload=request_payload,
                    root=root,
                    bootstrap_performed=bootstrap_performed,
                    compile_result=compile_result,
                    run_result=run_result,
                )
                return {
                    "run_id": run_id,
                    "root_alias": root.alias,
                    "bootstrap_performed": bootstrap_performed,
                    "compile": compile_result,
                    "run": run_result,
                    "failure_artifacts_path": str(failure_dir),
                }

            cleanup_success_run(run_dir)
            return {
                "run_id": run_id,
                "root_alias": root.alias,
                "bootstrap_performed": bootstrap_performed,
                "compile": compile_result,
                "run": run_result,
            }
        except PythiaSimError:
            raise
        except Exception as exc:  # pragma: no cover - defensive server-side fallback
            compile_result = {
                "ok": False,
                "exit_code": compile_result.get("exit_code"),
                "stdout": str(compile_result.get("stdout", "")),
                "stderr": str(compile_result.get("stderr", ""))
                + _format_stage_output("internal error", str(exc)),
                "command_summary": str(compile_result.get("command_summary", "")),
            }
            failure_dir = self._copy_failed_artifacts(
                run_dir,
                run_id=run_id,
                request_payload=request_payload,
                root=root,
                bootstrap_performed=bootstrap_performed,
                compile_result=compile_result,
                run_result=run_result,
            )
            raise PythiaSimError(
                f"Unexpected internal error. Failure artifacts preserved at {failure_dir}.",
                failure_artifacts_path=str(failure_dir),
            ) from exc


LIST_ROOTS_TOOL: dict[str, Any] = {
    "name": "list_pythia_roots",
    "description": "List configured standalone Pythia roots, their readiness, compiler, and whether execution is available.",
    "inputSchema": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

SEARCH_EXAMPLES_TOOL: dict[str, Any] = {
    "name": "search_pythia_examples",
    "description": "Search the configured Pythia examples directory for standalone reference code and .cmnd files.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text query used to find relevant .cc or .cmnd example snippets.",
            },
            "root_alias": {
                "type": "string",
                "description": "Configured Pythia root alias. Defaults to the registry default_alias.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_EXAMPLE_SEARCH_RESULTS,
            },
            "include_cmnd": {
                "type": "boolean",
                "description": "Whether .cmnd companion files should be included in the search.",
            },
            "safety_mode": {
                "type": "string",
                "enum": [
                    EXAMPLE_SAFETY_MODE_STANDALONE_ONLY,
                    EXAMPLE_SAFETY_MODE_ALL,
                ],
                "description": "Use standalone_only to exclude examples that rely on unsupported external integrations.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

SUMMARIZE_EVENT_RECORD_TOOL: dict[str, Any] = {
    "name": "summarize_event_record",
    "description": "Run a bounded declarative standalone Pythia simulation and persist private event-record snapshots for later introspection.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "root_alias": {
                "type": "string",
                "description": "Configured Pythia root alias. Defaults to the registry default_alias.",
            },
            "commands": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Pythia readString commands to apply before init().",
            },
            "cmnd_text": {
                "type": "string",
                "description": "Optional raw .cmnd file text to load as settings.cmnd before init().",
            },
            "event_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EVENT_COUNT,
            },
            "random_seed": {"type": "integer", "minimum": 1},
            "example_event_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EXAMPLE_EVENTS,
            },
            "compile_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_COMPILE_TIMEOUT_SEC,
            },
            "run_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RUN_TIMEOUT_SEC,
            },
            "max_output_bytes": {
                "type": "integer",
                "minimum": MIN_OUTPUT_BYTES,
                "maximum": MAX_OUTPUT_BYTES,
            },
        },
        "additionalProperties": False,
    },
}

TRACE_PARTICLE_LINEAGE_TOOL: dict[str, Any] = {
    "name": "trace_particle_lineage",
    "description": "Trace a selected particle through stored or freshly generated event-record snapshots using structured particle selectors and ancestry options.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "run_id": {
                "type": "string",
                "description": "Reuse a previously captured event-record run instead of rerunning the simulation.",
            },
            "root_alias": {"type": "string"},
            "commands": {"type": "array", "items": {"type": "string"}},
            "cmnd_text": {"type": "string"},
            "event_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EVENT_COUNT,
            },
            "random_seed": {"type": "integer", "minimum": 1},
            "example_event_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EXAMPLE_EVENTS,
            },
            "compile_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_COMPILE_TIMEOUT_SEC,
            },
            "run_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RUN_TIMEOUT_SEC,
            },
            "max_output_bytes": {
                "type": "integer",
                "minimum": MIN_OUTPUT_BYTES,
                "maximum": MAX_OUTPUT_BYTES,
            },
            "particle_selector": {
                "type": "object",
                "properties": {
                    "pdg_id": {"type": "integer"},
                    "final_state": {"type": "boolean"},
                    "charge": {"type": "integer", "enum": [-1, 0, 1]},
                    "status_codes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                    "rank_by": {
                        "type": "string",
                        "enum": [TRACE_RANK_BY_PT, TRACE_RANK_BY_ENERGY, TRACE_RANK_BY_ETA_ABS],
                    },
                    "rank": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            "trace_options": {
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": [TRACE_DIRECTION_ANCESTORS, TRACE_DIRECTION_DESCENDANTS],
                    },
                    "stop_at": {
                        "oneOf": [
                            {
                                "type": "string",
                                "enum": [
                                    TRACE_STOP_AT_HARD_PROCESS_BOSON,
                                    TRACE_STOP_AT_INCOMING_PARTONS,
                                    TRACE_STOP_AT_BEAM,
                                ],
                            },
                            {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                        ]
                    },
                    "max_depth": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_TRACE_DEPTH,
                    },
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    },
}

FIND_DECAY_CHAIN_TOOL: dict[str, Any] = {
    "name": "find_decay_chain",
    "description": "Count and sample stored or freshly generated decay-chain occurrences using a structured parent/intermediate/child query.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "root_alias": {"type": "string"},
            "commands": {"type": "array", "items": {"type": "string"}},
            "cmnd_text": {"type": "string"},
            "event_count": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EVENT_COUNT,
            },
            "random_seed": {"type": "integer", "minimum": 1},
            "example_event_limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_INTROSPECTION_EXAMPLE_EVENTS,
            },
            "compile_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_COMPILE_TIMEOUT_SEC,
            },
            "run_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RUN_TIMEOUT_SEC,
            },
            "max_output_bytes": {
                "type": "integer",
                "minimum": MIN_OUTPUT_BYTES,
                "maximum": MAX_OUTPUT_BYTES,
            },
            "decay_chain": {
                "type": "object",
                "properties": {
                    "parent_pdg_id": {"type": "integer"},
                    "child_pdg_id": {"type": "integer"},
                    "intermediate_pdg_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["parent_pdg_id", "child_pdg_id"],
                "additionalProperties": False,
            },
        },
        "required": ["decay_chain"],
        "additionalProperties": False,
    },
}

EXPLAIN_STATUS_CODES_TOOL: dict[str, Any] = {
    "name": "explain_status_codes",
    "description": "Explain curated Pythia status-code meanings, with optional observed counts from a previously captured event-record run.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "status_codes": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 1,
                "maxItems": MAX_STATUS_CODES_QUERY,
            },
            "run_id": {"type": "string"},
        },
        "required": ["status_codes"],
        "additionalProperties": False,
    },
}

RUN_SIMULATION_TOOL: dict[str, Any] = {
    "name": "run_pythia_simulation",
    "description": "Compile and run raw standalone Pythia C++ in an isolated directory, with auto-build for configured standalone roots when needed.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "root_alias": {
                "type": "string",
                "description": "Configured Pythia root alias. Defaults to the registry default_alias.",
            },
            "source_cpp": {
                "type": "string",
                "description": "Raw standalone C++ source that uses only standalone Pythia and safe standard library headers.",
            },
            "supporting_files": {
                "type": "array",
                "description": "Optional text companion files such as .cmnd files.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["name", "content"],
                    "additionalProperties": False,
                },
            },
            "compile_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_COMPILE_TIMEOUT_SEC,
            },
            "run_timeout_sec": {
                "type": "integer",
                "minimum": 1,
                "maximum": MAX_RUN_TIMEOUT_SEC,
            },
            "max_output_bytes": {
                "type": "integer",
                "minimum": MIN_OUTPUT_BYTES,
                "maximum": MAX_OUTPUT_BYTES,
            },
        },
        "required": ["source_cpp"],
        "additionalProperties": False,
    },
}
