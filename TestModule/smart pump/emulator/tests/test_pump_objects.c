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
    CHECK(Binary_Input_Present_Value(31) == 0);
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
    CHECK(NEAR(Analog_Input_Present_Value(5), 2.0));
    CHECK(write_value(OBJECT_MULTI_STATE_OUTPUT, 1, 2, 1, false));
    CHECK(NEAR(Analog_Input_Present_Value(5), 0));
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
    puts("PASS: read/write contract, bus control, modes, priorities, validation, stop and timers");
    return 0;
}
