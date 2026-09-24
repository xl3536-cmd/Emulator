#include "pump_profile.h"

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "bacnet/basic/object/ai.h"
#include "bacnet/basic/object/ao.h"
#include "bacnet/basic/object/av.h"
#include "bacnet/basic/object/bi.h"
#include "bacnet/basic/object/bo.h"
#include "bacnet/basic/object/ms-input.h"
#include "bacnet/basic/object/mso.h"

static pump_state_t *Active_State = NULL;

const char *pump_profile_operating_mode_name(uint32_t value)
{
    switch (value) {
        case 1:
            return "Start";
        case 2:
            return "Stop";
        case 3:
            return "Minimum";
        case 4:
            return "Maximum";
        default:
            return "Unknown";
    }
}

const char *pump_profile_control_mode_name(uint32_t value)
{
    switch (value) {
        case 1:
            return "Constant speed";
        case 2:
            return "Constant pressure";
        case 3:
            return "Proportional pressure";
        case 4:
            return "AUTOADAPT";
        case 5:
            return "Constant flow";
        case 6:
            return "Constant temperature";
        case 7:
            return "Constant level";
        case 8:
            return "Constant percentage";
        case 9:
            return "FLOWADAPT";
        case 10:
            return "Closed-loop sensor";
        case 11:
            return "Constant diff pressure";
        case 12:
            return "Constant diff temperature";
        default:
            return "Unknown";
    }
}

static bool control_mode_blocks_manual(uint32_t value)
{
    return (value == 4U) || (value == 9U);
}

static void note_command_activity(pump_state_t *state)
{
    state->seconds_since_command = 0U;
}

static void update_derived_state(pump_state_t *state)
{
    float load;
    float setpoint_factor;

    if ((state->bus_control == BINARY_ACTIVE) &&
        !control_mode_blocks_manual(state->control_mode_actual)) {
        state->operating_mode_actual = state->operating_mode_command;
    }

    setpoint_factor = state->command_setpoint_pct / 100.0f;
    if (setpoint_factor < 0.10f) {
        setpoint_factor = 0.10f;
    }
    if (setpoint_factor > 1.0f) {
        setpoint_factor = 1.0f;
    }

    switch (state->operating_mode_actual) {
        case 1:
            load = 0.72f * setpoint_factor;
            break;
        case 3:
            load = 0.42f * setpoint_factor;
            break;
        case 4:
            load = 1.00f * setpoint_factor;
            break;
        case 2:
        default:
            load = 0.0f;
            break;
    }

    if (state->fault_simulation == BINARY_ACTIVE) {
        load = 0.0f;
        state->fault_code = 9901.0f;
        state->warning_code = 9901.0f;
    } else if (control_mode_blocks_manual(state->control_mode_actual)) {
        state->warning_code = 9.0f;
        state->fault_code = 0.0f;
    } else {
        state->warning_code = 0.0f;
        state->fault_code = 0.0f;
    }

    state->run_status = (load > 0.0f) ? BINARY_ACTIVE : BINARY_INACTIVE;
    state->pump_running = state->run_status;
    state->capacity_pct = load * 100.0f;
    state->relative_performance_pct = 68.0f + (load * 22.0f);
    state->speed_pct = load * 100.0f;
    state->pressure_bar = 1.15f + (load * 1.75f);
    state->flow_lps = load * 3.25f;
    state->actual_setpoint = state->command_setpoint_pct;
    state->motor_current = 0.10f + (load * 4.20f);
    state->power_watts = load * 720.0f;
    state->power_electronics_temp_c = 28.0f + (load * 18.0f);
    state->fluid_temp_c = 24.0f + (load * 6.5f);
    state->specific_energy = 0.30f + (load * 0.85f);
    state->remote_temperature_2_c = 21.0f + (load * 5.0f);
    state->user_setpoint = state->command_setpoint_pct;
    state->power_limit = BINARY_INACTIVE;
    state->cim_status = (load > 0.0f) ? 2U : 1U;
}

