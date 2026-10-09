/* One physical UART, multiple independent BACnet MS/TP master stations.
 * Reuses the vendor Receive/Master FSMs, including CRCs, PFM discovery, token
 * recovery and Reply Postponed. No MAC rewriting and no multiple UART owners.
 * All stations see both physical RX and frames sent by other local stations.
 * The pump applications live in isolated processes connected by packet sockets.
 */
#include "group_ipc.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>
#include "bacnet/datalink/mstp.h"
#include "bacnet/npdu.h"
#include "termios2.h"

#define RX_CAPACITY 4096
#define TX_CAPACITY 32
#define FRAME_CAPACITY (PUMP_NPDU_MAX + 10)

typedef struct {
    uint8_t peer, der;
    uint16_t length;
    uint8_t data[PUMP_NPDU_MAX];
} Packet;

typedef struct {
    struct mstp_port_struct_t port;
    int fd;
    uint8_t input[PUMP_NPDU_MAX], output[FRAME_CAPACITY];
    uint8_t rx[RX_CAPACITY];
    size_t rx_head, rx_count;
    Packet tx[TX_CAPACITY];
    unsigned tx_count;
    uint64_t last_octet;
    unsigned long received, transmitted;
} Station;

static Station stations[PUMP_GROUP_MAX];
static unsigned station_count;
static unsigned long send_generation;
static volatile sig_atomic_t running = 1;
static bool failed;
static uint64_t bus_activity;
static int serial_fd = -1;
static unsigned serial_baud;
static struct termios2 saved_termios;
static bool saved_termios_valid;

static uint64_t real_clock(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000000 + (uint64_t)now.tv_nsec / 1000;
}

/* Injectable clock/writer allow object-level tests without serial hardware. */
static uint64_t (*clock_us)(void) = real_clock;
static bool (*wire_write)(const uint8_t *, size_t);

static void fail_bus(const char *message)
{
    fprintf(stderr, "ERROR bus: %s\n", message);
    failed = true;
    running = 0;
}

static uint32_t silence(void *arg)
{
    struct mstp_port_struct_t *port = arg;
    Station *s = port->UserData;
    uint64_t elapsed = (clock_us() - s->last_octet) / 1000;
    return elapsed > UINT32_MAX ? UINT32_MAX : (uint32_t)elapsed;
}

static void silence_reset(void *arg)
{
    struct mstp_port_struct_t *port = arg;
    ((Station *)port->UserData)->last_octet = clock_us();
}

static void receive_bytes(const uint8_t *bytes, size_t count, const Station *sender)
{
    uint64_t now = clock_us();
    bus_activity = now;
    for (unsigned i = 0; i < station_count; ++i) {
        Station *s = &stations[i];
        /* Shared physical line activity resets every station's silence timer,
         * including the sender. Only peers receive the actual frame bytes. */
        s->last_octet = now;
        if (s == sender) continue;
        if (count > RX_CAPACITY - s->rx_count) {
            fail_bus("station RX queue overflow");
            return;
        }
        for (size_t j = 0; j < count; ++j)
            s->rx[(s->rx_head + s->rx_count++) % RX_CAPACITY] = bytes[j];
    }
}

void MSTP_Send_Frame(struct mstp_port_struct_t *port, const uint8_t *frame, uint16_t size)
{
    Station *s = port->UserData;
    if (!running) return;
    /* This synchronous writer returns only after bytes have left the UART.
     * Thus token/reply timers start at real TX completion, not at IPC enqueue. */
    if (!wire_write || !wire_write(frame, size)) {
        fail_bus("serial transmission failed");
        return;
    }
    s->transmitted++;
    send_generation++;
    receive_bytes(frame, size, s);
}

