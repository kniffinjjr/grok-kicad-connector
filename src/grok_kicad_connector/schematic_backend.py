"""
Thin adapter for schematic operations.

Current implementation uses kicad-sch-api for create/edit/save and
kicad-cli for ERC + manufacturing exports.  When official IPC schematic
support lands in KiCad 11, a second backend can be added behind the same
interface without changing agent-facing tools.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Optional dependency — only required when the file-based backend is used.
try:
    import kicad_sch_api as ksa
    _HAS_KSA = True
except ImportError:
    ksa = None  # type: ignore
    _HAS_KSA = False


@dataclass
class ComponentRef:
    reference: str
    lib_id: str
    value: str
    uuid: str | None = None
    position: tuple[float, float] | None = None


@dataclass
class ERCResult:
    ok: bool
    exit_code: int
    report_path: Path | None = None
    raw_output: str = ""
    violations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SchematicHandle:
    """Opaque handle returned by create/load."""
    name: str
    path: Path | None = None
    _internal: Any = field(default=None, repr=False)  # ksa.Schematic instance


class SchematicBackend:
    """
    Stable interface for schematic operations.

    Today: file-based (kicad-sch-api) + kicad-cli.
    Future: live IPC when KiCad >= 11 and get_schematic() is available.
    """

    def __init__(self, kicad_cli: str | None = None):
        self.kicad_cli = kicad_cli or shutil.which("kicad-cli") or "kicad-cli"
        if not _HAS_KSA:
            raise ImportError(
                "kicad-sch-api is required for the current schematic backend. "
                "Install with: pip install kicad-sch-api"
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def create(self, name: str = "Untitled") -> SchematicHandle:
        sch = ksa.create_schematic(name)
        return SchematicHandle(name=name, _internal=sch)

    def load(self, path: str | Path) -> SchematicHandle:
        path = Path(path)
        sch = ksa.Schematic(str(path))  # or ksa.load_schematic depending on version
        return SchematicHandle(name=path.stem, path=path, _internal=sch)

    def save(self, handle: SchematicHandle, path: str | Path | None = None) -> Path:
        target = Path(path) if path else handle.path
        if target is None:
            raise ValueError("No path provided and handle has no associated path")
        handle._internal.save(str(target))
        handle.path = target
        return target

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_component(
        self,
        handle: SchematicHandle,
        lib_id: str,
        reference: str,
        value: str,
        position: tuple[float, float],
        footprint: str | None = None,
        **kwargs: Any,
    ) -> ComponentRef:
        sch = handle._internal
        comp = sch.components.add(
            lib_id,
            reference,
            value,
            position=position,
            footprint=footprint,
            **kwargs,
        )
        return ComponentRef(
            reference=reference,
            lib_id=lib_id,
            value=value,
            uuid=getattr(comp, "uuid", None),
            position=position,
        )

    def connect_pins(
        self,
        handle: SchematicHandle,
        from_ref: str,
        from_pin: str,
        to_ref: str,
        to_pin: str,
    ) -> None:
        """Create a wire between two component pins (Manhattan if supported)."""
        sch = handle._internal
        # Prefer the high-level helper when available
        if hasattr(sch, "add_wire_between_pins"):
            sch.add_wire_between_pins(from_ref, from_pin, to_ref, to_pin)
        else:
            # Fallback — callers should prefer the high-level path
            raise NotImplementedError(
                "add_wire_between_pins not available in this kicad-sch-api version"
            )

    # ------------------------------------------------------------------
    # Validation & Export (delegated to kicad-cli)
    # ------------------------------------------------------------------

    def run_erc(self, path: str | Path, output: str | Path | None = None) -> ERCResult:
        path = Path(path)
        if output is None:
            output = path.with_suffix(".erc.json")
        output = Path(output)

        cmd = [
            self.kicad_cli,
            "sch",
            "erc",
            str(path),
            "--format",
            "json",
            "--output",
            str(output),
            "--exit-code-violations",
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            ok = proc.returncode == 0
            return ERCResult(
                ok=ok,
                exit_code=proc.returncode,
                report_path=output if output.exists() else None,
                raw_output=proc.stdout + proc.stderr,
            )
        except FileNotFoundError:
            return ERCResult(
                ok=False,
                exit_code=-1,
                raw_output=f"kicad-cli not found (looked for: {self.kicad_cli})",
            )
        except subprocess.TimeoutExpired:
            return ERCResult(ok=False, exit_code=-2, raw_output="ERC timed out")

    def export_bom(self, path: str | Path, output: str | Path) -> None:
        path, output = Path(path), Path(output)
        cmd = [
            self.kicad_cli,
            "sch",
            "export",
            "bom",
            str(path),
            "--output",
            str(output),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)

    def export_netlist(
        self,
        path: str | Path,
        output: str | Path,
        fmt: str = "kicadsexpr",
    ) -> None:
        path, output = Path(path), Path(output)
        cmd = [
            self.kicad_cli,
            "sch",
            "export",
            "netlist",
            str(path),
            "--output",
            str(output),
            "--format",
            fmt,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)


# Convenience factory used by the rest of the harness
def get_schematic_backend(kicad_cli: str | None = None) -> SchematicBackend:
    return SchematicBackend(kicad_cli=kicad_cli)
