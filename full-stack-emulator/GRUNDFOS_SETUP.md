# Grundfos pump integration

The implementation has been reviewed statically. No application run, build, automated test, or physical BACnet verification was performed for this integration. The commands and checks below are for you to run.

## Architecture

The module follows the existing layering:

```text
frontend/src/features/grundfos/GrundfosPage.jsx
  -> frontend/src/api/client.js
  -> backend/src/routes/grundfos_routes.py
  -> backend/src/controllers/grundfos_controller.py
  -> backend/src/services/grundfos_service.py
  -> backend/src/managers/grundfos_manager.py
  -> backend/src/sensors/grundfos/emulator.py
  -> backend/grundfos_engine/run_group.py
  -> mstp_bus + one pump_worker per device
```

The bundled C engine and group transport provide complete object snapshots, live command editing, measurement overrides, and controller confirmation compatibility. Web edits and BACnet controller writes use the same C pump objects. The full-stack deployment does not require a sibling TestModule folder.

Device address fields are blank and pump names are generic in this copy. Enter your own device settings before deployment. The backend launcher defaults to `localhost`; set `EMULATOR_HOST` locally if another bind host is needed.

`models/grundfos.py` validates saved settings; the existing config store persists them under `grundfos.devices` in `backend/emulator_config.json`. Existing configuration files gain this section through model defaults. `EmulatorManager` owns the pump manager, includes snapshots in `/api/runtime`, guards configuration changes, and stops pump processes at shutdown. The existing frontend poll refreshes the cards.

## Build and start on the emulator Pi

Use Raspberry Pi OS/Linux, Python 3.10+, the existing backend environment, and one backend worker. From `full-stack-emulator`, run:

```bash
sudo apt install build-essential cmake git
python3 backend/grundfos_engine/build.py
```

The builder fetches missing BACnet Stack source, compiles, and runs the engine checks. The first build needs network access or a supplied copy of the pinned source under `backend/grundfos_engine/vendor/bacnet-stack`. The pin is `bacnet-stack-1.6.1`, revision `7a53f0a72a92de1621d30fc63703a29afe12bfaf`. Preserve its license files. Build this copy; older workers lack the web snapshot protocol and are rejected.

Rebuild the frontend using your normal workflow:

```bash
cd frontend
npm ci
npm run build
```

Optional backend checks, from `backend` using its Python environment:

```bash
python3 -m unittest discover -s tests -p 'test_grundfos.py'
```

The checks cover configuration, live-group edit guards, value validation, snapshot parsing, acknowledgements and stale-state handling without opening hardware. They were added but not run.

Start the backend/frontend using the existing deployment instructions. Pump groups remain stopped until you click Start Adapter Group. Windows supports editing saved configuration, but MS/TP Start requires Linux and compiled binaries.

The backend service user needs serial permissions (normally `dialout`). Prefer `/dev/serial/by-id/...`. Use a dedicated automatic-direction RS485 adapter with local echo disabled, as required by the original transport. Do not share it with Arctic Modbus or another running pump emulator.

## Match top-level controller src

The path remains `controller BACnet/IP -> BASrouter -> RS485 MS/TP -> emulator`. Pumps have MS/TP MACs and BACnet device instances, not Ethernet IPs. Router IP/network settings stay in controller `src/utils/bacnet_routers.py` and the physical router.

The sample default is Grundfos Pump 1, MAC 11, device instance 227011, router MAC 10 and baud 9600. Configure these values to match your controller and physical router.

Only pump 1 is created by default. Add/configure others as needed; Add Pump selects an unused identity on the first adapter. Use separate adapter groups for separate physical trunks. Decimal 227011 and controller string 0227011 are the same device instance.

The card ID identifies the pump in the emulator API. Matching controller IDs is convenient; routing depends on network/MAC. MACs must be unique per adapter; card IDs and device instances must be globally unique. Up to 32 pumps share an adapter, with matching baud, Max Master and router MAC. Max Master includes all pump/router MACs. The router-MAC field validates settings; it does not configure the physical router.

## Card behavior

