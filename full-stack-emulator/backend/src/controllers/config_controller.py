from src.models.config import EmulatorConfig
from src.services.config_service import config_service


class ConfigController:
    def get_config(self) -> EmulatorConfig:
        return config_service.get_config()

    def update_config(self, config: EmulatorConfig) -> EmulatorConfig:
        return config_service.update_config(config)


config_controller = ConfigController()
