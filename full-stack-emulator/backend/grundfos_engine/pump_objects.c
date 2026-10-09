/* Command/reading emulator matched to src/managers/pump_manager.py. */
#include "pump_objects.h"
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "bacnet/bacapp.h"
#include "bacnet/bacdcode.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/object/ai.h"
#include "bacnet/basic/object/ao.h"
#include "bacnet/basic/object/bi.h"
#include "bacnet/basic/object/bo.h"
#include "bacnet/basic/object/ms-input.h"
#include "bacnet/basic/object/mso.h"
#include "bacnet/basic/object/netport.h"

static PumpConfig settings;
static unsigned actual_control;
static unsigned actual_operating;
static float actual_setpoint;
static double running_hours, powered_hours;
static bool manual_active[59];
static float manual_value[59];
static unsigned cim_status = 1;
/* Compatibility with the unchanged controller's AO5 -> AI5 confirmation.
 * Track occupied AO5 priority slots; the stack still resolves their values. */
static bool flow_command_priority[16];

typedef struct { uint32_t id; const char *name; BACNET_ENGINEERING_UNITS units; } Point;
static const Point inputs[] = {
    {0, "FaultCodes", UNITS_NO_UNITS}, {1, "WarningCodes", UNITS_NO_UNITS},
    {3, "Capacity", UNITS_PERCENT}, {4, "Pressure", UNITS_BARS},
    {5, "Flow", UNITS_CUBIC_METERS_PER_HOUR}, {6, "RelPerformance", UNITS_PERCENT},
    {9, "ActualSetPoint", UNITS_PERCENT}, {10, "MotorCurrent", UNITS_AMPERES},
    {13, "Power", UNITS_WATTS}, {18, "PowerElectronicTemp", UNITS_DEGREES_CELSIUS},
    {22, "Temperature", UNITS_DEGREES_CELSIUS}, {26, "SpecificEnergy", UNITS_NO_UNITS},
    {27, "TotalOperatingTime", UNITS_HOURS}, {28, "TotalOnTime", UNITS_HOURS},
    {57, "RemoteTemperature2", UNITS_DEGREES_CELSIUS}, {58, "UserSetPoint", UNITS_PERCENT}
};
static const char control_labels[] =
    "Constant Curve\0Constant Pressure\0Proportional Pressure\0Auto Adapt\0"
    "Constant Flow\0Constant Temperature\0Reserved 7\0Reserved 8\0"
    "Flow Adapt\0Reserved 10\0Reserved 11\0Differential Temperature\0";
static const char operating_labels[] = "Start (normal)\0Stop\0Minimum\0Maximum\0";
static const char cim_labels[] = "OK\0EEPROM FAULT\0Memory Fault\0";

static bool control_valid(uint32_t mode)
{
    return (mode >= 1 && mode <= 6) || mode == 9 || mode == 12;
}

static bool fail(BACNET_WRITE_PROPERTY_DATA *wp, BACNET_ERROR_CODE code)
{
    wp->error_class = ERROR_CLASS_PROPERTY;
    wp->error_code = code;
    return false;
}

static bool read_only(BACNET_WRITE_PROPERTY_DATA *wp)
{
    return fail(wp, ERROR_CODE_WRITE_ACCESS_DENIED);
}

/* Output priorities and NULL relinquishment are handled by the BACnet stack.
 * Inputs expose actual state. Remote output writes are stored while local;
 * enabling bus control applies the stored commands. */
