import asyncio
import threading
from typing import Dict, List, Optional

from src.models.state import ArcticDeviceState, ArcticRegisterState, ArcticServerState
from src.sensors.arctic_hp.register_map import BITFIELDS, DEFAULT_VALUES, REGS
from src.utils.logging import get_logger

logger = get_logger(__name__)

REGISTER_ALIASES = {
    2117: (2118,),
    2118: (2117,),
}

try:
    from pymodbus.datastore import ModbusDeviceContext, ModbusSequentialDataBlock, ModbusServerContext  # type: ignore
    from pymodbus.framer import FramerType  # type: ignore
    from pymodbus.server import ModbusSerialServer  # type: ignore
except Exception:  # pragma: no cover
    ModbusDeviceContext = None
    ModbusSequentialDataBlock = None
    ModbusServerContext = None
    ModbusSerialServer = None
    FramerType = None


def to_raw(value: float, signed: bool, scale: float) -> int:
    try:
        raw = int(round(value / scale))
    except Exception:
        raw = 0
    return raw & 0xFFFF


def from_raw(raw: int, signed: bool, scale: float) -> float:
    raw16 = raw & 0xFFFF
    if signed and raw16 >= 0x8000:
        raw16 -= 0x10000
    return raw16 * scale


def format_bitfield(raw: int, bit_map: Dict[int, str]) -> str:
    raw16 = raw & 0xFFFF
    bits = format(raw16, "016b")
    lines = [f"RAW: {raw16}", f"HEX: 0x{raw16:04X}", f"BIN: {bits[0:4]} {bits[4:8]} {bits[8:12]} {bits[12:16]}", ""]
    enabled = [f"Bit{bit}: {bit_map.get(bit, 'Reserved/Undefined')}" for bit in range(16) if (raw16 >> bit) & 1]
    lines.extend(enabled or ["ON bits: (none)"])
    return "\n".join(lines)


class DeviceEmulator:
    def __init__(self, device_id: int, unit_id: int, name: str, display_side: str, esp32_ip: str):
        self.device_id = device_id
        self.unit_id = unit_id
        self.name = name
        self.display_side = display_side
        self.esp32_ip = esp32_ip
        self.reg_defs = {reg.address: reg for reg in REGS}

        max_addr = max(self.reg_defs)
        self.lock = threading.Lock()
        self.raw_values = {addr: 0 for addr in self.reg_defs}
        self.datablock = ModbusSequentialDataBlock(0, [0] * (max_addr + 2)) if ModbusSequentialDataBlock else None
        self.reset_defaults()

    def apply_metadata(self, unit_id: int, name: str, display_side: str, esp32_ip: str) -> None:
        self.unit_id = unit_id
        self.name = name
        self.display_side = display_side
        self.esp32_ip = esp32_ip

    def _write_datablock(self, addr: int, raw: int) -> None:
        if self.datablock is not None:
            self.datablock.setValues(addr + 1, [raw & 0xFFFF])

    def _sync_aliases(self, addr: int, raw: int) -> None:
        for alias_addr in REGISTER_ALIASES.get(addr, ()):
            if alias_addr not in self.reg_defs:
                continue
            self.raw_values[alias_addr] = raw
            self._write_datablock(alias_addr, raw)

    def reset_defaults(self) -> None:
        for addr, value in DEFAULT_VALUES.items():
            self.set_display_value(addr, float(value))

    def set_raw(self, addr: int, raw_u16: int) -> None:
        if addr not in self.reg_defs:
            return
        raw = raw_u16 & 0xFFFF
        with self.lock:
            self.raw_values[addr] = raw
            self._write_datablock(addr, raw)
            self._sync_aliases(addr, raw)

    def set_display_value(self, addr: int, value: float) -> None:
        reg = self.reg_defs.get(addr)
        if not reg:
            return
        raw = to_raw(value, reg.signed, reg.scale)
        self.set_raw(addr, raw)

    def set_manual_value(self, addr: int, value: float) -> bool:
        reg = self.reg_defs.get(addr)
        if not reg or not reg.manual_editable:
            return False
        self.set_display_value(addr, value)
        return True

    def get_raw(self, addr: int) -> int:
        with self.lock:
            if self.datablock is not None:
                raw = self.datablock.getValues(addr + 1, 1)[0] & 0xFFFF
                self.raw_values[addr] = raw
                self._sync_aliases(addr, raw)
                return raw
            return self.raw_values.get(addr, 0) & 0xFFFF

    def get_display_value(self, addr: int) -> float:
        reg = self.reg_defs.get(addr)
        if not reg:
            return 0.0
        return from_raw(self.get_raw(addr), reg.signed, reg.scale)

    def decode_bitfield(self, addr: int) -> Optional[str]:
        bitfield = BITFIELDS.get(addr)
        if not bitfield:
            return None
        return format_bitfield(self.get_raw(addr), bitfield[1])

    def snapshot(self) -> ArcticDeviceState:
        registers: List[ArcticRegisterState] = []
        for addr, reg in sorted(self.reg_defs.items()):
            registers.append(
                ArcticRegisterState(
                    address=addr,
                    name=reg.name,
                    value=self.get_display_value(addr),
                    raw=self.get_raw(addr),
                    unit=reg.unit,
                    note=reg.note,
                    signed=reg.signed,
                    scale=reg.scale,
                    access=reg.access,
                    manual_editable=reg.manual_editable,
                    bitfield_text=self.decode_bitfield(addr),
                )
            )
        return ArcticDeviceState(
            device_id=self.device_id,
            unit_id=self.unit_id,
            name=self.name,
            display_side=self.display_side,
            esp32_ip=self.esp32_ip,
            registers=registers,
        )


