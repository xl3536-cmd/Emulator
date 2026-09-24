import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils.logging import get_logger

logger = get_logger(__name__)


class RuntimeStore:
    def __init__(self, runtime_path: Optional[Path] = None):
        backend_root = Path(__file__).resolve().parents[2]
        self.runtime_path = runtime_path or backend_root / "emulator_runtime.json"

    def load(self) -> Dict[str, Any]:
        if not self.runtime_path.exists():
            return {}

        try:
            with self.runtime_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
                return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Failed to load runtime state from %s: %s", self.runtime_path, exc)
            return {}

    def save(self, data: Dict[str, Any]) -> None:
        try:
            self.runtime_path.parent.mkdir(parents=True, exist_ok=True)
            with self.runtime_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
        except Exception as exc:
            logger.warning("Failed to save runtime state to %s: %s", self.runtime_path, exc)


runtime_store = RuntimeStore()
