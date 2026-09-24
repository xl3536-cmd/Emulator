from typing import Dict, Optional, Tuple

from src.utils.logging import get_logger

logger = get_logger(__name__)

try:
    import SM16uout  # type: ignore
except Exception:  # pragma: no cover
    SM16uout = None


class LeakSensorHardwareAdapter:
    def __init__(self, i2c_bus: int = 1):
        self.i2c_bus = i2c_bus
        self.available = SM16uout is not None
        self.output_boards: Dict[int, object] = {}
        self.stack_errors: Dict[int, str] = {}

    def apply_config(self, sensors) -> None:
        required_stacks = {int(sensor.output_channel.stack) for sensor in sensors if int(sensor.output_channel.channel) > 0}
        self.stack_errors = {}

        for stack in list(self.output_boards):
            if stack not in required_stacks:
                self.output_boards.pop(stack, None)

        if not self.available:
            for stack in required_stacks:
                self.stack_errors[stack] = "Analog output library unavailable"
            return

        for stack in required_stacks:
            if stack in self.output_boards:
                continue
            try:
                self.output_boards[stack] = SM16uout.SM16uout(stack=stack, i2c=self.i2c_bus)
            except Exception as exc:
                self.stack_errors[stack] = str(exc)
                logger.warning("Leak sensor VOUT stack %s unavailable: %s", stack, exc)

    def has_output(self, stack: int) -> bool:
        return stack in self.output_boards

    def get_output_error(self, stack: int) -> Optional[str]:
        return self.stack_errors.get(stack)

    def write_output(self, stack: int, channel: int, voltage: float) -> Tuple[bool, Optional[str]]:
        if stack not in self.output_boards:
            return False, self.stack_errors.get(stack, "Analog output board unavailable")
        try:
            self.output_boards[stack].set_u_out(channel, float(voltage))
            return True, None
        except Exception as exc:
            logger.warning("Failed to write leak sensor VOUT stack=%s channel=%s: %s", stack, channel, exc)
            return False, str(exc)
