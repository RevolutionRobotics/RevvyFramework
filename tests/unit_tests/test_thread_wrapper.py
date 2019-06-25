import time
import unittest

from mock import Mock

from revvy.thread_wrapper import ThreadWrapper, ThreadContext

sleep_time = 0.01


class TestThreadWrapper(unittest.TestCase):
    def test_thread_wrapper_can_be_exited_if_not_started(self):
        tw = ThreadWrapper(lambda: None)
        tw.exit()

    def test_thread_function_runs_only_once_per_start(self):
        mock = Mock()

        tw = ThreadWrapper(mock)

        tw.start()
        time.sleep(sleep_time)
        self.assertEqual(1, mock.call_count)

        tw.start()
        time.sleep(sleep_time)

        tw.exit()
        self.assertEqual(2, mock.call_count)

    def test_thread_function_can_be_signalled_to_stop(self):
        mock = Mock()

        def _dummy_thread_fn(ctx: ThreadContext):
            mock()
            while not ctx.stop_requested:
                time.sleep(0.001)

        tw = ThreadWrapper(_dummy_thread_fn)

        tw.start()
        time.sleep(sleep_time)
        tw.exit()

        self.assertEqual(1, mock.call_count)

    def test_callback_is_called_when_thread_stops(self):
        mock = Mock()

        tw = ThreadWrapper(lambda x: None)
        tw.on_stopped(mock)

        tw.start()
        time.sleep(sleep_time)
        tw.exit()

        self.assertEqual(1, mock.call_count)

    def test_stopped_thread_can_be_restarted(self):
        mock = Mock()

        def _dummy_thread_fn(ctx: ThreadContext):
            mock()
            while not ctx.stop_requested:
                time.sleep(0.001)

        tw = ThreadWrapper(_dummy_thread_fn)

        tw.start()
        time.sleep(sleep_time)

        # repeated start has no effect when the thread is running
        tw.start()
        time.sleep(sleep_time)

        tw.stop()
        time.sleep(sleep_time)

        self.assertEqual(1, mock.call_count)

        tw.start()
        time.sleep(sleep_time)

        tw.exit()

        self.assertEqual(2, mock.call_count)

    def test_stop_request_can_be_observed(self):
        mock = Mock()

        def _dummy_thread_fn(ctx: ThreadContext):
            ctx.on_stopped(mock)
            while not ctx.stop_requested:
                time.sleep(sleep_time)

        tw = ThreadWrapper(_dummy_thread_fn)

        tw.start()
        time.sleep(sleep_time)
        tw.exit()

        self.assertEqual(1, mock.call_count)

    def test_exception_stops_but_does_not_crash(self):
        mock = Mock()

        # noinspection PyUnusedLocal
        def _dummy_thread_fn(ctx: ThreadContext):
            raise Exception

        tw = ThreadWrapper(_dummy_thread_fn)
        tw.on_stopped(mock)

        tw.start()
        time.sleep(sleep_time)

        tw.start()
        time.sleep(sleep_time)

        tw.exit()
        self.assertEqual(2, mock.call_count)

    def test_exited_thread_can_not_be_restarted(self):
        tw = ThreadWrapper(lambda x: None)

        tw.exit()
        self.assertRaises(AssertionError, tw.start)

    def test_sleep_can_be_interrupted(self):
        tw = ThreadWrapper(lambda ctx: ctx.sleep(10000))
        start_time = time.time()
        tw.start()
        time.sleep(sleep_time)
        tw.exit()
        end_time = time.time()
        self.assertLess(end_time - start_time, 2)

    def test_stopped_thread_can_be_started(self):
        mock = Mock()

        def _thread_fn(ctx: ThreadContext):
            while not ctx.stop_requested:
                mock()
                ctx.sleep(100 * sleep_time)

        tw = ThreadWrapper(_thread_fn)
        tw.stop()
        self.assertEqual(0, mock.call_count)

        tw.start()
        time.sleep(sleep_time)
        tw.exit()
        self.assertEqual(1, mock.call_count)