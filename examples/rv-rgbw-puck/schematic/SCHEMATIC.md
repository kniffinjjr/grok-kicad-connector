# Schematic Netlist — RV RGBW Smart Puck (Refined for Prototype)

## Power Input

- J1-1 = +12V (wire pad)
- J1-2 = GND (wire pad)
- D2 (SMAJ15A) across +12V to GND (cathode to +12V)
- D1 (SS14) anode to J1-1, cathode = VIN_PROTECTED
- C_in 100 µF + 100 nF on VIN_PROTECTED to GND

## 3.3 V Rail

- U2 input = VIN_PROTECTED
- U2 output = 3V3
- Decoupling 10 µF + 100 nF at U2 output and near ESP32 VDD

## ESP32-C3

- VDD = 3V3
- GND = GND
- EN pulled to 3V3 via 10 kΩ (optional RC for clean reset)
- GPIO4 → Red channel
- GPIO5 → Green channel
- GPIO6 → Blue channel
- GPIO7 → White channel
- Antenna keep-out observed

## LED Channels (identical topology)

For each color (example Red):

- VIN_PROTECTED → LED string anode
- LED string cathode → Q1 Drain
- Q1 Source → R_limit → GND
- Q1 Gate ← 100 Ω ← GPIO4
- 10 kΩ from Gate to GND

Same pattern for Green (GPIO5), Blue (GPIO6), White (GPIO7).

## Mechanical

- Round 30.0 mm outline
- Center non-plated hole Ø5.2 mm
- Large copper pour under LED group, thermal vias to bottom pour
- Module placed so antenna faces board edge with clear keep-out