- Edit identity, serial settings and starting values, then Save Pump Config. Stop the adapter group before changing its devices or starting settings. Unrelated module config updates keep pumps running.
- Start/Stop Adapter Group affects every pump sharing that adapter. BACnet operating-mode Stop affects only pump operation; the device remains online. Running on the card means the engine initialized, not that the controller connection has been verified.
- Enable BusControl for remote commands. If controller startup-only bus control ran before the emulator started, enable bus control again, restart the controller afterward, or use its existing `PUMP_BUS_CONTROL_MODE=each_write` setting.
- BO0, MSO0, MSO1, AO0 and AO5 are editable on the card and writable by src. Both use priority 1; the latest write wins. Release relinquishes that priority slot, including a value last written by the controller.
- Inputs remain read-only over BACnet. The private web pipe edits simulated faults, warnings, temperatures, counters and CIM status. Direct overrides for capacity, pressure, flow, relative performance, current, power and specific energy remain fixed until Release/restart, even across Stop/fault changes. A successful AO5 write also clears the flow override to restore command confirmation.
- Command feedback BI0/BI31, MSI0/MSI1 and AI9/AI58 stays derived from commands. Local controls apply while BusControl is Local; nominal readings scale with the original simple pump model unless an AO5 command or measurement override controls the reported flow.
- Live edits do not overwrite saved startup settings. Restart restores starting values, clears overrides/output priority arrays and resets counter increments. Stopped/stale snapshots are labelled and live editing is disabled.

## Compatibility with the unchanged controller

Do not change or redeploy controller source for this integration. Compatibility is implemented only inside `full-stack-emulator`:

| Original controller behavior | Emulator behavior |
| --- | --- |
| BO0 confirms through BI31, labelled PowerLimit in src | BI31 mirrors BusControl, just like BI0. It is not an independently editable power-limit status in this profile. |
| AO5 confirms by reading AI5, multiplying by 4.4 and comparing to the command | AO5 uses the controller-facing GPM command. While bus control is enabled and any AO5 priority slot is occupied, AI5 reports the effective AO5 value divided by 4.4, including while stopped/faulted. |
| MSO0/MSO1 and AO0 use applied feedback | MSI0/MSI1 and AI9/AI58 continue to follow the active bus/local controls. |

The AO5 behavior is a controller compatibility echo, not physical measured flow or a manual-accurate m³/h flow limit. Releasing all AO5 priority slots restores simulated flow. A manually injected AI5 value temporarily overrides that echo; the next successful AO5 write clears the injection. The cards label these semantics explicitly.

The original src rounds converted Flow to two decimals and compares it exactly against the requested AO5 value. Use ordinary pump-range commands with at most two decimal places; arbitrary precision cannot pass that unchanged comparison. The emulator cannot change this client-side limitation.

The original 20-field read list, RPM batches of five and sequential fallback are retained. Pressure bar ×14.5 -> PSI and AI5 m³/h ×4.4 -> GPM remain unchanged. The controller's manual single-point validator still excludes AI3 and BI0; full-pump reads include AI3, and BO0 confirmation uses BI31 as originally implemented.

## Acceptance checks for you to run

1. Start one matched pump and read it from src. Confirm all 20 fields and native/display unit conversions.
2. Enable bus control, start, change control mode and setpoint. Check BO0/BI31, MSO0/MSI0, MSO1/MSI1 and AO0/AI9/AI58 using the unchanged controller.
3. Write AO5 (for example 12.34). Confirm the original controller reads AI5 as 12.34 GPM, including while stopped. Release all AO5 priorities and confirm stopped simulated flow returns to zero.
4. Edit a card command, then overwrite it from src. Verify the next controller value appears on the card. Check local/bus behavior and priority release.
5. Inject/clear a fault, change a temperature, and apply/release a flow override. Verify src reads the changes and BACnet writes to inputs are rejected.
6. Add a second pump on the same adapter; verify independent device state and group stop/restart behavior.
7. Verify invalid/occupied serial errors, active-group configuration rejection, saved startup restoration, and adapter release at backend shutdown.
