# Raspberry Pi Grundfos pump emulator

This folder emulates BACnet MS/TP pumps over USB-to-RS485 adapters. The GUI groups pumps by serial adapter: multiple pump MAC addresses can share one adapter, and separate adapters can run separate groups. It uses the included C BACnet Stack for MS/TP token handling and BACnet services; the Python scripts configure, build, and launch it. The original `src` files are unchanged.

## Desktop GUI

Run these commands yourself on the emulator Pi, from this folder:

```bash
sudo apt install python3-tk
python3 build.py
python3 gui.py
```

Rebuild to create the new `mstp_bus` and `pump_worker` executables required by the GUI. `build.py` also runs the object, group transport, and configuration checks. No code, build, or tests were run during preparation of this change. Use a desktop session (local display or remote desktop); the emulator GUI needs no additional pip packages.

The GUI begins with your working `config.json` (including baud `9600`) and does not open hardware until **Start selected adapter group**. The real BASrouter still routes MS/TP traffic to the controller. See [the adapter grouping guide](GROUPS.md) for the two-pump example and verification steps.

1. Select the starting device, or choose one of the eight pump profiles/custom device and click **Add device from profile**.
2. Set its serial adapter, MAC, device ID, baud, Max Master, BASrouter MAC, and starting state. Use the same serial path for pumps sharing an adapter. BASrouter MAC defaults to `40`, as shown blue in your status screenshot; this field does not reconfigure the router. Click **Apply profile edits** before selecting another device. Unapplied form edits are discarded when switching selection.
3. Click **Start selected adapter group** to start all configured pumps on that adapter. State updates appear about once per second. Running indicates initialization; successful controller reads are needed to verify BASrouter communication.
4. In the controller GUI on the other Pi, configure this pump's MAC/device ID and the real BASrouter's IP/network, then read status, enable bus control, and start the pump.
5. To inject a fault, choose `fault_code`, enter a nonzero code and click **Apply live**. Enter `0` to clear it. Live temperature, flow, pressure, power, current, warnings, and local mode/setpoint changes use the same control.
6. Use **Save all profiles** to retain the device list and acknowledged live simulation settings in `gui_devices.json`. It does not overwrite your original `config.json`. Starting-state edits for a running device require stopping its adapter group first; the live controls are separate. Stop/start resets counters and output priority arrays to the saved/in-memory startup settings.

Local mode/setpoint changes affect the actual pump only while bus control is off. Use **Local** in the controller GUI to return to local operation. Changing simulation readings does not make BACnet input properties writable and does not alter the bus output priority arrays. The GUI uses a private stdin pipe for simulation changes; the controller still uses real BACnet ReadProperty/WriteProperty.

An adapter group supports up to **32 independent virtual pump stations** with unique MAC addresses. All pumps on that adapter must use the same baud, Max Master, and BASrouter MAC. Device instances must be unique across groups. The adapter lock prevents two group managers or the original `run.py` from opening the same adapter. The pumps have no Ethernet IP; enter the **BASrouter IP in the controller GUI**.

**Stop selected adapter group** disconnects every virtual pump on that adapter. A controller **Stop** command only stops operation of its selected pump, which remains online. To change group membership, stop that group, add/edit profiles, and restart it. Other adapter groups can remain running.

Closing the emulator GUI stops the processes it launched. Apply/save before closing if you want to keep edits. Original terminal commands remain available, but should not share an adapter with a GUI-launched device.

The code has not been verified on your Raspberry Pi, USB adapter, or BASrouter. All commands below are for the Raspberry Pi. Do not run them on Windows.

## Connection and addresses

```text
Emulator Pi -- USB/RS485 -- BASRT-B -- Ethernet -- TI-ELC80 LAN bridge
                                                        |
                                                     Ethernet
                                                        |
                                                 Controller Pi
```

