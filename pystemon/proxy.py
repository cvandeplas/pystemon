import logging.handlers
import threading
import time
import random
import os

logger = logging.getLogger('pystemon')

class ThreadProxyList(threading.Thread):
    '''
    Threaded file listener for proxy list file. Modification to the file results
    in updating the proxy list.
    '''
    def __init__(self, proxies_list, wait=1):
        threading.Thread.__init__(self)
        self.list = proxies_list
        self.last_mtime = proxies_list.last_mtime
        self.wait = wait
        self.condition = threading.Condition()
        self.kill_received = False

    def __repr__(self):
        return 'ThreadProxyList[{}]'.format(self.list.filename)

    def stop(self):
        with self.condition:
            logger.info('ThreadProxyList exiting')
            self.kill_received = True
            self.condition.notify_all()

    def reset(self, wait=1):
        with self.condition:
            self.last_mtime = 0
            self.filename = filename
            self.wait = wait

    def run(self):
        logger.info('ThreadProxyList started')
        try:
            with self.condition:
                while not self.kill_received:
                    mtime = os.stat(self.list.filename).st_mtime
                    if mtime != self.last_mtime:
                        logger.debug('Proxy configuration file changed. Reloading proxy list.')
                        self.list.load_proxies_from_file()
                        self.last_mtime = mtime
                    self.condition.wait(1)
        except Exception as e:
            logger.error('ThreadProxyList crashed: {0}'.format(e))
        logger.info('ThreadProxyList exited')

class ProxyList():

    def __init__(self, filename):
        self.proxies_failed = []
        self.proxies_list = []
        self.proxies_lock = threading.Lock()
        self.thread_proxy_list = None
        self.filename = filename
        self.last_mtime = 0
        self.load_proxies_from_file()

    def monitor(self, wait=1):
        if self.thread_proxy_list:
            self.thread_proxy_list.reset(self, wait)
        else:
            t = ThreadProxyList(self, wait)
            t.setDaemon(True)
            self.thread_proxy_list = t
        return self.thread_proxy_list

    def load_proxies_from_file(self):
        try:
            filename = self.filename
            logger.debug('Loading proxy configuration from file "{file}" ...'.format(file=filename))
            proxies_list = []
            with self.proxies_lock, open(filename) as f:
                self.last_mtime = os.fstat(f.fileno()).st_mtime
                for line in f:
                    line = line.strip()
                    if line:  # LATER verify if the proxy line has the correct structure
                        proxies_list.append(line)
                self.proxies_failed = []
                self.proxies_list = proxies_list
            logger.debug('Found {count} proxies in file "{file}"'.format(file=filename, count=len(proxies_list)))
        except Exception as e:
            logger.error('Configuration problem: error reading proxyfile "{file}": {e}'.format(file=filename, e=e))

    def get_random_proxy(self):
        proxy = None
        with self.proxies_lock:
            if self.proxies_list:
                proxy = random.choice(tuple(self.proxies_list))
        return proxy

    def failed_proxy(self,proxy):
        with self.proxies_lock:
            if len(self.proxies_list) == 1:
                logger.info("Failing proxy {} not removed as it's the only proxy left.".format(proxy))
            else:
                self.proxies_failed.append(proxy)
                if self.proxies_failed.count(proxy) >= 2 and proxy in self.proxies_list:
                    logger.info("Removing proxy {0} from proxy list because of to many errors errors.".format(proxy))
                    try:
                        self.proxies_list.remove(proxy)
                    except ValueError:
                        pass
                    logger.info("Proxies left: {0}".format(len(self.proxies_list)))

