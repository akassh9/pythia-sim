# `pythia-sim` Feature Notes

`pythia-sim` is a local Codex plugin that exposes standalone Pythia 8 workflows through a stdio MCP server.

The current design is intentionally narrow:

- deterministic text-only tool output
- bounded standalone compilation and execution
- private event-record snapshot reuse through `run_id`
- no public artifact, image, or resource layer

## Runtime Overview

The plugin provides:

1. Root discovery and readiness checks
2. Example search across the local Pythia `examples/` tree
3. Raw standalone C++ execution in isolated temp directories
4. Structured event-record capture for later lineage and decay-chain analysis
5. Source validation and runtime limits for bounded standalone usage

## Text Output Helpers

The generated helper header `pythia_sim_artifacts.h` still provides:

- `emit_text`
- `emit_json`
- `emit_csv`
- `emit_histogram`

Those helpers no longer create persisted artifacts.

Current behavior:

- helper calls emit terminal output blocks into stdout
- JSON blocks are normalized before results are returned
- histogram blocks render fixed-width ASCII bars
- successful raw runs return only text output and compile/run metadata

## Run Persistence Model

Successful raw simulations do not persist public outputs.

Persistent state is limited to:

- failed-run directories for debugging
- private completed snapshots for structured event-record analysis

Failed runs preserve:

- the working directory
- `metadata.json`
- compile/run details
- the original request payload

Private completed event-record snapshots preserve:

- `metadata.json`
- `event_record_summary.json`
- `event_record_examples.json`

Current retention policy:

- completed snapshots are pruned to the most recent 25 directories
- temporary run directories are deleted after successful completion
- failed runs are intentionally retained for debugging

## MCP Surface

The server exposes tools only.

It does not expose:

- `resources/read`
- `resources/list`
- resource subscriptions
- inline image blocks
- resource-link content items

All user-visible results are text summaries plus structured payloads.

## Event-Record Analysis

The analysis-oriented tools are:

- `summarize_event_record`
- `trace_particle_lineage`
- `find_decay_chain`
- `explain_status_codes`

`summarize_event_record` generates a standalone capture program from structured inputs, writes summary/example JSON into the isolated run directory, snapshots those files privately on success, and returns a `run_id`.

The follow-up tools consume that `run_id` by reading the private snapshot files directly.

## Safety Boundaries

Still supported:

- standalone Pythia headers and safe standard library headers for user code
- bounded stdout/stderr capture
- optional example-build fallback when direct compilation fails

Still disallowed:

- FastJet, HepMC, ROOT, LHAPDF, Rivet, EvtGen, and similar external integrations
- filesystem, network, process-spawning, and threading APIs in user-supplied C++
- persistent public artifacts or binary output channels

## Testing Focus

The test suite covers:

- registry loading and example search
- compile/run success and failure handling
- terminal output normalization for text, JSON, CSV, and ASCII histograms
- private event-record snapshot reuse
- server summaries and MCP stdio behavior
