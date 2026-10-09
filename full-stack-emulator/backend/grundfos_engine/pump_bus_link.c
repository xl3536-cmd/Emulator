/* Pump application side of the grouped MS/TP transport. GNU ld --wrap keeps
 * the existing single-device executable and the vendor sources unchanged.
 * Only the group manager opens serial hardware. This process retains its own
 * BACnet objects, output priority arrays, device identity and service handlers. */
#include "group_ipc.h"
#include <errno.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <signal.h>
#include <unistd.h>
#include "bacnet/datalink/dlmstp.h"

static int bus_fd = -1;

static void disconnected(void)
{
    fputs("ERROR group transport disconnected\n", stderr);
    exit(3);
}

bool __wrap_dlmstp_init(const char *ifname)
{
    (void)ifname;
    const char *text = getenv("PUMP_BUS_FD");
    const char *parent = getenv("PUMP_PARENT_PID");
    char *end;
    if (!text || !parent) {
        fputs("Use run_group.py to launch pump_worker\n", stderr);
        return false;
    }
    long fd = strtol(text, &end, 10);
    if (*end || fd < 3 || fd > INT_MAX) return false;
    int socket_type = 0;
    socklen_t size = sizeof(socket_type);
    if (getsockopt((int)fd, SOL_SOCKET, SO_TYPE, &socket_type, &size) ||
        socket_type != SOCK_SEQPACKET) return false;
    if (prctl(PR_SET_PDEATHSIG, SIGTERM) || getppid() != (pid_t)strtol(parent, NULL, 10))
        return false;
    bus_fd = (int)fd;
    return true;
}

void __wrap_dlmstp_cleanup(void)
{
    if (bus_fd >= 0) close(bus_fd);
    bus_fd = -1;
}

int __wrap_dlmstp_send_pdu(BACNET_ADDRESS *dest, BACNET_NPDU_DATA *npdu,
    uint8_t *pdu, unsigned length)
{
    if (bus_fd < 0 || !length || length > PUMP_NPDU_MAX) return 0;
    uint8_t packet[PUMP_IPC_MAX];
    packet[0] = dest && dest->mac_len ? dest->mac[0] : 255;
    packet[1] = npdu && npdu->data_expecting_reply ? 1 : 0;
    memcpy(packet + PUMP_IPC_HEADER, pdu, length);
    ssize_t count;
    do {
        count = send(bus_fd, packet, length + PUMP_IPC_HEADER, MSG_DONTWAIT | MSG_NOSIGNAL);
    } while (count < 0 && errno == EINTR);
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
        fputs("ERROR group transmit queue full\n", stderr);
        return 0;
    }
    if (count != (ssize_t)(length + PUMP_IPC_HEADER)) disconnected();
    return (int)length;
}

uint16_t __wrap_dlmstp_receive(BACNET_ADDRESS *source, uint8_t *pdu,
    uint16_t maximum, unsigned timeout)
{
    struct pollfd descriptor = {.fd = bus_fd, .events = POLLIN};
    int result = poll(&descriptor, 1, timeout > INT_MAX ? INT_MAX : (int)timeout);
    if (result < 0 && errno == EINTR) return 0;
    if (result < 0) disconnected();
    if (!result) return 0;
    uint8_t packet[PUMP_IPC_MAX];
    ssize_t count = recv(bus_fd, packet, sizeof(packet), MSG_DONTWAIT | MSG_TRUNC);
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return 0;
    if (count <= 0) disconnected();
    if (count <= PUMP_IPC_HEADER || count > (ssize_t)sizeof(packet) ||
        count - PUMP_IPC_HEADER > maximum) return 0;
    if (source) {
        memset(source, 0, sizeof(*source));
        source->mac_len = 1;
        source->mac[0] = packet[0];
    }
    memcpy(pdu, packet + PUMP_IPC_HEADER, (size_t)count - PUMP_IPC_HEADER);
    return (uint16_t)(count - PUMP_IPC_HEADER);
}
