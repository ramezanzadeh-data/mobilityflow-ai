
import time
import threading
from collections import defaultdict, deque


class RateLimiter:

    def __init__(self, max_requests=60, window_seconds=60):

        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests = defaultdict(deque)
        self._lock = threading.Lock()

    def is_allowed(self, key):

        now = time.monotonic()

        with self._lock:

            request_times = self._requests[key]


            while request_times and request_times[0] <= now - self.window_seconds:
                request_times.popleft()

            if len(request_times) >= self.max_requests:
                retry_after = self.window_seconds - (now - request_times[0])
                return False, max(retry_after, 0)

            request_times.append(now)
            return True, None

    def reset(self, key=None):

        with self._lock:
            if key is None:
                self._requests.clear()
            else:
                self._requests.pop(key, None)
