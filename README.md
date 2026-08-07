# grok-kicad-connector

AI connector between xAI Grok and KiCad using Python + the official IPC API (`kicad-python`).

Natural-language PCB design, component placement, routing assistance, DRC loops, and (with KiCad 11+) schematic support.

## Status

**Early harness phase.**  
PCB-focused tools are the primary target on KiCad 9/10.  
Schematic support uses a file-based bridge until official IPC schematic APIs land in KiCad 11 (expected ~Feb 2027).

## Architecture Overview

- **Harness layer** — narrow, version-gated tools with strong pre/post conditions and checkpoints  
- **Loop layer** — verification / evidence loops (DRC, connectivity, human gates)  
- **Graph layer** — workflow topology (place → route → verify → export)

See [`docs/HARNESS.md`](docs/HARNESS.md) for the full Harness Engineering Spec.

## Version Support Matrix

| KiCad Version | PCB IPC API | Schematic IPC API | Headless `api-server` | Recommended Schematic Path |
|---------------|-------------|-------------------|-----------------------|----------------------------|
| 9.x | Yes (public beta) | No | No | File-based (`kicad-sch-api`) |
| 10.x | Yes (mature) | No / incomplete | Nightly only | File-based (`kicad-sch-api`) |
| 11.0+ (~Feb 2027) | Yes | Yes (planned) | Yes | Official IPC preferred |

## PCB Tools (live IPC)

Implemented in `src/grok_kicad_connector/pcb_backend.py`:

| Tool | Description |
|------|-------------|
| `get_board_status` | Snapshot of footprints, tracks, vias, nets, stackup |
| `place_footprint` | Place a footprint (commit + optional checkpoint) |
| `add_track` | Create a straight track segment |
| `add_via` | Create a through-via |
| `create_checkpoint` | Durable file checkpoint of the `.kicad_pcb` |
| `rollback_to_checkpoint` | Restore a prior checkpoint |
| `run_drc` | Design Rule Check via `kicad-cli` (evidence-rich) |

All results follow the harness `ToolResult` contract (`ok`, `status`, `evidence`, `checkpoint_id`, …).

## Schematic Bridge (Interim)

Until KiCad 11 ships a stable schematic IPC surface, this project uses:

- [`kicad-sch-api`](https://github.com/circuit-synth/kicad-sch-api) for create/edit/load/save of `.kicad_sch` files (exact format preservation)
- `kicad-cli sch erc|export …` for validation and manufacturing outputs

Details: [`docs/SCHEMATIC_BRIDGE.md`](docs/SCHEMATIC_BRIDGE.md)

## Quick Start (Development)

```bash
pip install kicad-python kicad-sch-api
# Enable KiCad API server: Preferences → Plugins → Enable IPC API
# Open a board in KiCad, then:

from grok_kicad_connector import get_pcb_backend

pcb = get_pcb_backend()
print(pcb.connect())
print(pcb.get_board_status())
```

## Repository Layout

```
docs/
  HARNESS.md              # Full Harness Engineering Spec
  SCHEMATIC_BRIDGE.md     # Interim schematic strategy
src/grok_kicad_connector/
  pcb_backend.py          # Live IPC PCB tools
  schematic_backend.py    # File-based schematic adapter
```

## License

MIT (planned)
