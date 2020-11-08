import logging.handlers
import threading
import time

try:
    from queue import Queue
except ImportError:
    from Queue import Queue

logger = logging.getLogger('pystemon')

class ThreadThrottler(threading.Thread):

    def __init__(self, site, throttling):
        threading.Thread.__init__(self)
        self.site = site
        self.throttling = throttling
        self.queue = Queue()
        self.kill_received = False

    def wait(self):
        event = threading.Event()
        event.clear()
        self.queue.put(event)
        event.wait()

    def run(self):
        queue = self.queue
        throttling = self.throttling
        sleeptime = throttling/float(1000)
        site = self.site
        while not self.kill_received:
            logger.debug("ThreadThrottler[{}]: waiting for a download request ...".format(site))
            consumer_lock = queue.get()
            logger.debug("ThreadThrottler[{}]: releasing download request".format(site))
            consumer_lock.set()
            logger.debug("ThreadThrottler[{}]: now waiting {} second(s) ...".format(site, sleeptime))
            time.sleep(sleeptime)
