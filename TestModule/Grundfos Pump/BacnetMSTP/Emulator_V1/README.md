# BACnet MS/TP Pump Emulator

## Project Record

- project owner: `Xiaxin Liu`
- last updated: `2026-03-17`

## Hardware Setup

- emulator host: Raspberry Pi
- receiver host: Raspberry Pi
- BACnet router: Contemporary Controls BASrouter
- BASrouter IP: `192.168.68.7`
- BASrouter BACnet/IP network: `5`
- BASrouter MS/TP network: `4004`
- BASrouter MS/TP MAC: `12`
- BASrouter MS/TP baud: `9600`
- Pi serial adapter: USB to RS-485
- observed Linux serial path: `/dev/ttyACM1`
- current emulator test MAC: `14`
- current emulator test device id: `227014`

This project is for your current topology:

- Raspberry Pi emulator
- USB to RS-485 adapter on the Pi
- real BASrouter handling BACnet/IP <-> MS/TP routing
- receiver Pi talking BACnet/IP to the BASrouter

That means this emulator is only the pump device. The BASrouter provides the
routing layer.

## BASrouter Hardware and UI Configuration Guide

https://docs.google.com/document/d/1-cZ38wTf52Rq9n5b9UIuoKpuNzBOLujjxYZWO5k5bE8/edit?tab=t.0

--- Docs provided by Sebastian

## Example Code Defaults

- BASrouter BACnet/IP address: `192.168.68.7`
- BASrouter BACnet/IP network: `5`
- BASrouter MS/TP network: `4004`
- emulator pump MAC: `15`
- emulator pump device id: `227015`
- emulator vendor id: `227`
- serial interface: `/dev/ttyACM0` or `/dev/ttyACM1` depending on enumeration

Expected routed address from the receiver Pi:

```text
4004:15@192.168.68.7
```

## Device profile

The emulator is configured to behave like a Grundfos CIM 300 style MS/TP
device:

- vendor name: `Grundfos`
- vendor id: `227`
- model name: `CIM 300`
- master node on MS/TP
- `Max_Info_Frames = 1`
- `Max_Master = 127`

## Implemented object model

Core CIM/NYSERDA points:

- `binaryOutput,0` bus control
- `binaryOutput,4` reset fault
- `binaryOutput,5` fault simulation
- `multiStateOutput,0` control mode command
- `multiStateOutput,1` operating mode command
- `multiStateInput,0` actual control mode
- `multiStateInput,1` actual operating mode
- `multiStateInput,3` CIM status
- `analogOutput,0` pump setpoint
- `analogValue,1` BACnet watchdog
- `binaryInput,0`, `1`, `2`, `31`, `65`
- `analogInput,0`, `1`, `3`, `4`, `5`, `6`, `7`, `9`, `10`, `13`, `18`,
  `22`, `26`, `27`, `28`, `30`, `57`, `58`, `131`, `132`

Behavior:

- `binaryOutput,0 = 1` enables BUS mode
- `binaryOutput,0 = 0` forces LOCAL mode
- `multiStateOutput,0` updates actual control mode
- `multiStateOutput,1` updates commanded operating mode
- `analogOutput,0` controls the command setpoint (0-100%)
- `analogValue,1` sets the BACnet watchdog (5-3600 s)
- watchdog expiry forces LOCAL mode

## Build on the Pi

Expected layout:

```text
~/Desktop/
  bacnet-stack/
  bacnet_emulator_mstp/
```

Install or prepare `bacnet-stack` first:

```bash
cd ~/Desktop
git clone https://github.com/bacnet-stack/bacnet-stack.git
```

If you already have `bacnet-stack`, keep it beside this project as:

```text
~/Desktop/bacnet-stack
```

Typical Linux build tools you may need:

```bash
sudo apt update
sudo apt install -y build-essential git
```

Build:

```bash
cd ~/Desktop/bacnet_emulator_mstp
make stack-clean
make
```

Use `make stack-clean` first if you previously built any routed/BACnet-IP
experiments in the same `bacnet-stack` tree. Old `BAC_ROUTING` objects will
break this MS/TP emulator link.

## Run on the Pi

Set the MS/TP interface and parameters first:

```bash
export BACNET_IFACE=/dev/ttyACM1
export BACNET_MSTP_MAC=14
export BACNET_MSTP_BAUD=9600
export BACNET_MAX_MASTER=127
export BACNET_MAX_INFO_FRAMES=1
```

Then start the emulator:

```bash
cd ~/Desktop/bacnet_emulator_mstp
./nyserda_bacnet_emulator_mstp \
  --device-id 227014 \
  --vendor-id 227 \
  --name "Grundfos MAGNA3 Emulator"
```

Full example:

```bash
cd ~/Desktop/bacnet_emulator_mstp
export BACNET_IFACE=/dev/ttyACM1
export BACNET_MSTP_MAC=14
export BACNET_MSTP_BAUD=9600
export BACNET_MAX_MASTER=127
export BACNET_MAX_INFO_FRAMES=1
./nyserda_bacnet_emulator_mstp --device-id 227014 --vendor-id 227 --name "Grundfos MAGNA3 Emulator"
```

If the serial device path changes after reboot or reconnect, find the current
adapter name with:

```bash
ls -l /dev/ttyACM* /dev/ttyUSB*
```

Then update `BACNET_IFACE` to the device that actually exists, for example:

```bash
export BACNET_IFACE=/dev/ttyACM0
```

or:

```bash
export BACNET_IFACE=/dev/ttyUSB0
```

## Read from the receiver Pi

Use:

```bash
python3 reader_via_basrouter.py
```

Or:

```bash
 python3 mstp_reader.py --router-ip 192.168.68.7 --mstp-network 4004 --pump-mac 14
```

## NYSERDA scripts

For NYSERDA-style reads, the target shape is:

```text
4004:15@192.168.68.7
```

Because you now have a real BASrouter, the compatibility problem is reduced to
the pump device behavior on MS/TP rather than software router emulation.

## Current Stage

- BASrouter sees the emulator node online on MS/TP
- token passing is active between BASrouter MAC `12` and emulator MAC `13/14`
- the emulator now receives BACnet PDUs from the BASrouter
- remaining work is BACnet object/read compatibility, not basic MS/TP bus presence

## Git Notes

- `.o` files are compiled object files generated during `make`
- they are build artifacts, not source files
- do not commit `.o` files to GitHub
- do not commit built binaries like `nyserda_bacnet_emulator_mstp` unless you intentionally want release artifacts in the repo
