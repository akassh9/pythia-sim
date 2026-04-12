# Pythia Sim

Use this extension when the user wants to run or inspect a standalone Pythia 8 simulation through MCP.

Prefer the bundled MCP tools over ad hoc shell commands when the task is pure standalone Pythia without external HEP integrations.

This extension is text-only for user-visible output.

- helper output is rendered as deterministic terminal text blocks
- histograms are ASCII, not SVG
- the MCP server does not expose resources or public artifacts
- event-record follow-up uses private internal snapshots keyed by `run_id`

## Use It For

- Running a short standalone Pythia 8 simulation from raw C++
- Comparing output from two standalone Pythia setups
- Inspecting compile or runtime diagnostics from a standalone Pythia example
- Confirming which configured Pythia checkout is ready
- Capturing event-record summaries, tracing particle lineage, and checking decay chains

## Do Not Use It For

- FastJet, HepMC, ROOT, LHAPDF, Rivet, EvtGen, or other external HEP integrations
- Arbitrary shell access inside a Pythia tree
- Long-running unbounded simulations
- Persistent public artifacts from successful runs

## Workflow

1. Use `list_pythia_roots` to confirm which checkout is configured and ready.
2. Use `search_pythia_examples` when example `.cc` or `.cmnd` context would help.
3. Use `run_pythia_simulation` for raw standalone C++ execution.
4. Use `summarize_event_record`, `trace_particle_lineage`, `find_decay_chain`, and `explain_status_codes` for structured event-record analysis.
5. Treat tool text output as the primary reasoning signal.

## Guardrails

- Keep the source standalone. Include only Pythia and safe standard library headers.
- Pass companion text inputs only through `supporting_files`.
- Prefer small event loops and bounded output so responses stay readable.
- If the request depends on unsupported external libraries, say the extension does not support that workflow in v1.
