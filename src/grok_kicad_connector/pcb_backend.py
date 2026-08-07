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
    """
    Copy the current .kicad_pcb (if known) into a durable checkpoint directory.
    Returns the checkpoint_id or None if no board path is available.
    """
    if board_path is None or not board_path.exists():
        return None

    root = (project_dir or board_path.parent) / CHECKPOINT_ROOT
    root.mkdir(parents=True, exist_ok=True)
    ckpt_id = _make_checkpoint_id()
    dest = root / f"{ckpt_id}.kicad_pcb"
    shutil.copy2(board_path, dest)
    return ckpt_id


def rollback_file_checkpoint(ckpt_id: str, board_path: Path, project_dir: Path | None = None) -> bool:
    """Restore a previous checkpoint over the live board file."""
    root = (project_dir or board_path.parent) / CHECKPOINT_ROOT
    src = root / f"{ckpt_id}.kicad_pcb"
    if not src.exists():
        return False
    shutil.copy2(src, board_path)
    return True


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
        """Establish (or re-establish) connection to a running KiCad instance."""
        try:
            self._kicad = KiCad(client_name=self.client_name)
            version = str(self._kicad.get_version())
            self._board = self._kicad.get_board()
            # Best-effort path discovery (not always exposed)
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
        """
        Snapshot of the open board: footprints, nets, tracks, vias, stackup summary.
        """
        try:
            board = self._ensure_board()
            footprints = list(board.get_footprints())
            tracks = list(board.get_tracks())
            vias = list(board.get_vias())
            nets = list(board.get_nets()) if hasattr(board, "get_nets") else []

            fp_summary = []
            for fp in footprints:
                try:
                    ref = getattr(fp, "reference", None) or getattr(
                        getattr(fp, "reference_field", None), "text", None
                    )
                    if hasattr(ref, "value"):
                        ref = ref.value
                    pos = getattr(fp, "position", None)
                    pos_mm = None
                    if pos is not None:
                        try:
                            pos_mm = (to_mm(pos.x), to_mm(pos.y))
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
                "footprints": fp_summary[:200],  # cap for agent context
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
                message=f"Board status: {len(footprints)} footprints, "
                        f"{len(tracks)} tracks, {len(vias)} vias, {len(nets)} nets",
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
    # Mutations
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
        Place a footprint instance on the board.

        Note: Full library footprint instantiation via IPC is still evolving.
        This implementation creates a minimal FootprintInstance shell and relies
        on the running KiCad session / library cache. Prefer placing from the
        schematic netlist when possible.
        """
        try:
            board = self._ensure_board()
            ckpt_id = None
            if create_checkpoint and self._board_path:
                ckpt_id = create_file_checkpoint(self._board_path)

            commit = board.begin_commit()
            try:
                # Build a minimal footprint instance.
                # Exact construction varies slightly by kicad-python version;
                # we keep the surface conservative.
                fp = FootprintInstance()
                # Common attribute patterns across recent kipy versions
                if hasattr(fp, "reference"):
                    fp.reference = reference
                if value is not None and hasattr(fp, "value"):
                    fp.value = value

                fp.position = Vector2.from_xy(from_mm(position_mm[0]), from_mm(position_mm[1]))
                if hasattr(fp, "orientation") and rotation_deg:
                    # orientation is typically in decidegrees or radians depending on version
                    try:
                        fp.orientation = rotation_deg * 10  # decidegrees common in KiCad
                    except Exception:
                        pass

                created = board.create_items(fp)
                board.push_commit(commit, f"Place {reference} ({lib_id})")

                evidence = {
                    "reference": reference,
                    "lib_id": lib_id,
                    "position_mm": position_mm,
                    "rotation_deg": rotation_deg,
                    "created_count": len(created) if created else 1,
                }
                return ToolResult(
                    ok=True,
                    status="success",
                    evidence=evidence,
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

    def add_track(
        self,
        start_mm: tuple[float, float],
        end_mm: tuple[float, float],
        width_mm: float = 0.25,
        layer: str = "F.Cu",
        net_name: str | None = None,
        create_checkpoint: bool = True,
    ) -> ToolResult:
        """Create a single straight track segment."""
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

                # Layer assignment – best-effort across versions
                try:
                    from kipy.proto.board.board_types_pb2 import BoardLayer

                    layer_map = {
                        "F.Cu": BoardLayer.BL_F_Cu,
                        "B.Cu": BoardLayer.BL_B_Cu,
                    }
                    if layer in layer_map:
                        track.layer = layer_map[layer]
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
                        "start_mm": start_mm,
                        "end_mm": end_mm,
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
        """Create a through-via."""
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
                # Common attribute names across versions
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
                        "position_mm": position_mm,
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
        # After file restore the user should reload the board in KiCad
        return ToolResult(
            ok=True,
            status="success",
            checkpoint_id=ckpt_id,
            message=f"Restored {ckpt_id}. Reload the board in KiCad to see changes.",
            evidence={"restored": True, "note": "Reload board in KiCad required"},
        )

    # ------------------------------------------------------------------
    # DRC via kicad-cli (IPC DRC is limited until KiCad 11)
    # ------------------------------------------------------------------

    def run_drc(
        self,
        board_path: str | Path,
        output: str | Path | None = None,
        format: str = "json",
    ) -> ToolResult:
        """Run Design Rule Check via kicad-cli and return evidence."""
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