void pump_profile_publish(const pump_state_t *state)
{
    Binary_Output_Present_Value_Set(
        PUMP_BO_BUS_CONTROL, state->bus_control, BACNET_MAX_PRIORITY);
    Binary_Output_Present_Value_Set(
        PUMP_BO_RESET_FAULT, state->reset_fault, BACNET_MAX_PRIORITY);
    Binary_Output_Present_Value_Set(
        PUMP_BO_FAULT_SIMULATION, state->fault_simulation,
        BACNET_MAX_PRIORITY);

    Binary_Input_Present_Value_Set(PUMP_BI_READY, state->pump_ready);
    Binary_Input_Present_Value_Set(PUMP_BI_RUN_STATUS, state->run_status);
    Binary_Input_Present_Value_Set(PUMP_BI_PUMP_RUNNING, state->pump_running);
    Binary_Input_Present_Value_Set(PUMP_BI_POWER_LIMIT, state->power_limit);
    Binary_Input_Present_Value_Set(PUMP_BI_ENABLE_STATUS, state->enable_status);

    Multistate_Input_Present_Value_Set(
        PUMP_MSI_CONTROL_MODE, state->control_mode_actual);
    Multistate_Input_Present_Value_Set(
        PUMP_MSI_OPERATING_MODE, state->operating_mode_actual);
    Multistate_Input_Present_Value_Set(
        PUMP_MSI_CIM_STATUS, state->cim_status);

    Analog_Output_Present_Value_Set(
        PUMP_AO_SETPOINT, state->command_setpoint_pct, BACNET_MAX_PRIORITY);
    Analog_Value_Present_Value_Set(
        PUMP_AV_WATCHDOG, (float)state->watchdog_seconds,
        BACNET_MAX_PRIORITY);

    Analog_Input_Present_Value_Set(0U, state->fault_code);
    Analog_Input_Present_Value_Set(1U, state->warning_code);
    Analog_Input_Present_Value_Set(3U, state->capacity_pct);
    Analog_Input_Present_Value_Set(4U, state->pressure_bar);
    Analog_Input_Present_Value_Set(5U, state->flow_lps);
    Analog_Input_Present_Value_Set(6U, state->relative_performance_pct);
    Analog_Input_Present_Value_Set(7U, state->speed_pct);
    Analog_Input_Present_Value_Set(9U, state->actual_setpoint);
    Analog_Input_Present_Value_Set(10U, state->motor_current);
    Analog_Input_Present_Value_Set(13U, state->power_watts);
    Analog_Input_Present_Value_Set(18U, state->power_electronics_temp_c);
    Analog_Input_Present_Value_Set(22U, state->fluid_temp_c);
    Analog_Input_Present_Value_Set(26U, state->specific_energy);
    Analog_Input_Present_Value_Set(27U, state->total_operating_time_h);
    Analog_Input_Present_Value_Set(28U, state->total_on_time_h);
    Analog_Input_Present_Value_Set(30U, state->total_energy_kwh);
    Analog_Input_Present_Value_Set(57U, state->remote_temperature_2_c);
    Analog_Input_Present_Value_Set(58U, state->user_setpoint);
    Analog_Input_Present_Value_Set(131U, state->min_frequency_hz);
    Analog_Input_Present_Value_Set(132U, state->max_frequency_hz);
}

static void bus_control_callback(
    uint32_t object_instance,
    BACNET_BINARY_PV old_value,
    BACNET_BINARY_PV value)
{
    (void)object_instance;
    (void)old_value;

    if (!Active_State) {
        return;
    }

    Active_State->bus_control = value;
    note_command_activity(Active_State);
    update_derived_state(Active_State);
    pump_profile_publish(Active_State);
    printf("bus control -> %s\n", (value == BINARY_ACTIVE) ? "BUS" : "LOCAL");
}