uint16_t MSTP_Put_Receive(struct mstp_port_struct_t *port)
{
    Station *s = port->UserData;
    if (!port->DataLength || port->DataLength > PUMP_NPDU_MAX) return 0;
    uint8_t packet[PUMP_IPC_MAX];
    packet[0] = port->SourceAddress;
    packet[1] = port->FrameType == FRAME_TYPE_BACNET_DATA_EXPECTING_REPLY ? 1 : 0;
    memcpy(packet + PUMP_IPC_HEADER, port->InputBuffer, port->DataLength);
    ssize_t sent;
    do {
        sent = send(s->fd, packet, port->DataLength + PUMP_IPC_HEADER, MSG_DONTWAIT | MSG_NOSIGNAL);
    } while (sent < 0 && errno == EINTR);
    if (sent != port->DataLength + PUMP_IPC_HEADER) {
        fail_bus("pump IPC receive queue full or disconnected");
        return 0;
    }
    s->received++;
    return port->DataLength;
}

static uint16_t take_packet(Station *s, unsigned index)
{
    Packet *p = &s->tx[index];
    uint8_t type = p->der ? FRAME_TYPE_BACNET_DATA_EXPECTING_REPLY : FRAME_TYPE_BACNET_DATA_NOT_EXPECTING_REPLY;
    uint16_t length = MSTP_Create_Frame(s->output, sizeof(s->output), type,
        p->peer, s->port.This_Station, p->data, p->length);
    if (!length) {
        fail_bus("cannot encode MS/TP frame");
        return 0;
    }
    --s->tx_count;
    memmove(&s->tx[index], &s->tx[index + 1], (s->tx_count - index) * sizeof(Packet));
    return length;
}

uint16_t MSTP_Get_Send(struct mstp_port_struct_t *port, unsigned timeout)
{
    (void)timeout;
    Station *s = port->UserData;
    return s->tx_count ? take_packet(s, 0) : 0;
}

uint16_t MSTP_Get_Reply(struct mstp_port_struct_t *port, unsigned timeout)
{
    (void)timeout;
    Station *s = port->UserData;
    for (unsigned i = 0; i < s->tx_count; ++i) {
        Packet *p = &s->tx[i];
        if (npdu_is_data_expecting_reply(port->InputBuffer, port->DataLength,
                port->SourceAddress, p->data, p->length, p->peer))
            return take_packet(s, i);
    }
    return 0;
}

static void get_worker_packets(Station *s)
{
    /* Bounded queues give socket backpressure instead of silently overwriting
     * another pump's command. The worker reports an error if its socket fills. */
    while (s->tx_count < TX_CAPACITY && running) {
        uint8_t bytes[PUMP_IPC_MAX];
        ssize_t n = recv(s->fd, bytes, sizeof(bytes), MSG_DONTWAIT | MSG_TRUNC);
        if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) break;
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { fail_bus("pump process disconnected"); break; }
        if (n <= PUMP_IPC_HEADER || n > (ssize_t)sizeof(bytes) || bytes[1] > 1) {
            fail_bus("invalid pump IPC packet");
            break;
        }
        Packet *p = &s->tx[s->tx_count++];
        p->peer = bytes[0];
        p->der = bytes[1];
        p->length = (uint16_t)(n - PUMP_IPC_HEADER);
        memcpy(p->data, bytes + PUMP_IPC_HEADER, p->length);
    }
}

static bool frame_pending(const Station *s)
{
    return s->port.ReceivedValidFrame || s->port.ReceivedValidFrameNotForUs ||
        s->port.ReceivedInvalidFrame;
}

