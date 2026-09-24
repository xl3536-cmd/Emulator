#ifndef NYSERDA_MSTP_PUMP_PROFILE_H
#define NYSERDA_MSTP_PUMP_PROFILE_H

#include <stdint.h>

#include "bacnet/bacdef.h"

#define PUMP_BI_READY 0U
#define PUMP_BI_RUN_STATUS 1U
#define PUMP_BI_PUMP_RUNNING 2U
#define PUMP_BI_POWER_LIMIT 31U
#define PUMP_BI_ENABLE_STATUS 65U

#define PUMP_BO_BUS_CONTROL 0U
#define PUMP_BO_RESET_FAULT 4U
#define PUMP_BO_FAULT_SIMULATION 5U

#define PUMP_MSI_CONTROL_MODE 0U
#define PUMP_MSI_OPERATING_MODE 1U
#define PUMP_MSI_CIM_STATUS 3U

#define PUMP_MSO_CONTROL_MODE 0U
#define PUMP_MSO_OPERATING_MODE 1U

#define PUMP_AO_SETPOINT 0U
#define PUMP_AV_WATCHDOG 1U

typedef struct pump_state {
    uint32_t control_mode_actual;
    uint32_t control_mode_command;
    uint32_t operating_mode_actual;
    uint32_t operating_mode_command;
    BACNET_BINARY_PV bus_control;
    BACNET_BINARY_PV pump_ready;
    BACNET_BINARY_PV run_status;
    BACNET_BINARY_PV pump_running;
    BACNET_BINARY_PV power_limit;
    BACNET_BINARY_PV enable_status;
    BACNET_BINARY_PV reset_fault;
    BACNET_BINARY_PV fault_simulation;
    float fault_code;
    float warning_code;
    float capacity_pct;
    float pressure_bar;
    float flow_lps;
    float relative_performance_pct;
    float speed_pct;
    float actual_setpoint;
    float command_setpoint_pct;
    float motor_current;
    float power_watts;
    float power_electronics_temp_c;
    float fluid_temp_c;
    float specific_energy;
    float total_operating_time_h;
    float total_on_time_h;
    float total_energy_kwh;
    float remote_temperature_2_c;
    float user_setpoint;
    float min_frequency_hz;
    float max_frequency_hz;
    uint32_t cim_status;
    uint32_t watchdog_seconds;
    uint32_t seconds_since_command;
} pump_state_t;

const char *pump_profile_operating_mode_name(uint32_t value);
const char *pump_profile_control_mode_name(uint32_t value);

void pump_profile_create_objects(void);
void pump_profile_init_defaults(pump_state_t *state);
void pump_profile_publish(const pump_state_t *state);
void pump_profile_seed_outputs(const pump_state_t *state);
void pump_profile_register_write_callbacks(pump_state_t *state);
void pump_profile_tick(pump_state_t *state, unsigned elapsed_seconds);

#endif
