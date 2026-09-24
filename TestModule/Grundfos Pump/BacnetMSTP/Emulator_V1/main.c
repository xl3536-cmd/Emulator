#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bacnet/apdu.h"
#include "bacnet/dcc.h"
#include "bacnet/iam.h"
#include "bacnet/basic/npdu/h_npdu.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/service/h_cov.h"
#include "bacnet/basic/service/h_dcc.h"
#include "bacnet/basic/service/h_noserv.h"
#include "bacnet/basic/service/h_rd.h"
#include "bacnet/basic/service/h_rp.h"
#include "bacnet/basic/service/h_rpm.h"
#include "bacnet/basic/service/h_rr.h"
#include "bacnet/basic/service/h_ts.h"
#include "bacnet/basic/service/h_whohas.h"
#include "bacnet/basic/service/h_whois.h"
#include "bacnet/basic/service/h_wp.h"
#include "bacnet/basic/service/h_wpm.h"
#include "bacnet/basic/services.h"
#include "bacnet/basic/sys/debug.h"
#include "bacnet/basic/tsm/tsm.h"
#include "bacnet/datalink/datalink.h"
#include "bacnet/datalink/dlenv.h"
#include "bacnet/datalink/dlmstp.h"

#include "pump_profile.h"

#define DEFAULT_DEVICE_ID 227015U
#define DEFAULT_VENDOR_ID 227U
#define DEFAULT_DEVICE_NAME "Grundfos MAGNA3 Emulator"
#define DEFAULT_DESCRIPTION "CIM 300 style MS/TP emulator"
#define UPDATE_INTERVAL_SECONDS 2U

typedef struct emulator_config {
    uint32_t device_id;
    uint16_t vendor_id;
    char device_name[64];
    char description[96];
} emulator_config_t;

static emulator_config_t Emulator_Config;
static pump_state_t Pump_State;
static uint8_t Rx_Buf[MAX_MPDU] = { 0 };

static void print_address_summary(const BACNET_ADDRESS *address)
{
    unsigned i;

    printf("net=%u mac_len=%u mac=", (unsigned)address->net, (unsigned)address->mac_len);
    if (address->mac_len == 0U) {
        printf("none");
    } else {
        for (i = 0; i < address->mac_len; i++) {
            printf("%02X", address->mac[i]);
            if ((i + 1U) < address->mac_len) {
                printf(":");
            }
        }
    }
}

static void log_received_pdu(const BACNET_ADDRESS *src, const uint8_t *pdu, uint16_t pdu_len)
{
    unsigned i;
    unsigned dump_len = (pdu_len < 12U) ? pdu_len : 12U;

    printf("rx %u bytes from ", (unsigned)pdu_len);
    print_address_summary(src);
    printf(" head=");
    for (i = 0; i < dump_len; i++) {
        printf("%02X", pdu[i]);
        if ((i + 1U) < dump_len) {
            printf(" ");
        }
    }
    if (pdu_len > dump_len) {
        printf(" ...");
    }
    printf("\n");
    fflush(stdout);
}

static void usage(const char *program)
{
    printf(
        "Usage: %s [options]\n"
        "  --device-id <id>      pump BACnet device id (default 227015)\n"
        "  --vendor-id <id>      vendor id (default 227)\n"
        "  --name <name>         device object name\n"
        "  --description <text>  device description\n"
        "  --help                show help\n",
        program);
}

static int parse_u32(const char *text, uint32_t *value)
{
    char *endptr = NULL;
    unsigned long parsed = strtoul(text, &endptr, 10);

    if ((endptr == text) || (*endptr != '\0')) {
        return 0;
    }

    *value = (uint32_t)parsed;
    return 1;
}

static int parse_u16(const char *text, uint16_t *value)
{
    uint32_t parsed = 0;

    if (!parse_u32(text, &parsed) || (parsed > 65535U)) {
        return 0;
    }

    *value = (uint16_t)parsed;
    return 1;
}

static int parse_args(int argc, char *argv[])
{
    int i;

    memset(&Emulator_Config, 0, sizeof(Emulator_Config));
    Emulator_Config.device_id = DEFAULT_DEVICE_ID;
    Emulator_Config.vendor_id = DEFAULT_VENDOR_ID;
    strncpy(
        Emulator_Config.device_name, DEFAULT_DEVICE_NAME,
        sizeof(Emulator_Config.device_name) - 1U);
    strncpy(
        Emulator_Config.description, DEFAULT_DESCRIPTION,
        sizeof(Emulator_Config.description) - 1U);

    for (i = 1; i < argc; i++) {
        if ((strcmp(argv[i], "--device-id") == 0) && ((i + 1) < argc)) {
            if (!parse_u32(argv[++i], &Emulator_Config.device_id)) {
                return 0;
            }
        } else if ((strcmp(argv[i], "--vendor-id") == 0) && ((i + 1) < argc)) {
            if (!parse_u16(argv[++i], &Emulator_Config.vendor_id)) {
                return 0;
            }
        } else if ((strcmp(argv[i], "--name") == 0) && ((i + 1) < argc)) {
            strncpy(
                Emulator_Config.device_name, argv[++i],
                sizeof(Emulator_Config.device_name) - 1U);
        } else if ((strcmp(argv[i], "--description") == 0) && ((i + 1) < argc)) {
            strncpy(
                Emulator_Config.description, argv[++i],
                sizeof(Emulator_Config.description) - 1U);
        } else if (strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            exit(0);
        } else {
            return 0;
        }
    }

    return 1;
}

