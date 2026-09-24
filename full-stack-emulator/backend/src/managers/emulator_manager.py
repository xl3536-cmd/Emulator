import asyncio

from src.config.store import config_store
from src.config.runtime_store import runtime_store
from src.managers.arctic_hp_manager import ArcticHPManager
from src.managers.rtd_manager import RTDManager
from src.managers.leak_sensor_manager import LeakSensorManager
from src.managers.scheduling_manager import SchedulingManager
from src.managers.valve_manager import ValveManager
from src.models.config import EmulatorConfig
from src.models.emulator import RuntimeSnapshot


class EmulatorManager:
    def __init__(self):
        self.config: EmulatorConfig = config_store.load()
        self.persisted_runtime = runtime_store.load()
        self.rtd_manager = RTDManager(self.config.rtd)
        self.valve_manager = ValveManager(self.config.valves, persisted_state=self.persisted_runtime)
        self.leak_sensor_manager = LeakSensorManager(self.config.leak_sensors)
        self.scheduling_manager = SchedulingManager(self.rtd_manager, self.config.valves)
        self.arctic_hp_manager = ArcticHPManager(self.config.arctic_hp)
        self._task = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.arctic_hp_manager.start_server()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
            self._task = None
        self._save_runtime_if_needed(force=True)
        self.arctic_hp_manager.stop_server()
        self.leak_sensor_manager.cleanup()
        self.valve_manager.cleanup()
        self.rtd_manager.close()

    async def _run_loop(self) -> None:
        while self._running:
            self.valve_manager.tick()
            self._save_runtime_if_needed()
            self.scheduling_manager.tick(realtime_mode=self.valve_manager.is_realtime_mode())
            await asyncio.sleep(0.5)

    def refresh_config(self, new_config: EmulatorConfig) -> EmulatorConfig:
        self.config = config_store.save(new_config)
        self.rtd_manager.apply_config(self.config.rtd)
        self.valve_manager.apply_config(self.config.valves)
        self.leak_sensor_manager.apply_config(self.config.leak_sensors)
        self.scheduling_manager.apply_config(self.config.valves)
        self._save_runtime_if_needed(force=True)
        self.arctic_hp_manager.apply_config(self.config.arctic_hp)
        return self.config

    def get_snapshot(self):
        realtime = self.valve_manager.is_realtime_mode()
        playback_state = self.scheduling_manager.playback_state(realtime)
        snapshot = RuntimeSnapshot(
            rtd=self.rtd_manager.snapshot(
                playback_state=playback_state,
                current_rtd_codes=self.scheduling_manager.current_rtd_codes,
                current_valve_states=self.scheduling_manager.current_valve_states,
            ),
            valves={
                "ball_valves": [item.model_dump() for item in self.valve_manager.snapshot()],
                "relay_detectors": [item.model_dump() for item in self.valve_manager.snapshot_detectors()],
            },
            leak_sensors={
                "sensors": [item.model_dump() for item in self.leak_sensor_manager.snapshot()],
            },
            arctic_hp=self.arctic_hp_manager.snapshot(),
        )
        return snapshot.model_dump()

    def _save_runtime_if_needed(self, force: bool = False) -> None:
        if force or self.valve_manager.consume_persisted_state_dirty():
            self.persisted_runtime = self.valve_manager.export_persisted_state()
            runtime_store.save(self.persisted_runtime)


emulator_manager = EmulatorManager()