static void update_readings(void)
{
    bool remote = Binary_Output_Present_Value(0) == BINARY_ACTIVE;
    if (remote) {
        actual_control = Multistate_Output_Present_Value(0);
        actual_operating = Multistate_Output_Present_Value(1);
        actual_setpoint = Analog_Output_Present_Value(0);
    } else {
        actual_control = settings.control_mode;
        actual_operating = settings.operating_mode;
        actual_setpoint = (float)settings.setpoint;
    }
    bool running = actual_operating != 2 && settings.fault_code == 0;
    double fraction = actual_setpoint / 100.0;
    if (actual_operating == 3) fraction = 0.25;
    if (actual_operating == 4) fraction = 1.0;
    if (running && fraction < 0.25) fraction = 0.25;
    if (!running) fraction = 0;
    double flow = settings.flow_gpm * fraction;
    /* The original src confirms AO5 by reading AI5, multiplying by 4.4 and
     * comparing to the command. Echo the effective command as GPM whenever
     * a bus AO5 priority is occupied, including while stopped/faulted. This
     * is an explicit controller-compatibility profile, not physical flow. */
    if (remote) {
        for (unsigned i = 0; i < 16; ++i) {
            if (flow_command_priority[i]) {
                flow = Analog_Output_Present_Value(5);
                break;
            }
        }
    }
    double watts = settings.power_w * fraction;
    Analog_Input_Present_Value_Set(0, (float)settings.fault_code);
    Analog_Input_Present_Value_Set(1, (float)settings.warning_code);
    Analog_Input_Present_Value_Set(3, (float)(fraction * 100));
    Analog_Input_Present_Value_Set(4, (float)(settings.pressure_psi * fraction / 14.5));
    Analog_Input_Present_Value_Set(5, (float)(flow / 4.4));
    Analog_Input_Present_Value_Set(6, (float)(fraction * 100));
    Analog_Input_Present_Value_Set(9, actual_setpoint);
    Analog_Input_Present_Value_Set(10, (float)(settings.current_a * fraction));
    Analog_Input_Present_Value_Set(13, (float)watts);
    Analog_Input_Present_Value_Set(18, (float)settings.electronics_temperature_c);
    Analog_Input_Present_Value_Set(22, (float)settings.temperature_c);
    Analog_Input_Present_Value_Set(26, flow > 0 ? (float)((watts / 1000) / (flow / 4.4)) : 0);
    Analog_Input_Present_Value_Set(27, (float)running_hours);
    Analog_Input_Present_Value_Set(28, (float)powered_hours);
    Analog_Input_Present_Value_Set(57, (float)settings.remote_temperature_c);
    Analog_Input_Present_Value_Set(58, actual_setpoint);
    Multistate_Input_Present_Value_Set(0, actual_control);
    Multistate_Input_Present_Value_Set(1, actual_operating);
    Multistate_Input_Present_Value_Set(3, cim_status);
    /* Grundfos manual: BI0 is Control source status (local/bus). */
    Binary_Input_Present_Value_Set(0, remote ? BINARY_ACTIVE : BINARY_INACTIVE);
    /* Original src confirms BO0 through BI31 (labelled PowerLimit there).
     * Mirror bus control at both BI0 and BI31 without changing src. */
    Binary_Input_Present_Value_Set(31, remote ? BINARY_ACTIVE : BINARY_INACTIVE);
    for (unsigned i = 0; i < 59; ++i)
        if (manual_active[i]) Analog_Input_Present_Value_Set(i, manual_value[i]);
}

