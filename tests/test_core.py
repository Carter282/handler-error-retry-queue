import logging
import unittest

from handler_error_retry_queue import RetryHandler, RetryableError


class _RecordingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def flush(self):
        pass


class _FailingOnceHandler(logging.Handler):
    def __init__(self, fail_count=1):
        super().__init__()
        self.fail_count = fail_count
        self.attempts = 0
        self.records = []

    def emit(self, record):
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError("simulated transient failure")
        self.records.append(record)

    def flush(self):
        pass


class _AlwaysFailingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.attempts = 0

    def emit(self, record):
        self.attempts += 1
        raise RuntimeError("permanent failure")

    def flush(self):
        pass


def _make_record(msg):
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


class RetryHandlerInitTests(unittest.TestCase):
    def test_requires_handler(self):
        with self.assertRaises(TypeError):
            RetryHandler("not a handler")

    def test_rejects_non_int_max_queue(self):
        with self.assertRaises(TypeError):
            RetryHandler(_RecordingHandler(), max_queue="big")

    def test_clamps_zero_max_queue(self):
        h = RetryHandler(_RecordingHandler(), max_queue=0)
        self.assertEqual(h.max_queue, 1)

    def test_clamps_negative_max_queue(self):
        h = RetryHandler(_RecordingHandler(), max_queue=-5)
        self.assertEqual(h.max_queue, 1)


class RetryHandlerEmitTests(unittest.TestCase):
    def test_succeeds_immediately_when_delegate_succeeds(self):
        inner = _RecordingHandler()
        wrapper = RetryHandler(inner)
        rec = _make_record("hello")
        wrapper.emit(rec)
        self.assertEqual(inner.records, [rec])
        self.assertEqual(wrapper.pending(), 0)

    def test_queued_record_replayed_on_next_emit(self):
        inner = _FailingOnceHandler(fail_count=1)
        wrapper = RetryHandler(inner)
        first = _make_record("first")
        second = _make_record("second")
        wrapper.emit(first)
        self.assertEqual(wrapper.pending(), 1)
        self.assertEqual(inner.attempts, 1)
        wrapper.emit(second)
        self.assertEqual(inner.records, [first, second])
        self.assertEqual(wrapper.pending(), 0)

    def test_permanent_failure_stays_queued(self):
        inner = _AlwaysFailingHandler()
        wrapper = RetryHandler(inner)
        rec = _make_record("doomed")
        wrapper.emit(rec)
        self.assertEqual(inner.attempts, 1)
        self.assertEqual(wrapper.pending(), 1)
        rec2 = _make_record("doomed2")
        wrapper.emit(rec2)
        self.assertEqual(inner.attempts, 3)
        self.assertEqual(wrapper.pending(), 2)

    def test_queue_bounded_drops_oldest(self):
        inner = _AlwaysFailingHandler()
        wrapper = RetryHandler(inner, max_queue=2)
        r1 = _make_record("1")
        r2 = _make_record("2")
        r3 = _make_record("3")
        wrapper.emit(r1)
        wrapper.emit(r2)
        captured = []
        wrapper.handleError = lambda record: captured.append(record)
        wrapper.emit(r3)
        self.assertEqual(len(captured), 1)
        self.assertEqual(wrapper.pending(), 2)

    def test_retryable_error_is_not_special(self):
        class _RetryableRaisingHandler(logging.Handler):
            def __init__(self):
                super().__init__()
                self.attempts = 0
                self.records = []

            def emit(self, record):
                self.attempts += 1
                if self.attempts == 1:
                    raise RetryableError("retryable")
                self.records.append(record)

            def flush(self):
                pass

        inner = _RetryableRaisingHandler()
        wrapper = RetryHandler(inner)
        rec = _make_record("r")
        wrapper.emit(rec)
        self.assertEqual(wrapper.pending(), 1)
        wrapper.emit(_make_record("r2"))
        self.assertEqual(wrapper.pending(), 0)

    def test_replay_order_is_fifo(self):
        class _FailingThenOK(logging.Handler):
            def __init__(self):
                super().__init__()
                self.fail_until = 1
                self.attempts = 0
                self.records = []

            def emit(self, record):
                self.attempts += 1
                if self.attempts <= self.fail_until:
                    raise RuntimeError("no")
                self.records.append(record)

            def flush(self):
                pass

        inner = _FailingThenOK()
        wrapper = RetryHandler(inner)
        a = _make_record("a")
        b = _make_record("b")
        c = _make_record("c")
        wrapper.emit(a)
        wrapper.emit(b)
        self.assertEqual(wrapper.pending(), 0)
        wrapper.emit(c)
        self.assertEqual(inner.records, [a, b, c])
        self.assertEqual(wrapper.pending(), 0)


class RetryHandlerFlushTests(unittest.TestCase):
    def test_flush_replays_then_flushes_delegate(self):
        inner = _FailingOnceHandler(fail_count=1)
        wrapper = RetryHandler(inner)
        rec = _make_record("flush-me")
        wrapper.emit(rec)
        self.assertEqual(wrapper.pending(), 1)
        wrapper.flush()
        self.assertEqual(inner.records, [rec])
        self.assertEqual(wrapper.pending(), 0)


class RetryHandlerCloseTests(unittest.TestCase):
    def test_close_does_not_close_delegate(self):
        closed = []

        class _TrackCloseHandler(logging.Handler):
            def emit(self, record):
                pass

            def flush(self):
                pass

            def close(self):
                closed.append(True)
                super().close()

        inner = _TrackCloseHandler()
        wrapper = RetryHandler(inner)
        wrapper.emit(_make_record("x"))
        wrapper.close()
        self.assertEqual(closed, [])
        self.assertEqual(wrapper.pending(), 0)


if __name__ == "__main__":
    unittest.main()
