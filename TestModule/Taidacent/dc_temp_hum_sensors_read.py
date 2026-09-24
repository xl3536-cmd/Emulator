from time import sleep, time
import minimalmodbus
import serial

serialPort = "/dev/ttyAMA3"
UNIT_IDS = [1, 2, 3]

def make_sensor(port: str, unit_id: int) -> minimalmodbus.Instrument:
    ins = minimalmodbus.Instrument(port, unit_id, debug=False)
    ins.mode = minimalmodbus.MODE_RTU

    ins.serial.baudrate = 9600
    ins.serial.timeout = 2
    ins.serial.bytesize = 8
    ins.serial.stopbits = 1
    ins.serial.parity = serial.PARITY_NONE

    # Optional
    try:
        ins.clear_buffers_before_each_transaction = True
    except Exception:
        pass

    return ins

sensors = [make_sensor(serialPort, uid) for uid in UNIT_IDS]

poll_gap = 0.2         # gap between temp and hum reads
between_sensors = 0.4  # gap between sensors
loop_delay = 0.5       # delay after finishing 1->2->3

print(f"Polling Modbus RTU on {serialPort} for Unit IDs {UNIT_IDS} ... (Ctrl+C to stop)")

try:
    while True:
        cycle_ts = time()

        for uid, s in zip(UNIT_IDS, sensors):
            try:
                temperature = s.read_register(0, 2, 3, False)
                sleep(poll_gap)
                humidity = s.read_register(1, 2, 3, False)

                print(f"[Unit {uid}] Temp={temperature:.2f} °C  Hum={humidity:.2f} %RH")
            except Exception as e:
                # Don't crash; print and continue polling others
                print(f"[Unit {uid}] ERROR: {e!r}")

            sleep(between_sensors)

        # optional: show cycle timing
        # print(f"Cycle took {time() - cycle_ts:.2f}s\n")

        sleep(loop_delay)

except KeyboardInterrupt:
    print("\nCtrl+C received. Stopping...")

finally:
    for s in sensors:
        try:
            s.serial.close()
        except Exception:
            pass
    print("Ports Now Closed")