static bool write_output(BACNET_WRITE_PROPERTY_DATA *wp)
{
    BACNET_APPLICATION_DATA_VALUE value = {0};
    BACNET_WRITE_PROPERTY_DATA normalized;
    bool ok;
    if (wp->object_property != PROP_PRESENT_VALUE)
        return fail(wp, ERROR_CODE_WRITE_ACCESS_DENIED);
    if (wp->array_index != BACNET_ARRAY_ALL)
        return fail(wp, ERROR_CODE_PROPERTY_IS_NOT_AN_ARRAY);
    int used = bacapp_decode_application_data(wp->application_data, wp->application_data_len, &value);
    if (used <= 0 || used != wp->application_data_len)
        return fail(wp, ERROR_CODE_INVALID_DATA_TYPE);
    if (value.tag != BACNET_APPLICATION_TAG_NULL) {
        if (wp->object_type == OBJECT_ANALOG_OUTPUT) {
            if (value.tag != BACNET_APPLICATION_TAG_REAL)
                return fail(wp, ERROR_CODE_INVALID_DATA_TYPE);
            if (!isfinite(value.type.Real) || value.type.Real < 0 ||
                (wp->object_instance == 0 && value.type.Real > 100))
                return fail(wp, ERROR_CODE_VALUE_OUT_OF_RANGE);
        } else if (wp->object_type == OBJECT_MULTI_STATE_OUTPUT) {
            if (value.tag != BACNET_APPLICATION_TAG_UNSIGNED_INT)
                return fail(wp, ERROR_CODE_INVALID_DATA_TYPE);
            uint32_t n = value.type.Unsigned_Int;
            if ((wp->object_instance == 0 && !control_valid(n)) ||
                (wp->object_instance == 1 && (n < 1 || n > 4)))
                return fail(wp, ERROR_CODE_VALUE_OUT_OF_RANGE);
        } else if (wp->object_type == OBJECT_BINARY_OUTPUT) {
            /* The supplied manager constructs Unsigned for BO. Accept it
             * as well as the standard enumerated value used by BACpypes3. */
            uint32_t n;
            if (value.tag == BACNET_APPLICATION_TAG_UNSIGNED_INT) n = value.type.Unsigned_Int;
            else if (value.tag == BACNET_APPLICATION_TAG_ENUMERATED) n = value.type.Enumerated;
            else return fail(wp, ERROR_CODE_INVALID_DATA_TYPE);
            if (n > 1) return fail(wp, ERROR_CODE_VALUE_OUT_OF_RANGE);
            normalized = *wp;
            normalized.application_data_len = encode_application_enumerated(normalized.application_data, n);
            ok = Binary_Output_Write_Property(&normalized);
            wp->error_class = normalized.error_class;
            wp->error_code = normalized.error_code;
            if (!ok) return false;
            update_readings();
            pump_print_status();
            return true;
        }
    }
    switch (wp->object_type) {
        case OBJECT_ANALOG_OUTPUT: ok = Analog_Output_Write_Property(wp); break;
        case OBJECT_MULTI_STATE_OUTPUT: ok = Multistate_Output_Write_Property(wp); break;
        case OBJECT_BINARY_OUTPUT: ok = Binary_Output_Write_Property(wp); break;
        default: return fail(wp, ERROR_CODE_WRITE_ACCESS_DENIED);
    }
    if (ok) {
        if (wp->object_type == OBJECT_ANALOG_OUTPUT && wp->object_instance == 5) {
            if (wp->priority >= 1 && wp->priority <= 16)
                flow_command_priority[wp->priority - 1] = value.tag != BACNET_APPLICATION_TAG_NULL;
            /* A fresh command restores its confirmation after sensor injection. */
            manual_active[5] = false;
        }
        update_readings();
        pump_print_status();
    }
    return ok;
}

#define ENTRY(kind, prefix, writer) { \
    .Object_Type = kind, .Object_Init = prefix##_Init, .Object_Count = prefix##_Count, \
    .Object_Index_To_Instance = prefix##_Index_To_Instance, \
    .Object_Valid_Instance = prefix##_Valid_Instance, .Object_Name = prefix##_Object_Name, \
    .Object_Read_Property = prefix##_Read_Property, .Object_Write_Property = writer, \
    .Object_RPM_List = prefix##_Property_Lists }

static object_functions_t object_table[] = {
    { .Object_Type = OBJECT_DEVICE, .Object_Count = Device_Count,
      .Object_Index_To_Instance = Device_Index_To_Instance,
      .Object_Valid_Instance = Device_Valid_Object_Instance_Number,
      .Object_Name = Device_Object_Name, .Object_Read_Property = Device_Read_Property_Local,
      .Object_Write_Property = read_only, .Object_RPM_List = Device_Property_Lists },
    ENTRY(OBJECT_ANALOG_INPUT, Analog_Input, read_only),
    ENTRY(OBJECT_ANALOG_OUTPUT, Analog_Output, write_output),
    ENTRY(OBJECT_BINARY_INPUT, Binary_Input, read_only),
    ENTRY(OBJECT_BINARY_OUTPUT, Binary_Output, write_output),
    ENTRY(OBJECT_MULTI_STATE_INPUT, Multistate_Input, read_only),
    ENTRY(OBJECT_MULTI_STATE_OUTPUT, Multistate_Output, write_output),
    ENTRY(OBJECT_NETWORK_PORT, Network_Port, read_only),
    { .Object_Type = MAX_BACNET_OBJECT_TYPE }
};

void pump_config_defaults(PumpConfig *c)
{
    *c = (PumpConfig){.flow_gpm = 40, .pressure_psi = 15, .power_w = 150,
        .current_a = 1.2, .temperature_c = 23, .remote_temperature_c = 24,
        .electronics_temperature_c = 35, .setpoint = 50,
        .control_mode = 1, .operating_mode = 2};
}

