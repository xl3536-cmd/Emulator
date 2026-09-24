Power

Pi USB-C adapter → Pi

Pi 5 V (physical pin 2 or 4) → PCB VIN (+5 V)

Pi GND (e.g., pin 6) → PCB GND

(Always share ground.)

Shift-register (74HC595) control

MOSI SPI0: Pi pin 19 (BCM10) → PCB DS

SCLK SPI0: Pi pin 23 (BCM11) → PCB SHCP/SCLK

LATCH: Pi pin 29 (BCM5) → PCB STCP/RCLK

CE0/CE1: Not used for the 74HC595.

Chaining (optional)

PCB DOUT → Next board DS (leave unconnected if only one board).

RTD I/O (your measurement path)

Your Sequent RTD HAT reads stack 0, channel 1 via librtd.

The programmable-resistor board’s R_OUT terminals connect to your measurement instrument / loop as the RTD emulator.

Notes

Keep 5 V/GND leads short; don’t back-feed 5 V into the Pi if you ever power the PCB from a separate supply—only share GND in that case.
