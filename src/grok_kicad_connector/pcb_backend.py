"""
PCB backend for grok-kicad-connector.

Wraps the official kicad-python (kipy) IPC API with the narrow, checkpointed
tool surface defined in docs/HARNESS.md.

All mutating operations:
  1. Create a durable file checkpoint (optional but recommended)
  2. Open a board commit
  3. Apply changes
  4. Push or drop the commit
  5. Return structured evidence + checkpoint_id
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

# ---------------------------------------------------------------------------
# Optional dependency – required at runtime when talking to a live KiCad
# ---------------------------------------------------------------------------
try:
    from kipy import KiCad
    from kipy.geometry import Vector2
    from kipy.board_types import Track, Via, FootprintInstance
    from kipy.util.units import from_mm, to_mm

    _HAS_KIPY = True
except ImportError:
    KiCad = None  # type: ignore
    Vector2 = None  # type: ignore
    Track = Via = FootprintInstance = None  # type: ignore
    from_mm = to_mm = None  # type: ignore
    _HAS_KIPY = False

try:
    from kipy.common_types import LibraryIdentifier
except Exception:
    LibraryIdentifier = None  # type: ignore

try:
    from kipy.proto.board.board_types_pb2 import BoardLayer
except Exception:
    BoardLayer = None  # type: ignore


# ---------------------------------------------------------------------------
# Structured result (matches Harness Spec §7)
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    ok: bool
    status: str  # success | soft_fail | hard_fail | busy | needs_human
    evidence: dict[str, Any] = field(default_factory=dict)
    checkpoint_id: str | None = None
    message: str = ""
    kicad_version: str | None = None
    backend: str = "ipc"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Checkpoint helpers (file-based, project-local)
# ---------------------------------------------------------------------------

CHECKPOINT_ROOT = Path(".grok-kicad") / "checkpoints"


def _make_checkpoint_id() -> str:
    return f"ckpt_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def create_file_checkpoint(board_path: Path | None, project_dir: Path | None = None) -> str | None:
    if board_path is None or not board_path.exists():
        return None

    root = (project_dir or board_path.parent) / CHECKPOINT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    ckpt_id = _make_checkpoint_id()
    dest = root / f"{ckpt_id}.kicad_pcb"
    shutil.copy2(board_path, dest)
    return ckpt_id


def rollback_file_checkpoint(ckpt_id: str, board_path: Path, project_dir: Path | None = None) -> bool:
    root = (project_dir or board_path.parent) / CHECKPOINT_ROOT
    src = root / f"{ckpt_id}.kicad_pcb"
    if not src.exists():
        return False
    shutil.copy2(src, board_path)
    return True


def _parse_lib_id(lib_id: str) -> tuple[str, str]:
    """Split 'LibraryNickname:FootprintName' into (library, name)."""
    if ":" in lib_id:
        lib, name = lib_id.split(":", 1)
        return lib.strip(), name.strip()
    return "", lib_id.strip()


def _set_orientation(fp: Any, rotation_deg: float) -> None:
    """Best-effort orientation across kipy versions (degrees / decidegrees / Angle)."""
    if not rotation_deg or not hasattr(fp, "orientation"):
        return
    try:
        from kipy.geometry import Angle

        fp.orientation = Angle.from_degrees(rotation_deg)
        return
    except Exception:
        pass
    try:
        fp.orientation = rotation_deg * 10  # decidegrees
    except Exception:
        try:
            fp.orientation = rotation_deg
        except Exception:
            pass


def _set_layer(fp: Any, layer: str) -> None:
    if BoardLayer is None:
        return
    layer_map = {
        "F.Cu": getattr(BoardLayer, "BL_F_Cu", None),
        "B.Cu": getattr(BoardLayer, "BL_B_Cu", None),
    }
    val = layer_map.get(layer)
    if val is not None and hasattr(fp, "layer"):
        try:
            fp.layer = val
        except Exception:
            pass


def _set_reference_value(fp: Any, reference: str, value: str | None) -> None:
    """Set reference/value via field objects when available (KiCad 9+ style)."""
    # Preferred: reference_field / value_field (documented path)
    try:
        if hasattr(fp, "reference_field") and fp.reference_field is not None:
            text = getattr(fp.reference_field, "text", None)
            if text is not None and hasattr(text, "value"):
                text.value = reference
            elif hasattr(fp.reference_field, "value"):
                fp.reference_field.value = reference
            if hasattr(fp.reference_field, "visible"):
                fp.reference_field.visible = True
    except Exception:
        pass

    if value is not None:
        try:
            if hasattr(fp, "value_field") and fp.value_field is not None:
                text = getattr(fp.value_field, "text", None)
                if text is not None and hasattr(text, "value"):
                    text.value = value
                elif hasattr(fp.value_field, "value"):
                    fp.value_field.value = value
        except Exception:
            pass

    # Fallback direct attrs
    for attr, val in (("reference", reference), ("value", value)):
        if val is None:
            continue
        if hasattr(fp, attr):
            try:
                setattr(fp, attr, val)
            except Exception:
                pass


def _set_lib_id(fp: Any, lib_id: str) -> None:
    """Attach LibraryIdentifier to the footprint definition when possible."""
    lib, name = _parse_lib_id(lib_id)
    if not name:
        return

    try:
        definition = getattr(fp, "definition", None)
        if definition is None:
            return
        if LibraryIdentifier is not None and hasattr(definition, "id"):
            lid = LibraryIdentifier()
            if lib:
                lid.library = lib
            lid.name = name
            definition.id = lid
            return
        # Proto-style fallback
        if hasattr(definition, "id") and definition.id is not None:
            if lib and hasattr(definition.id, "library"):
                definition.id.library = lib
            if hasattr(definition.id, "name"):
                definition.id.name = name
    except Exception:
        pass


def _find_footprint_by_ref(board: Any, reference: str) -> Any | None:
    for fp in board.get_footprints():
        ref = getattr(fp, "reference", None)
        if ref is None and hasattr(fp, "reference_field"):
            rf = fp.reference_field
            text = getattr(rf, "text", None)
            ref = getattr(text, "value", None) if text is not None else getattr(rf, "value", None)
        if str(ref) == reference:
            return fp
    return None


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class PcbBackend:
    """
    Live IPC backend for PCB operations.

    Requires a running KiCad instance with the API server enabled
    (Preferences → Plugins → Enable IPC API) and a board open.
    """

    def __init__(self, kicad_cli: str | None = None, client_name: str = "grok-kicad-connector"):
        if not _HAS_KIPY:
            raise ImportError(
                "kicad-python is required. Install with: pip install kicad-python"
            )
        self.kicad_cli = kicad_cli or shutil.which("kicad-cli") or "kicad-cli"
        self.client_name = client_name
        self._kicad: Any = None
        self._board: Any = None
        self._board_path: Path | None = None

    def connect(self) -> ToolResult:
        try:
            self._kicad = KiCad(client_name=self.client_name)
            version = str(self._kicad.get_version())
            self._board = self._kicad.get_board()
            self._board_path = None
            return ToolResult(
                ok=True,
                status="success",
                message="Connected to KiCad",
                kicad_version=version,
                evidence={"connected": True},
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"Failed to connect to KiCad: {e}",
                evidence={"error": str(e)},
            )

    def set_board_path(self, path: str | Path) -> None:
        """Tell the backend where the live .kicad_pcb lives (for checkpoints)."""
        self._board_path = Path(path)

    def _ensure_board(self) -> Any:
        if self._board is None:
            result = self.connect()
            if not result.ok:
                raise RuntimeError(result.message)
        return self._board

    # ------------------------------------------------------------------
    # Read-only tools
    # ------------------------------------------------------------------

    def get_board_status(self) -> ToolResult:
        try:
            board = self._ensure_board()
            footprints = list(board.get_footprints())
            tracks = list(board.get_tracks())
            vias = list(board.get_vias())
            nets = list(board.get_nets()) if hasattr(board, "get_nets") else []

            fp_summary = []
            for fp in footprints:
                try:
                    ref = getattr(fp, "reference", None)
                    if ref is None and hasattr(fp, "reference_field"):
                        rf = fp.reference_field
                        text = getattr(rf, "text", None)
                        ref = getattr(text, "value", None) if text is not None else getattr(rf, "value", None)
                    pos = getattr(fp, "position", None)
                    pos_mm = None
                    if pos is not None:
                        try:
                            pos_mm = (round(to_mm(pos.x), 4), round(to_mm(pos.y), 4))
                        except Exception:
                            pos_mm = (getattr(pos, "x", None), getattr(pos, "y", None))
                    fp_summary.append(
                        {
                            "reference": str(ref) if ref else None,
                            "position_mm": pos_mm,
                            "layer": str(getattr(fp, "layer", None)),
                        }
                    )
                except Exception:
                    fp_summary.append({"error": "failed to serialize footprint"})

            stackup_info = None
            try:
                stackup = board.get_stackup()
                stackup_info = {
                    "copper_layer_count": getattr(stackup, "copper_layer_count", None),
                    "layers": len(getattr(stackup, "layers", []) or []),
                }
            except Exception:
                pass

            evidence = {
                "footprint_count": len(footprints),
                "track_count": len(tracks),
                "via_count": len(vias),
                "net_count": len(nets),
                "footprints": fp_summary[:200],
                "stackup": stackup_info,
            }

            version = None
            if self._kicad:
                try:
                    version = str(self._kicad.get_version())
                except Exception:
                    pass

            return ToolResult(
                ok=True,
                status="success",
                evidence=evidence,
                message=(
                    f"Board status: {len(footprints)} footprints, "
                    f"{len(tracks)} tracks, {len(vias)} vias, {len(nets)} nets"
                ),
                kicad_version=version,
            )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"get_board_status failed: {e}",
                evidence={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # Mutations — footprints
    # ------------------------------------------------------------------

    def place_footprint(
        self,
        lib_id: str,
        reference: str,
        position_mm: tuple[float, float],
        rotation_deg: float = 0.0,
        layer: str = "F.Cu",
        value: str | None = None,
        create_checkpoint: bool = True,
    ) -> ToolResult:
        """
        Place a footprint instance on the board (KiCad 9/10 IPC).

        Sets LibraryIdentifier, reference/value fields, position, layer, and
        orientation using the patterns that work against current kicad-python.

        Limitations on 9/10:
          - IPC does not fully expand library pad geometry the way pcbnew.FootprintLoad did.
          - For production placement prefer Update PCB from Schematic, or clone an
            existing footprint then move/relabel it via move_footprint.
          - This tool still creates a valid instance with correct identity + fields
            so agents can iterate layout before a netlist refresh.
        """
        try:
            board = self._ensure_board()
            ckpt_id = None
            if create_checkpoint and self._board_path:
                ckpt_id = create_file_checkpoint(self._board_path)

            commit = board.begin_commit()
            try:
                fp = FootprintInstance()
                _set_lib_id(fp, lib_id)
                _set_reference_value(fp, reference, value)
                fp.position = Vector2.from_xy(
                    from_mm(position_mm[0]), from_mm(position_mm[1])
                )
                _set_orientation(fp, rotation_deg)
                _set_layer(fp, layer)

                created = board.create_items(fp)
                board.push_commit(commit, f"Place {reference} ({lib_id})")

                return ToolResult(
                    ok=True,
                    status="success",
                    evidence={
                        "reference": reference,
                        "lib_id": lib_id,
                        "position_mm": list(position_mm),
                        "rotation_deg": rotation_deg,
                        "layer": layer,
                        "created_count": len(created) if created else 1,
                        "note": (
                            "Instance created with lib_id + fields. "
                            "Pad geometry may require netlist update or clone."
                        ),
                    },
                    checkpoint_id=ckpt_id,
                    message=f"Placed {reference} at {position_mm}",
                )
            except Exception as e:
                try:
                    board.drop_commit(commit)
                except Exception:
                    pass
                return ToolResult(
                    ok=False,
                    status="hard_fail",
                    message=f"place_footprint failed: {e}",
                    evidence={"error": str(e)},
                    checkpoint_id=ckpt_id,
                )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"place_footprint failed: {e}",
                evidence={"error": str(e)},
            )

    def move_footprint(
        self,
        reference: str,
        position_mm: tuple[float, float],
        rotation_deg: float | None = None,
        create_checkpoint: bool = True,
    ) -> ToolResult:
        """
        Move (and optionally rotate) an existing footprint by reference.

        This is the reliable path on KiCad 9/10 for layout work: operate on
        footprints already on the board (from netlist / prior placement).
        """
        try:
            board = self._ensure_board()
            fp = _find_footprint_by_ref(board, reference)
            if fp is None:
                return ToolResult(
                    ok=False,
                    status="soft_fail",
                    message=f"Footprint {reference!r} not found on board",
                    evidence={"reference": reference},
                )

            ckpt_id = None
            if create_checkpoint and self._board_path:
                ckpt_id = create_file_checkpoint(self._board_path)

            commit = board.begin_commit()
            try:
                fp.position = Vector2.from_xy(
                    from_mm(position_mm[0]), from_mm(position_mm[1])
                )
                if rotation_deg is not None:
                    _set_orientation(fp, rotation_deg)

                board.update_items([fp])
                board.push_commit(
                    commit,
                    f"Move {reference} to {position_mm}"
                    + (f" rot={rotation_deg}" if rotation_deg is not None else ""),
                )

                return ToolResult(
                    ok=True,
                    status="success",
                    evidence={
                        "reference": reference,
                        "position_mm": list(position_mm),
                        "rotation_deg": rotation_deg,
                    },
                    checkpoint_id=ckpt_id,
                    message=f"Moved {reference} to {position_mm}",
                )
            except Exception as e:
                try:
                    board.drop_commit(commit)
                except Exception:
                    pass
                return ToolResult(
                    ok=False,
                    status="hard_fail",
                    message=f"move_footprint failed: {e}",
                    evidence={"error": str(e)},
                    checkpoint_id=ckpt_id,
                )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"move_footprint failed: {e}",
                evidence={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # Mutations — tracks / vias
    # ------------------------------------------------------------------

    def add_track(
        self,
        start_mm: tuple[float, float],
        end_mm: tuple[float, float],
        width_mm: float = 0.25,
        layer: str = "F.Cu",
        net_name: str | None = None,
        create_checkpoint: bool = True,
    ) -> ToolResult:
        try:
            board = self._ensure_board()
            ckpt_id = None
            if create_checkpoint and self._board_path:
                ckpt_id = create_file_checkpoint(self._board_path)

            commit = board.begin_commit()
            try:
                track = Track()
                track.start = Vector2.from_xy(from_mm(start_mm[0]), from_mm(start_mm[1]))
                track.end = Vector2.from_xy(from_mm(end_mm[0]), from_mm(end_mm[1]))
                track.width = from_mm(width_mm)

                if BoardLayer is not None:
                    layer_map = {
                        "F.Cu": getattr(BoardLayer, "BL_F_Cu", None),
                        "B.Cu": getattr(BoardLayer, "BL_B_Cu", None),
                    }
                    val = layer_map.get(layer)
                    if val is not None:
                        try:
                            track.layer = val
                        except Exception:
                            pass

                if net_name and hasattr(board, "get_nets"):
                    for net in board.get_nets():
                        if getattr(net, "name", None) == net_name:
                            track.net = net
                            break

                created = board.create_items(track)
                board.push_commit(commit, f"Add track {start_mm} → {end_mm}")

                return ToolResult(
                    ok=True,
                    status="success",
                    evidence={
                        "start_mm": list(start_mm),
                        "end_mm": list(end_mm),
                        "width_mm": width_mm,
                        "layer": layer,
                        "net_name": net_name,
                        "created_count": len(created) if created else 1,
                    },
                    checkpoint_id=ckpt_id,
                    message=f"Track added {start_mm} → {end_mm}",
                )
            except Exception as e:
                try:
                    board.drop_commit(commit)
                except Exception:
                    pass
                return ToolResult(
                    ok=False,
                    status="hard_fail",
                    message=f"add_track failed: {e}",
                    evidence={"error": str(e)},
                    checkpoint_id=ckpt_id,
                )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"add_track failed: {e}",
                evidence={"error": str(e)},
            )

    def add_via(
        self,
        position_mm: tuple[float, float],
        diameter_mm: float = 0.8,
        drill_mm: float = 0.4,
        net_name: str | None = None,
        create_checkpoint: bool = True,
    ) -> ToolResult:
        try:
            board = self._ensure_board()
            ckpt_id = None
            if create_checkpoint and self._board_path:
                ckpt_id = create_file_checkpoint(self._board_path)

            commit = board.begin_commit()
            try:
                via = Via()
                via.position = Vector2.from_xy(
                    from_mm(position_mm[0]), from_mm(position_mm[1])
                )
                for attr, val in [
                    ("diameter", from_mm(diameter_mm)),
                    ("drill_diameter", from_mm(drill_mm)),
                    ("drill", from_mm(drill_mm)),
                ]:
                    if hasattr(via, attr):
                        try:
                            setattr(via, attr, val)
                        except Exception:
                            pass

                try:
                    from kipy.proto.board.board_types_pb2 import ViaType

                    via.type = ViaType.VT_THROUGH
                except Exception:
                    pass

                if net_name and hasattr(board, "get_nets"):
                    for net in board.get_nets():
                        if getattr(net, "name", None) == net_name:
                            via.net = net
                            break

                created = board.create_items(via)
                board.push_commit(commit, f"Add via at {position_mm}")

                return ToolResult(
                    ok=True,
                    status="success",
                    evidence={
                        "position_mm": list(position_mm),
                        "diameter_mm": diameter_mm,
                        "drill_mm": drill_mm,
                        "net_name": net_name,
                        "created_count": len(created) if created else 1,
                    },
                    checkpoint_id=ckpt_id,
                    message=f"Via added at {position_mm}",
                )
            except Exception as e:
                try:
                    board.drop_commit(commit)
                except Exception:
                    pass
                return ToolResult(
                    ok=False,
                    status="hard_fail",
                    message=f"add_via failed: {e}",
                    evidence={"error": str(e)},
                    checkpoint_id=ckpt_id,
                )
        except Exception as e:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"add_via failed: {e}",
                evidence={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def create_checkpoint(self, board_path: str | Path | None = None) -> ToolResult:
        path = Path(board_path) if board_path else self._board_path
        ckpt_id = create_file_checkpoint(path)
        if ckpt_id is None:
            return ToolResult(
                ok=False,
                status="soft_fail",
                message="No board path available for checkpoint",
            )
        return ToolResult(
            ok=True,
            status="success",
            checkpoint_id=ckpt_id,
            message=f"Checkpoint created: {ckpt_id}",
            evidence={"checkpoint_id": ckpt_id},
        )

    def rollback_to_checkpoint(
        self, ckpt_id: str, board_path: str | Path | None = None
    ) -> ToolResult:
        path = Path(board_path) if board_path else self._board_path
        if path is None:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message="No board path available for rollback",
            )
        ok = rollback_file_checkpoint(ckpt_id, path)
        if not ok:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"Checkpoint {ckpt_id} not found",
            )
        return ToolResult(
            ok=True,
            status="success",
            checkpoint_id=ckpt_id,
            message=f"Restored {ckpt_id}. Reload the board in KiCad to see changes.",
            evidence={"restored": True, "note": "Reload board in KiCad required"},
        )

    # ------------------------------------------------------------------
    # DRC via kicad-cli
    # ------------------------------------------------------------------

    def run_drc(
        self,
        board_path: str | Path,
        output: str | Path | None = None,
        format: str = "json",
    ) -> ToolResult:
        board_path = Path(board_path)
        if output is None:
            output = board_path.with_suffix(".drc.json")
        output = Path(output)

        cmd = [
            self.kicad_cli,
            "pcb",
            "drc",
            str(board_path),
            "--output",
            str(output),
            "--format",
            format,
            "--exit-code-violations",
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180
            )
            ok = proc.returncode == 0
            evidence: dict[str, Any] = {
                "exit_code": proc.returncode,
                "report_path": str(output) if output.exists() else None,
                "stdout_tail": (proc.stdout or "")[-2000:],
                "stderr_tail": (proc.stderr or "")[-1000:],
            }
            if output.exists() and format == "json":
                try:
                    evidence["report"] = json.loads(output.read_text())
                except Exception:
                    pass

            return ToolResult(
                ok=ok,
                status="success" if ok else "soft_fail",
                evidence=evidence,
                message="DRC clean" if ok else f"DRC reported violations (exit {proc.returncode})",
                backend="cli",
            )
        except FileNotFoundError:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message=f"kicad-cli not found (looked for: {self.kicad_cli})",
                backend="cli",
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                ok=False,
                status="hard_fail",
                message="DRC timed out",
                backend="cli",
            )


def get_pcb_backend(kicad_cli: str | None = None) -> PcbBackend:
    return PcbBackend(kicad_cli=kicad_cli)
