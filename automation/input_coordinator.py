import threading


class ForegroundInputCoordinator:
    """Serialize complete foreground input operations across plugin sessions."""

    def __init__(self):
        self._lock = threading.RLock()

    def run(self, operation):
        with self._lock:
            return operation()


GLOBAL_FOREGROUND_INPUT = ForegroundInputCoordinator()
