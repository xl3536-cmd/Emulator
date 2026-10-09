#ifndef PUMP_GROUP_IPC_H
#define PUMP_GROUP_IPC_H

/* One SOCK_SEQPACKET record: peer MAC, DER flag (0/1), complete NPDU.
 * Each pump has its own socket; pump identity is never inferred from the NPDU.
 * Legacy MS/TP data frames carry at most 501 data octets. */
#define PUMP_NPDU_MAX 501
#define PUMP_IPC_HEADER 2
#define PUMP_IPC_MAX (PUMP_IPC_HEADER + PUMP_NPDU_MAX)
#define PUMP_GROUP_MAX 32

#endif
