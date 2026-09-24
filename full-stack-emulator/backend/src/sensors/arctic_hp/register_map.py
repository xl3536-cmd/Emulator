from dataclasses import dataclass
from typing import Dict, List


READ_ONLY = "read_only"
WRITABLE = "writable"
TEMP_UNIT = "\u00B0C"


@dataclass(frozen=True)
class RegisterDef:
    address: int
    name: str
    note: str
    signed: bool
    unit: str
    scale: float
    access: str = READ_ONLY

    @property
    def writable(self) -> bool:
        return self.access == WRITABLE

    @property
    def manual_editable(self) -> bool:
        return not self.writable


REGS: List[RegisterDef] = [
    RegisterDef(2000, "Unit ON/OFF", "0=OFF, 1=ON", False, "", 1.0, WRITABLE),
    RegisterDef(2001, "Working mode", "0=Cooling,1=Underfloor heat,2=Fan coil heat,5=Hot water,6=Auto", False, "", 1.0, WRITABLE),
    RegisterDef(2002, "Cooling temp setpoint", "model dependent", False, TEMP_UNIT, 1.0, WRITABLE),
    RegisterDef(2003, "Heating temp setpoint", "model dependent", False, TEMP_UNIT, 1.0, WRITABLE),
    RegisterDef(2004, "Hot water temp setpoint", "model dependent", False, TEMP_UNIT, 1.0, WRITABLE),
    RegisterDef(2052, "Pump behavior after reaching setpoint", "0=cycle using 2053, 1=keep OFF, 2=keep ON", False, "", 1.0, WRITABLE),
    RegisterDef(2053, "Water pump running interval", "see manual", False, "", 1.0, WRITABLE),
    RegisterDef(2054, "Low ambient temp to run pump in standby", "see manual", True, TEMP_UNIT, 1.0, WRITABLE),
    RegisterDef(2056, "Accept compressor freq control", "0=NO, 1=YES", False, "", 1.0, WRITABLE),
    RegisterDef(2057, "Compressor freq setting value", "Hz", False, "Hz", 1.0, WRITABLE),
    RegisterDef(2100, "Water tank temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2102, "Outlet water temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2103, "Inlet water temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2104, "Discharge temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2105, "Suction temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2107, "External coil temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2108, "Cooling coil temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2110, "Outdoor ambient temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2115, "Brine inlet water temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2116, "Brine outlet water temperature", "", True, TEMP_UNIT, 1.0),
    RegisterDef(2117, "Compressor running frequency", "legacy alias for older Arctic script compatibility", False, "Hz", 1.0),
    RegisterDef(2118, "Compressor operating frequency", "NYSERDA controller reads this register", True, "Hz", 1.0),
    RegisterDef(2119, "Fan motor speed", "NYSERDA controller reads this register", False, "rpm", 1.0),
    RegisterDef(2120, "AC supply/drive voltage", "", False, "V", 1.0),
    RegisterDef(2121, "AC current", "", False, "A", 1.0),
    RegisterDef(2122, "DC voltage", "", False, "V", 1.0),
    RegisterDef(2123, "DC current", "", False, "A", 1.0),
    RegisterDef(2133, "System working status bits", "bitfield", False, "", 1.0),
    RegisterDef(2134, "Error code bits", "bitfield", False, "", 1.0),
    RegisterDef(2135, "Status register 1", "bitfield", False, "", 1.0),
    RegisterDef(2136, "Status register 2", "bitfield; bit5=defrost", False, "", 1.0),
    RegisterDef(2138, "Status register 4 (protections)", "bitfield", False, "", 1.0),
]


BITFIELDS: Dict[int, tuple[str, Dict[int, str]]] = {
    2133: ("2133 System working status bits", {
        0: "Frequency reaches upper limit",
        1: "Frequency reaches lower limit",
    }),
    2134: ("2134 Error code bits", {
        0: "Brine inlet temp sensor error",
        1: "Brine outlet temp sensor error",
        2: "Brine flow protection",
        3: "Water tank temp sensor error",
    }),
    2135: ("2135 Status register 1 bits", {
        0: "Unit ON/OFF status",
        1: "Compressor status (manual/document bit)",
        2: "Compressor status (NYSERDA backend decode bit)",
        3: "Medium wind speed",
        4: "Low wind speed",
        5: "Water pump",
        6: "4-way valve",
        7: "Electric heater",
        8: "Water flow switch",
        9: "High pressure switch",
        10: "Low pressure switch",
        11: "Remote ON/OFF switch",
        12: "Mode switch",
        13: "3-way valve1",
        14: "3-way valve2",
        15: "Brine side water flow switch",
    }),
    2136: ("2136 Status register 2 bits", {
        5: "Defrosting operation status (1=enter, 0=exit)",
    }),
    2138: ("2138 Protections bits", {
        0: "AC current protection",
        1: "Compressor current protection",
        2: "DC fan motor protection",
        3: "Bus voltage protection",
        4: "IPM temperature protection",
        5: "High discharge temp protection",
        6: "High pressure switch protection",
        7: "Low pressure switch protection",
        8: "Water flow switch protection",
        9: "Water flow protection (NYSERDA backend decode bit)",
        10: "Low ambient temp protection",
        11: "Primary circuit low pressure protection",
        12: "Secondary circuit low pressure protection",
        13: "Large inlet/outlet temp diff protection",
        14: "Low outlet water temp protection",
        15: "Compressor differential pressure protection",
    }),
}


DEFAULT_VALUES = {
    2000: 0,
    2001: 5,
    2002: 3.0,
    2003: 15.0,
    2004: 20.0,
    2052: 2,
    2053: 5,
    2054: -1.0,
    2056: 0,
    2057: 0,
    2100: 26.0,
    2102: 25.0,
    2103: 25.0,
    2104: 5.0,
    2105: 3.0,
    2107: -2.0,
    2108: 11.0,
    2110: 4.0,
    2115: 0.0,
    2116: 0.0,
    2117: 0,
    2118: 0,
    2119: 650,
    2120: 247,
    2121: 0,
    2122: 348,
    2123: 0,
    2133: 0,
    2134: 0,
    2135: 0,
    2136: 0,
    2138: 0,
}