static void binary_output_callback(
    uint32_t object_instance,
    BACNET_BINARY_PV old_value,
    BACNET_BINARY_PV value)
{
    (void)old_value;

    if (!Active_State) {
        return;
    }

    if (object_instance == PUMP_BO_BUS_CONTROL) {
        bus_control_callback(object_instance, old_value, value);
    } else if (object_instance == PUMP_BO_RESET_FAULT) {
        Active_State->reset_fault = value;
        if (value == BINARY_ACTIVE) {
            Active_State->fault_code = 0.0f;
            Active_State->warning_code = 0.0f;
        }
        note_command_activity(Active_State);
        update_derived_state(Active_State);
        pump_profile_publish(Active_State);
        printf("reset fault -> %s\n",
            (value == BINARY_ACTIVE) ? "ACTIVE" : "INACTIVE");
    } else if (object_instance == PUMP_BO_FAULT_SIMULATION) {
        Active_State->fault_simulation = value;
        note_command_activity(Active_State);
        update_derived_state(Active_State);
        pump_profile_publish(Active_State);
        printf("fault simulation -> %s\n",
            (value == BINARY_ACTIVE) ? "ACTIVE" : "INACTIVE");
    }
}

static void multistate_output_callback(
    uint32_t object_instance,
    uint32_t old_value,
    uint32_t value)
{
    (void)old_value;

    if (!Active_State) {
        return;
    }

    if ((object_instance == PUMP_MSO_CONTROL_MODE) &&
        (value >= 1U) && (value <= 12U)) {
        Active_State->control_mode_command = value;
        Active_State->control_mode_actual = value;
        note_command_activity(Active_State);
        update_derived_state(Active_State);
        pump_profile_publish(Active_State);
        printf(
            "control mode -> %lu (%s)\n", (unsigned long)value,
            pump_profile_control_mode_name(value));
    } else if ((object_instance == PUMP_MSO_OPERATING_MODE) &&
        (value >= 1U) && (value <= 4U)) {
        Active_State->operating_mode_command = value;
        note_command_activity(Active_State);
        update_derived_state(Active_State);
        pump_profile_publish(Active_State);
        printf(
            "operating mode cmd -> %lu (%s), actual -> %lu (%s)\n",
            (unsigned long)Active_State->operating_mode_command,
            pump_profile_operating_mode_name(
                Active_State->operating_mode_command),
            (unsigned long)Active_State->operating_mode_actual,
            pump_profile_operating_mode_name(
                Active_State->operating_mode_actual));
    }
}

static void analog_output_callback(
    uint32_t object_instance,
    float old_value,
    float value)
{
    (void)old_value;

    if (!Active_State || (object_instance != PUMP_AO_SETPOINT)) {
        return;
    }

    if (value < 0.0f) {
        value = 0.0f;
    }
    if (value > 100.0f) {
        value = 100.0f;
    }

    Active_State->command_setpoint_pct = value;
    note_command_activity(Active_State);
    update_derived_state(Active_State);
    pump_profile_publish(Active_State);
    printf("setpoint -> %.1f%%\n", value);
}

static void analog_value_callback(
    uint32_t object_instance,
    float old_value,
    float value)
{
    (void)old_value;

    if (!Active_State || (object_instance != PUMP_AV_WATCHDOG)) {
        return;
    }

    if (value < 5.0f) {
        value = 5.0f;
    }
    if (value > 3600.0f) {
        value = 3600.0f;
    }

    Active_State->watchdog_seconds = (uint32_t)value;
    note_command_activity(Active_State);
    pump_profile_publish(Active_State);
    printf("watchdog -> %lus\n", (unsigned long)Active_State->watchdog_seconds);
}

