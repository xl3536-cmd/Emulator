# Multiple pumps on one adapter, or several adapter groups

The code is written and source-reviewed, but has not been compiled, executed, or tested on hardware during this change. You will build and verify it on your Pi.

## Update and build

1. Close the old emulator GUI and terminal emulator processes.
2. Copy the updated emulator folder, including `vendor`, to the Pi. Preserve your `config.json` and `gui_devices.json`. Do not copy a `build` directory from another location or computer.
3. From the emulator folder, run:

   ```bash
   python3 build.py
   python3 gui.py
   ```

If CMake reports that its cache belongs to another directory, rename `build` to an unused backup name (for example, `build-old-location`) and repeat `python3 build.py`. The updated GUI needs both new binaries, `mstp_bus` and `pump_worker`; an old `pump_emulator` binary alone is insufficient. An old binary sitting on disk does not conflict, but an old process still using the adapter does.

## Two pumps sharing `/dev/ttyUSB0`

Configure these profiles in the emulator GUI, clicking **Apply profile edits** after editing each:

| Field | Pump 1 | Pump 2 |
| --- | --- | --- |
| Source profile | Climate Master SP0 | Nordic SP0 |
| Profile ID | 1 | 2 |
| Serial adapter path | `/dev/ttyUSB0` | `/dev/ttyUSB0` |
| MS/TP MAC | 11 | 12 |
| BACnet device ID | 227xxx | 227xxx |
| Baud | 9600 | 9600 |
| Max Master | 127 | 127 |
| Max Info Frames | 1 | 1 |
| BASrouter MAC | 40 | 40 |

Use your actual baud and router MAC if different. The `40` comes from the blue router MAC in your screenshot; the GUI field only checks for address conflicts and does not change router settings. Router and pump Max Master settings must include every master MAC on their trunk.

Select either pump and click **Start selected adapter group**. Both start together. Selecting a pump and using **Apply live** changes only that pump's simulation. Save profiles to keep your list and settings.

To add a third pump to an active group, stop that group, add the new profile with the same serial path and unused MAC/device ID, apply/save, then start the group again. A group supports up to 32 pumps. Stopping or restarting a group affects all its pumps and resets their runtime counters/output priorities.

## Verify from the real BASrouter and controller

1. Start the emulator group first. Wait for both entries to show Running. This confirms process initialization only.
2. Refresh the BASrouter's MS/TP status page. MACs **11 and 12** should appear online/green; **40** remains the router/blue. Initial discovery can take time, especially at 9600 baud with Max Master 127.
3. Add both pumps in the controller GUI. They share the real router IP and MS/TP network, but use their respective MACs/device IDs. With the existing defaults the destinations are `4001:xx@192.168.xx.xx` and `4001:xx@192.168.xx.xx`.
4. Select pump 1 and **Read pump status**. Read `device,xxxxxx` / `object-name`. Select pump 2 and read its status and `device,xxxxxx` / `object-name`. Both should respond with their own identity.
5. On pump 1, choose **Bus on**, **Start**, then write a 40% setpoint. On pump 2 choose **Bus on**, **Start**, then write 70%. Read each back; AI9 should show its own setpoint. Check that both emulator snapshots remain independent.
6. Select pump 1 in the emulator, set `fault_code` to `1`, and click **Apply live**. Pump 1 should report the fault and stop simulated flow; pump 2 should keep its own state. Set the fault back to `0` to clear it.
7. In the controller, **Stop** pump 1. Only pump 1's operation should stop; both devices remain readable. In the emulator, **Stop selected adapter group** disconnects both from that adapter.

If a read times out, check the group log, router network number, baud, MAC conflicts, serial permissions, wiring, and local echo. The group expects an automatic-direction RS485 adapter without local receive echo. Hardware timing still needs verification with your adapter and BASrouter. Hardware-free build checks cannot establish physical communication.

## More than one adapter

Serial path determines group membership. For example:

| Adapter group | Pump MACs | Start/stop behavior |
| --- | --- | --- |
| `/dev/ttyUSB0` | 11, 12 | Starts/stops these two together |
| `/dev/ttyUSB1` | 21, 22, 23 | Starts/stops these three together |

Start each group by selecting one of its pumps and clicking **Start selected adapter group**. Other groups keep running when one is stopped. Prefer `/dev/serial/by-id/...` paths because USB numbering may change after reconnecting adapters. Aliases resolving to the same adapter are treated as one group.

If both adapters are wired onto the same physical MS/TP trunk, every pump MAC must be unique across both groups and distinct from the router and other physical devices. The software cannot infer which separate adapters are wired together. Keep their baud and router settings consistent.

If the adapters serve separate physical trunks, each trunk needs a route to the controller, typically its own BASrouter and distinct BACnet MS/TP network number. Configure the corresponding router IP/network on each controller profile. The same MAC may be reused on separate networks; BACnet device IDs must remain globally unique. A single BASRT-B MS/TP port is one trunk, not two independent networks.

## Terminal group launch

After saving the GUI profiles:

```bash
python3 run_group.py --check
python3 run_group.py --serial-port /dev/ttyUSB0
```

Use a separate terminal for another adapter:

```bash
python3 run_group.py --serial-port /dev/ttyUSB1
```

Stop with Ctrl+C. Do not launch the GUI and terminal group on the same adapter concurrently. The original `python3 run.py` remains available for a single pump.

## Implementation and limits

One `mstp_bus` process owns each physical UART. It keeps an independent vendor MS/TP receive/master state machine for every virtual MAC, including token passing, poll-for-master replies, CRC checks and reply timing. All local stations receive frames sent by their local peers as well as received wire frames. Each pump's existing BACnet application runs in its own `pump_worker` process, with separate device identity, objects, output priority arrays, readings, counters, and live control pipe. Private packet sockets carry BACnet NPDUs between the workers and their adapter manager.

This simulates separate BACnet stations on the same shared bus. It does not reproduce separate physical RS485 transceivers, cable sections, electrical loading, or wiring faults of actual daisy-chained pumps. All pumps on one adapter share that adapter's failure point. A worker or transport failure stops its group so the GUI does not leave a partly failed group appearing healthy.

`build.py` includes hardware-free checks for object behavior, group configuration conflicts, per-MAC poll replies, local token passing, unicast/broadcast routing, CRC rejection, reply matching, reply postponement, and token recovery. These checks were added but not run during preparation.