bool pump_objects_init(const PumpConfig *c, uint32_t device_id, const char *name)
{
    if (!control_valid(c->control_mode) || c->operating_mode < 1 || c->operating_mode > 4 ||
        !isfinite(c->setpoint) || c->setpoint < 0 || c->setpoint > 100) return false;
    settings = *c;
    memset(manual_active, 0, sizeof(manual_active));
    cim_status = 1;
    memset(flow_command_priority, 0, sizeof(flow_command_priority));
    running_hours = c->operating_hours;
    powered_hours = c->on_hours;
    Device_Init(object_table);
    Device_Set_Object_Instance_Number(device_id);
    if (!Device_Object_Name_ANSI_Init(name)) return false;
    Device_Set_Vendor_Identifier(227);
    Device_Set_Vendor_Name("Grundfos", 8);
    Device_Set_Model_Name("MAGNA3 controller emulator", strlen("MAGNA3 controller emulator"));
    Device_Set_Description("Simulated pump; source-code compatibility profile", strlen("Simulated pump; source-code compatibility profile"));
    Device_Set_Application_Software_Version("pump-emulator-1", 15);
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {
        if (Analog_Input_Create(inputs[i].id) != inputs[i].id) return false;
        Analog_Input_Name_Set(inputs[i].id, inputs[i].name);
        Analog_Input_Units_Set(inputs[i].id, inputs[i].units);
    }
    if (Analog_Output_Create(0) != 0 || Analog_Output_Create(5) != 5 ||
        Binary_Input_Create(0) != 0 || Binary_Input_Create(31) != 31 ||
        Binary_Output_Create(0) != 0) return false;
    Analog_Output_Name_Set(0, "Setpoint");
    Analog_Output_Units_Set(0, UNITS_PERCENT);
    Analog_Output_Relinquish_Default_Set(0, (float)c->setpoint);
    Analog_Output_Name_Set(5, "MaximumFlowLimit");
    Analog_Output_Units_Set(5, UNITS_US_GALLONS_PER_MINUTE);
    Analog_Output_Max_Pres_Value_Set(5, 1000000);
    Analog_Output_Relinquish_Default_Set(5, (float)c->flow_gpm);
    Binary_Input_Name_Set(0, "ControlSourceStatus");
    Binary_Input_Name_Set(31, "PowerLimit");
    Binary_Output_Name_Set(0, "BusControl");
    Binary_Output_Relinquish_Default_Set(0, c->bus_control ? BINARY_ACTIVE : BINARY_INACTIVE);
    for (unsigned i = 0; i < 2; ++i) {
        if (Multistate_Input_Create(i) != i || Multistate_Output_Create(i) != i) return false;
        const char *labels = i == 0 ? control_labels : operating_labels;
        if (!Multistate_Input_State_Text_List_Set(i, labels) ||
            !Multistate_Output_State_Text_List_Set(i, labels)) return false;
    }
    Multistate_Input_Name_Set(0, "ActualControlMode");
    Multistate_Input_Name_Set(1, "ActualOperatingMode");
    Multistate_Output_Name_Set(0, "ControlMode");
    Multistate_Output_Name_Set(1, "OperatingMode");
    Multistate_Output_Relinquish_Default_Set(0, c->control_mode);
    Multistate_Output_Relinquish_Default_Set(1, c->operating_mode);
    if (Multistate_Input_Create(3) != 3) return false;
    Multistate_Input_Name_Set(3, "CIMStatus");
    if (!Multistate_Input_State_Text_List_Set(3, cim_labels)) return false;
    update_readings();
    return true;
}

void pump_tick(double seconds)
{
    powered_hours += seconds / 3600;
    if (actual_operating != 2 && settings.fault_code == 0) running_hours += seconds / 3600;
    Analog_Input_Present_Value_Set(27, (float)running_hours);
    Analog_Input_Present_Value_Set(28, (float)powered_hours);
}

