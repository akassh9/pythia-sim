# `pythia-sim`

`pythia-sim` exposes standalone Pythia 8 workflows through a local stdio MCP server.

The repo supports two hosts with the same runtime:

- Codex plugin packaging through `.codex-plugin/plugin.json`
- Gemini CLI extension packaging through `gemini-extension.json`

The shared runtime lives in `scripts/pythia_sim_server.py`.

## What It Supports

- Listing configured standalone Pythia roots
- Searching the local `examples/` tree for reference `.cc` and `.cmnd` snippets
- Compiling and running bounded standalone Pythia C++ snippets
- Rendering helper output as deterministic text blocks in terminal stdout
- Capturing private event-record snapshots for later `run_id` reuse
- Tracing particle lineage and counting decay chains from stored event-record snapshots
- Explaining curated Pythia status codes

## What It Does Not Support

- FastJet, HepMC, ROOT, LHAPDF, Rivet, EvtGen, or other external HEP integrations
- Public artifact files, resource links, inline images, or histogram SVG rendering
- Arbitrary shell access inside a Pythia checkout
- Windows support in v1

## Output Model

`run_pythia_simulation` is text-only.

- `emit_text`, `emit_json`, `emit_csv`, and `emit_histogram` still exist in `pythia_sim_artifacts.h`
- those helpers now render deterministic terminal blocks into stdout
- JSON output is normalized before the result is returned
- histograms are rendered as fixed-width ASCII bars
- successful raw runs do not persist public artifacts

Event-record tools still preserve reusable state, but only as private internal snapshots containing:

- `metadata.json`
- `event_record_summary.json`
- `event_record_examples.json`

Those snapshots are used for `run_id` follow-up analysis and are not exposed through MCP resources.

## Gemini CLI Install

Development flow:

```bash
gemini extensions link /path/to/pythia-sim
```

Public GitHub install flow:

```bash
gemini extensions install <repo-url>
```

Gemini CLI requires trusted workspaces for stdio MCP servers. In any workspace where you want the extension to run:

```bash
gemini trust
```

You can validate the extension manifest locally with:

```bash
gemini extensions validate .
```

## Configuration

The fastest setup path is a single environment variable:

```bash
export PYTHIA_SIM_ROOT=/path/to/pythia
```

Optional environment variables:

- `PYTHIA_SIM_ROOT_ALIAS`: Alias for the single-root setup. Defaults to `default`.
- `PYTHIA_SIM_REGISTRY_PATH`: Path to a `roots.json` registry file. Takes precedence over `PYTHIA_SIM_ROOT`.
- `PYTHIA_SIM_STATE_DIR`: Where run state, private snapshots, failed-run directories, and locks are stored.

Registry discovery order:

1. `PYTHIA_SIM_REGISTRY_PATH`
2. Synthetic single-root config from `PYTHIA_SIM_ROOT`
3. `${XDG_CONFIG_HOME}/pythia-sim/roots.json` when `XDG_CONFIG_HOME` is set
4. macOS fallback: `~/Library/Application Support/pythia-sim/roots.json`
5. Linux fallback: `~/.config/pythia-sim/roots.json`
6. Legacy repo-local `config/roots.json`

State directory resolution order:

1. `PYTHIA_SIM_STATE_DIR`
2. `${XDG_STATE_HOME}/pythia-sim` when `XDG_STATE_HOME` is set
3. macOS fallback: `~/Library/Application Support/pythia-sim/state`
4. Linux fallback: `~/.local/state/pythia-sim`

For a multi-root or custom-build setup, start from the example registry:

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

## Codex Usage

The existing Codex packaging remains in place:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/pythia-sim/SKILL.md`

Codex and Gemini CLI both use the same MCP tool surface.

## Development

Run the test suite:

```bash
pytest -q
```

Manual acceptance flow:

1. `gemini extensions link .`
2. Restart the host.
3. Confirm the extension appears.
4. Ask it to list roots, search examples, run a tiny standalone simulation, and summarize an event record.
