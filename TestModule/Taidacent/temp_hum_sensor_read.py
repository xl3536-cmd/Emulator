#!/usr/bin/env python3
import time
import minimalmodbus, serial
from serial.rs485 import RS485Settings

# PORTS = ["/dev/ttyAMA2", "/dev/ttyAMA3", "/dev/ttyAMA4", "/dev/ttyAMA5"]
PORTS =  ["/dev/ttyAMA3"]
RTS_MODES = ["no_rts", "rts_normal", "rts_invert"]
SLAVE_ID = 1

POLL_PERIOD_SEC = 2.0
TIMEOUT_SEC = 2.0
INTER_REQUEST_GAP_SEC = 0.15

def make(port, sid, rts_mode):
    ins = minimalmodbus.Instrument(port, sid, debug=False)
    ins.mode = minimalmodbus.MODE_RTU

    ins.serial.baudrate = 9600
    ins.serial.bytesize = 8
    ins.serial.parity = serial.PARITY_NONE
    ins.serial.stopbits = 1
    ins.serial.timeout = TIMEOUT_SEC
    ins.serial.write_timeout = TIMEOUT_SEC
    ins.clear_buffers_before_each_transaction = True

    if rts_mode == "rts_normal":
        ins.serial.rs485_mode = RS485Settings(True, False, 0.01, 0.08)
    elif rts_mode == "rts_invert":
        ins.serial.rs485_mode = RS485Settings(False, True, 0.01, 0.08)

    return ins

def try_read(ins):
    # Try base 0 then base 1
    for base in (0, 1):
        time.sleep(INTER_REQUEST_GAP_SEC)
        regs = ins.read_registers(base, 2, functioncode=3)  # FC03, read 2 regs
        t = regs[0] / 100.0
        h = regs[1] / 100.0
        return base, regs, t, h
    raise RuntimeError("unreachable")

def auto_find():
    for port in PORTS:
        for rts_mode in RTS_MODES:
            ins = make(port, SLAVE_ID, rts_mode)
            try:
                base, regs, t, h = try_read(ins)
                print(f"✅ FOUND port={port} rts={rts_mode} base={base} regs={regs} -> T={t:.2f}C H={h:.2f}%")
                return port, rts_mode, base
            except Exception as e:
                print(f"❌ fail port={port} rts={rts_mode}: {type(e).__name__}")
            finally:
                try: ins.serial.close()
                except: pass
            time.sleep(0.05)
    raise RuntimeError("Nothing responded. Check wiring/A-B/port.")

def read_loop(port, rts_mode, base):
    ins = make(port, SLAVE_ID, rts_mode)
    print(f"▶️  Reading loop on {port}, rts={rts_mode}, base={base}")
    try:
        while True:
            try:
                time.sleep(INTER_REQUEST_GAP_SEC)
                regs = ins.read_registers(base, 2, functioncode=3)
                t = regs[0] / 100.0
                h = regs[1] / 100.0
                print(f"Temp={t:.2f}C  Hum={h:.2f}%  raw={regs}")
            except Exception as e:
                print("Read error:", e)
                # Close and force re-find (most reliable recovery)
                try: ins.serial.close()
                except: pass
                raise
            time.sleep(POLL_PERIOD_SEC)
    finally:
        try: ins.serial.close()
        except: pass

if __name__ == "__main__":
    while True:
        try:
            port, rts_mode, base = auto_find()
            read_loop(port, rts_mode, base)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print("🔁 Re-trying auto-find after error:", e)
            time.sleep(1.0)


