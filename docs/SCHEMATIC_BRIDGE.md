# Schematic Bridge — Interim Strategy

**Purpose**: Provide a reliable, format-preserving schematic path while the official KiCad IPC schematic API is still incomplete (KiCad 9/10).

**Status**: Active until KiCad 11 ships a stable `get_schematic()` + CRUD surface.

---

## Why a Bridge Is Required

- Official IPC API on KiCad 9 and 10 is **PCB-only**.
- Schematic IPC support is planned for KiCad 11 (targeted ~February 2027).
- Agents still need to create, edit, validate, and export schematics today.

Therefore the connector uses a dual-backend approach:

1. **File-based editing** via [`kicad-sch-api`](https://github.com/circuit-synth/kicad-sch-api)
2. **Validation & export** via the official `kicad-cli sch …` commands

---

## Primary Library: kicad-sch-api

| Item | Detail |
|------|--------|
| Install | `pip install kicad-sch-api` |
| Strength | Exact format preservation, hierarchical sheets, pin-aware wiring, MCP-ready |
| Limitation | Partial ERC, global-label handling still maturing |
| Compatibility | Generates files that open cleanly in modern KiCad |

### Typical usage pattern

```python
import kicad_sch_api as ksa

sch = ksa.create_schematic("Power Stage")
r1 = sch.components.add("Device:R", "R1", "10k", position=(100, 100),
                        footprint="Resistor_SMD:R_0603_1608Metric")
sch.wires.add_wire_between_pins("R1", "2", "C1", "1")
sch.save("power_stage.kicad_sch")
```

The `SchematicBackend` adapter in this repository wraps the above so the rest of the harness never imports `kicad-sch-api` directly.

---

## Secondary Tooling: kicad-cli

All of these run headlessly and are already stable on KiCad 9/10:

```bash
# Electrical Rules Check
kicad-cli sch erc board.kicad_sch --format json --exit-code-violations

# Manufacturing outputs
kicad-cli sch export bom board.kicad_sch -o bom.csv
kicad-cli sch export netlist board.kicad_sch -o netlist.net
kicad-cli sch export pdf board.kicad_sch -o schematic.pdf
kicad-cli sch export svg board.kicad_sch -o schematic.svg
```

These commands are the preferred way to obtain ERC evidence and manufacturing artifacts until the live IPC surface can return the same data.

---

## Adapter Contract (`SchematicBackend`)

The thin adapter (`src/grok_kicad_connector/schematic_backend.py`) exposes a stable interface:

```python
class SchematicBackend:
    def create(self, name: str) -> SchematicHandle
    def load(self, path: str) -> SchematicHandle
    def save(self, handle: SchematicHandle, path: str | None = None) -> None
    def add_component(self, handle, lib_id, ref, value, pos, **kwargs) -> ComponentRef
    def connect_pins(self, handle, from_ref, from_pin, to_ref, to_pin) -> None
    def run_erc(self, path: str) -> ERCResult          # delegates to kicad-cli
    def export_bom(self, path: str, out: str) -> None  # delegates to kicad-cli
    # …
```

When official IPC schematic support becomes available, a second implementation of the same interface will be added and selected by KiCad version detection. Agent-facing tools will not change.

---

## Migration Path (KiCad 11+)

1. Detect KiCad ≥ 11 and a working `get_schematic()`.
2. Prefer the live IPC backend for all mutations.
3. Keep the file-based backend as a fallback and for pure headless generation.
4. Gradually retire direct `kicad-sch-api` calls from the critical path once IPC parity is proven.

---

## Safety Rules

- Always create a checkpoint (full `.kicad_sch` copy) before any multi-step mutation sequence.
- Prefer `kicad-cli` for ERC evidence over any in-process approximation.
- Never claim live schematic IPC capabilities on KiCad 9 or 10.
