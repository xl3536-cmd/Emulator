from src.managers.emulator_manager import emulator_manager
from src.models.config import EmulatorConfig
from src.models.valves import ValveConfig


class ConfigService:
    def get_config(self) -> EmulatorConfig:
        return emulator_manager.config

    def update_config(self, config: EmulatorConfig) -> EmulatorConfig:
        valve_config = config.valves
        if not isinstance(valve_config, ValveConfig):
            valve_config = ValveConfig.model_validate(valve_config)
            config.valves = valve_config
        valve_config.validate_runtime_constraints()
        return emulator_manager.refresh_config(config)


config_service = ConfigService()