The BASRT-B routes BACnet/IP to BACnet MS/TP. The emulator's pump interface needs an MS/TP MAC and BACnet Device instance, not an IP address. Both Ethernet devices must be able to communicate through the repeater/bridge. The TI-ELC80's actual operating mode still needs checking on site.

Use these consistent example settings, changing IP addresses to match your LAN:

| Setting | Example |
| --- | --- |
| BASrouter LAN IP | `192.168.68.5` (use its actual configured LAN mask) |
| Controller Pi LAN IP | `192.168.68.101/22` |
| BACnet/IP UDP port | `47808` / `0xBAC0` |
| BASrouter BACnet/IP network | `1` (unique in your BACnet installation) |
| BASrouter MS/TP network | `4001` |
| BASrouter MS/TP MAC | `40` (blue in your router status screenshot) |
| Emulator pump MS/TP MAC | `11` |
| Emulator pump Device instance | `227011` |
| MS/TP baud, both ends | `9600` |
| MS/TP Max Master, both ends | `127` |
| Emulator Max Info Frames | `1` |
| Controller destination | `4001:11@192.168.68.5` |

Network numbers, MS/TP MAC addresses, Device instances, and IP addresses are different identifiers. Keep both BACnet network numbers distinct. Every station on the MS/TP trunk needs a unique MAC, and every BACnet device needs a unique Device instance. Leave the BASrouter's own Device instance unique too. If your BASrouter already uses another MS/TP network number, put that number in the controller configuration instead.

Use a **two-wire, half-duplex USB RS485 adapter with automatic transmit-direction control and local receive echo disabled**. The group manager distributes transmitted frames to the other virtual stations itself; adapter echo would deliver them twice. This program does not toggle a GPIO pin or manually manage an adapter's RTS direction line. USB adapters differ in buffering and turnaround timing; compatibility needs checking on the Pi.

Connect signal `+`, signal `-`, and signal common according to the adapter and BASrouter manuals. Manufacturers do not consistently use `A` and `B` for the same polarity, so check their signal definitions. Use the specified RS485 cable and termination at the two physical ends. Check the BASrouter's installed termination and bias configuration before adding resistors or changing jumpers; avoid duplicate termination or bias networks. Signal common is not the same as the cable shield.

## Prepare and run the emulator Pi

Copy this entire `emulator` folder, **including `vendor/bacnet-stack`**, to the Pi. Keep its license files. Omit any `build`, `build-test`, or Python cache directories from the transfer: compiled files must be rebuilt for the Pi.

On Raspberry Pi OS/Linux:

