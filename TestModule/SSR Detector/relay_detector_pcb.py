"""
Author: Xiaxin Liu
Date: Mar-03-2026

MCP23017 16-Channel Digital Input Monitor (I2C)
================================================

What this script does
---------------------
- Uses I2C (smbus2) to read MCP23017 GPIOA + GPIOB (16 pins total).
- Treats the 16 pins as 16 input channels (ch1..ch16).
- Prints the raw 16-bit word (GPIOB<<8 | GPIOA) and per-channel states.
- Updates periodically (default every 10 seconds).

Channel mapping (IMPORTANT)
---------------------------
- bit0  = GPA0 = ch1 ... bit7  = GPA7 = ch8, bit8  = GPB0 = ch9 ... bit15 = GPB7 = ch16

User settings you may change
----------------------------
BUS
  - Raspberry Pi I2C bus number (usually 1).
ADDR
  - MCP23017 I2C address (e.g., 0x20). Confirm with: i2cdetect -y 1
UPDATE_S
  - Print interval in seconds.
ACTIVE_LOW
  - If your circuit/relay detector outputs LOW when "ON", set True.
  - If "ON" is HIGH, keep False.
USE_INTERNAL_PULLUPS
  - Enable MCP23017 internal pull-ups (GPPU) for floating inputs.
  - Keep False if you already have external pull-ups/pull-downs or the input is driven.

Output meaning
--------------
- RAW word: shows the combined 16-bit register value in hex.
- "1" means the channel is considered ON after ACTIVE_LOW logic.
- "0" means OFF.
- "ON channels" lists which channels are currently ON.

Notes / common issues
---------------------
- Input power +3.3V (Avoid +5V)
- If all channels read 0 or all read 1, check wiring and pull-ups/pull-downs.
- This script assumes MCP23017 is in BANK=0 register mode (default).
"""

from smbus2 import SMBus
import time

# ===== User settings =====
BUS = 1
ADDR = 0x20          # Your working MCP23017 address (from i2cdetect)
UPDATE_S = 10        # Print every 10 seconds
ACTIVE_LOW = False   # Set True only if relay ON reads 0 at MCP pin
USE_INTERNAL_PULLUPS = False  # Leave False unless you want floating inputs pulled to 1

# ===== MCP23017 registers (BANK=0) =====
IODIRA = 0x00
IODIRB = 0x01
GPPUA  = 0x0C
GPPUB  = 0x0D
GPIOA  = 0x12
GPIOB  = 0x13

def init_mcp(bus: SMBus) -> None:
    """Configure MCP23017: all inputs, optional pull-ups."""
    bus.write_byte_data(ADDR, IODIRA, 0xFF)
    bus.write_byte_data(ADDR, IODIRB, 0xFF)

    if USE_INTERNAL_PULLUPS:
        bus.write_byte_data(ADDR, GPPUA, 0xFF)
        bus.write_byte_data(ADDR, GPPUB, 0xFF)
    else:
        bus.write_byte_data(ADDR, GPPUA, 0x00)
        bus.write_byte_data(ADDR, GPPUB, 0x00)

def read16(bus: SMBus) -> int:
    """Read GPIOA+GPIOB as a 16-bit word. bit0=ch1 ... bit15=ch16"""
    a = bus.read_byte_data(ADDR, GPIOA)
    b = bus.read_byte_data(ADDR, GPIOB)
    return a | (b << 8)

def word_to_states(word: int):
    """Return list of channel states [ch1..ch16] after ACTIVE_LOW logic."""
    states = []
    for ch in range(1, 17):
        raw = (word >> (ch - 1)) & 1
        state = (1 - raw) if ACTIVE_LOW else raw
        states.append(state)
    return states

def print_states(states):
    """Pretty print ch1..ch16"""
    line = " ".join([f"{i+1}:{states[i]}" for i in range(16)])
    on_list = [i+1 for i in range(16) if states[i] == 1]
    print(line)
    print("ON channels:", on_list)

def main():
    with SMBus(BUS) as bus:
        init_mcp(bus)

        while True:
            w = read16(bus)
            states = word_to_states(w)

            print(f"\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"RAW word: {hex(w)}")
            print_states(states)

            time.sleep(UPDATE_S)

if __name__ == "__main__":
    main()
