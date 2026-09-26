/* Hardware-free tests of the production group scheduler and vendor FSMs. */
#define PUMP_BUS_TEST 1
#include "../mstp_bus.c"
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL %d: %s\n", __LINE__, #x); exit(1); } } while (0)
static uint64_t fake_time = 1000000;
static int peers[2];
static uint8_t frames[64][FRAME_CAPACITY];
static unsigned frame_count;
static uint64_t test_clock(void) { return fake_time; }
static bool test_write(const uint8_t *data, size_t size)
{
    CHECK(frame_count < 64 && size <= FRAME_CAPACITY);
    memcpy(frames[frame_count++], data, size);
    fake_time += size * 10000000ULL / 9600;
    return true;
}
static void reset_group(void)
{
    for (unsigned i = 0; i < station_count; ++i) { close(stations[i].fd); close(peers[i]); }
    station_count = 2;
    clock_us = test_clock;
    wire_write = test_write;
    frame_count = 0;
    send_generation = 0;
    running = 1;
    failed = false;
    for (unsigned i = 0; i < station_count; ++i) {
        int pair[2];
        CHECK(socketpair(AF_UNIX, SOCK_SEQPACKET, 0, pair) == 0);
        station_init(&stations[i], 11 + i, pair[0], 40, 1);
        peers[i] = pair[1];
    }
}
static void settle_bus(void)
{
    /* Production repeats bus_step() immediately while queued work remains.
     * A send deliberately ends a pass before the remaining masters run, so
     * peers may need several passes to consume earlier frames before replying.
     * Do not advance idle time; only test_write advances wire time. Bound
     * the passes to catch a scheduler spin. */
    for (unsigned pass = 0; pass < 256; ++pass) {
        bool immediate = bus_step();
        CHECK(!failed);
        if (!immediate) return;
    }
    CHECK(false); /* queued work did not settle */
}
static void inject(uint8_t type, uint8_t destination, const uint8_t *pdu, size_t size)
{
    uint8_t frame[FRAME_CAPACITY];
    uint16_t length = MSTP_Create_Frame(frame, sizeof(frame), type, destination, 40, pdu, (uint16_t)size);
    CHECK(length != 0);
    receive_bytes(frame, length, NULL);
    settle_bus();
}
static void no_packet(unsigned pump)
{
    uint8_t packet[PUMP_IPC_MAX];
    CHECK(recv(peers[pump], packet, sizeof(packet), MSG_DONTWAIT) < 0);
    CHECK(errno == EAGAIN || errno == EWOULDBLOCK);
}
static void expect_packet(unsigned pump, const uint8_t *pdu, size_t size)
{
    uint8_t packet[PUMP_IPC_MAX];
    CHECK(recv(peers[pump], packet, sizeof(packet), MSG_DONTWAIT) == (ssize_t)(size + 2));
    CHECK(packet[0] == 40 && memcmp(packet + 2, pdu, size) == 0);
}
int main(void)
{
    reset_group();
    inject(FRAME_TYPE_POLL_FOR_MASTER, 11, NULL, 0);
    CHECK(frame_count == 1 && frames[0][2] == FRAME_TYPE_REPLY_TO_POLL_FOR_MASTER);
    CHECK(frames[0][3] == 40 && frames[0][4] == 11);
    inject(FRAME_TYPE_POLL_FOR_MASTER, 12, NULL, 0);
    CHECK(frame_count == 2 && frames[1][2] == FRAME_TYPE_REPLY_TO_POLL_FOR_MASTER);
    CHECK(frames[1][3] == 40 && frames[1][4] == 12);

    reset_group();
    /* A real wire token passes through both virtual stations to the router. */
    stations[0].port.Next_Station = 12;
    stations[1].port.Next_Station = 40;
    stations[0].port.TokenCount = stations[1].port.TokenCount = 0;
    inject(FRAME_TYPE_TOKEN, 11, NULL, 0);
    CHECK(frame_count == 2 && frames[0][2] == FRAME_TYPE_TOKEN);
    CHECK(frames[0][3] == 12 && frames[0][4] == 11);
    CHECK(frame_count == 2 && frames[1][2] == FRAME_TYPE_TOKEN);
    CHECK(frames[1][3] == 40 && frames[1][4] == 12);

    reset_group();
    const uint8_t whois[] = {1, 0, 0x10, 8};
    inject(FRAME_TYPE_BACNET_DATA_NOT_EXPECTING_REPLY, 255, whois, sizeof(whois));
    expect_packet(0, whois, sizeof(whois));
    expect_packet(1, whois, sizeof(whois));
    CHECK(frame_count == 0);
    inject(FRAME_TYPE_BACNET_DATA_NOT_EXPECTING_REPLY, 12, whois, sizeof(whois));
    no_packet(0);
    expect_packet(1, whois, sizeof(whois));
    uint8_t frame[FRAME_CAPACITY];
    uint16_t length = MSTP_Create_Frame(frame, sizeof(frame), FRAME_TYPE_BACNET_DATA_NOT_EXPECTING_REPLY,
        255, 40, whois, sizeof(whois));
    frame[length - 1] ^= 0x80;
    receive_bytes(frame, length, NULL);
    settle_bus();
    no_packet(0);
    no_packet(1);

    reset_group();
    /* Match invoke ID behind an unrelated queued reply; preserve source MAC. */
    const uint8_t request[] = {1, 4, 0, 3, 7, 12};
    const uint8_t wrong_reply[] = {40, 0, 1, 0, 0x30, 8, 12};
    const uint8_t right_reply[] = {40, 0, 1, 0, 0x30, 7, 12};
    inject(FRAME_TYPE_BACNET_DATA_EXPECTING_REPLY, 11, request, sizeof(request));
    expect_packet(0, request, sizeof(request));
    no_packet(1);
    CHECK(stations[0].port.master_state == MSTP_MASTER_STATE_ANSWER_DATA_REQUEST);
    CHECK(send(peers[0], wrong_reply, sizeof(wrong_reply), 0) == (ssize_t)sizeof(wrong_reply));
    CHECK(send(peers[0], right_reply, sizeof(right_reply), 0) == (ssize_t)sizeof(right_reply));
    settle_bus();
    CHECK(frame_count == 1 && frames[0][3] == 40 && frames[0][4] == 11);
    CHECK(memcmp(frames[0] + 8, right_reply + 2, sizeof(right_reply) - 2) == 0);
    CHECK(stations[0].tx_count == 1 && stations[1].tx_count == 0);

    reset_group();
    /* BASrouter requests carry the controller's source network/IP address;
     * replies carry it as a destination and still leave from the pump MAC. */
    const uint8_t routed_request[] = {
        1, 0x0c, 0, 1, 6, 192, 168, 68, 101, 0xba, 0xc0, 0, 3, 7, 12
    };
    const uint8_t routed_reply[] = {
        40, 0, 1, 0x20, 0, 1, 6, 192, 168, 68, 101, 0xba, 0xc0, 255, 0x30, 7, 12
    };
    inject(FRAME_TYPE_BACNET_DATA_EXPECTING_REPLY, 12, routed_request, sizeof(routed_request));
    expect_packet(1, routed_request, sizeof(routed_request));
    no_packet(0);
    CHECK(send(peers[1], routed_reply, sizeof(routed_reply), 0) == (ssize_t)sizeof(routed_reply));
    settle_bus();
    CHECK(frame_count == 1 && frames[0][3] == 40 && frames[0][4] == 12);
    CHECK(memcmp(frames[0] + 8, routed_reply + 2, sizeof(routed_reply) - 2) == 0);

    reset_group();
    inject(FRAME_TYPE_BACNET_DATA_EXPECTING_REPLY, 12, request, sizeof(request));
    expect_packet(1, request, sizeof(request));
    fake_time += 201000;
    settle_bus();
    CHECK(frame_count == 1 && frames[0][2] == FRAME_TYPE_REPLY_POSTPONED && frames[0][4] == 12);

    reset_group();
    fake_time += 501000;
    settle_bus();
    fake_time += Tslot * 11 * 1000;
    settle_bus();
    /* Settling also lets MAC 12 answer discovery and receive the token. */
    CHECK(frame_count >= 3 && frames[0][2] == FRAME_TYPE_POLL_FOR_MASTER);
    CHECK(frames[0][3] == 12 && frames[0][4] == 11);
    CHECK(frames[1][2] == FRAME_TYPE_REPLY_TO_POLL_FOR_MASTER);
    CHECK(frames[1][3] == 11 && frames[1][4] == 12);
    CHECK(frames[2][2] == FRAME_TYPE_TOKEN);
    CHECK(frames[2][3] == 12 && frames[2][4] == 11);
    settle_bus();
    CHECK(!failed);
    for (unsigned i = 0; i < station_count; ++i) { close(stations[i].fd); close(peers[i]); }
    puts("PASS: group PFM, tokens, unicast/broadcast isolation, CRC, replies, token recovery");
    return 0;
}
