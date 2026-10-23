"""Closing, reload races and in-flight work must not strand or interrupt the app."""
import unittest

from editor_lifecycle import EditorLifecycle


class EditorLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.life = EditorLifecycle(clock=lambda: self.now)

    def window(self, event, client='first', sequence=1):
        self.life.update(dict(client_id=client, event=event, sequence=sequence))

    def test_final_close_shuts_down_after_two_seconds_even_without_idle_timeout(self):
        self.window('open')
        self.window('close', sequence=2)
        self.now = 1.9
        self.assertFalse(self.life.begin_shutdown_if_due(0))
        self.now = 2
        self.assertTrue(self.life.begin_shutdown_if_due(0))
        self.assertFalse(self.life.begin_shutdown_if_due(0))

    def test_reload_cancels_close_deadline_and_old_document_cannot_close_new_one(self):
        self.window('open')
        self.window('close', sequence=2)
        self.now = 1
        self.window('open', 'reloaded')
        self.window('close', sequence=3)
        self.now = 10
        self.assertFalse(self.life.begin_shutdown_if_due(180))
        self.window('close', 'reloaded', 2)
        self.now = 12
        self.assertTrue(self.life.begin_shutdown_if_due(180))

    def test_closing_one_of_two_windows_keeps_other_window_alive(self):
        self.window('open')
        self.window('open', 'second')
        self.window('close', sequence=2)
        self.now = 10
        self.assertFalse(self.life.begin_shutdown_if_due(180))

    def test_out_of_order_notifications_and_restored_page(self):
        self.window('close', sequence=2)
        self.window('open')  # Slow startup notification arriving after close.
        self.now = 2
        self.assertTrue(self.life.begin_shutdown_if_due(180))
        self.setUp()
        self.window('open')
        self.window('close', sequence=2)
        self.window('open', sequence=3)  # Restored from browser back/forward cache.
        self.window('close', sequence=2)  # A late, duplicated close.
        self.now = 10
        self.assertFalse(self.life.begin_shutdown_if_due(180))

    def test_pending_save_or_export_finishes_before_shutdown(self):
        self.window('open')
        with self.life.request():
            self.window('close', sequence=2)
            self.now = 200
            self.assertFalse(self.life.begin_shutdown_if_due(180))
        self.assertTrue(self.life.begin_shutdown_if_due(180))

    def test_idle_fallback_for_browser_crash_and_no_browser_startup(self):
        self.window('open')
        self.now = 179
        self.assertFalse(self.life.begin_shutdown_if_due(180))
        self.life.touch()
        self.now = 358
        self.assertFalse(self.life.begin_shutdown_if_due(180))
        self.now = 359
        self.assertTrue(self.life.begin_shutdown_if_due(180))
        self.setUp()
        self.now = 1000
        self.assertFalse(self.life.begin_shutdown_if_due(0))
        self.assertTrue(self.life.begin_shutdown_if_due(180))

    def test_invalid_notifications_cannot_trigger_shutdown(self):
        for data in ({}, {'client_id': '', 'event': 'close', 'sequence': 1},
                     {'client_id': 'first', 'event': 'other', 'sequence': 1},
                     {'client_id': 'first', 'event': 'close', 'sequence': True}):
            with self.assertRaises(ValueError):
                self.life.update(data)
        self.now = 10
        self.assertFalse(self.life.begin_shutdown_if_due(180))

    def test_socket_disconnect_closes_window_without_browser_notification(self):
        self.window('open')
        self.life.disconnected('first', 1)
        self.now = 2
        self.assertTrue(self.life.begin_shutdown_if_due(180))

    def test_old_socket_cannot_disconnect_reconnected_window(self):
        self.window('open')
        self.window('open', sequence=2)
        self.life.disconnected('first', 1)
        self.now = 10
        self.assertFalse(self.life.begin_shutdown_if_due(180))
        self.life.disconnected('first', 2)
        self.now = 12
        self.assertTrue(self.life.begin_shutdown_if_due(180))


if __name__ == '__main__':
    unittest.main()
