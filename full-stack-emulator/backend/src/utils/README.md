# Utils

The `utils` package contains small shared helpers that do not belong to a specific emulator domain.

## Files

- `logging.py`: creates named loggers with a consistent logging setup.

## Boundary

Keep this package small. Prefer domain-specific helpers near the domain code unless they are genuinely shared by multiple backend areas.

Good candidates for `utils`:

- Logging setup.
- Small process-wide formatting or parsing helpers.

Poor candidates for `utils`:

- RTD frame math.
- Valve state transitions.
- Config migration.
- Hardware board adapters.

Those belong in their domain packages so behavior stays easy to trace.