void pump_profile_create_objects(void)
{
    Binary_Output_Create(PUMP_BO_BUS_CONTROL);
    Binary_Output_Name_Set(PUMP_BO_BUS_CONTROL, "Bus Control");
    Binary_Output_Create(PUMP_BO_RESET_FAULT);
    Binary_Output_Name_Set(PUMP_BO_RESET_FAULT, "Reset Fault");
    Binary_Output_Create(PUMP_BO_FAULT_SIMULATION);
    Binary_Output_Name_Set(PUMP_BO_FAULT_SIMULATION, "Fault Simulation");

    Binary_Input_Create(PUMP_BI_READY);
    Binary_Input_Name_Set(PUMP_BI_READY, "Pump Ready");
    Binary_Input_Create(PUMP_BI_RUN_STATUS);
    Binary_Input_Name_Set(PUMP_BI_RUN_STATUS, "Run Status");
    Binary_Input_Create(PUMP_BI_PUMP_RUNNING);
    Binary_Input_Name_Set(PUMP_BI_PUMP_RUNNING, "Pump Running");
    Binary_Input_Create(PUMP_BI_POWER_LIMIT);
    Binary_Input_Name_Set(PUMP_BI_POWER_LIMIT, "Power Limit");
    Binary_Input_Create(PUMP_BI_ENABLE_STATUS);
    Binary_Input_Name_Set(PUMP_BI_ENABLE_STATUS, "Enable Status");

    Multistate_Input_Create(PUMP_MSI_CONTROL_MODE);
    Multistate_Input_Name_Set(PUMP_MSI_CONTROL_MODE, "Actual Control Mode");
    Multistate_Input_Create(PUMP_MSI_OPERATING_MODE);
    Multistate_Input_Name_Set(PUMP_MSI_OPERATING_MODE, "Actual Operating Mode");
    Multistate_Input_Create(PUMP_MSI_CIM_STATUS);
    Multistate_Input_Name_Set(PUMP_MSI_CIM_STATUS, "CIM Status");

    Multistate_Output_Create(PUMP_MSO_CONTROL_MODE);
    Multistate_Output_Name_Set(PUMP_MSO_CONTROL_MODE, "Control Mode Command");
    Multistate_Output_Create(PUMP_MSO_OPERATING_MODE);
    Multistate_Output_Name_Set(
        PUMP_MSO_OPERATING_MODE, "Operating Mode Command");

    Analog_Output_Create(PUMP_AO_SETPOINT);
    Analog_Output_Name_Set(PUMP_AO_SETPOINT, "Pump Setpoint");

    Analog_Value_Create(PUMP_AV_WATCHDOG);
    Analog_Value_Name_Set(PUMP_AV_WATCHDOG, "BACnet Watchdog");

    Analog_Input_Create(0U);
    Analog_Input_Name_Set(0U, "Fault Codes");
    Analog_Input_Create(1U);
    Analog_Input_Name_Set(1U, "Warning Codes");
    Analog_Input_Create(3U);
    Analog_Input_Name_Set(3U, "Capacity");
    Analog_Input_Create(4U);
    Analog_Input_Name_Set(4U, "Pressure");
    Analog_Input_Create(5U);
    Analog_Input_Name_Set(5U, "Flow");
    Analog_Input_Create(6U);
    Analog_Input_Name_Set(6U, "Relative Performance");
    Analog_Input_Create(7U);
    Analog_Input_Name_Set(7U, "Speed");
    Analog_Input_Create(9U);
    Analog_Input_Name_Set(9U, "Actual Setpoint");
    Analog_Input_Create(10U);
    Analog_Input_Name_Set(10U, "Motor Current");
    Analog_Input_Create(13U);
    Analog_Input_Name_Set(13U, "Power");
    Analog_Input_Create(18U);
    Analog_Input_Name_Set(18U, "Power Electronics Temp");
    Analog_Input_Create(22U);
    Analog_Input_Name_Set(22U, "Temperature");
    Analog_Input_Create(26U);
    Analog_Input_Name_Set(26U, "Specific Energy");
    Analog_Input_Create(27U);
    Analog_Input_Name_Set(27U, "Total Operating Time");
    Analog_Input_Create(28U);
    Analog_Input_Name_Set(28U, "Total On Time");
    Analog_Input_Create(30U);
    Analog_Input_Name_Set(30U, "Energy");
    Analog_Input_Create(57U);
    Analog_Input_Name_Set(57U, "Remote Temperature 2");
    Analog_Input_Create(58U);
    Analog_Input_Name_Set(58U, "User Setpoint");
    Analog_Input_Create(131U);
    Analog_Input_Name_Set(131U, "Min Frequency");
    Analog_Input_Create(132U);
    Analog_Input_Name_Set(132U, "Max Frequency");
}

