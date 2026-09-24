from typing import List, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)

try:
    import spidev  # type: ignore
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover
    spidev = None
    GPIO = None


LATCH_PIN = 5
SPI_BUS = 0
SPI_DEV = 0
SPI_MAX_HZ = 1_000_000
SPI_MODE = 0
MAX_BOARDS = 200


class ChainDriver:
    def __init__(self, n_boards: int = 1, invert: bool = False, reverse: bool = False):
        self.spi = None
        self.gpio_ready = False
        self.board_bits: List[List[int]] = []
        self.board_widths: List[int] = []
        self.last_frame_bytes: List[int] = []
        self.hardware_error: Optional[str] = None
        self.n_boards = 1
        self.invert_bits = bool(invert)
        self.reverse_order = bool(reverse)
        self.hardware_available = spidev is not None and GPIO is not None

        if self.hardware_available:
            try:
                self.spi = spidev.SpiDev()
                self.spi.open(SPI_BUS, SPI_DEV)
                self.spi.max_speed_hz = SPI_MAX_HZ
                self.spi.mode = SPI_MODE
                GPIO.setwarnings(False)
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(LATCH_PIN, GPIO.OUT, initial=GPIO.LOW)
                self.gpio_ready = True
                self.hardware_error = None
            except Exception as exc:
                logger.warning("RTD hardware chain unavailable: %s", exc)
                self.spi = None
                self.gpio_ready = False
                self.hardware_available = False
                self.hardware_error = str(exc)

        self.configure(n_boards, invert, reverse)

    def close(self) -> None:
        try:
            if self.spi is not None:
                self.spi.close()
        finally:
            if self.gpio_ready and GPIO is not None:
                try:
                    GPIO.cleanup(LATCH_PIN)
                except Exception:
                    pass

    def _normalize_width(self, width: int) -> int:
        return 8 if int(width) == 8 else 5

    def _mask_for_board(self, board_index: int) -> int:
        return 0xFF if self.board_width(board_index) == 8 else 0x1F

    def _coerce_bits(self, bits: List[int], board_index: int) -> List[int]:
        width = self.board_width(board_index)
        return [(1 if index < len(bits) and bits[index] else 0) for index in range(width)]

    def board_width(self, board_index: int) -> int:
        if 0 <= board_index < len(self.board_widths):
            return self.board_widths[board_index]
        return 5

    def configure(self, n_boards: int, invert: bool, reverse: bool, board_widths: Optional[List[int]] = None) -> None:
        new_count = max(1, min(int(n_boards), MAX_BOARDS))
        self.invert_bits = bool(invert)
        self.reverse_order = bool(reverse)
        previous = self.board_bits[:]
        previous_widths = self.board_widths[:]
        requested_widths = board_widths or []
        self.board_bits = []
        self.board_widths = []
        for index in range(new_count):
            width = self._normalize_width(requested_widths[index] if index < len(requested_widths) else (previous_widths[index] if index < len(previous_widths) else 5))
            self.board_widths.append(width)
            if index < len(previous):
                bits = (previous[index] + [0] * width)[:width]
            else:
                bits = [0] * width
            self.board_bits.append([1 if bit else 0 for bit in bits])
        self.n_boards = new_count
        self.transmit_frame([self._calc_code(index, bits) for index, bits in enumerate(self.board_bits)])

    def _calc_code(self, board_index: int, bits: List[int]) -> int:
        code = 0
        for bit_index in range(self.board_width(board_index)):
            if bit_index < len(bits) and bits[bit_index]:
                code |= 1 << bit_index
        if self.invert_bits:
            code ^= self._mask_for_board(board_index)
        return code & self._mask_for_board(board_index)

    def _decode_code(self, board_index: int, code: int, apply_inversion: bool = False) -> List[int]:
        width = self.board_width(board_index)
        mask = self._mask_for_board(board_index)
        if apply_inversion and self.invert_bits:
            code ^= mask
        code &= mask
        return [(code >> bit_index) & 1 for bit_index in range(width)]

    def _push_frame(self, frame: List[int]) -> None:
        if self.reverse_order:
            frame = list(reversed(frame))
        self.last_frame_bytes = frame[:]
        if self.spi is not None:
            try:
                self.spi.xfer2(frame)
                if GPIO is not None and self.gpio_ready:
                    GPIO.output(LATCH_PIN, 1)
                    GPIO.output(LATCH_PIN, 0)
                self.hardware_available = True
                self.hardware_error = None
            except Exception as exc:
                logger.warning("RTD frame push failed: %s", exc)
                self.hardware_available = False
                self.hardware_error = str(exc)

    def transmit_frame(self, frame: List[int]) -> None:
        payload = [(int(value) & 0xFF) for value in frame[: self.n_boards]]
        if len(payload) < self.n_boards:
            payload.extend([0] * (self.n_boards - len(payload)))
        self._push_frame(payload)

    def push_all(self) -> None:
        self.transmit_frame([self._calc_code(index, bits) for index, bits in enumerate(self.board_bits)])

    def encode_board(self, board_index: int) -> int:
        if 0 <= board_index < self.n_boards:
            return self._calc_code(board_index, self.board_bits[board_index])
        return 0

    def set_board_bits(self, board_index: int, bits: List[int]) -> None:
        if 0 <= board_index < self.n_boards:
            self.board_bits[board_index] = self._coerce_bits(bits, board_index)

    def set_board_code(self, board_index: int, code: int, apply_inversion: bool = False) -> None:
        if 0 <= board_index < self.n_boards:
            self.board_bits[board_index] = self._decode_code(board_index, code, apply_inversion=apply_inversion)

    def clear_board_codes(self) -> None:
        for index in range(self.n_boards):
            self.board_bits[index] = [0] * self.board_width(index)

    def get_frame_bytes(self) -> List[int]:
        return self.last_frame_bytes[:]
