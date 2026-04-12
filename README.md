# `pythia-sim`

`pythia-sim` is a high-performance Model Context Protocol (MCP) plugin that empowers AI coding agents to natively execute and analyze standalone [Pythia 8](https://pythia.org/) particle physics simulations. 

By abstracting away fragile manual shell workflows, `pythia-sim` provides a deterministic and bounded execution environment. It allows AI agents to instantly generate, trace, and summarize complex high-energy physics (HEP) events directly within their context window.

---

## 🚀 Core Capabilities

* **Zero-Config Bootstrapping:** Automatically discovers local Pythia installations or securely downloads, compiles, and registers a fresh instance on the fly.
* **Advanced Event Analysis:** Generates compact, LLM-optimized JSON snapshots of event records. Includes dedicated pipelines to trace particle lineage, map decay chains, and explain physics status codes.
* **Omni-Host Ready:** Ships with plug-and-play manifests for seamless integration with Gemini CLI and Claude Code. 

---

## Installation

### Gemini CLI

Install from a Git repository:

```bash
gemini extensions install https://github.com/akassh9/pythia-sim
```

### Claude Code

Install flow:

```bash
claude plugin marketplace add https://github.com/akassh9/pythia-sim
claude plugin install pythia-sim@akash009-plugins
```

## Configuration

### Auto-detection behavior

If no explicit registry or single-root environment variable is configured, the plugin attempts to auto-detect a usable local Pythia installation before failing.

The implementation probes a small set of common sources, including:

- `PYTHIA8DATA`
- `pythia8-config`
- common Homebrew-style prefixes
- selected `~/pythia*` and `~/src/pythia*` locations

If no usable root is found, call `bootstrap_pythia`.

On a clean first-use machine, `bootstrap_pythia` skips the host search and installs directly into the plugin-managed vendor directory, then writes a registry entry so later tool calls can find that install immediately.

## 🛠️ MCP Tool Surface

The server exposes a targeted suite of tools designed for autonomous agent workflows:

| Tool | Capability |
| --- | --- |
| `list_pythia_roots` | Scans the host for available Pythia environments and compiler readiness. |
| `bootstrap_pythia` | Downloads, builds, and registers a managed Pythia 8 installation. |
| `search_pythia_examples` | Surfaces relevant `.cc` and `.cmnd` snippets from Pythia's official examples. |
| `run_pythia_simulation` | Executes sandboxed, bounded C++ simulations and captures formatted stdout. |
| `summarize_event_record` | Runs a simulation and returns a reusable `run_id` linked to a compact JSON state. |
| `trace_particle_lineage` | Deep-dives into a specific `run_id` to map a particle's exact history. |
| `find_decay_chain` | Counts and samples structured decay-chain matches from stored event data. |
| `explain_status_codes` | Decodes Pythia status codes based on observed event frequencies. |

---

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

## Limitations

This repository is intentionally narrow.

- It is for standalone Pythia 8 only.
- It is optimized for agent-driven tooling, not for large production simulation pipelines.
- It does not expose resources or artifact browsing through MCP.
- It does not support external HEP integrations in the current version.
- It does not currently ship a Windows story.

If you need ROOT, FastJet, HepMC, LHAPDF, Rivet, or arbitrary analysis code around Pythia, this plugin should be treated as the wrong abstraction rather than stretched to fit.
