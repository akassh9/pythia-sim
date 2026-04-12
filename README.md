# `pythia-sim`

`pythia-sim` is a local MCP plugin for running standalone [Pythia 8](https://pythia.org/) simulations from AI coding agents without dropping into manual shell workflows.

It exposes a bounded stdio MCP server that can:

- discover or bootstrap a usable standalone Pythia installation
- search the local `examples/` tree for reference `.cc` and `.cmnd` files
- compile and run raw standalone Pythia C++ in isolated temporary directories
- capture compact event-record summaries for later structured analysis
- trace particle lineage, count decay chains, and explain common status codes

The repository ships the same runtime for multiple hosts:

- Codex plugin packaging via [`.codex-plugin/plugin.json`](/Users/akash009/plugins/pythia-sim/.codex-plugin/plugin.json)
- Gemini CLI extension packaging via [`gemini-extension.json`](/Users/akash009/plugins/pythia-sim/gemini-extension.json)
- Claude Code plugin packaging via [`.claude-plugin/plugin.json`](/Users/akash009/plugins/pythia-sim/.claude-plugin/plugin.json)

The shared implementation lives in [`scripts/pythia_sim_core.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_core.py) and [`scripts/pythia_sim_server.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_server.py).

## Contents

- [Why this exists](#why-this-exists)
- [Functionality](#functionality)
- [Tool surface](#tool-surface)
- [How it works](#how-it-works)
- [Installation](#installation)
- [Configuration](#configuration)
- [Repository structure](#repository-structure)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

## Why this exists

Running Pythia through an agent is easy to get wrong if the agent has to improvise shell commands, build flags, example paths, and follow-up analysis logic. `pythia-sim` narrows that surface into a small, explicit toolset with validation and runtime limits.

Design goals:

- standalone Pythia only
- deterministic text-first results
- bounded compilation and execution
- reusable event-record snapshots through `run_id`
- minimal host-specific code

This is intentionally not a general HEP execution environment. It does not try to expose arbitrary shell access inside a Pythia checkout, and it does not pretend to support external libraries that are out of scope for the plugin.

## Functionality

### Core capabilities

- Root discovery:
  Find configured Pythia checkouts, report readiness, and surface compiler/build status.
- Auto-detection:
  If no explicit registry is present, the plugin attempts to find a usable local Pythia installation before failing.
- Bootstrapping:
  If nothing is configured, the plugin can download and build a supported standalone Pythia release for the local user.
- Example search:
  Search the configured Pythia `examples/` tree for `.cc` and optional `.cmnd` snippets that match the task.
- Raw simulation runs:
  Compile and execute raw standalone C++ in an isolated working directory with capped output and time limits.
- Event-record introspection:
  Run declarative event-record captures that return a reusable `run_id` for later structured analysis.
- Follow-up analysis:
  Trace a particle's ancestors or descendants, search for decay chains, and map common Pythia status codes to curated explanations.

### Output model

Successful runs are text-only from the MCP perspective.

- Helper outputs such as text, JSON, CSV, and histograms are rendered back into stdout as deterministic terminal blocks.
- JSON helper output is normalized before being returned.
- Histograms are rendered as fixed-width ASCII bars.
- Successful raw runs do not create public artifact files.

Persistent state is limited to private internal directories used for debugging and follow-up analysis:

- failed runs preserve working state and metadata for debugging
- completed event-record snapshots preserve compact JSON summaries and examples
- completed snapshots are pruned to the most recent 25 runs

## Tool surface

The server exposes the following MCP tools.

| Tool | Purpose |
| --- | --- |
| `list_pythia_roots` | List configured or auto-detected roots, compiler availability, build status, and whether standalone execution is possible. |
| `bootstrap_pythia` | Download, configure, build, and register a managed standalone Pythia installation for the local user. On a clean machine it skips host discovery and installs directly into the plugin-managed location. |
| `search_pythia_examples` | Search the configured `examples/` tree for relevant `.cc` and optional `.cmnd` snippets. |
| `run_pythia_simulation` | Compile and run raw standalone Pythia C++ in an isolated directory with bounded time and output. |
| `summarize_event_record` | Run a declarative simulation, store a compact private snapshot, and return a reusable `run_id`. |
| `trace_particle_lineage` | Trace a selected particle through stored or fresh event-record data using structured selectors. |
| `find_decay_chain` | Count and sample structured decay-chain matches from stored or fresh event-record data. |
| `explain_status_codes` | Explain curated Pythia status codes, optionally enriched with observed counts from a stored `run_id`. |

### What is supported

- standalone Pythia headers and safe standard library headers
- `.cmnd` companion files and other text supporting files
- automatic configure/build when a checkout exists but is not fully built
- bounded stdout and stderr capture
- reuse of prior event-record analysis via `run_id`

### What is not supported

- FastJet, HepMC, ROOT, LHAPDF, Rivet, EvtGen, or similar external integrations
- arbitrary shell access inside a Pythia checkout
- filesystem, network, process-spawning, or threading APIs in user-supplied C++
- public artifacts, binary attachments, inline images, or histogram SVG output
- Windows support in the current version

## How it works

At a high level, the runtime is split into two layers:

- [`scripts/pythia_sim_server.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_server.py):
  Minimal JSON-RPC stdio MCP server. It exposes the tool definitions, dispatches calls, and formats user-facing summaries.
- [`scripts/pythia_sim_core.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_core.py):
  Root discovery, validation, bootstrapping, source checks, isolated compilation, bounded execution, output parsing, state management, and event-record analysis.

Execution flow for a raw simulation:

1. Resolve the target Pythia root from explicit config, the persisted managed install, or auto-detection.
2. Validate the source against the plugin's standalone-only guardrails.
3. Create an isolated temporary run directory under the state root.
4. Compile against the chosen Pythia installation.
5. Run the produced binary with capped output and wall-clock limits.
6. Return structured metadata plus text summaries.
7. Keep failed runs for debugging; clean up successful temporary directories.

Execution flow for event-record tools:

1. Generate or reuse a compact event-record snapshot.
2. Persist `metadata.json`, `event_record_summary.json`, and `event_record_examples.json` privately.
3. Return a `run_id`.
4. Use that `run_id` in lineage, decay-chain, or status-code follow-up tools.

## Installation

### Prerequisites

You need the following on the host where the MCP server runs:

- `python3`
- a POSIX-like environment
- `make`
- a working C++ compiler toolchain usable by the target Pythia build

If you want the plugin to bootstrap Pythia automatically, outbound network access is also required so it can download the configured Pythia source tarball. The current bootstrap target is Pythia `8.317`.

The Python runtime uses the standard library only. There is no separate Python dependency install step for the plugin itself.

### Quick local setup

If you already have a usable Pythia checkout:

```bash
export PYTHIA_SIM_ROOT=/absolute/path/to/pythia
```

Then do a quick sanity check from the repo root:

```bash
python3 -m py_compile ./scripts/pythia_sim_server.py ./scripts/pythia_sim_core.py
```

In practice you usually do not talk to the server directly. A host such as Codex, Gemini CLI, or Claude Code launches it through the included MCP manifest files.

### Codex

The Codex packaging is already present:

- [`.codex-plugin/plugin.json`](/Users/akash009/plugins/pythia-sim/.codex-plugin/plugin.json)
- [`.mcp.json`](/Users/akash009/plugins/pythia-sim/.mcp.json)
- [`skills/pythia-sim/SKILL.md`](/Users/akash009/plugins/pythia-sim/skills/pythia-sim/SKILL.md)

For local development, point Codex at the repository as a plugin/workspace that can launch the stdio MCP server described in [`.mcp.json`](/Users/akash009/plugins/pythia-sim/.mcp.json).

### Gemini CLI

Development flow:

```bash
gemini extensions link /absolute/path/to/pythia-sim
```

Install from a Git repository:

```bash
gemini extensions install <repo-url>
```

Gemini requires trusted workspaces for stdio MCP servers:

```bash
gemini trust
```

Validate the extension manifest:

```bash
gemini extensions validate .
```

### Claude Code

Development flow:

```bash
claude --plugin-dir /absolute/path/to/pythia-sim
```

Persistent install flow:

```bash
claude plugin marketplace add /absolute/path/to/pythia-sim
claude plugin install pythia-sim@akash009-plugins
```

Validate the Claude manifests:

```bash
claude plugin validate .
```

## Configuration

### Simplest configuration

The fastest setup is a single environment variable:

```bash
export PYTHIA_SIM_ROOT=/absolute/path/to/pythia
```

Optional companion variables:

- `PYTHIA_SIM_ROOT_ALIAS`: alias for the single-root setup, defaults to `default`
- `PYTHIA_SIM_REGISTRY_PATH`: explicit path to a `roots.json` registry file
- `PYTHIA_SIM_STATE_DIR`: explicit state directory for runs, snapshots, failures, and locks

### Auto-detection behavior

If no explicit registry or single-root environment variable is configured, the plugin attempts to auto-detect a usable local Pythia installation before failing.

The implementation probes a small set of common sources, including:

- `PYTHIA8DATA`
- `pythia8-config`
- common Homebrew-style prefixes
- selected `~/pythia*` and `~/src/pythia*` locations

If no usable root is found, call `bootstrap_pythia`.

On a clean first-use machine, `bootstrap_pythia` skips the host search and installs directly into the plugin-managed vendor directory, then writes a registry entry so later tool calls can find that install immediately.

### Multi-root registry

For multi-root or custom-build setups, start from the example file:

```bash
cp config/roots.example.json ~/.config/pythia-sim/roots.json
```

Example registry:

```json
{
  "default_alias": "pythia8317",
  "roots": [
    {
      "alias": "pythia8317",
      "path": "/absolute/path/to/pythia8317"
    }
  ]
}
```

### Registry discovery order

The runtime resolves roots in this order:

1. `PYTHIA_SIM_REGISTRY_PATH`
2. synthetic single-root config derived from `PYTHIA_SIM_ROOT`
3. `${XDG_CONFIG_HOME}/pythia-sim/roots.json`
4. macOS fallback: `~/.pythia-sim/roots.json`
5. Linux fallback: `~/.config/pythia-sim/roots.json`
6. legacy repo-local `config/roots.json` if present
7. auto-detected local Pythia installs

### State directory resolution

State is resolved in this order:

1. `PYTHIA_SIM_STATE_DIR`
2. `${XDG_STATE_HOME}/pythia-sim`
3. macOS fallback: `~/.pythia-sim/state`
4. Linux fallback: `~/.local/state/pythia-sim`

The state root holds:

- temporary run directories
- failed run directories
- completed event-record snapshots
- lock files used around bootstrapping/build operations

## Repository structure

```text
pythia-sim/
├── .codex-plugin/
│   └── plugin.json
├── .claude-plugin/
│   ├── marketplace.json
│   └── plugin.json
├── config/
│   └── roots.example.json
├── scripts/
│   ├── pythia_sim_core.py
│   └── pythia_sim_server.py
├── skills/
│   └── pythia-sim/
│       └── SKILL.md
├── tests/
│   └── test_pythia_sim.py
├── .mcp.json
├── FEATURES.md
├── GEMINI.md
├── gemini-extension.json
├── package.json
└── README.md
```

### Important files

- [`scripts/pythia_sim_core.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_core.py):
  Main runtime, safety checks, root handling, compile/run execution, and event-record analysis.
- [`scripts/pythia_sim_server.py`](/Users/akash009/plugins/pythia-sim/scripts/pythia_sim_server.py):
  JSON-RPC stdio server wrapper and response summarization.
- [`tests/test_pythia_sim.py`](/Users/akash009/plugins/pythia-sim/tests/test_pythia_sim.py):
  Unit tests covering registry loading, example search, execution behavior, output normalization, and event-record reuse.
- [`skills/pythia-sim/SKILL.md`](/Users/akash009/plugins/pythia-sim/skills/pythia-sim/SKILL.md):
  Host-side usage guidance for agents deciding when to call these tools.
- [`FEATURES.md`](/Users/akash009/plugins/pythia-sim/FEATURES.md):
  Additional design notes on runtime behavior and output/persistence choices.
- [`GEMINI.md`](/Users/akash009/plugins/pythia-sim/GEMINI.md):
  Gemini-specific context file used by the extension packaging.

## Development

### Run tests

```bash
pytest -q
```

### Typical local verification flow

1. Confirm `python3` can launch the server.
2. Confirm a Pythia root is available through config, the persisted managed install, auto-detection, or bootstrap.
3. Run `pytest -q`.
4. Validate the host manifest you are targeting.
5. Exercise a minimal end-to-end workflow in the host:
   `list_pythia_roots` -> `search_pythia_examples` -> `run_pythia_simulation` -> `summarize_event_record`

### What the test suite covers

The current tests focus on:

- registry loading and environment-based root resolution
- example search behavior
- compile/run success and failure paths
- terminal output normalization for text, JSON, CSV, and ASCII histograms
- private event-record snapshot reuse through `run_id`
- server summaries and stdio MCP behavior

## Troubleshooting

### No roots are available

On a clean machine with no local Pythia, start with `bootstrap_pythia`. Otherwise start with `list_pythia_roots`.

- If it finds a usable root, use that alias explicitly if needed.
- If it does not, set `PYTHIA_SIM_ROOT` or create a registry file.
- If you do not already have Pythia installed, call `bootstrap_pythia`.

### A checkout is found but not runnable

This usually means the checkout exists but is not fully configured or built.

- Make sure `make` and a compiler are available.
- Re-run the tool; the plugin can auto-build some roots when needed.
- If that still fails, inspect the returned diagnostics and any preserved failure directory.

### User C++ is rejected before compile

The plugin validates source code before compile to keep the runtime bounded and standalone-only.

Common causes:

- including unsupported external headers
- using filesystem or networking APIs
- spawning subprocesses
- using threads or dynamic loading APIs

If the requested workflow genuinely needs those capabilities, it is outside this plugin's scope.

### Output is too noisy

Prefer valid Pythia controls rather than guessing settings from memory. Useful options include:

```text
Next:numberShowEvent = 0
Next:numberShowInfo = 0
Next:numberShowProcess = 0
```

Also prefer concise custom summaries in the user C++ rather than printing full event dumps.

### A host installs the repo but cannot start the server

Check the following:

- `python3` is on `PATH`
- the workspace is trusted if the host requires that
- the host is loading the manifest from this repository, not a stale copy
- the current working directory used by the host matches the manifest expectations

## Limitations

This repository is intentionally narrow.

- It is for standalone Pythia 8 only.
- It is optimized for agent-driven tooling, not for large production simulation pipelines.
- It does not expose resources or artifact browsing through MCP.
- It does not support external HEP integrations in the current version.
- It does not currently ship a Windows story.

If you need ROOT, FastJet, HepMC, LHAPDF, Rivet, or arbitrary analysis code around Pythia, this plugin should be treated as the wrong abstraction rather than stretched to fit.