class ArcticServerRunner:
    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.server = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.last_error: Optional[str] = None

    @property
    def transport_available(self) -> bool:
        return ModbusSerialServer is not None and ModbusDeviceContext is not None and ModbusServerContext is not None and FramerType is not None

    def _build_context(self, devices: List[DeviceEmulator]):
        devmap = {}
        for device in devices:
            if device.datablock is not None:
                devmap[device.unit_id] = ModbusDeviceContext(hr=device.datablock)
        return ModbusServerContext(devices=devmap, single=False)

    def start(self, devices: List[DeviceEmulator], port_config) -> None:
        if self.running or not self.transport_available:
            if not self.transport_available:
                self.last_error = "pymodbus transport is unavailable"
            return

        context = self._build_context(devices)
        self.last_error = None

        def runner():
            try:
                self.loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self.loop)

                async def main_async():
                    self.server = ModbusSerialServer(
                        context,
                        framer=FramerType.RTU,
                        port=port_config.serial_file,
                        baudrate=port_config.baudrate,
                        bytesize=port_config.bytesize,
                        parity=port_config.parity,
                        stopbits=port_config.stopbits,
                        timeout=port_config.timeout,
                    )
                    self.running = True
                    await self.server.serve_forever()

                self.loop.run_until_complete(main_async())
            except Exception as exc:
                self.last_error = str(exc)
                logger.warning("Arctic serial server failed: %s", exc)
            finally:
                self.running = False
                if self.loop is not None:
                    try:
                        self.loop.stop()
                        self.loop.close()
                    except Exception:
                        pass
                self.loop = None
                self.server = None

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.loop or not self.server:
            self.running = False
            return

        async def shutdown():
            try:
                await self.server.shutdown()
            except Exception:
                pass

        try:
            future = asyncio.run_coroutine_threadsafe(shutdown(), self.loop)
            future.result(timeout=2.0)
        except Exception:
            pass

        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass

        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None

    def snapshot(self, port_config) -> ArcticServerState:
        if self.running:
            message = "Modbus RTU server running"
        elif self.transport_available:
            message = self.last_error or "Server stopped"
        else:
            message = "pymodbus not installed - emulator stays in offline edit mode"
        return ArcticServerState(
            running=self.running,
            transport_available=self.transport_available,
            port=port_config.serial_file,
            baudrate=port_config.baudrate,
            message=message,
        )