static void init_service_handlers(void)
{
    Device_Init(NULL);
    Device_Set_Object_Instance_Number(Emulator_Config.device_id);
    Device_Object_Name_ANSI_Init(Emulator_Config.device_name);
    Device_Set_Vendor_Identifier(Emulator_Config.vendor_id);
    Device_Set_Vendor_Name("Grundfos", strlen("Grundfos"));
    Device_Set_Model_Name("CIM 300", strlen("CIM 300"));
    Device_Set_Description(
        Emulator_Config.description, strlen(Emulator_Config.description));

    apdu_set_unrecognized_service_handler_handler(handler_unrecognized_service);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_WHO_IS, handler_who_is);
    apdu_set_unconfirmed_handler(SERVICE_UNCONFIRMED_WHO_HAS, handler_who_has);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_PROPERTY, handler_read_property);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_PROP_MULTIPLE, handler_read_property_multiple);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_WRITE_PROPERTY, handler_write_property);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_WRITE_PROP_MULTIPLE, handler_write_property_multiple);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_READ_RANGE, handler_read_range);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_REINITIALIZE_DEVICE, handler_reinitialize_device);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_TIME_SYNCHRONIZATION, handler_timesync);
    apdu_set_unconfirmed_handler(
        SERVICE_UNCONFIRMED_UTC_TIME_SYNCHRONIZATION, handler_timesync_utc);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_SUBSCRIBE_COV, handler_cov_subscribe);
    apdu_set_confirmed_handler(
        SERVICE_CONFIRMED_DEVICE_COMMUNICATION_CONTROL,
        handler_device_communication_control);
}

static void print_runtime_banner(void)
{
    BACNET_ADDRESS my_address = { 0 };

    datalink_get_my_address(&my_address);

    printf("BACnet MS/TP Grundfos pump emulator\n");
    printf("device-id:       %lu\n", (unsigned long)Emulator_Config.device_id);
    printf("vendor-id:       %u\n", Emulator_Config.vendor_id);
    printf("device-name:     %s\n", Emulator_Config.device_name);
    printf("description:     %s\n", Emulator_Config.description);
    printf("mstp-mac:        %u\n", (unsigned)my_address.mac[0]);
    printf("mstp-max-master: %u\n", (unsigned)dlmstp_max_master());
    printf("mstp-max-info:   %u\n", (unsigned)dlmstp_max_info_frames());
    printf("mstp-baud:       %lu\n", (unsigned long)dlmstp_baud_rate());
}

int main(int argc, char *argv[])
{
    BACNET_ADDRESS src = { 0 };
    uint16_t pdu_len = 0;
    unsigned timeout = 1000U;
    time_t last_seconds = 0;
    time_t last_tick = 0;
    time_t current_seconds = 0;
    uint32_t elapsed_seconds = 0;
    uint32_t elapsed_milliseconds = 0;

    if (!parse_args(argc, argv)) {
        usage(argv[0]);
        return 1;
    }

    init_service_handlers();
    dlenv_debug_enable();
    dlenv_init();
    atexit(datalink_cleanup);

    pump_profile_create_objects();
    pump_profile_init_defaults(&Pump_State);
    pump_profile_seed_outputs(&Pump_State);
    pump_profile_publish(&Pump_State);
    pump_profile_register_write_callbacks(&Pump_State);

    print_runtime_banner();
    Send_I_Am(&Handler_Transmit_Buffer[0]);
    printf("startup I-Am sent\n");
    fflush(stdout);

    last_seconds = time(NULL);
    last_tick = last_seconds;

    for (;;) {
        current_seconds = time(NULL);
        pdu_len = datalink_receive(&src, Rx_Buf, MAX_MPDU, timeout);
        if (pdu_len) {
            log_received_pdu(&src, Rx_Buf, pdu_len);
            npdu_handler(&src, Rx_Buf, pdu_len);
            printf("npdu_handler complete\n");
            fflush(stdout);
        }

        elapsed_seconds = (uint32_t)(current_seconds - last_seconds);
        if (elapsed_seconds > 0U) {
            last_seconds = current_seconds;
            dcc_timer_seconds(elapsed_seconds);
            datalink_maintenance_timer(elapsed_seconds);
            dlenv_maintenance_timer(elapsed_seconds);
            elapsed_milliseconds = elapsed_seconds * 1000U;
            tsm_timer_milliseconds(elapsed_milliseconds);
            Device_Timer(elapsed_milliseconds);
        }

        if ((current_seconds - last_tick) >= UPDATE_INTERVAL_SECONDS) {
            pump_profile_tick(&Pump_State, UPDATE_INTERVAL_SECONDS);
            last_tick = current_seconds;
        }

        handler_cov_task();
    }

    return 0;
}
