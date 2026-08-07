# Schematic Specification — RV RGBW Smart Puck

## 1. Power input

| Ref | Description | Notes |
|-----|-------------|-------|
| J1 | 12 V wire pads | +12 V and GND; wires exit through center hollow rivet |
| D1 | Reverse polarity protection | Schottky (e.g. SS14 / 1N5819) or ideal-diode P-MOS |
| C_in | Input bulk + HF | 100 µF electrolytic + 100 nF ceramic near input |
| U_reg | 12 V → 3.3 V | Prototype: AMS1117-3.3 or better LDO. Production: small buck (MP1584 / AP63205 class) to reduce heat |
| C_3v3 | Decoupling | 10 µF + 100 nF close to ESP32 |

## 2. MCU

- ESP32-C3 (module or bare)
- Powered from 3.3 V rail
- Antenna keep-out on board edge
- Optional BOOT / EN circuitry for first flash

### GPIO assignment
| Function | GPIO |
|----------|------|
| Red PWM | GPIO4 |
| Green PWM | GPIO5 |
| Blue PWM | GPIO6 |
| White PWM | GPIO7 |

## 3. LED drive channels (×4, identical)

Each color:

```
12V ── LED string (series as needed) ── Drain of Qx
                                          |
                                       Source ── R_limit ── GND
                                          |
                                        Gate ←─ 100 Ω ← GPIO
                                          |
                                       10 kΩ pull-down to GND
```

| Ref | Part | Notes |
|-----|------|-------|
| Q1–Q4 | AO3400 / AO3400A or SI2302 | Logic-level N-MOSFET, SOT-23, low Vgs(th), good for 3.3 V drive |
| R_gate | 100 Ω | Series gate resistor |
| R_pd | 10 kΩ | Gate pull-down (off at boot) |
| R_limit | Calculated | Sets peak current per channel (start ~3–15 Ω depending on LED Vf and desired mA) |
| LEDs | Discrete R / G / B / WW 2835 or 3535 | Series count chosen so Vf total sits comfortably under 12 V at target current |

**Power target**: keep total ~4–5.5 W so the steel housing remains a comfortable heatsink.

## 4. Mechanical

- Round board matching Facon-style housing (~30–32 mm usable diameter)
- **Center hole Ø5.0–5.5 mm** for new hollow rivet / eyelet + wire pass-through
- LED copper pours thermally coupled to steel housing (thermal interface material under LED zone)
- Spring clips on housing remain for ceiling mount; board is retained by the center rivet

## 5. Suggested first-prototype BOM (high level)

- 1× ESP32-C3 module
- 4× AO3400 (or SI2302) SOT-23
- 4× 100 Ω + 4× 10 kΩ (gate)
- 4× current-limit resistors (value after LED choice)
- Discrete RGBW LEDs (or separate R/G/B + warm-white)
- Input protection diode + bulk/ceramic caps
- 3.3 V regulator (LDO first, buck later)
- 2 wire pads near center hole

## 6. Next engineering steps

1. Choose exact LED part numbers and series count → calculate R_limit
2. Enter this netlist into KiCad (or generate via connector tools)
3. Layout: prioritise thermal pour under LEDs + clean antenna keep-out
4. Flash ESPHome YAML, verify colour mixing and thermal behaviour in housing