void pump_print_status(void)
{
    printf("bus=%u control=%u operating=%u setpoint=%.2f flow=%.2f GPM power=%.2f W\n",
        Binary_Input_Present_Value(0), actual_control, actual_operating,
        (double)actual_setpoint, (double)Analog_Input_Present_Value(5) * 4.4,
        (double)Analog_Input_Present_Value(13));
    fflush(stdout);
}

/* Card output commands use the same writer and priority 1 as src's controller.
 * The latest write at that priority wins, including the next controller write.
 * NULL releases priority 1 through the stack's normal priority-array handling. */
static bool card_command(const char *field, double value, bool release)
{
    BACNET_WRITE_PROPERTY_DATA wp = {
        .object_property = PROP_PRESENT_VALUE, .array_index = BACNET_ARRAY_ALL,
        .priority = 1
    };
    if (strcmp(field, "command_bus_control") == 0) {
        if (!release && (value < 0 || value > 1 || value != floor(value))) return false;
        wp.object_type = OBJECT_BINARY_OUTPUT;
        wp.object_instance = 0;
    } else if (strcmp(field, "command_control_mode") == 0 ||
               strcmp(field, "command_operating_mode") == 0) {
        if (!release && (value < 1 || value > 12 || value != floor(value))) return false;
        wp.object_type = OBJECT_MULTI_STATE_OUTPUT;
        wp.object_instance = strcmp(field, "command_control_mode") == 0 ? 0 : 1;
    } else if (strcmp(field, "command_setpoint") == 0 || strcmp(field, "command_max_flow") == 0) {
        if (!release && (value < 0 || value > 1000000)) return false;
        wp.object_type = OBJECT_ANALOG_OUTPUT;
        wp.object_instance = strcmp(field, "command_setpoint") == 0 ? 0 : 5;
    } else return false;
    if (release) wp.application_data_len = encode_application_null(wp.application_data);
    else if (wp.object_type == OBJECT_ANALOG_OUTPUT)
        wp.application_data_len = encode_application_real(wp.application_data, (float)value);
    else wp.application_data_len = encode_application_unsigned(wp.application_data, (uint32_t)value);
    return write_output(&wp);
}

/* Simulation injection remains private to the web/GUI pipe. Inputs stay
 * read-only over BACnet. Feedback for commands is always derived, never frozen. */
bool pump_set_simulation(const char *field, double value)
{
    if (!isfinite(value)) return false;
    if (strncmp(field, "command_", 8) == 0) return card_command(field, value, false);
    if (strncmp(field, "release_command_", 16) == 0) return card_command(field + 8, value, true);
    if (strncmp(field, "ai_", 3) == 0 || strncmp(field, "clear_ai_", 9) == 0) {
        bool clear = strncmp(field, "clear_", 6) == 0;
        const char *suffix = field + (clear ? 9 : 3);
        unsigned id = 0;
        char extra;
        if (sscanf(suffix, "%u%c", &id, &extra) != 1) return false;
        if (!(id == 3 || id == 4 || id == 5 || id == 6 || id == 10 || id == 13 || id == 26)) return false;
        if (value < 0 || value > ((id == 3 || id == 6) ? 100 : 1000000)) return false;
        manual_active[id] = !clear;
        manual_value[id] = (float)value;
    } else if (strcmp(field, "cim_status") == 0) {
        if (value != floor(value) || value < 1 || value > 3) return false;
        cim_status = (unsigned)value;
    } else if (strcmp(field, "operating_hours") == 0 || strcmp(field, "on_hours") == 0) {
        if (value < 0 || value > 10000000) return false;
        if (strcmp(field, "operating_hours") == 0) {
            if (value > powered_hours) return false;
            running_hours = value;
        } else {
            if (value < running_hours) return false;
            powered_hours = value;
        }
    } else if (strcmp(field, "local_control_mode") == 0) {
        if (value < 1 || value > 12 || value != floor(value) || !control_valid((unsigned)value)) return false;
        settings.control_mode = (unsigned)value;
    } else if (strcmp(field, "local_operating_mode") == 0) {
        if (value < 1 || value > 4 || value != floor(value)) return false;
        settings.operating_mode = (unsigned)value;
    } else if (strcmp(field, "local_setpoint") == 0) {
        if (value < 0 || value > 100) return false;
        settings.setpoint = value;
    } else if (strcmp(field, "fault_code") == 0 || strcmp(field, "warning_code") == 0) {
        if (value < 0 || value > 65535 || value != floor(value)) return false;
        if (strcmp(field, "fault_code") == 0) settings.fault_code = (unsigned)value;
        else settings.warning_code = (unsigned)value;
    } else {
        double *target = NULL;
        double minimum = 0, maximum = 1000000;
        if (strcmp(field, "flow_gpm") == 0) target = &settings.flow_gpm;
        else if (strcmp(field, "pressure_psi") == 0) target = &settings.pressure_psi;
        else if (strcmp(field, "power_w") == 0) target = &settings.power_w;
        else if (strcmp(field, "current_a") == 0) target = &settings.current_a;
        else {
            minimum = -273.15;
            maximum = 1000;
            if (strcmp(field, "temperature_c") == 0) target = &settings.temperature_c;
            else if (strcmp(field, "remote_temperature_c") == 0) target = &settings.remote_temperature_c;
            else if (strcmp(field, "electronics_temperature_c") == 0) target = &settings.electronics_temperature_c;
        }
        if (!target || value < minimum || value > maximum) return false;
        *target = value;
    }
    update_readings();
    return true;
}

