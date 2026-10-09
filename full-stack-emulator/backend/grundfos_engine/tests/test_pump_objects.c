#include "pump_objects.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bacnet/bacdcode.h"
#include "bacnet/basic/object/device.h"
#include "bacnet/basic/object/ai.h"
#include "bacnet/basic/object/ao.h"
#include "bacnet/basic/object/bi.h"
#include "bacnet/basic/object/ms-input.h"

#define CHECK(test) do { if (!(test)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #test); exit(1); } } while (0)
#define NEAR(a, b) (fabs((double)(a) - (double)(b)) < 0.01)

static bool write_value(BACNET_OBJECT_TYPE type, unsigned instance, double value, unsigned priority, bool null_value)
{
    uint8_t data[32];
    int length;
    if (null_value) length = encode_application_null(data);
    else if (type == OBJECT_ANALOG_OUTPUT || type == OBJECT_ANALOG_INPUT)
        length = encode_application_real(data, (float)value);
    else length = encode_application_unsigned(data, (uint32_t)value);
    BACNET_WRITE_PROPERTY_DATA wp = {.object_type = type, .object_instance = instance,
        .object_property = PROP_PRESENT_VALUE, .array_index = BACNET_ARRAY_ALL,
        .priority = priority, .application_data_len = length};
    memcpy(wp.application_data, data, length);
    return Device_Write_Property(&wp);
}