static bool bus_step(void)
{
    bool pending_bytes = false;
    /* First deliver the same wire input to every receiver. Never let one
     * station transmit before the other stations have seen the previous frame. */
    for (unsigned i = 0; i < station_count && running; ++i) {
        Station *s = &stations[i];
        get_worker_packets(s);
        while (s->rx_count && !frame_pending(s)) {
            s->port.DataRegister = s->rx[s->rx_head];
            s->rx_head = (s->rx_head + 1) % RX_CAPACITY;
            --s->rx_count;
            s->port.DataAvailable = true;
            MSTP_Receive_Frame_FSM(&s->port);
        }
        if (!frame_pending(s)) MSTP_Receive_Frame_FSM(&s->port);
        pending_bytes |= s->rx_count != 0;
    }
    unsigned long generation = send_generation;
    for (unsigned i = 0; i < station_count && running; ++i) {
        Station *s = &stations[i];
        /* Bound immediate transitions: sole-master cycles must not starve
         * the other stations, physical receive, or application IPC. */
        for (unsigned step = 0; step < 16 && running; ++step) {
            bool again = MSTP_Master_Node_FSM(&s->port);
            if (generation != send_generation) return true;
            if (!again) break;
        }
    }
    return pending_bytes;
}

static void station_init(Station *s, unsigned mac, int fd, unsigned maximum, unsigned frames)
{
    memset(s, 0, sizeof(*s));
    s->fd = fd;
    s->port.This_Station = (uint8_t)mac;
    s->port.Nmax_master = (uint8_t)maximum;
    s->port.Nmax_info_frames = (uint8_t)frames;
    s->port.InputBuffer = s->input;
    s->port.InputBufferSize = sizeof(s->input);
    s->port.OutputBuffer = s->output;
    s->port.OutputBufferSize = sizeof(s->output);
    s->port.UserData = s;
    s->port.SilenceTimer = silence;
    s->port.SilenceTimerReset = silence_reset;
    /* Match the existing Linux stack's tolerance for USB packet buffering. */
    s->port.Tframe_abort = 100;
    s->port.Treply_delay = 200;
    s->port.Treply_timeout = 300;
    s->port.Tusage_timeout = 35;
    MSTP_Init(&s->port);
    /* Complete INITIALIZE before allowing any received frame to be consumed. */
    MSTP_Master_Node_FSM(&s->port);
}

#ifndef PUMP_BUS_TEST
static void stop_bus(int sig) { (void)sig; running = 0; }

static void wait_until(uint64_t deadline)
{
    while (running) {
        uint64_t now = clock_us();
        if (now >= deadline) break;
        uint64_t left = deadline - now;
        struct timespec delay = {.tv_sec = (time_t)(left / 1000000),
                                .tv_nsec = (long)(left % 1000000) * 1000};
        if (nanosleep(&delay, NULL) == 0) break;
        if (errno != EINTR) break;
    }
}

static bool serial_write_frame(const uint8_t *frame, size_t size)
{
    wait_until(bus_activity + (40000000ULL + serial_baud - 1) / serial_baud);
    if (!running) return false;
    uint64_t start = clock_us();
    size_t sent = 0;
    while (sent < size && running) {
        ssize_t count = write(serial_fd, frame + sent, size - sent);
        if (count > 0) { sent += (size_t)count; continue; }
        if (count < 0 && errno == EINTR) continue;
        if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            struct pollfd out = {.fd = serial_fd, .events = POLLOUT};
            if (poll(&out, 1, 100) < 0 && errno != EINTR) return false;
            if (clock_us() - start > 2000000) return false;
            continue;
        }
        return false;
    }
    int result;
    do { result = ioctl(serial_fd, TCSBRK, 1); } while (result < 0 && errno == EINTR && running);
    if (result < 0 || !running) return false;
    /* Some USB drivers drain the host queue before the final serial stop bit.
     * Never complete faster than the frame's nominal wire duration. */
    wait_until(start + (size * 10000000ULL + serial_baud - 1) / serial_baud);
    return running != 0;
}

static void serial_cleanup(void)
{
    if (serial_fd < 0) return;
    if (saved_termios_valid) ioctl(serial_fd, TCSETS2, &saved_termios);
    ioctl(serial_fd, TIOCNXCL);
    close(serial_fd);
    serial_fd = -1;
}

