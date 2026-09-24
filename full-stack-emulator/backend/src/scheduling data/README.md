# Scheduling Data

This directory stores sample or reference scheduling files used by CSV playback workflows.

## Current File

- `mapped_bits_rtd_bv.csv`: RTD and ball-valve scheduling data with columns that can be matched against configured RTD sensor names and valve IDs.

## How Scheduling Works

CSV playback is implemented by `src/managers/scheduling_manager.py`.

The manager:

1. Stores the uploaded CSV header and rows in memory.
2. Matches RTD columns by configured sensor name or fallback `T{board_index + 1}`.
3. Matches valve columns by valve ID.
4. Applies each row to the RTD manager as board codes.
5. Tracks valve state markers from rows so the frontend can show upcoming transitions.
6. Switches playback to slow mode when a valve transition is coming or active runtime valve movement is happening.

Scheduling data files are not the source of truth for configuration. They are input data consumed by runtime playback.
