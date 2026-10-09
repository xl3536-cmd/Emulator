# Adapter groups

Configure groups using the Grundfos Pumps page. Pumps sharing the same canonical serial path start and stop together. Each group supports up to 32 independent pump stations, unique MACs, and shared baud/Max Master/router MAC. Card IDs and device instances must be unique across groups.

Stop a group before editing its saved configuration. A controller operating-mode Stop stops one pump's operation while keeping that device online. Controller communication remains BACnet through the real BASrouter; web pipes only carry private emulator edits and snapshots.

See [the setup guide](../../GRUNDFOS_SETUP.md) for the controller topology, lifecycle and acceptance checks.
