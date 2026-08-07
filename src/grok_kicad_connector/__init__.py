"""grok-kicad-connector — AI harness for KiCad via IPC + file-based schematic bridge."""

__version__ = "0.1.0"

from .pcb_backend import PcbBackend, ToolResult, get_pcb_backend
from .schematic_backend import SchematicBackend, get_schematic_backend

__all__ = [
    "PcbBackend",
    "ToolResult",
    "get_pcb_backend",
    "SchematicBackend",
    "get_schematic_backend",
]