static bool serial_open(const char *path)
{
    serial_fd = open(path, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (serial_fd < 0) return false;
    atexit(serial_cleanup);
    if (ioctl(serial_fd, TIOCEXCL) < 0 || ioctl(serial_fd, TCGETS2, &saved_termios) < 0)
        return false;
    saved_termios_valid = true;
    struct termios2 settings;
    memset(&settings, 0, sizeof(settings));
    settings.c_cflag = CS8 | CLOCAL | CREAD | BOTHER | (BOTHER << IBSHIFT);
    settings.c_ispeed = serial_baud;
    settings.c_ospeed = serial_baud;
    settings.c_cc[VMIN] = 0;
    settings.c_cc[VTIME] = 0;
    return ioctl(serial_fd, TCSETS2, &settings) == 0 && ioctl(serial_fd, TCFLSH, TCIOFLUSH) == 0;
}

int main(int argc, char **argv)
{
    if (argc == 2 && strcmp(argv[1], "--version") == 0) { puts("pump-mstp-group-1"); return 0; }
    if (argc < 5 || argc > 4 + PUMP_GROUP_MAX) {
        fputs("Use run_group.py: mstp_bus SERIAL BAUD MAX_MASTER MAC:FD:FRAMES ...\n", stderr);
        return 2;
    }
    const char *parent = getenv("PUMP_PARENT_PID");
    if (!parent || prctl(PR_SET_PDEATHSIG, SIGTERM) || getppid() != (pid_t)strtol(parent, NULL, 10)) return 2;
    char *end;
    unsigned long baud = strtoul(argv[2], &end, 10);
    if (*end || (baud != 9600 && baud != 19200 && baud != 38400 && baud != 76800)) return 2;
    serial_baud = (unsigned)baud;
    unsigned long maximum = strtoul(argv[3], &end, 10);
    if (*end || maximum < 1 || maximum > 127) return 2;
    for (int i = 4; i < argc; ++i) {
        unsigned mac, frames;
        int fd, type;
        char extra;
        socklen_t length = sizeof(type);
        if (sscanf(argv[i], "%u:%d:%u%c", &mac, &fd, &frames, &extra) != 3 ||
            mac > maximum || fd < 3 || frames < 1 || frames > 255 ||
            getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &length) || type != SOCK_SEQPACKET) return 2;
        for (unsigned n = 0; n < station_count; ++n)
            if (stations[n].port.This_Station == mac || stations[n].fd == fd) return 2;
        station_init(&stations[station_count++], mac, fd, (unsigned)maximum, frames);
    }
    signal(SIGINT, stop_bus);
    signal(SIGTERM, stop_bus);
    if (!serial_open(argv[1])) { perror("Cannot open group serial adapter"); return 2; }
    wire_write = serial_write_frame;
    bus_activity = clock_us();
    printf("BUS_READY adapter=%s baud=%u stations=%u\n", argv[1], serial_baud, station_count);
    fflush(stdout);
    bool immediate = false;
    while (running) {
        struct pollfd fds[PUMP_GROUP_MAX + 1];
        fds[0] = (struct pollfd){.fd = serial_fd, .events = POLLIN};
        for (unsigned i = 0; i < station_count; ++i)
            fds[i + 1] = (struct pollfd){.fd = stations[i].fd, .events = POLLIN};
        int ready = poll(fds, station_count + 1, immediate ? 0 : 1);
        if (ready < 0 && errno != EINTR) { fail_bus("poll failed"); break; }
        if (ready < 0) continue;
        for (unsigned i = 0; i <= station_count; ++i)
            if (fds[i].revents & (POLLERR | POLLHUP | POLLNVAL)) fail_bus("adapter or pump disconnected");
        if (!running) break;
        if (fds[0].revents & POLLIN) {
            uint8_t bytes[1024];
            ssize_t n = read(serial_fd, bytes, sizeof(bytes));
            if (n > 0) receive_bytes(bytes, (size_t)n, NULL);
            else if (n < 0 && errno != EAGAIN && errno != EINTR) fail_bus("serial read failed");
        }
        immediate = bus_step();
    }
    return failed ? 3 : 0;
}
#endif