void pump_print_snapshot(void)
{
    printf("STATE {\"bus_control\":%u,\"control_mode\":%u,\"operating_mode\":%u,"
        "\"setpoint_pct\":%.6g,\"fault_code\":%u,\"warning_code\":%u,"
        "\"flow_m3h\":%.6g,\"pressure_bar\":%.6g,\"power_w\":%.6g,"
        "\"current_a\":%.6g,\"temperature_c\":%.6g,\"operating_hours\":%.6g,\"on_hours\":%.6g}\n",
        (unsigned)Binary_Input_Present_Value(0), actual_control, actual_operating,
        (double)actual_setpoint, settings.fault_code, settings.warning_code,
        (double)Analog_Input_Present_Value(5), (double)Analog_Input_Present_Value(4),
        (double)Analog_Input_Present_Value(13), (double)Analog_Input_Present_Value(10),
        (double)Analog_Input_Present_Value(22), running_hours, powered_hours);
    /* Full object values let cards show actual command values even in local
     * mode, when the corresponding feedback deliberately differs. */
    printf("OBJECTS {");
    for (unsigned i = 0; i < sizeof(inputs) / sizeof(inputs[0]); ++i) {
        printf("%s\"analogInput,%u\":%.9g", i ? "," : "", inputs[i].id,
            (double)Analog_Input_Present_Value(inputs[i].id));
    }
    printf(",\"binaryInput,0\":%u,\"binaryInput,31\":%u,\"binaryOutput,0\":%u",
        (unsigned)Binary_Input_Present_Value(0), (unsigned)Binary_Input_Present_Value(31),
        (unsigned)Binary_Output_Present_Value(0));
    printf(",\"multiStateInput,0\":%u,\"multiStateInput,1\":%u,\"multiStateInput,3\":%u",
        (unsigned)Multistate_Input_Present_Value(0), (unsigned)Multistate_Input_Present_Value(1),
        (unsigned)Multistate_Input_Present_Value(3));
    printf(",\"multiStateOutput,0\":%u,\"multiStateOutput,1\":%u,\"analogOutput,0\":%.9g,\"analogOutput,5\":%.9g}\n",
        (unsigned)Multistate_Output_Present_Value(0), (unsigned)Multistate_Output_Present_Value(1),
        (double)Analog_Output_Present_Value(0), (double)Analog_Output_Present_Value(5));
    printf("SIMULATION {\"flow_gpm\":%.9g,\"pressure_psi\":%.9g,\"power_w\":%.9g,\"current_a\":%.9g,"
        "\"local_control_mode\":%u,\"local_operating_mode\":%u,\"local_setpoint\":%.9g}\n",
        settings.flow_gpm, settings.pressure_psi, settings.power_w, settings.current_a,
        settings.control_mode, settings.operating_mode, settings.setpoint);
    printf("OVERRIDES [");
    bool first = true;
    for (unsigned i = 0; i < 59; ++i) {
        if (manual_active[i]) {
            printf("%s\"ai_%u\"", first ? "" : ",", i);
            first = false;
        }
    }
    puts("]");
    fflush(stdout);
}
