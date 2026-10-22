# handler-error-retry-queue

Catches exceptions from a logging handler, queues the records whose emit failed, and replays them on subsequent emit calls up to a fixed queue limit.

```python
import logging
from handler_error_retry_queue import RetryHandler

inner = logging.StreamHandler()  # any real handler
wrapper = RetryHandler(inner, max_queue=128)
logger = logging.getLogger("demo")
logger.addHandler(wrapper)
logger.info("hello")  # if inner raises, the record is queued and retried next time
```

## Why this exists

The stdlib `logging` module, when `logging.raiseExceptions` is False (the default), silently discards records whose handler raises. For handlers that talk to flaky downstreams — a remote endpoint that briefly refuses connections, a disk that momentarily fills up — a single transient failure becomes a permanent record loss. This wrapper holds failed records in a bounded queue and retries them before each new emit, so a transient outage no longer swallows log lines.

The trade-off: we trade a bounded amount of memory for the chance of recovery. Records that never succeed are eventually evicted oldest-first when the queue fills, and the eviction is reported through the standard `handle_error` path so it remains observable.

## Edge you will hit

If your delegate handler fails permanently, every record you log will be attempted at least twice (once on arrival, once on the next emit's replay pass) before being evicted. That doubles the work of logging under a sustained outage. If your downstream is down for a long time, raise `max_queue` to buffer more, or accept the eviction — there is no back-pressure mechanism here, because logging calls must not block their caller.

`close()` does **not** close the delegate handler. The caller still owns the delegate and may reuse it; if you want it closed, close it yourself.

## Exports

- `RetryHandler(handler, max_queue=128)` — a `logging.Handler` subclass wrapping another handler.
- `RetryableError` — a marker exception reserved for future opt-in retry signalling. Currently all exceptions are queued uniformly; this class is exported so callers can express intent without the library committing to a filtering scheme yet.

Methods you will call:

- `emit(record)` — attempt to emit, replaying queued failures first.
- `flush()` — replay queued records, then flush the delegate.
- `close()` — clear the queue and close this wrapper (not the delegate).
- `pending()` — return the number of records currently queued for retry.

Run the tests:

```
PYTHONPATH=src python -m unittest discover -s tests
```

## Design notes

The window stores values eagerly rather than keeping running aggregates. Running
sums drift with floating point over long streams, and recomputing from a small
buffer is cheap enough that the drift is not worth the speed.

