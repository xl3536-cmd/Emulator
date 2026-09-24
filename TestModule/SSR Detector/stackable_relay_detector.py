from smbus2 import SMBus
import tkinter as tk
from tkinter import ttk
import time

# =========================
# User settings
# =========================
BUS_NUM = 1
UPDATE_MS = 1000              # GUI refresh interval in ms
ACTIVE_LOW = False            # True if relay detect is LOW when ON
USE_INTERNAL_PULLUPS = False  # True only if inputs are floating and need pull-up

# Add as many MCP23017 boards as you want here
# Example: 2 boards, 3 boards, 5 boards...
BOARDS = [
    {"name": "Relay PCB 1", "addr": 0x20},
    {"name": "Relay PCB 2", "addr": 0x21},
    # {"name": "Relay PCB 3", "addr": 0x22},
    # {"name": "Relay PCB 4", "addr": 0x23},
    # {"name": "Relay PCB 5", "addr": 0x24},
]

# =========================
# MCP23017 registers (BANK=0)
# =========================
IODIRA = 0x00
IODIRB = 0x01
GPPUA  = 0x0C
GPPUB  = 0x0D
GPIOA  = 0x12
GPIOB  = 0x13

# =========================
# MCP helper functions
# =========================
def init_mcp(bus: SMBus, addr: int) -> None:
    """Configure one MCP23017: all inputs, optional pull-ups."""
    bus.write_byte_data(addr, IODIRA, 0xFF)
    bus.write_byte_data(addr, IODIRB, 0xFF)

    if USE_INTERNAL_PULLUPS:
        bus.write_byte_data(addr, GPPUA, 0xFF)
        bus.write_byte_data(addr, GPPUB, 0xFF)
    else:
        bus.write_byte_data(addr, GPPUA, 0x00)
        bus.write_byte_data(addr, GPPUB, 0x00)

def read16(bus: SMBus, addr: int) -> int:
    """Read GPIOA + GPIOB as 16-bit word. bit0=ch1 ... bit15=ch16"""
    a = bus.read_byte_data(addr, GPIOA)
    b = bus.read_byte_data(addr, GPIOB)
    return a | (b << 8)

def word_to_states(word: int):
    """Convert 16-bit word into [ch1..ch16] states after ACTIVE_LOW logic."""
    states = []
    for ch in range(1, 17):
        raw = (word >> (ch - 1)) & 1
        state = (1 - raw) if ACTIVE_LOW else raw
        states.append(state)
    return states

# =========================
# GUI App
# =========================
class MCPMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Multi-MCP23017 SSR Detect Monitor")
        self.root.geometry("1200x700")

        self.bus = SMBus(BUS_NUM)

        # store widgets per board
        self.board_widgets = {}

        # top info
        top_frame = ttk.Frame(root, padding=10)
        top_frame.pack(fill="x")

        ttk.Label(
            top_frame,
            text=f"I2C Bus: {BUS_NUM}   |   Refresh: {UPDATE_MS} ms   |   ACTIVE_LOW: {ACTIVE_LOW}",
            font=("Arial", 11, "bold")
        ).pack(anchor="w")

        self.time_label = ttk.Label(top_frame, text="", font=("Arial", 10))
        self.time_label.pack(anchor="w", pady=(5, 0))

        # canvas + scrollbar for many boards
        container = ttk.Frame(root)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container)
        self.scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = ttk.Frame(self.canvas)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # init all MCPs and build GUI panels
        self.build_board_panels()

        # first update
        self.update_loop()

        # clean shutdown
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_board_panels(self):
        for idx, board in enumerate(BOARDS):
            name = board["name"]
            addr = board["addr"]

            # Try init
            init_ok = True
            init_msg = "OK"
            try:
                init_mcp(self.bus, addr)
            except Exception as e:
                init_ok = False
                init_msg = f"Init failed: {e}"

            frame = ttk.LabelFrame(
                self.scrollable_frame,
                text=f"{name}   (addr=0x{addr:02X})",
                padding=10
            )
            frame.grid(row=idx // 2, column=idx % 2, padx=10, pady=10, sticky="nsew")

            # status line
            status_label = ttk.Label(
                frame,
                text=f"Board status: {'Connected' if init_ok else init_msg}",
                font=("Arial", 10, "bold")
            )
            status_label.grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 5))

            # raw word label
            raw_label = ttk.Label(frame, text="RAW word: --", font=("Consolas", 10))
            raw_label.grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 10))

            # ON channels label
            on_label = ttk.Label(frame, text="ON channels: []", font=("Arial", 10))
            on_label.grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 10))

            # channel boxes
            ch_labels = []
            for ch in range(16):
                r = 3 + ch // 4
                c = ch % 4

                lbl = tk.Label(
                    frame,
                    text=f"ch{ch+1}\n--",
                    width=12,
                    height=3,
                    relief="ridge",
                    bd=2,
                    font=("Arial", 10, "bold"),
                    bg="lightgray"
                )
                lbl.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")
                ch_labels.append(lbl)

            self.board_widgets[addr] = {
                "frame": frame,
                "status_label": status_label,
                "raw_label": raw_label,
                "on_label": on_label,
                "ch_labels": ch_labels,
            }

    def update_board_display(self, addr: int, states, raw_word: int):
        widgets = self.board_widgets[addr]

        widgets["status_label"].config(text="Board status: Connected")
        widgets["raw_label"].config(text=f"RAW word: 0x{raw_word:04X}")

        on_list = [i + 1 for i, s in enumerate(states) if s == 1]
        widgets["on_label"].config(text=f"ON channels: {on_list}")

        for i, state in enumerate(states):
            if state == 1:
                widgets["ch_labels"][i].config(
                    text=f"ch{i+1}\nON",
                    bg="#4CAF50",   # green
                    fg="white"
                )
            else:
                widgets["ch_labels"][i].config(
                    text=f"ch{i+1}\nOFF",
                    bg="#D9534F",   # red
                    fg="white"
                )

    def show_board_error(self, addr: int, err_msg: str):
        widgets = self.board_widgets[addr]

        widgets["status_label"].config(text=f"Board status: ERROR - {err_msg}")
        widgets["raw_label"].config(text="RAW word: --")
        widgets["on_label"].config(text="ON channels: --")

        for i in range(16):
            widgets["ch_labels"][i].config(
                text=f"ch{i+1}\nERR",
                bg="gray",
                fg="white"
            )

    def update_loop(self):
        self.time_label.config(text="Time: " + time.strftime("%Y-%m-%d %H:%M:%S"))

        for board in BOARDS:
            addr = board["addr"]
            try:
                raw_word = read16(self.bus, addr)
                states = word_to_states(raw_word)
                self.update_board_display(addr, states, raw_word)
            except Exception as e:
                self.show_board_error(addr, str(e))

        self.root.after(UPDATE_MS, self.update_loop)

    def on_close(self):
        try:
            self.bus.close()
        except Exception:
            pass
        self.root.destroy()

# =========================
# Main
# =========================
def main():
    root = tk.Tk()
    app = MCPMonitorApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
