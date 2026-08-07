"""
Thin MCP (Model Context Protocol) server for grok-kicad-connector.

Exposes the harness tools so AI agents (Claude, Cursor, Grok tool-calling, etc.)
can drive KiCad without embedding the backends themselves.

Run:
  python -m grok_kicad_connector.mcp_server

Or via entry point once installed:
  grok-kicad-mcp
"""

from __future__ import annotations

import json
from typing import Any

# mcp is optional at import time so the rest of the package still works without it
try:
    from mcp.server.fastmcp import FastMCP

    _HAS_MCP = True
except ImportError:
    FastMCP = None  # type: ignore
    _HAS_MCP = False

from .pcb_backend import get_pcb_backend, ToolResult
from .schematic_backend import get_schematic_backend


def _result(r: ToolResult | dict[str, Any]) -> str:
    if isinstance(r, ToolResult):
        return json.dumps(r.to_dict(), default=str)
    return json.dumps(r, default=str)


def build_mcp() -> Any:
    if not _HAS_MCP:
        raise ImportError(
            "mcp is required for the server. Install with: pip install mcp"
        )

    mcp = FastMCP("grok-kicad-connector")
    pcb = get_pcb_backend()
    sch = None  # lazy — schematic needs kicad-sch-api

    def _sch():
        nonlocal sch
        if sch is None:
            sch = get_schematic_backend()
        return sch

    # ---- PCB tools ----

    @mcp.tool()
    def pcb_connect() -> str:
        """Connect to a running KiCad instance with IPC API enabled and a board open."""
        return _result(pcb.connect())

    @mcp.tool()
    def pcb_get_board_status() -> str:
        """Snapshot footprints, tracks, vias, nets, and stackup of the open board."""
        return _result(pcb.get_board_status())

    @mcp.tool()
    def pcb_place_footprint(
        lib_id: str,
        reference: str,
        x_mm: float,
        y_mm: float,
        rotation_deg: float = 0.0,
        layer: str = "F.Cu",
        value: str | None = None,
        create_checkpoint: bool = True,
    ) -> str:
        """
        Place a footprint on the board.

        lib_id is 'LibraryNickname:FootprintName' (e.g. Resistor_SMD:R_0603_1608Metric).
        On KiCad 9/10 this creates a FootprintInstance with lib id + fields set;
        full pad geometry from the library is best obtained via netlist update or
        by cloning an existing footprint when possible.
        """
        return _result(
            pcb.place_footprint(
                lib_id=lib_id,
                reference=reference,
                position_mm=(x_mm, y_mm),
                rotation_deg=rotation_deg,
                layer=layer,
                value=value,
                create_checkpoint=create_checkpoint,
            )
        )

    @mcp.tool()
    def pcb_move_footprint(
        reference: str,
        x_mm: float,
        y_mm: float,
        rotation_deg: float | None = None,
        create_checkpoint: bool = True,
    ) -> str:
        """Move (and optionally rotate) an existing footprint by reference designator."""
        return _result(
            pcb.move_footprint(
                reference=reference,
                position_mm=(x_mm, y_mm),
                rotation_deg=rotation_deg,
                create_checkpoint=create_checkpoint,
            )
        )

    @mcp.tool()
    def pcb_add_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        width_mm: float = 0.25,
        layer: str = "F.Cu",
        net_name: str | None = None,
        create_checkpoint: bool = True,
    ) -> str:
        """Add a straight copper track segment."""
        return _result(
            pcb.add_track(
                start_mm=(x1_mm, y1_mm),
                end_mm=(x2_mm, y2_mm),
                width_mm=width_mm,
                layer=layer,
                net_name=net_name,
                create_checkpoint=create_checkpoint,
            )
        )

    @mcp.tool()
    def pcb_add_via(
        x_mm: float,
        y_mm: float,
        diameter_mm: float = 0.8,
        drill_mm: float = 0.4,
        net_name: str | None = None,
        create_checkpoint: bool = True,
    ) -> str:
        """Add a through-via."""
        return _result(
            pcb.add_via(
                position_mm=(x_mm, y_mm),
                diameter_mm=diameter_mm,
                drill_mm=drill_mm,
                net_name=net_name,
                create_checkpoint=create_checkpoint,
            )
        )

    @mcp.tool()
    def pcb_create_checkpoint(board_path: str | None = None) -> str:
        """Create a durable file checkpoint of the .kicad_pcb."""
        return _result(pcb.create_checkpoint(board_path))

    @mcp.tool()
    def pcb_rollback_checkpoint(ckpt_id: str, board_path: str | None = None) -> str:
        """Restore a prior checkpoint. Reload the board in KiCad afterward."""
        return _result(pcb.rollback_to_checkpoint(ckpt_id, board_path))

    @mcp.tool()
    def pcb_run_drc(board_path: str, output: str | None = None) -> str:
        """Run Design Rule Check via kicad-cli; returns evidence and report path."""
        return _result(pcb.run_drc(board_path, output=output))

    # ---- Schematic tools (file-based bridge) ----

    @mcp.tool()
    def sch_create(name: str = "Untitled") -> str:
        """Create a new empty schematic (file-based backend)."""
        handle = _sch().create(name)
        return json.dumps({"ok": True, "name": handle.name})

    @mcp.tool()
    def sch_load(path: str) -> str:
        """Load an existing .kicad_sch file."""
        handle = _sch().load(path)
        return json.dumps({"ok": True, "name": handle.name, "path": str(handle.path)})

    @mcp.tool()
    def sch_add_component(
        path: str,
        lib_id: str,
        reference: str,
        value: str,
        x_mm: float,
        y_mm: float,
        footprint: str | None = None,
    ) -> str:
        """Add a component to a schematic file and save."""
        backend = _sch()
        handle = backend.load(path)
        ref = backend.add_component(
            handle,
            lib_id=lib_id,
            reference=reference,
            value=value,
            position=(x_mm, y_mm),
            footprint=footprint,
        )
        backend.save(handle)
        return json.dumps(
            {
                "ok": True,
                "reference": ref.reference,
                "lib_id": ref.lib_id,
                "value": ref.value,
                "position_mm": [x_mm, y_mm],
            }
        )

    @mcp.tool()
    def sch_run_erc(path: str, output: str | None = None) -> str:
        """Run Electrical Rules Check via kicad-cli."""
        result = _sch().run_erc(path, output=output)
        return json.dumps(
            {
                "ok": result.ok,
                "exit_code": result.exit_code,
                "report_path": str(result.report_path) if result.report_path else None,
                "raw_output_tail": (result.raw_output or "")[-1500:],
            }
        )

    return mcp


def main() -> None:
    mcp = build_mcp()
    mcp.run()


if __name__ == "__main__":
    main()
