# Standalone pump controller and desktop GUI

This controller talks BACnet/IP from the controller Raspberry Pi to the real BASrouter, then BACnet MS/TP to a selected Grundfos pump/emulator. It supports multiple configured devices without importing the large `src` application.

## Desktop GUI

On the controller Pi, use the existing virtual environment and install Tkinter if needed:

```bash
sudo apt install python3-tk
source .venv/bin/activate
pip install -r requirements.txt
python3 gui.py
```

Use a desktop session (local display or remote desktop). The window opens without sending BACnet requests. Your current `config.json` values remain the defaults: controller `192.168.xx.xx/22`, BASrouter `192.168.xx.xx`, MS/TP network `4001`, and pump MAC `11` / device `xxxxxx`.

1. Check the controller IP/mask at the top. This must be an address assigned to the controller Pi.
2. Select a pump, or choose a source profile/custom device and click **Add device**. Set the BASrouter IP, UDP port, MS/TP network, pump MAC and device ID. Source profiles use your current standalone router defaults; they do not copy the production router topology.
3. Use **Apply device edits** before selecting another pump, and **Save configuration** to persist changes. Sending a request also applies the selected pump's form edits. Merely selecting another pump discards unapplied form edits.
4. Click **Read pump status**, then **Bus on**, then **Start**. Use **Write** for mode, setpoint, or flow-limit changes. Each button affects only the selected pump.
5. Use the ReadProperty form for any supported object/property. For example, object `device,xxxxxx`, property `object-name`; or `analog-output,0`, property `priority-array`, index `8`. Read `object-list` one index at a time if the full response exceeds the device's APDU size; index `0` reads its length.

The write form intentionally exposes only the emulator's five writable output `present-value` properties. Input properties remain read-only. **Release priority** writes BACnet NULL at the selected priority. Writes report acknowledgement, effective output, and actual input separately; local control or a higher-priority command can make them differ. Priority 6 is reserved. For AO5, the input is measured flow and is not expected to equal the limit.

Optional automatic status refresh targets the selected enabled pump. Network I/O runs outside the Tk event loop, with one operation at a time and a timeout for each BACnet request. Errors appear in the result log. Do not run another controller process bound to the same local IP/UDP port while using the GUI. If closing during a request, wait for completion and close again.

Controller and emulator device lists are separate. Adding a controller entry does not start an emulator; match its MAC/device ID with a running device in the emulator GUI.

The emulator now supports multiple pump MACs on one USB/RS485 adapter, plus separate adapter groups. For two pumps on the same trunk, keep the same BASrouter IP and MS/TP network in both controller entries; use different pump MACs and device IDs (for example, `11` / `xxx011` and `12` / `xxx012`). The controller does not need the emulator's USB path. For separate trunks, set each pump's actual router IP and MS/TP network. See [the emulator grouping and verification guide](../emulator/GROUPS.md).

Controller **Start**, **Stop**, and property writes affect only the selected pump. The emulator GUI's **Stop selected adapter group** disconnects all emulated pumps sharing that adapter.

## Pumps found in `src`

The manual source configuration contains **8 active pump entries**, plus 4 commented-out entries (Nordic HP, ClimateMaster 1, ClimateMaster 2, Controls pump).

| ID | Active pump | MS/TP MAC | Device instance |
| --- | --- | --- | --- |
| 1 | Climate Master SP0 | 11 | xxx011 |
| 2 | Nordic SP0 | 12 | xxx012 |
| 3 | TESW SP0 | 21 | xxxxxx |
| 4 | TESW SP1 | 22 | xxxxxx |
| 5 | TESW SP2 | 23 | xxxxxx |
| 6 | TESC SP0 | 31 | xxxxxx |
| 7 | TESC SP1 | 32 | xxxxxx |
| 8 | TESC SP2 | 33 | xxxxxx |

Reference: `../src/utils/pump_system/pump_config_manual.py`. Dynamic discovery in the large application can change its runtime device list. No `src` files are changed or imported by this controller.

## Addressing

Edit `config.json` before use:

- `local_ip`: controller Pi Ethernet IP + CIDR mask.
- `router_ip`: BASrouter Ethernet IP.
- `mstp_network`: the BASrouter's MS/TP BACnet network number.
- `mac`: the pump/emulator MS/TP MAC.
- `device_id`: pump BACnet Device instance (identity/documentation; routed requests use network + MAC).

Each pump may override `router_ip`, `router_port`, and `mstp_network`; omitted values inherit the top-level settings. The GUI stores explicit values when you apply device edits. Names and profile IDs are local labels; MAC and network determine the routed destination.

With the example config, the routed destination is:

```text
4001:11@192.168.68.5
```

The repeater should simply provide Ethernet connectivity between controller Pi and BASrouter. If it creates a routed/NAT boundary, configure that network separately.

## Install on the controller Pi

```bash
cd ~/smart-pump/controller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Commands

The existing one-pump commands still work. When multiple pumps are enabled, select one with `--pump ID` before the command:

```bash
python3 pump_controller.py --pump 2 status
python3 pump_controller.py --pump 2 read device,xxx012 object-name
python3 pump_controller.py --pump 2 read analog-output,0 priority-array --index 8
python3 pump_controller.py --pump 2 --priority 8 write analog-output,0 50
python3 pump_controller.py --pump 2 --priority 8 write analog-output,0 null
```

Start by reading status:

```bash
python3 pump_controller.py status
```

Enable BACnet bus control before trying to operate the pump:

```bash
python3 pump_controller.py bus on
python3 pump_controller.py start
python3 pump_controller.py mode constant-pressure
python3 pump_controller.py setpoint 50
python3 pump_controller.py status
```

Stop it:

```bash
python3 pump_controller.py stop
```

Return control to local control:

```bash
python3 pump_controller.py bus off
```

Optional maximum-flow limit, in **m^3/h**:

```bash
python3 pump_controller.py max-flow 6.0
```

Important: AO5 is a maximum-flow-limit command. AI5 is measured flow. The controller does **not** incorrectly require AI5 to equal the AO5 command.

## Manual-correct confirmations used here

| Command | Write | Confirmation |
| --- | --- | --- |
| Bus/local control | BO0 | BI0 Control source status |
| Control mode | MSO0 | MSI0 Actual control mode |
| Start/stop/min/max | MSO1 | MSI1 Actual operating mode |
| Setpoint | AO0 | AI9 Actual setpoint |
| Maximum flow limit | AO5 | Read AO5 command value; AI5 remains measured flow |

BI31 is PowerLimit and is **not** used as bus-control confirmation.

## Notes

- Default write priority is 8. Priority 6 is reserved and blocked by this script.
- This is a standalone controller with a device list, not the original large control application.
- The files were prepared but not built, run, or hardware-tested. You will perform those tests on your Pis.

The property service calls follow the BACpypes3 [ReadProperty/WriteProperty implementation](https://github.com/JoelBender/BACpypes3/blob/master/bacpypes3/service/object.py); the installed dependency remains pinned in `requirements.txt`.