void pump_profile_init_defaults(pump_state_t *state)
{
    memset(state, 0, sizeof(*state));
    state->control_mode_actual = 1U;
    state->control_mode_command = 1U;
    state->operating_mode_actual = 2U;
    state->operating_mode_command = 2U;
    state->bus_control = BINARY_ACTIVE;
    state->pump_ready = BINARY_ACTIVE;
    state->enable_status = BINARY_ACTIVE;
    state->command_setpoint_pct = 50.0f;
    state->watchdog_seconds = 60U;
    state->min_frequency_hz = 25.0f;
    state->max_frequency_hz = 60.0f;
    state->total_operating_time_h = 148.0f;
    state->total_on_time_h = 92.0f;
    state->total_energy_kwh = 26.0f;
    update_derived_state(state);
}

void pump_profile_seed_outputs(const pump_state_t *state)
{
    Binary_Output_Present_Value_Set(
        PUMP_BO_BUS_CONTROL, state->bus_control, BACNET_MAX_PRIORITY);
    Binary_Output_Present_Value_Set(
        PUMP_BO_RESET_FAULT, state->reset_fault, BACNET_MAX_PRIORITY);
    Binary_Output_Present_Value_Set(
        PUMP_BO_FAULT_SIMULATION, state->fault_simulation,
        BACNET_MAX_PRIORITY);
    Multistate_Output_Present_Value_Set(
        PUMP_MSO_CONTROL_MODE, state->control_mode_command,
        BACNET_MAX_PRIORITY);
    Multistate_Output_Present_Value_Set(
        PUMP_MSO_OPERATING_MODE, state->operating_mode_command,
        BACNET_MAX_PRIORITY);
    Analog_Output_Present_Value_Set(
        PUMP_AO_SETPOINT, state->command_setpoint_pct, BACNET_MAX_PRIORITY);
    Analog_Value_Present_Value_Set(
        PUMP_AV_WATCHDOG, (float)state->watchdog_seconds,
        BACNET_MAX_PRIORITY);
}

void pump_profile_register_write_callbacks(pump_state_t *state)
{
    Active_State = state;
    Binary_Output_Write_Present_Value_Callback_Set(binary_output_callback);
    Multistate_Output_Write_Present_Value_Callback_Set(
        multistate_output_callback);
    Analog_Output_Write_Present_Value_Callback_Set(analog_output_callback);
    Analog_Value_Write_Present_Value_Callback_Set(analog_value_callback);
}

void pump_profile_tick(pump_state_t *state, unsigned elapsed_seconds)
{
    float adjust;

    state->seconds_since_command += elapsed_seconds;

    if ((state->bus_control == BINARY_ACTIVE) &&
        (state->watchdog_seconds >= 5U) &&
        (state->seconds_since_command >= state->watchdog_seconds)) {
        state->bus_control = BINARY_INACTIVE;
        state->operating_mode_actual = 2U;
        printf("watchdog expired -> forcing LOCAL control\n");
    }

    if (state->run_status == BINARY_ACTIVE) {
        state->total_operating_time_h += (elapsed_seconds / 3600.0f);
        state->total_on_time_h += (elapsed_seconds / 3600.0f);
        state->total_energy_kwh +=
            ((state->power_watts / 1000.0f) * (elapsed_seconds / 3600.0f));
        adjust = (float)((state->seconds_since_command / 2U) % 5U) * 0.03f;
        state->pressure_bar += adjust;
        state->flow_lps += (adjust * 0.6f);
        state->power_watts += (adjust * 30.0f);
    }

    update_derived_state(state);
    pump_profile_publish(state);
}
