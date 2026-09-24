from typing import Dict, List, Optional, Tuple

from src.models.valves import DetectorState, RelayDetectorConfig
from src.utils.logging import get_logger

logger = get_logger(__name__)
SMBUS_BACKEND = None

try:
    from smbus2 import SMBus  # type: ignore
    SMBUS_BACKEND = "smbus2"
except Exception:  # pragma: no cover
    try:
        from smbus import SMBus  # type: ignore
        SMBUS_BACKEND = "smbus"
    except Exception:  # pragma: no cover
        SMBus = None

try:
    import SM16relind  # type: ignore
except Exception:  # pragma: no cover
    SM16relind = None


IODIRA = 0x00
IODIRB = 0x01
GPPUA = 0x0C
GPPUB = 0x0D
GPIOA = 0x12
GPIOB = 0x13


class BallValveRelayHardwareAdapter:
    def __init__(self, relay_detectors: Optional[List[RelayDetectorConfig]] = None, relay_output_i2c_bus: int = 1):
        self.detector_configs: Dict[int, RelayDetectorConfig] = {}
        self.implicit_detector_configs: Dict[int, RelayDetectorConfig] = {}
        self.detector_buses: Dict[int, SMBus] = {}
        self.detector_initialized: set[Tuple[int, int]] = set()
        self.detector_last_words: Dict[int, int] = {}
        self.detector_errors: Dict[int, str] = {}
        self.detector_available: Dict[int, bool] = {}
        self.relay_output_i2c_bus = relay_output_i2c_bus
        self.relay_boards: Dict[int, object] = {}
        self.relay_board_errors: Dict[int, str] = {}
        self.relay_states: Dict[Tuple[int, int], bool] = {}
        self.apply_config(relay_detectors or [], relay_output_i2c_bus)

    def apply_config(self, relay_detectors: List[RelayDetectorConfig], relay_output_i2c_bus: int) -> None:
        self.detector_configs = {item.i2c_address: item for item in relay_detectors}
        self.implicit_detector_configs = {}
        self.relay_output_i2c_bus = relay_output_i2c_bus
        configured_addresses = set(self.detector_configs)
        self.detector_last_words = {address: word for address, word in self.detector_last_words.items() if address in configured_addresses}
        self.detector_errors = {address: error for address, error in self.detector_errors.items() if address in configured_addresses}
        self.detector_available = {address: available for address, available in self.detector_available.items() if address in configured_addresses}

    def _resolve_detector_config(self, i2c_address: Optional[int]) -> Optional[RelayDetectorConfig]:
        if i2c_address is None:
            return None
        config = self.detector_configs.get(i2c_address)
        if config is not None:
            return config
        if i2c_address not in self.implicit_detector_configs:
            self.implicit_detector_configs[i2c_address] = RelayDetectorConfig(
                i2c_address=i2c_address,
                i2c_bus=1,
                active_low=False,
                use_internal_pullups=False,
                enabled=True,
            )
        return self.implicit_detector_configs[i2c_address]

    def _get_bus(self, i2c_bus: int):
        if SMBus is None:
            return None
        if i2c_bus not in self.detector_buses:
            self.detector_buses[i2c_bus] = SMBus(i2c_bus)
        return self.detector_buses[i2c_bus]

    def _init_detector(self, config: RelayDetectorConfig) -> bool:
        if SMBus is None:
            self.detector_errors[config.i2c_address] = "SMBus library not available"
            self.detector_available[config.i2c_address] = False
            return False
        key = (config.i2c_bus, config.i2c_address)
        if key in self.detector_initialized:
            return True
        bus = self._get_bus(config.i2c_bus)
        if bus is None:
            self.detector_errors[config.i2c_address] = f"I2C bus {config.i2c_bus} unavailable"
            self.detector_available[config.i2c_address] = False
            return False
        try:
            bus.write_byte_data(config.i2c_address, IODIRA, 0xFF)
            bus.write_byte_data(config.i2c_address, IODIRB, 0xFF)
            pullup_value = 0xFF if config.use_internal_pullups else 0x00
            bus.write_byte_data(config.i2c_address, GPPUA, pullup_value)
            bus.write_byte_data(config.i2c_address, GPPUB, pullup_value)
            self.detector_initialized.add(key)
            self.detector_errors.pop(config.i2c_address, None)
            self.detector_available[config.i2c_address] = True
            return True
        except Exception as exc:
            self.detector_errors[config.i2c_address] = str(exc)
            self.detector_available[config.i2c_address] = False
            logger.warning("Failed to initialize relay detector addr=%s: %s", hex(config.i2c_address), exc)
            return False

    def _read_word(self, config: RelayDetectorConfig) -> Optional[int]:
        if not config.enabled:
            self.detector_errors[config.i2c_address] = "Detector disabled"
            self.detector_available[config.i2c_address] = False
            return None
        if not self._init_detector(config):
            return None
        bus = self._get_bus(config.i2c_bus)
        if bus is None:
            self.detector_errors[config.i2c_address] = f"I2C bus {config.i2c_bus} unavailable"
            self.detector_available[config.i2c_address] = False
            return None
        try:
            gpio_a = bus.read_byte_data(config.i2c_address, GPIOA)
            gpio_b = bus.read_byte_data(config.i2c_address, GPIOB)
            word = gpio_a | (gpio_b << 8)
            self.detector_last_words[config.i2c_address] = word
            self.detector_errors.pop(config.i2c_address, None)
            self.detector_available[config.i2c_address] = True
            return word
        except Exception as exc:
            self.detector_errors[config.i2c_address] = str(exc)
            self.detector_available[config.i2c_address] = False
            logger.warning("Failed to read relay detector addr=%s: %s", hex(config.i2c_address), exc)
            return None

    def read_detector_channel(self, i2c_address: Optional[int], channel: int) -> Optional[bool]:
        config = self._resolve_detector_config(i2c_address)
        if config is None:
            return None
        word = self._read_word(config)
        if word is None:
            return None
        raw = (word >> (channel - 1)) & 1
        state = (1 - raw) if config.active_low else raw
        return bool(state)

    def has_detector(self, i2c_address: Optional[int]) -> bool:
        config = self._resolve_detector_config(i2c_address)
        if config is None:
            return False
        if not config.enabled:
            return False
        if i2c_address not in self.detector_available:
            self._read_word(config)
        return self.detector_available.get(i2c_address, False)

    def get_detector_error(self, i2c_address: Optional[int]) -> Optional[str]:
        if i2c_address is None:
            return "Relay detector address not configured"
        return self.detector_errors.get(i2c_address)

    def _get_relay_board(self, stack: int):
        if SM16relind is None:
            self.relay_board_errors[stack] = "SM16relind not available"
            return None
        if stack not in self.relay_boards:
            try:
                self.relay_boards[stack] = SM16relind.SM16relind(stack=stack, i2c=self.relay_output_i2c_bus)
                self.relay_board_errors.pop(stack, None)
            except Exception as exc:
                self.relay_board_errors[stack] = str(exc)
                logger.warning("Failed to initialize relay feedback stack=%s: %s", stack, exc)
                return None
        return self.relay_boards.get(stack)

    def has_feedback_stack(self, stack: int) -> bool:
        return self._get_relay_board(stack) is not None

    def get_feedback_stack_error(self, stack: int) -> Optional[str]:
        if stack not in self.relay_boards and stack not in self.relay_board_errors:
            self._get_relay_board(stack)
        return self.relay_board_errors.get(stack)

    def write_feedback_relay(self, stack: int, channel: int, state: bool) -> bool:
        board = self._get_relay_board(stack)
        if board is None:
            return False
        key = (stack, channel)
        try:
            board.set(channel, 1 if state else 0)
            self.relay_states[key] = bool(state)
            return True
        except Exception as exc:
            self.relay_board_errors[stack] = str(exc)
            logger.warning("Failed to write relay feedback stack=%s channel=%s: %s", stack, channel, exc)
            return False

    def snapshot_detectors(self) -> List[DetectorState]:
        items: List[DetectorState] = []
        all_configs = {**self.implicit_detector_configs, **self.detector_configs}
        for i2c_address, config in sorted(all_configs.items()):
            items.append(
                DetectorState(
                    i2c_address=config.i2c_address,
                    i2c_bus=config.i2c_bus,
                    active_low=config.active_low,
                    use_internal_pullups=config.use_internal_pullups,
                    enabled=config.enabled,
                    available=self.detector_available.get(i2c_address, False),
                    last_word=self.detector_last_words.get(i2c_address),
                    error=self.detector_errors.get(i2c_address),
                )
            )
        return items

    def cleanup(self) -> None:
        for (stack, channel), is_on in list(self.relay_states.items()):
            if is_on:
                self.write_feedback_relay(stack, channel, False)
        for bus in self.detector_buses.values():
            try:
                bus.close()
            except Exception:
                pass
        self.detector_buses.clear()
