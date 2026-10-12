import logging
from collections import deque


class RetryableError(Exception):
    pass


class RetryHandler(logging.Handler):
    def __init__(self, handler, max_queue=128):
        super().__init__()
        if not isinstance(handler, logging.Handler):
            raise TypeError("handler must be a logging.Handler instance")
        if not isinstance(max_queue, int):
            raise TypeError("max_queue must be an int")
        if max_queue < 1:
            max_queue = 1
        self._delegate = handler
        self._queue = deque()
        self._max = max_queue

    @property
    def delegate(self):
        return self._delegate

    @property
    def max_queue(self):
        return self._max

    def pending(self):
        return len(self._queue)

    def emit(self, record):
        queued = list(self._queue)
        self._queue.clear()
        for queued_record in queued:
            try:
                self._delegate.emit(queued_record)
            except Exception:
                if len(self._queue) >= self._max:
                    dropped = self._queue.popleft()
                    self.handleError(self._make_error_record(dropped))
                self._queue.append(queued_record)
        try:
            self._delegate.emit(record)
        except Exception:
            if len(self._queue) >= self._max:
                dropped = self._queue.popleft()
                self.handleError(self._make_error_record(dropped))
            self._queue.append(record)

    def _make_error_record(self, dropped):
        import sys
        return logging.LogRecord(
            name=self.name or "handler_error_retry_queue",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="dropped queued log record due to full retry queue",
            args=None,
            exc_info=None,
        )

    def flush(self):
        queued = list(self._queue)
        self._queue.clear()
        for queued_record in queued:
            try:
                self._delegate.emit(queued_record)
            except Exception:
                if len(self._queue) >= self._max:
                    dropped = self._queue.popleft()
                    self.handleError(self._make_error_record(dropped))
                self._queue.append(queued_record)
        try:
            self._delegate.flush()
        except Exception:
            pass

    def close(self):
        try:
            super().close()
        finally:
            self._queue.clear()
