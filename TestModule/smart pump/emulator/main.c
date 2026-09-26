#include "pump_objects.h"
#include <errno.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <unistd.h>
#include "bacnet/apdu.h"
#include "bacnet/dcc.h"
#include "bacnet/npdu.h"
#include "bacnet/basic/binding/address.h"
#include "bacnet/basic/services.h"
#include "bacnet/basic/sys/mstimer.h"
#include "bacnet/basic/tsm/tsm.h"
#include "bacnet/datalink/datalink.h"
#include "bacnet/datalink/dlenv.h"

static volatile sig_atomic_t keep_running = 1;
static void stop(int signal_number) { (void)signal_number; keep_running = 0; }

/* Only enabled by run.py --interactive. Read complete lines without ever
 * blocking the MS/TP loop on a partial pipe message. */
static void poll_controls(void)
{
    static bool eof = false, overflow = false;
    static char line[256];
    static size_t used = 0;
    if (eof) return;
    fd_set ready;
    FD_ZERO(&ready);
    FD_SET(STDIN_FILENO, &ready);
    struct timeval timeout = {0, 0};
    if (select(STDIN_FILENO + 1, &ready, NULL, NULL, &timeout) <= 0) return;
    char chunk[256];
    ssize_t count = read(STDIN_FILENO, chunk, sizeof(chunk));
    if (count == 0) { eof = true; return; }
    if (count < 0) return;
    for (ssize_t i = 0; i < count; ++i) {
        char ch = chunk[i];
        if (ch == '\n') {
            line[used] = '\0';
            if (overflow) puts("ERROR control line too long");
            else if (strcmp(line, "status") == 0) pump_print_snapshot();
            else {
                char field[64], extra;
                double value;
                if (sscanf(line, "set %63s %lf %c", field, &value, &extra) != 2 ||
                    !pump_set_simulation(field, value)) {
                    puts("ERROR invalid simulation field or value");
                } else {
                    printf("APPLIED %s %.9g\n", field, value);
                    pump_print_snapshot();
                }
            }
            fflush(stdout);
            used = 0;
            overflow = false;
        } else if (ch != '\r') {
            if (used + 1 < sizeof(line)) line[used++] = ch;
            else overflow = true;
        }
    }
}

static double env_number(const char *name, double fallback, double min, double max)
{
    const char *text = getenv(name);
    char *end;
    if (!text) return fallback;
    errno = 0;
    double result = strtod(text, &end);
    if (errno || end == text || *end || !isfinite(result) || result < min || result > max) {
        fprintf(stderr, "Invalid %s: expected %g..%g\n", name, min, max);
        exit(2);
    }
    return result;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--transport") == 0) {
#ifdef PUMP_TEST_BIP
        puts("bip-test");
#elif defined(PUMP_GROUP_WORKER)
        puts("mstp-worker-1");
#else
        puts("mstp");
#endif
        return 0;
    }
    if (argc != 1) {
        fprintf(stderr, "Run with python3 run.py --config config.json\n");
        return 2;
    }
    PumpConfig c;
    pump_config_defaults(&c);
    c.flow_gpm = env_number("PUMP_FLOW_GPM", c.flow_gpm, 0, 1000000);
    c.pressure_psi = env_number("PUMP_PRESSURE_PSI", c.pressure_psi, 0, 1000000);
    c.power_w = env_number("PUMP_POWER_W", c.power_w, 0, 1000000);
    c.current_a = env_number("PUMP_CURRENT_A", c.current_a, 0, 1000000);
    c.temperature_c = env_number("PUMP_TEMPERATURE_C", c.temperature_c, -273.15, 1000);
    c.remote_temperature_c = env_number("PUMP_REMOTE_TEMPERATURE_C", c.remote_temperature_c, -273.15, 1000);
    c.electronics_temperature_c = env_number("PUMP_ELECTRONICS_TEMPERATURE_C", c.electronics_temperature_c, -273.15, 1000);
    c.operating_hours = env_number("PUMP_OPERATING_HOURS", 0, 0, 10000000);
    c.on_hours = env_number("PUMP_ON_HOURS", 0, c.operating_hours, 10000000);
    c.setpoint = env_number("PUMP_SETPOINT", c.setpoint, 0, 100);
    c.control_mode = (unsigned)env_number("PUMP_CONTROL_MODE", c.control_mode, 1, 12);
    c.operating_mode = (unsigned)env_number("PUMP_OPERATING_MODE", c.operating_mode, 1, 4);
    c.fault_code = (unsigned)env_number("PUMP_FAULT_CODE", 0, 0, 65535);
    c.warning_code = (unsigned)env_number("PUMP_WARNING_CODE", 0, 0, 65535);
    c.bus_control = env_number("PUMP_BUS_CONTROL", 0, 0, 1) != 0;
    uint32_t device_id = (uint32_t)env_number("PUMP_DEVICE_ID", xxxxxx, 0, 4194302);
    const char *name = getenv("PUMP_NAME");
    if (!name) name = "Grundfos Pump Emulator";
    if (!pump_objects_init(&c, device_id, name)) {
        fprintf(stderr, "Cannot initialize pump objects. Check settings and object name.\n");
        return 2;
    }
    address_init();
    apdu_set_unrecognized_service_handler_handler(handler_unrecognized_service);
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_WHO_IS, handler_who_is);
    apdu_set_confirmed_handler(SERVICE_CONFIRMED_READ_PROPERTY, handler_read_property);
    apdu_set_confirmed_handler(SERVICE_CONFIRMED_READ_PROP_MULTIPLE, handler_read_property_multiple);
    apdu_set_confirmed_handler(SERVICE_CONFIRMED_WRITE_PROPERTY, handler_write_property);
    signal(SIGINT, stop);
    signal(SIGTERM, stop);
    dlenv_init();
    atexit(datalink_cleanup);
    printf("Pump ready: device=%u name=%s max_apdu=480 segmentation=none\n", device_id, name);
    pump_print_status();
    bool interactive = getenv("PUMP_GUI_CONTROL") != NULL;
    if (interactive) pump_print_snapshot();
    Send_I_Am(Handler_Transmit_Buffer);
    unsigned long last_tick = mstimer_now(), last_maintenance = last_tick;
    uint8_t buffer[MAX_MPDU];
    while (keep_running) {
        if (interactive) poll_controls();
        BACNET_ADDRESS source = {0};
        uint16_t length = datalink_receive(&source, buffer, sizeof(buffer), 20);
        unsigned long now = mstimer_now();
        unsigned long elapsed = now - last_tick;
        last_tick = now;
        pump_tick(elapsed / 1000.0);
        if (elapsed) tsm_timer_milliseconds((uint16_t)(elapsed > 65535 ? 65535 : elapsed));
        if (length) npdu_handler(&source, buffer, length);
        unsigned long seconds = (now - last_maintenance) / 1000;
        if (seconds) {
            last_maintenance += seconds * 1000;
            dcc_timer_seconds((unsigned)seconds);
            datalink_maintenance_timer((unsigned)seconds);
            dlenv_maintenance_timer((unsigned)seconds);
            if (interactive) pump_print_snapshot();
        }
    }
    puts("Pump emulator stopped.");
    return 0;
}
