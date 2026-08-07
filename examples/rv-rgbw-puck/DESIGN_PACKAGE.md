# RV RGBW Smart Puck — PCBWay Prototype Design Package

**Status**: Ready for KiCad layout on GrokBuild → Gerbers → PCBWay prototype (qty 2–5)

**Goal**: Drop-in replacement board for Facon-style ~3.5" (35 mm class) steel-housing RV puck lights. Discrete RGBW, ESP32-C3, ESPHome / Home Assistant, 12 V DC, all electronics on one board, housing used as heatsink.

---

## 1. Mechanical Specification (locked for first proto)

| Parameter | Value | Notes |
|-----------|-------|-------|
| Board shape | Round | |
| Board diameter | **30.0 mm** | Leaves clearance inside typical 3.5" housing |
| Board thickness | 1.6 mm FR4 | Standard, good stiffness |
| Center hole | **Ø5.2 mm** non-plated | For replacement hollow rivet / eyelet + wire pass-through |
| Edge clearance | ≥ 0.5 mm from copper to board edge | PCBWay standard |
| Antenna keep-out | ESP32-C3 module antenna zone clear of copper/components; place module near edge | Critical for Wi-Fi/BT |
| Thermal zone | Large copper pour (top + bottom) under LED area + thermal vias | Couple to steel housing via thermal pad / adhesive |

**Assembly note**: After drilling out original rivet, clamp new board to steel housing with hollow rivet or M3 screw + insulating washer. Apply thin thermal interface material under LED copper.

---

## 2. Electrical Architecture (safety-first)

```
12V wire → TVS (SMAJ15A) → Reverse protect (Schottky or P-MOS) → Bulk C
         → 3.3 V regulator (prefer small buck) → ESP32-C3
         → 4× low-side MOSFET channels (R/G/B/W) with series current-limit resistors
```

### Protection features included
- Input TVS for load-dump / spikes common on RV 12 V systems
- Reverse polarity protection
- Series current-limit resistors (no runaway if MOSFET fails short)
- Gate pull-downs so channels are OFF at boot / brown-out
- Adequate decoupling near ESP32
- Power target capped at ~4.5–5.5 W total so steel housing remains effective heatsink

### Voltage range
Designed for 11–14.4 V (typical RV system). Do not exceed 15 V continuous.

---

## 3. LED & Drive Strategy (first prototype)

**Approach**: Discrete mid-power LEDs + series current-limit resistor + low-side AO3400 MOSFET PWM.

**Target currents (full PWM duty)**:
- Red / Green / Blue: ~80–100 mA each
- White (warm ~3000 K): ~120–150 mA
- Total power ≈ 4.5–5.5 W at 12 V

**LED arrangement recommendation**:
- Red: 3× 2835 red in series (Vf ~2.0–2.2 V each → ~6.3 V string)
- Green: 3× 2835 green (Vf ~2.8–3.2 V → ~9 V string)
- Blue: 3× 2835 blue (Vf ~2.9–3.3 V → ~9.5 V string)
- White: 3× 2835 warm-white 0.5 W (Vf ~2.9–3.1 V → ~9 V string)

**R_limit calculation** (example at 12.0 V):
R = (V_in – V_string – V_mosfet) / I_target

Approximate starting values (adjust after measuring actual Vf):
- Red (~100 mA): 47–56 Ω
- Green (~90 mA): 22–33 Ω
- Blue (~90 mA): 22–33 Ω
- White (~130 mA): 15–22 Ω

Use 1206 or 1210 resistors rated for the power dissipation (I²R).

**MOSFET**: AO3400 / AO3400A (SOT-23). Logic-level, Rds(on) acceptable at 3.3 V gate drive.

---

## 4. Recommended BOM (prototype)

| Ref | Qty | Description | Suggested MPN / Notes | Footprint |
|-----|-----|-------------|-----------------------|-----------|
| U1 | 1 | ESP32-C3 module | ESP32-C3-MINI-1 or equivalent | Module |
| U2 | 1 | 3.3 V regulator | Prefer buck (AP63205 / similar) or AMS1117-3.3 for first proto | SOT-223 / module |
| Q1–Q4 | 4 | N-MOSFET | AO3400 / AO3400A | SOT-23 |
| D1 | 1 | Reverse protection | SS14 or better Schottky; or P-MOS ideal diode | SMA / SOT-23 |
| D2 | 1 | TVS | SMAJ15A (or SMAJ12A) | SMA |
| R_gate | 4 | 100 Ω | 0603 | |
| R_pd | 4 | 10 kΩ | 0603 | |
| R_limit | 4 | Current set | 1206/1210, values per section 3 | |
| C_in | 1+1 | 100 µF 25 V + 100 nF | Electrolytic + ceramic | |
| C_3v3 | 2 | 10 µF + 100 nF | Ceramic | |
| LEDs | 12 | 2835 R/G/B/WW | Discrete 2835, 3 per channel | 2835 |
| J1 | 1 | Wire pads | +12 V / GND near center hole | |

**Notes**:
- Prefer parts available on LCSC / JLCPCB for easy assembly if using their SMT service later.
- First PCBWay order: bare boards only (qty 5). Hand-assemble or use local SMT for critical parts.

---

## 5. PCBWay Manufacturing Notes

- Quantity: 5 pcs recommended (cheap, allows spares)
- Layers: 2-layer FR4
- Thickness: 1.6 mm
- Copper: 1 oz (35 µm)
- Surface finish: HASL lead-free or ENIG (ENIG preferred for small pads)
- Soldermask: Green (or black)
- Silkscreen: White
- Min trace/space: 0.15 mm / 0.15 mm (standard is fine)
- Min hole: 0.3 mm vias OK; center mechanical hole 5.2 mm
- Board outline: exact circle 30.0 mm diameter
- No panelization needed for qty 5
- Impedance control: not required

**Gerber checklist before upload**:
- Edge cuts clear
- Center hole present and dimensioned
- Copper pours under LEDs continuous
- Antenna keep-out free of copper
- No copper under module antenna area
- Silkscreen does not cover pads

---

## 6. Safety & Risk Mitigations

| Risk | Mitigation |
|------|------------|
| Reverse polarity | Schottky or P-MOS protection |
| Load dump / spikes | Input TVS |
| Overheating | Power limited to ~5 W; steel housing as heatsink; large copper + thermal interface |
| MOSFET stuck on | Series R_limit prevents thermal runaway |
| Boot with lights on | Gate pull-downs |
| Antenna performance | Keep-out + module placement at edge |
| Mechanical stress | 1.6 mm FR4 + center clamp |
| Dirty 12 V | Bulk capacitance + TVS |

This is a Class-2 style low-voltage design. Not intended for wet locations without additional sealing.

---

## 7. Next Steps for You

1. Take this package into KiCad (GrokBuild) and create the schematic + board layout matching the mechanical constraints.
2. Run DRC + ERC.
3. Generate Gerbers + drill files.
4. Upload to PCBWay (or JLCPCB) for 5 pcs.
5. While boards are in transit, order the BOM parts.
6. Assemble one unit, flash the ESPHome YAML, test thermal behaviour inside the steel housing at full white and full RGB.

---

## 8. Files in this folder

- `DESIGN_PACKAGE.md` (this file)
- `schematic/SCHEMATIC.md` (updated netlist)
- `esphome/rv-puck.yaml`
- `BOM.md` (detailed)

When the KiCad project is ready, add the `.kicad_sch` / `.kicad_pcb` and Gerbers under a `fab/` subfolder.