int main(void)
{
    PumpConfig c;
    pump_config_defaults(&c);
    CHECK(pump_objects_init(&c, 227011, "Pump test"));
    CHECK(Analog_Input_Count() == 16);
    CHECK(Binary_Input_Count() == 2);
    CHECK(Multistate_Input_Count() == 3);
    CHECK(Device_Vendor_Identifier() == 227);
    CHECK(Device_Segmentation_Supported() == SEGMENTATION_NONE);
    CHECK(NEAR(Analog_Input_Present_Value(5), 0));
    /* A command staged in local control must not start the pump. */
    CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 1, 1, false));
    CHECK(Multistate_Input_Present_Value(1) == 2);
    CHECK(write_value(OBJECT_BINARY_OUTPUT, 0, 1, 1, false));
    CHECK(Binary_Input_Present_Value(0) == 1);
    CHECK(Binary_Input_Present_Value(31) == 1); /* original src BO0 confirmation */
    CHECK(Multistate_Input_Present_Value(1) == 1);
    CHECK(Analog_Input_Present_Value(5) > 0);
    unsigned modes[] = {1, 2, 3, 4, 5, 6, 9, 12};
    for (unsigned i = 0; i < sizeof(modes) / sizeof(modes[0]); ++i) {
        CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 0, modes[i], 1, false));
        CHECK(Multistate_Input_Present_Value(0) == modes[i]);
    }
    CHECK(!write_value(OBJECT_MULTI_STATE_OUTPUT, 0, 7, 1, false));
    CHECK(!write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 0, 1, false));
    CHECK(!write_value(OBJECT_ANALOG_INPUT, 5, 42, 1, false));
    CHECK(!write_value(OBJECT_ANALOG_OUTPUT, 0, 101, 1, false));
    CHECK(!write_value(OBJECT_ANALOG_OUTPUT, 0, NAN, 1, false));
    CHECK(!write_value(OBJECT_ANALOG_OUTPUT, 5, -1, 1, false));
    CHECK(!write_value(OBJECT_BINARY_OUTPUT, 0, 2, 1, false));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 0, 65, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(9), 65));
    CHECK(NEAR(Analog_Input_Present_Value(58), 65));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 0, 30, 8, false));
    CHECK(NEAR(Analog_Input_Present_Value(9), 65));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 0, 0, 1, true));
    CHECK(NEAR(Analog_Input_Present_Value(9), 30));
    CHECK(!write_value(OBJECT_ANALOG_OUTPUT, 0, 80, 6, false));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 5, 2.0, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(5) * 4.4, 2.0));
    CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 2, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(5) * 4.4, 2.0)); /* command echo while stopped */
    CHECK(NEAR(Analog_Input_Present_Value(13), 0));
    pump_tick(3600);
    CHECK(NEAR(Analog_Input_Present_Value(27), 0));
    CHECK(NEAR(Analog_Input_Present_Value(28), 1));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 0, 0, 1, false));
    CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 1, 1, false));
    CHECK(Analog_Input_Present_Value(5) > 0); /* zero setpoint is not stop */
    pump_tick(3600);
    CHECK(NEAR(Analog_Input_Present_Value(27), 1));
    CHECK(NEAR(Analog_Input_Present_Value(28), 2));
    CHECK(write_value(OBJECT_BINARY_OUTPUT, 0, 0, 1, false));
    CHECK(Binary_Input_Present_Value(0) == 0);
    CHECK(Binary_Input_Present_Value(31) == 0);
    CHECK(Multistate_Input_Present_Value(1) == 2);
    CHECK(pump_set_simulation("local_operating_mode", 1));
    CHECK(Multistate_Input_Present_Value(1) == 1);
    CHECK(pump_set_simulation("fault_code", 42));
    CHECK(NEAR(Analog_Input_Present_Value(0), 42));
    CHECK(NEAR(Analog_Input_Present_Value(5), 0));
    CHECK(pump_set_simulation("fault_code", 0));
    CHECK(Analog_Input_Present_Value(5) > 0);
    CHECK(!pump_set_simulation("fault_code", 1.5));
    CHECK(!pump_set_simulation("temperature_c", NAN));
    CHECK(!pump_set_simulation("local_control_mode", 7));
    CHECK(write_value(OBJECT_BINARY_OUTPUT, 0, 1, 1, false));
    CHECK(pump_set_simulation("local_operating_mode", 2));
    CHECK(Multistate_Input_Present_Value(1) == 1); /* bus retains authority */
    /* Web commands and controller writes share the same priority slot. */
    CHECK(pump_set_simulation("command_setpoint", 72));
    CHECK(NEAR(Analog_Input_Present_Value(9), 72));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 0, 64, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(9), 64));
    CHECK(pump_set_simulation("release_command_setpoint", 0));
    CHECK(NEAR(Analog_Input_Present_Value(9), 30)); /* priority 8 still present */
    CHECK(!pump_set_simulation("command_control_mode", 7));
    CHECK(!pump_set_simulation("command_operating_mode", 0));
    CHECK(!pump_set_simulation("command_bus_control", 1.5));
    CHECK(!pump_set_simulation("command_setpoint", 101));
    CHECK(pump_set_simulation("command_max_flow", 0.5));
    CHECK(NEAR(Analog_Output_Present_Value(5), 0.5));
    CHECK(round((double)Analog_Input_Present_Value(5) * 4.4 * 100) / 100 == 0.5);
    CHECK(!pump_set_simulation("power_limit", 1)); /* BI31 follows bus authority */
    CHECK(Binary_Input_Present_Value(31) == 1);
    CHECK(pump_set_simulation("command_bus_control", 0));
    CHECK(Binary_Input_Present_Value(0) == 0);
    CHECK(Binary_Input_Present_Value(31) == 0);
    CHECK(pump_set_simulation("command_bus_control", 1));
    CHECK(pump_set_simulation("cim_status", 3));
    CHECK(Multistate_Input_Present_Value(3) == 3);
    CHECK(pump_set_simulation("ai_5", 8));
    CHECK(NEAR(Analog_Input_Present_Value(5), 8));
    CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 2, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(5), 8)); /* deliberate sensor override */
    CHECK(!write_value(OBJECT_ANALOG_INPUT, 5, 9, 1, false));
    CHECK(pump_set_simulation("clear_ai_5", 0));
    CHECK(NEAR(Analog_Input_Present_Value(5) * 4.4, 0.5));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 5, 1.25, 8, false));
    CHECK(NEAR(Analog_Input_Present_Value(5) * 4.4, 0.5)); /* priority 1 wins */
    CHECK(pump_set_simulation("release_command_max_flow", 0));
    CHECK(NEAR(Analog_Input_Present_Value(5) * 4.4, 1.25));
    CHECK(write_value(OBJECT_ANALOG_OUTPUT, 5, 0, 8, true));
    CHECK(NEAR(Analog_Input_Present_Value(5), 0));
    CHECK(pump_set_simulation("ai_5", 8));
    CHECK(pump_set_simulation("command_max_flow", 12.34));
    CHECK(round((double)Analog_Input_Present_Value(5) * 4.4 * 100) / 100 == 12.34);
    CHECK(pump_set_simulation("release_command_max_flow", 0));
    CHECK(NEAR(Analog_Input_Present_Value(5), 0));
    CHECK(!pump_set_simulation("ai_9", 12)); /* command feedback cannot freeze */
    CHECK(!pump_set_simulation("ai_3", 101));
    CHECK(pump_set_simulation("on_hours", 100));
    CHECK(pump_set_simulation("operating_hours", 50));
    CHECK(!pump_set_simulation("on_hours", 49));
    CHECK(!pump_set_simulation("operating_hours", 101));
    puts("PASS: read/write contract, bus control, modes, priorities, validation, stop and timers");
    return 0;
}
