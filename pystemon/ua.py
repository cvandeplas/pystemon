import logging.handlers
import time
import random
import requests
import threading
from requests.adapters import HTTPAdapter
import socket
import traceback

from pystemon.exception import PystemonKillReceived

global urllib_version
try:
    from urllib.error import HTTPError, URLError
    urllib_version = 3
except ImportError:
    from urllib2 import HTTPError, URLError
    urllib_version = 2

logger = logging.getLogger('pystemon')

true_socket = socket.socket
def make_bound_socket(source_ip):
    def bound_socket(*a, **k):
        sock = true_socket(*a, **k)
        sock.bind((source_ip, 0))
        return sock
    return bound_socket

# https://requests.readthedocs.io/en/master/user/advanced/#transport-adapters
class PystemonAdapter(HTTPAdapter):
    def __init__(self, ip_addr='', *args, **kwargs):
        self._source_address = ip_addr
        super(PystemonAdapter, self).__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False):
        super(PystemonAdapter, self).init_poolmanager(connections, maxsize, block, source_address=(self._source_address, 0))

class PystemonUA():

    def get_bound_session(self):
        global urllib_version
        session = requests.Session()
        if self.ip_addr:
            try:
                if urllib_version > 2:
                    logger.debug("{}: Bounding HTTPAdapter to IP '{}'".format(self.name, self.ip_addr))
                    session.mount('http://', PystemonAdapter(self.ip_addr))
                    session.mount('https://', PystemonAdapter(self.ip_addr))
                else:
                    logger.debug("{}: Bounding socket to IP '{}'".format(self.name, self.ip_addr))
                    socket.setdefaulttimeout(10)  # set a default timeout of 10 seconds to download the page (default = unlimited)
                    socket.socket = make_bound_socket(self.ip_addr)
            except Exception as e:
                logger.debug("{}: Unable to bind to IP '{}', using default IP address: {}".format(
                    self.name, self.ip_addr, str(e)))
        return session

    def __init__(self, name, proxies_list, user_agents_list = [],
            retries_client=5, retries_server=100,
            throttler=None, ip_addr=None,
            connection_timeout=3.05, read_timeout=10):
        self.name = "user-agent"+name
        self.user_agents_list = user_agents_list
        self.proxies_list = proxies_list
        self.retries_client = retries_client
        self.retries_server = retries_server
        self.throttler = throttler
        self.ip_addr = ip_addr
        self.connection_timeout = connection_timeout
        self.read_timeout = read_timeout
        self.condition = threading.Condition()
        self.kill_received = False
        logger.debug("{} initialized".format(self.name))

    def stop(self):
        with self.condition:
            self.kill_received = True
            self.condition.notify_all()

    def get_random_user_agent(self):
        if self.user_agents_list:
            return random.choice(self.user_agents_list)
        return 'Python-urllib/2.7'

    def __parse_http__(self, url, session, random_proxy):
        logger.debug("{}: Parsing response for url '{}'".format(self.name, url))
        try:
            response = session.get(url, stream=True, timeout=(self.connection_timeout, self.read_timeout))
            response.raise_for_status()
            res = {'response': response}
        except HTTPError as e:
            self.proxies_list.failed_proxy(random_proxy)
            logger.warning("{}: !!Proxy error on {}.".format(self.name, url))
            if 404 == e.code:
                htmlPage = e.read()
                logger.warning("{}: 404 from proxy received for {}".format(self.name, url))
                res = {'loop_client': True, 'wait': 60}
            elif 500 == e.code:
                htmlPage = e.read()
                logger.warning("{}: 500 from proxy received for {}".format(self.name, url))
                res = {'loop_server': True, 'wait': 60}
            elif 504 == e.code:
                htmlPage = e.read()
                logger.warning("{}: 504 from proxy received for {}".format(self.name, url))
                res = {'loop_server': True, 'wait': 60}
            elif 429 == e.code:
                retry_after = response.headers.get('Retry-After', 60)
                if retry_after.isdigit():
                    wait = int(retry_after)
                    logger.warning("{}: 429 from proxy received for {} requesting Retry-After {} seconds".format(self.name, url, wait))
                else:
                    logger.warning("{}: 429 from proxy received for {}".format(self.name, url))
                    wait = 60
                res = {'loop_server': True, 'wait': wait}
            elif 502 == e.code:
                htmlPage = e.read()
                logger.warning("{}: 502 from proxy received for {}".format(self.name, url))
                res = {'loop_server': True, 'wait': 60}
            elif 403 == e.code:
                htmlPage = e.read()
                if 'Please slow down' in htmlPage or 'has temporarily blocked your computer' in htmlPage or 'blocked' in htmlPage:
                    logger.warning("{}: Slow down message received for {}".format(self.name, url))
                    res = {'loop_server': True, 'wait': 60}
                else:
                    logger.warning("{}: 403 from proxy received for {}, aborting".format(self.name, url))
                    res = {'abort': True}
            else:
                logger.warning("{}: ERROR: HTTP Error ##### {} ######################## {}".format(self.name, e, url))
                res = {'abort': True}
        logger.debug("{}: Parsing response done for url '{}'".format(self.name, url))
        return res


    def __download_url__(self, url, session, random_proxy):
        try:
            with self.condition:
                if self.kill_received:
                    raise PystemonKillReceived("download request cancelled")
            res = self.__parse_http__(url, session, random_proxy)
        except URLError as e:
            logger.debug("{}: ERROR: URL Error ##### {} ########################".format(self.name, e))
            if random_proxy:  # remove proxy from the list if needed
                self.proxies_list.failed_proxy(random_proxy)
                logger.warning("{}: Failed to download the page because of proxy error: {}".format(self.name, url))
                res = {'loop_server': True}
            elif 'timed out' in e.reason:
                logger.warning("{}: Timed out or slow down for {}".format(self.name, url))
                res = {'loop_server': True, 'wait': 60}
        except socket.timeout as e:
            logger.debug("{}: ERROR: timeout ##### {} ######################## ".format(self.name, e))
            if random_proxy:  # remove proxy from the list if needed
                self.proxies_list.failed_proxy(random_proxy)
                logger.warning("{}: Failed to download the page because of socket error {}:".format(self.name, url))
                res = {'loop_server': True}
        except requests.ConnectionError as e:
            logger.debug("{}: ERROR: connection failed ##### {} ######################## ".format(self.name, e))
            if random_proxy:  # remove proxy from the list if needed
                self.proxies_list.failed_proxy(random_proxy)
            logger.warning("{}: Failed to download the page because of connection error: {}".format(self.name, url))
            logger.error(traceback.format_exc())
            res = {'loop_server': True, 'wait': 60}
        except PystemonKillReceived as e:
            logger.debug("{}: {}".format(self.name, e))
            res = {'abort': True}
        except Exception as e:
            logger.debug("{}: ERROR: Other HTTPlib error ##### {} ######################## ".format(self.name, e))
            if random_proxy:  # remove proxy from the list if needed
                self.proxies_list.failed_proxy(random_proxy)
            logger.warning("{}: Failed to download the page because of other HTTPlib error proxy error: {}".format(
                self.name, url))
            logger.error(traceback.format_exc())
            res = {'loop_server': True}
        # do NOT try to download the url again here, as we might end in enless loop
        return res

    def download_url(self, url, data=None, cookie=None, wait=0):
        # let's not recurse where exceptions can raise exceptions can raise exceptions can...
        response = None
        loop_client = 0
        loop_server = 0
        logger.debug("{}: download_url: about to fetch url '{}'".format(self.name, url))
        while (response is None) and (loop_client < self.retries_client) and (loop_server < self.retries_server):
            try:
                if self.throttler is not None and self.throttler.is_alive():
                    # wait until the throttler allows us to download
                    logger.debug("{}: download_url: throttling enabled, waiting for permission for download ...".format(self.name))
                    self.throttler.wait()
                    logger.debug("{}: download_url: permission to download granted".format(self.name))
                session = self.get_bound_session()
                random_proxy = None
                if self.proxies_list:
                    random_proxy = self.proxies_list.get_random_proxy()
                    if random_proxy:
                        session.proxies = {'http': random_proxy}
                user_agent = self.get_random_user_agent()
                session.headers.update({'User-Agent': user_agent, 'Accept-Charset': 'utf-8'})
                if cookie:
                    session.headers.update({'Cookie': cookie})
                if data:
                    session.headers.update(data)
            except Exception as e:
                logger.error("ERROR: unable to initialize session, aborting: {}".format(e))
                return None
            if wait > 0:
                logger.debug("{}: Waiting {}s before retrying {}".format(
                    self.name, wait, url))
                with self.condition:
                    self.condition.wait(wait)
            logger.debug('{name}: Downloading url: {url} with proxy: {proxy} and user-agent: {ua}'.format(
                name=self.name, url=url, proxy=random_proxy, ua=user_agent))
            if (loop_client > 0) or (loop_server > 0):
                logger.warning("{name}: Retry client={lc}/{tc}, server={ls}/{ts} for {url}".format(
                    name=self.name,
                    lc=loop_client, tc=self.retries_client,
                    ls=loop_server, ts=self.retries_server,
                    url=url
                ))
            now = time.time()
            res = self.__download_url__(url, session, random_proxy)
            time_taken = time.time() - now
            logger.debug('{}: Downloading url: {} done in {}s.'.format(self.name, url, time_taken))
            response = res.get('response', None)
            if res.get('abort', False):
                break
            if res.get('loop_client', False):
                loop_client += 1
            if res.get('loop_server', False):
                loop_server += 1
            wait = res.get('wait', wait)

        if response is None:
            # Client errors (40x): if more than 5 recursions, give up on URL (used for 404 case)
            if loop_client >= self.retries_client:
                logger.error("{}: ERROR: too many client errors, giving up on {}".format(self.name, url))
            # Server errors (50x): if more than 100 recursions, give up on URL
            elif loop_server >= self.retries_server:
                logger.error("{}: ERROR: too many server errors, giving up on {}".format(self.name, url))
            else:
                logger.error("{}: ERROR: too many errors, giving up on {}".format(self.name, url))

        return response

