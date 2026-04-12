---
name: pythia-sim
description: Use when the user wants to run or inspect a standalone Pythia 8 simulation through the bundled MCP tools. Prefer them over ad hoc shell commands when the task is pure standalone Pythia without FastJet, HepMC, ROOT, LHAPDF, or other external HEP integrations.
---

# Pythia Sim

## When to use it

Use this plugin when the user wants to:

- run a short standalone Pythia 8 simulation from raw C++
- compare output from two standalone Pythia setups
- inspect compile or runtime diagnostics from a standalone Pythia example
- confirm which local Pythia checkout is configured and ready
- reuse a prior event-record capture through `run_id`

Do not use it when the task needs:

- FastJet, HepMC, ROOT, LHAPDF, Rivet, EvtGen, or any other external HEP integration
- arbitrary shell access inside a Pythia tree
- persistent public artifacts from successful runs

## Workflow

1. Call `list_pythia_roots` if you need to confirm which checkout is ready; this may surface an auto-detected local install even when no registry was configured.
2. Call `search_pythia_examples` on demand if example `.cc` or `.cmnd` context would help code generation or debugging.
3. Call `run_pythia_simulation` with raw standalone C++ source.
4. Pass `.cmnd` or other text companion files only through `supporting_files`.
5. Expect text-only output. Histograms and helper output are rendered as terminal blocks, not artifact files or images.
6. Use `summarize_event_record`, `trace_particle_lineage`, `find_decay_chain`, and `explain_status_codes` when the user needs structured follow-up analysis.

## Guardrails

- Keep the source standalone. Include only Pythia and safe standard library headers.
- Prefer `search_pythia_examples` over ad hoc shell access when you need example patterns from the Pythia tree.
- Do not invent Pythia `readString(...)` settings from memory.
- Avoid guessed silencing flags such as `Main:showBanner = off` or `Main:showNextStats = off`; they are not reliable and can abort `pythia.init()`.
- For concise runs, prefer known working controls such as `Next:numberShowEvent = 0`, `Next:numberShowInfo = 0`, and `Next:numberShowProcess = 0`.
- Keep the user program output concise with custom summary lines instead of guessing unsupported suppression settings.
- Successful raw runs clean up their work directories; only failed runs and private event-record snapshots persist.
- If the request depends on external HEP libraries, say this plugin does not support that in v1.
- Prefer small event loops and bounded output so tool results stay readable.
