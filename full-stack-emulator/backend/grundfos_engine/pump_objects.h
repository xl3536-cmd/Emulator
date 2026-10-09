#ifndef PUMP_OBJECTS_H
#define PUMP_OBJECTS_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    double flow_gpm;
    double pressure_psi;
    double power_w;
    double current_a;
    double temperature_c;
    double remote_temperature_c;
    double electronics_temperature_c;
    double operating_hours;
    double on_hours;
    unsigned fault_code;
    unsigned warning_code;
    unsigned control_mode;
    unsigned operating_mode;
    double setpoint;
    bool bus_control;
} PumpConfig;

void pump_config_defaults(PumpConfig *config);
bool pump_objects_init(const PumpConfig *config, uint32_t device_id, const char *name);
void pump_tick(double seconds);
void pump_print_status(void);
void pump_print_snapshot(void);
bool pump_set_simulation(const char *field, double value);

#endif
