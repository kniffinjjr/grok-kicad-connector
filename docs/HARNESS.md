# Harness Engineering Spec — grok-kicad-connector

**Status**: Living document (early harness phase)  
**Last updated**: 2026-08-06

This document defines the **Harness** layer of the three-layer agent architecture (Harness / Loop / Graph). It constrains every tool the agent may call so that the system remains reliable, auditable, and safe to run against real KiCad designs.

---

## 1. Goals of the Harness

1. Expose only a **narrow, high-signal tool surface**.
2. Make every mutation **checkpointable and reversible**.
3. Provide deterministic **pre- and post-conditions** so the Loop layer can verify success.
4. Version-gate capabilities so the agent never assumes features that do not exist on the connected KiCad instance.
5. Keep schematic and PCB paths cleanly separated until official schematic IPC is stable.

---

## 2. Version Support Matrix & Schematic Caveats

| KiCad Version | PCB IPC API | Schematic IPC API | Headless `api-server` | Recommended Schematic Path |
|---------------|-------------|-------------------|-----------------------|----------------------------|
| 9.x | Yes (public beta) | No | No | File-based (`kicad-sch-api`) |
| 10.x | Yes (mature) | No / incomplete | Nightly only | File-based (`kicad-sch-api`) |
| 11.0+ (~Feb 2027) | Yes | Yes (planned / in master) | Yes | Official IPC preferred |

### Schematic Support Policy (non-negotiable)

- **Until KiCad 11 is released and the official IPC schematic surface is stable**, the harness treats schematic editing as a **file-based** concern.
- Primary library: [`kicad-sch-api`](https://github.com/circuit-synth/kicad-sch-api) (exact format preservation, hierarchical support, MCP-ready).
- Secondary tooling: `kicad-cli sch erc|export …` for validation and manufacturing outputs.
- Do **not** attempt to pretend full live schematic IPC exists on KiCad 9/10.
- When KiCad 11 ships, add a parallel `Schematic` tool surface using `kicad.get_schematic()` and prefer it over the file-based path.

### Headless / CI Guidance

- Prefer `kicad-cli` for pure validation/export jobs (ERC, BOM, netlist, Gerbers).
- For interactive or multi-step agent loops that need live board state, use the GUI IPC server (current) or `kicad-cli api-server` (KiCad 11+).
- Always keep a durable checkpoint of the `.kicad_sch` / `.kicad_pcb` before any mutating sequence.

---

## 3. Core Design Principles

### 3.1 Narrow Tools
Each tool does **one** well-defined thing. Prefer many small tools over a few god-tools.

### 3.2 Explicit Pre- and Post-conditions
Every tool declares:
- What must be true before it may run
- What evidence it produces after it finishes
- What constitutes success vs. soft-failure vs. hard-failure

### 3.3 Checkpoint-First Mutations
Any tool that mutates the design must:
1. Create a named checkpoint (file copy or commit) **before** changing anything
2. Record the checkpoint ID in the tool result
3. Allow the Loop layer to request a full rollback

### 3.4 Evidence over Assertions
Tools return structured evidence (lists of KIIDs, DRC markers, net lists, bounding boxes, etc.) rather than boolean “success” flags alone. The Loop layer decides whether the evidence is sufficient.

### 3.5 Human Gates for Irreversible or Manufacturing Actions
Export, netlist push to production, and any operation that writes outside the working project directory require an explicit human approval step.

---

## 4. Tool Surface (PCB — Primary)

These tools are implemented against the official `kicad-python` / IPC surface.

| Tool | Purpose | Mutation? | Checkpoint required? |
|------|---------|-----------|----------------------|
| `get_board_status` | Snapshot of footprints, nets, tracks, vias, stackup, layers | No | No |
| `search_component` | Library / footprint search | No | No |
| `place_footprint` | Place a footprint instance | Yes | Yes |
| `route_net` | Create track / arc / via segments | Yes | Yes |
| `run_drc` | Trigger or collect DRC evidence | Soft | Recommended |
| `undo` / `rollback_to_checkpoint` | Revert to a prior checkpoint | Yes | N/A |
| `create_checkpoint` | Explicit durable save point | Soft | N/A |
| `export` | Gerbers, drill, position, STEP, etc. | Yes (external) | Yes + Human gate |

Additional read-only helpers (get items by net, get selection, get stackup, etc.) may be exposed as needed.

---

## 5. Tool Surface (Schematic — Interim File-Based)

Implemented via the `SchematicBackend` adapter (see `src/grok_kicad_connector/schematic_backend.py`).

| Tool | Purpose | Backend |
|------|---------|---------|
| `create_schematic` | New empty schematic | kicad-sch-api |
| `load_schematic` | Open existing `.kicad_sch` | kicad-sch-api |
| `add_component` | Place symbol | kicad-sch-api |
| `add_wire` / `connect_pins` | Connectivity | kicad-sch-api |
| `save_schematic` | Write with format preservation | kicad-sch-api |
| `run_erc` | Electrical rules check | kicad-cli |
| `export_bom` / `export_netlist` | Manufacturing data | kicad-cli |

When official IPC schematic support arrives, the same tool names will be re-routed through the live IPC path without changing the agent-facing contract.

---

## 6. Checkpoint & Rollback Contract

```text
Checkpoint ID format:  ckpt_<timestamp>_<short-uuid>
Storage:               .grok-kicad/checkpoints/  (project-local)
Content:               full copy of the active .kicad_pcb or .kicad_sch
```

- Mutating tools **must** accept an optional `checkpoint_id` argument or create one automatically.
- The Loop layer may call `rollback_to_checkpoint(id)` at any time.
- Checkpoints older than a configurable retention window may be garbage-collected.

---

## 7. Error & Status Model

Tools return a structured result:

```python
{
  "ok": bool,
  "status": "success" | "soft_fail" | "hard_fail" | "busy" | "needs_human",
  "evidence": { … },          # free-form but documented per tool
  "checkpoint_id": str | None,
  "message": str,
  "kicad_version": str,
  "backend": "ipc" | "file" | "cli"
}
```

`AS_BUSY` / timeout from the IPC layer is mapped to `"busy"` and is considered a soft failure (retryable).

---

## 8. Future Work (KiCad 11+)

- Wire `kicad.get_schematic()` into the same tool surface.
- Prefer live IPC for all schematic mutations once the official surface is stable.
- Expand headless CI paths via `kicad-cli api-server`.
- Add library-editor tools if/when they appear.

---

*This harness is intentionally conservative. Reliability and auditability rank above feature completeness.*
