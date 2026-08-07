# BOM — RV RGBW Smart Puck (Prototype)

Target: hand-assembly friendly, common footprints, good availability.

| Qty | Ref | Value / Description | Suggested Part | Footprint | Notes |
|-----|-----|---------------------|----------------|-----------|-------|
| 1 | U1 | ESP32-C3 module | ESP32-C3-MINI-1 (or compatible) | Module | Antenna at edge |
| 1 | U2 | 3.3 V regulator | AMS1117-3.3 (proto) or AP63205-style buck | SOT-223 / SOT-23-6 | Buck preferred for heat |
| 4 | Q1-Q4 | N-MOSFET 30 V | AO3400 / AO3400A | SOT-23 | Logic level |
| 1 | D1 | Schottky reverse | SS14 | SMA | Or P-MOS ideal diode |
| 1 | D2 | TVS 15 V | SMAJ15A | SMA | Input protection |
| 4 | Rg | 100 Ω | 0603 | Gate series |
| 4 | Rpd | 10 kΩ | 0603 | Gate pull-down |
| 1 | Rr | ~47–56 Ω | 1206 | Red current limit |
| 1 | Rg | ~22–33 Ω | 1206 | Green current limit |
| 1 | Rb | ~22–33 Ω | 1206 | Blue current limit |
| 1 | Rw | ~15–22 Ω | 1206 | White current limit |
| 1 | Cin1 | 100 µF 25 V | Electrolytic | Bulk |
| 2 | Cin2 / C3v3 | 100 nF + 10 µF | 0603 / 0805 | Ceramic |
| 3 | LED-R | Red 2835 | Mid-power 2835 | 2835 | Series string |
| 3 | LED-G | Green 2835 | Mid-power 2835 | 2835 | Series string |
| 3 | LED-B | Blue 2835 | Mid-power 2835 | 2835 | Series string |
| 3 | LED-W | Warm white 2835 | 0.5 W class ~3000 K | 2835 | Series string |
| 1 | J1 | Wire pads | +12 V / GND | Custom pads near center |

**Power budget target**: ≤ 5.5 W total at 12 V full white + color mix.

**Resistor values are starting points**. Measure actual LED string Vf on the assembled board and adjust if needed.
