# RV RGBW Smart Puck (Facon RVRAHN-35 retrofit)

All-in-one drop-in board for the Facon-style 3.5" / 35 mm class RV puck housing.

## Goals
- Discrete RGBW (4 independent PWM channels)
- ESP32-C3 (Wi-Fi + Bluetooth)
- Native Home Assistant via ESPHome
- 12 V DC input (11–14.4 V tolerant)
- Steel housing used as heatsink
- Enlarged center hole for hollow rivet + wire pass-through

## Design decisions
- **MCU**: ESP32-C3
- **LED drive**: Low-side logic-level N-MOSFET PWM per color
- **Power target**: ~4–5.5 W total (similar to original 5 W mono)
- **Center hole**: Ø5.0–5.5 mm for new hollow rivet / eyelet
- **Thermal**: LED copper pours coupled to steel housing (thermal pad/adhesive under LED zone)

## Files
- `esphome/rv-puck.yaml` — ready-to-adapt ESPHome config
- `schematic/SCHEMATIC.md` — netlist, parts, connections, mechanical notes

## Status
Early design. Schematic is documentation-first so it can be entered into KiCad (or generated via the connector tools). First prototype recommended on FR4; move to aluminum-core / heavy copper if thermal testing requires it.
