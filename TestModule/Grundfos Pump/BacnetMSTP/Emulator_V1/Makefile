PREFIX ?=
CC = $(PREFIX)gcc
SIZE = $(PREFIX)size

BACDL ?= mstp
BACNET_PORT ?= linux

TARGET = nyserda_bacnet_emulator_mstp

BACNET_STACK_DIR ?= $(realpath ../bacnet-stack)
BACNET_LIB_DIR = $(realpath $(BACNET_STACK_DIR)/apps/lib)
BACNET_LIB_TARGET = $(BACNET_LIB_DIR)/libbacnet.a
BACNET_SRC_DIR = $(realpath $(BACNET_STACK_DIR)/src)
BACNET_PORT_DIR = $(realpath $(BACNET_STACK_DIR)/ports/$(BACNET_PORT))
BACNET_POSIX_DIR = $(realpath $(BACNET_STACK_DIR)/ports/posix)
BACNET_OBJECT_DIR = $(BACNET_SRC_DIR)/bacnet/basic/object

ifeq ($(BACDL),mstp)
BACDL_DEFINE = -DBACDL_MSTP=1
endif

PFLAGS = -pthread
SYSTEM_LIB = -lc,-lgcc,-lrt,-lm

CSTANDARD ?= -std=gnu89
OPTIMIZATION ?= -Os
DEBUGGING ?=
WARNINGS = -Wall -Wextra -pedantic -Wfloat-equal -Wredundant-decls -Wswitch-default
WARNINGS += -Wunused-variable -Wno-sign-conversion -Wno-conversion -Wno-sign-compare
WARNINGS += -Wno-long-long -Wno-attributes -Wno-implicit-fallthrough

BACNET_DEFINES := $(BACDL_DEFINE)
BACNET_DEFINES += -DWEAK_FUNC=
BACNET_DEFINES += -DBACAPP_ALL
BACNET_DEFINES += -DBACNET_TIME_MASTER
BACNET_DEFINES += -DBACNET_BACKUP_RESTORE
BACNET_DEFINES += -DBACNET_PROPERTY_LISTS=1
BACNET_DEFINES += -DBACNET_PROTOCOL_REVISION=28
BACNET_DEFINES += -DPRINT_ENABLED=1
BACNET_DEFINES += -DINTRINSIC_REPORTING

INCLUDES = -I$(BACNET_SRC_DIR) -I$(BACNET_PORT_DIR) -I$(BACNET_POSIX_DIR)
CFLAGS := $(WARNINGS) $(DEBUGGING) $(OPTIMIZATION) $(BACNET_DEFINES) $(INCLUDES) $(CSTANDARD)
CFLAGS += -ffunction-sections -fdata-sections
LFLAGS := -L$(BACNET_LIB_DIR) -lbacnet
LFLAGS += -Wl,$(SYSTEM_LIB) -Wl,--gc-sections

SRC := main.c pump_profile.c

BACNET_OBJECT_SRC := \
	$(BACNET_OBJECT_DIR)/device.c \
	$(BACNET_OBJECT_DIR)/access_credential.c \
	$(BACNET_OBJECT_DIR)/access_door.c \
	$(BACNET_OBJECT_DIR)/access_point.c \
	$(BACNET_OBJECT_DIR)/access_rights.c \
	$(BACNET_OBJECT_DIR)/access_user.c \
	$(BACNET_OBJECT_DIR)/access_zone.c \
	$(BACNET_OBJECT_DIR)/ai.c \
	$(BACNET_OBJECT_DIR)/ao.c \
	$(BACNET_OBJECT_DIR)/av.c \
	$(BACNET_OBJECT_DIR)/acc.c \
	$(BACNET_OBJECT_DIR)/auditlog.c \
	$(BACNET_OBJECT_DIR)/bacfile.c \
	$(BACNET_OBJECT_DIR)/bi.c \
	$(BACNET_OBJECT_DIR)/bitstring_value.c \
	$(BACNET_OBJECT_DIR)/bo.c \
	$(BACNET_OBJECT_DIR)/blo.c \
	$(BACNET_OBJECT_DIR)/bv.c \
	$(BACNET_OBJECT_DIR)/calendar.c \
	$(BACNET_OBJECT_DIR)/channel.c \
	$(BACNET_OBJECT_DIR)/color_object.c \
	$(BACNET_OBJECT_DIR)/color_temperature.c \
	$(BACNET_OBJECT_DIR)/command.c \
	$(BACNET_OBJECT_DIR)/credential_data_input.c \
	$(BACNET_OBJECT_DIR)/csv.c \
	$(BACNET_OBJECT_DIR)/iv.c \
	$(BACNET_OBJECT_DIR)/lc.c \
	$(BACNET_OBJECT_DIR)/lo.c \
	$(BACNET_OBJECT_DIR)/loop.c \
	$(BACNET_OBJECT_DIR)/lsp.c \
	$(BACNET_OBJECT_DIR)/lsz.c \
	$(BACNET_OBJECT_DIR)/ms-input.c \
	$(BACNET_OBJECT_DIR)/mso.c \
	$(BACNET_OBJECT_DIR)/msv.c \
	$(BACNET_OBJECT_DIR)/nc.c \
	$(BACNET_OBJECT_DIR)/netport.c \
	$(BACNET_OBJECT_DIR)/osv.c \
	$(BACNET_OBJECT_DIR)/piv.c \
	$(BACNET_OBJECT_DIR)/program.c \
	$(BACNET_OBJECT_DIR)/schedule.c \
	$(BACNET_OBJECT_DIR)/structured_view.c \
	$(BACNET_OBJECT_DIR)/time_value.c \
	$(BACNET_OBJECT_DIR)/timer.c \
	$(BACNET_OBJECT_DIR)/trendlog.c

SRCS := $(SRC) $(BACNET_OBJECT_SRC)
OBJS := $(SRCS:.c=.o)

.PHONY: all clean stack-clean

all: $(BACNET_LIB_TARGET) $(TARGET)

$(BACNET_LIB_TARGET):
	$(MAKE) -C $(BACNET_LIB_DIR) \
		BACDL=$(BACDL) \
		BACNET_PORT=$(BACNET_PORT) \
		BACNET_DEFINES='$(BACNET_DEFINES)'

$(TARGET): $(OBJS) $(BACNET_LIB_TARGET)
	$(CC) $(PFLAGS) $(OBJS) $(LFLAGS) -o $@
	$(SIZE) $@

.c.o:
	$(CC) -c $(CFLAGS) $*.c -o $@

clean:
	rm -f $(TARGET) $(OBJS)

stack-clean:
	$(MAKE) -C $(BACNET_LIB_DIR) clean
	find $(BACNET_SRC_DIR) -name '*.o' -delete
	find $(BACNET_STACK_DIR)/ports -name '*.o' -delete
	find $(BACNET_LIB_DIR) -name '*.a' -delete