```bash
cd ~/smart-pump/emulator
sudo apt update
sudo apt install -y build-essential cmake git python3
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing the group. Find the adapter:

```bash
ls -l /dev/serial/by-id/
```

Edit `config.json` to set `serial_port`. Prefer the stable `/dev/serial/by-id/...` path; `/dev/ttyUSB0` is the default. Set the baud and pump identity to agree with your BASrouter and controller setup. The adapter must not be in use by another serial program.

```bash
python3 build.py
python3 run.py --check
python3 run.py
```

`build.py` builds the single-pump and grouped MS/TP executables and runs hardware-free checks **on the Pi**. It uses the included BACnet Stack snapshot; if that source is missing it attempts to download the pinned upstream version. `run.py --check` validates the single-pump configuration without opening the adapter. A normal `run.py` launch prints the chosen settings and pump state, opens the RS485 adapter, and participates in MS/TP. Stop with `Ctrl+C`. For several pumps on one adapter, use the GUI or `run_group.py` as described in [GROUPS.md](GROUPS.md).

Use the separate `../controller/README.md` to prepare the other Pi. Start with its read command, then enable bus control and issue start/setpoint commands. The emulator starts with bus control disabled and operating mode `2` (stopped), so initial flow, pressure, current, and power are zero.

## Command and reading behavior

This is a command/reading emulator, with simple scaling of configured readings. It does not model a hydraulic system or reproduce the full Grundfos firmware.

| Write `presentValue` | Confirmation/readback |
| --- | --- |
| `binaryOutput,0`: `1` bus, `0` local | `binaryInput,0` Control source status |
| `multiStateOutput,0`: control mode | `multiStateInput,0` |
| `multiStateOutput,1`: operating mode | `multiStateInput,1` |
| `analogOutput,0`: setpoint, `0..100` | `analogInput,9` |
| `analogOutput,5`: maximum-flow limit (m^3/h) | AO5 command value; AI5 remains measured flow |

The manual-correct behavior is used here: BI0 reports the control source; BI31 remains PowerLimit. AO5 is a maximum-flow-limit command in m^3/h and constrains simulated measured flow rather than overwriting AI5 with the command.


Normal running scales `flow_gpm`, `pressure_psi`, `power_w`, and `current_a` from `config.json` by the setpoint fraction. The minimum running fraction is 25%; mode `3` forces 25%, mode `4` forces 100%, and mode `2` stops. A nonzero configured fault code stops normal readings. A 0% setpoint still runs at the minimum; use operating mode `2` to stop. Temperatures stay at their configured values. Operating hours increase while running; on-hours increase whenever the emulator runs.

While local control is selected, effective modes and setpoint come from `initial` in `config.json`. Bus commands are stored and take effect when bus control is enabled. BACnet output priority arrays and `NULL` relinquishment are supported; another command at a higher priority can hold the effective value. Priority `6` is reserved by the underlying stack.

Control modes accepted are `1` constant curve, `2` constant pressure, `3` proportional pressure, `4` auto adapt, `5` constant flow, `6` constant temperature, `9` flow adapt, and `12` differential temperature. These select reported modes; they do not implement distinct hydraulic algorithms.

Terminal launches do not save configuration or counters at shutdown. Edit `config.json` and restart for terminal starting settings, or use the GUI for live simulation changes and explicit profile saves. Running counters and BACnet output priorities are not persisted. The emulator supports Who-Is/I-Am, ReadProperty, ReadPropertyMultiple, and WriteProperty, with a 480-byte maximum APDU and no segmentation.

## Existing pump profiles and future expansion

`pump_profiles.json` contains all eight identities from the supplied controller:

Profile 1 retains your existing custom emulator name; its `source_name` records Climate Master SP0. The default `config.json` identity is unchanged.

| `--pump` | Name | MS/TP MAC | Device instance |
| --- | --- | --- | --- |
| `1` | Climate Master SP0 | `11` | `227011` |
| `2` | Nordic SP0 | `12` | `227012` |
| `3` | TESW SP0 | `21` | `227021` |
| `4` | TESW SP1 | `22` | `227022` |
| `5` | TESW SP2 | `23` | `227023` |
| `6` | TESC SP0 | `31` | `227031` |
| `7` | TESC SP1 | `32` | `227032` |
| `8` | TESC SP2 | `33` | `227033` |

For example, `python3 run.py --pump 4` selects the TESW SP1 identity while retaining the readings and serial settings from `config.json`. Without `--pump`, the identity comes from `config.json`. An adapter path can be overridden with `--serial-port /dev/serial/by-id/...`.

`run.py` remains the original **single-pump** launcher. Selecting a profile there does not create multiple pumps. For simultaneous pumps sharing an adapter, add profiles in the GUI and start their adapter group. Do not launch several independent `run.py` processes against one adapter.

## If the controller times out

Check the emulator terminal for errors, then verify serial permissions, signal polarity/common, baud, unique MACs, and the BASrouter MS/TP network number. The router's Max Master must include MAC `11` (or the selected pump's MAC). Check that the controller binds its actual LAN IP and reaches the BASrouter's actual IP with matching UDP port. Start with individual property reads if a batch fails. A ready message confirms program initialization, not successful MS/TP communication; the first successful controller read is the useful hardware check.
