"""Validate adapter groups without opening any hardware."""
import copy
from pathlib import Path

from run import number, prepare

MAX_GROUP_DEVICES = 32
GROUP_SETTINGS = ("baud", "max_master", "router_mac")


def adapter_key(config):
    # Resolve /dev/serial/by-id symlinks so aliases cannot bypass the port lock.
    return str(Path(config["serial_port"]).expanduser().resolve())


def device_config(config):
    cfg = copy.deepcopy(config)
    # The user's BASrouter status page shows MAC 40. Editable for other trunks.
    cfg.setdefault("router_mac", 40)
    prepare(cfg)
    cfg["pump"]["id"] = number(cfg["pump"]["id"], "profile ID", 1, 1000000, True)
    # prepare() accepts integral JSON floats; normalize them before forming
    # integer-only hub arguments and per-pump control prefixes.
    for field in ("mac", "device_id"):
        cfg["pump"][field] = int(cfg["pump"][field])
    for field in ("baud", "max_master", "max_info_frames"):
        cfg[field] = int(cfg[field])
    router = cfg["router_mac"] = number(cfg["router_mac"], "BASrouter MAC", 0, 127, True)
    if cfg["pump"]["mac"] == router:
        raise ValueError("Pump MAC conflicts with the BASrouter MAC")
    if cfg["max_master"] < router:
        raise ValueError("Max Master must include the BASrouter MAC")
    return cfg


def validate_devices(configs):
    """Return canonical adapter path -> independent device configurations."""
    groups, ids, instances = {}, set(), set()
    for raw in configs:
        cfg = device_config(raw)
        pid, instance = cfg["pump"]["id"], cfg["pump"]["device_id"]
        if pid in ids or instance in instances:
            raise ValueError("Profile IDs and BACnet device IDs must be unique across all adapters")
        ids.add(pid)
        instances.add(instance)
        port = adapter_key(cfg)
        group = groups.setdefault(port, [])
        if group:
            for field in GROUP_SETTINGS:
                if cfg[field] != group[0][field]:
                    raise ValueError(f"All pumps on {port} must use the same {field}")
            if any(p["pump"]["mac"] == cfg["pump"]["mac"] for p in group):
                raise ValueError(f"Duplicate pump MAC {cfg['pump']['mac']} on {port}")
        group.append(cfg)
        if len(group) > MAX_GROUP_DEVICES:
            raise ValueError(f"At most {MAX_GROUP_DEVICES} pump stations per adapter")
    return groups
