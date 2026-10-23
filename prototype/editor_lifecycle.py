"""Track browser documents so closing the last editor releases the EXE promptly."""
from contextlib import contextmanager
import threading
import time


class EditorLifecycle:
    def __init__(self, *, close_grace=2, clock=time.monotonic):
        self.clock = clock
        self.close_grace = close_grace
        self.lock = threading.Lock()
        self.clients = {}
        self.close_after = None
        self.last_contact = clock()
        self.active_requests = 0
        self.stopping = False

    def touch(self):
        with self.lock:
            self.last_contact = self.clock()

    @contextmanager
    def request(self):
        # A closed browser must not interrupt an export, save or folder picker.
        with self.lock:
            self.active_requests += 1
        try:
            yield
        finally:
            with self.lock:
                self.active_requests -= 1

    def update(self, data):
        if (set(data) != {'client_id', 'event', 'sequence'}
                or not isinstance(data['client_id'], str)
                or not 1 <= len(data['client_id']) <= 80
                or data['event'] not in ('open', 'close')
                or type(data['sequence']) is not int
                or not 1 <= data['sequence'] <= 2**53 - 1):
            raise ValueError('Invalid editor window notification')
        client = data['client_id']
        sequence = data['sequence']
        with self.lock:
            if self.stopping:
                raise ValueError('The editor is closing. Reopen the application.')
            previous, _ = self.clients.get(client, (0, False))
            if sequence <= previous:
                return
            self.clients[client] = (sequence, data['event'] == 'open')
            if any(opened for _, opened in self.clients.values()):
                self.close_after = None
            elif self.close_after is None:
                self.close_after = self.clock() + self.close_grace

    def begin_shutdown_if_due(self, idle_timeout):
        with self.lock:
            if self.stopping:
                return False
            now = self.clock()
            closed = self.close_after is not None and now >= self.close_after
            idle = idle_timeout > 0 and now - self.last_contact >= idle_timeout
            if not self.active_requests and (closed or idle):
                self.stopping = True
                return True
            return False

    def disconnected(self, client, sequence):
        with self.lock:
            # A late disconnect from an old document/connection must not close
            # a restored page that already reconnected with a newer sequence.
            if self.clients.get(client) != (sequence, True):
                return
            self.clients[client] = (sequence, False)
            if not any(opened for _, opened in self.clients.values()) and self.close_after is None:
                self.close_after = self.clock() + self.close_grace


def watch_editor(server, lifecycle, idle_timeout, stopped):
    while not stopped.wait(.25):
        if lifecycle.begin_shutdown_if_due(idle_timeout):
            server.shutdown()
            return
