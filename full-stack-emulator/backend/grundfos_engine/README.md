# Bundled Grundfos MS/TP engine

Adapted from `TestModule/Grundfos Pump/BACNet MSTP V2/emulator`. The original TestModule files are unchanged. The desktop GUI is not included in this copy.

See [GRUNDFOS_SETUP.md](../../GRUNDFOS_SETUP.md) for architecture, controller compatibility, build commands and checks to run. This integration has not been built or runtime-tested.

On the emulator Pi, run `python3 build.py`. It fetches missing pinned BACnet Stack source, builds the executables and runs their checks. Preserve dependency license files. The new worker reports `mstp-worker-web-3`; older workers are rejected.

The backend launches `run_group.py --interactive` with temporary configuration derived from `backend/emulator_config.json`. The local `config.json` is only a standalone sample. One `mstp_bus` owns each adapter and one `pump_worker` owns each pump's BACnet objects.

Web extensions add full OBJECTS/SIMULATION/OVERRIDES snapshots, priority-1 output commands/relinquishment, and private measurement injection. BACnet inputs remain read-only. For the unchanged controller src, BI31 mirrors BO0 and active bus AO5 commands echo through AI5 after the controller's GPM conversion. See the setup guide for the explicit compatibility semantics and precision limitation.

The standalone scripts remain available for diagnosis. Do not launch them on an adapter already owned by the web module.
