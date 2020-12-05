#!/usr/bin/env python3
# encoding: utf-8

'''
@author:     Christophe Vandeplas <christophe@vandeplas.com>
@copyright:  AGPLv3
             http://www.gnu.org/licenses/agpl.html

To be implemented:
- FIXME set all the config options in the class variables
- FIXME validate parsing of config file
'''

from datetime import datetime
import logging.handlers
import optparse
import os
import json
import sys
import signal
import threading
# LATER: multiprocessing to parse regex
import time
from io import open
from pystemon.proxy import ProxyList
from pystemon.ua import PystemonUA
from pystemon.throttler import ThreadThrottler
from pystemon.pastie import ThreadPasties
from pystemon.pastiesite import PastieSite
from pystemon.sendmail import PystemonSendmail
from pystemon.storage import PastieStorage
from pystemon.config import PystemonConfig
from pystemon.storage import StorageSync, StorageThread, StorageDispatcher
from pystemon.exception import *

try:
    from urllib.error import HTTPError, URLError
except ImportError:
    from urllib2 import HTTPError, URLError
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

try:
    import yaml
except ImportError:
    exit('ERROR: Cannot import the yaml Python library. Are you sure it is installed?')

try:
    if sys.version_info < (2, 7):
        raise Exception
except Exception:
    exit('You need python version 2.7 or newer.')

def load_config(config):

    logger.debug("About to load configuration")
    config.reload()
    threads=[]
    sites_loaded=0

    if config.proxies_list is not None:
        threads.append(config.proxies_list.monitor())

    storage = StorageDispatcher()
    if config.storage_engines:
        if config.save_thread:
            logger.info("Pasties will be saved asynchronously")
        else:
            logger.info("Pasties will be saved synchronously")
        for db in config.storage_engines:
            # start the threads handling database storage if needed
            if config.save_thread:
                t = StorageThread(db)
                threads.append(t)
                storage.add_storage(t)
                t.setDaemon(True)
            # save pasties synchronously
            else:
                s = StorageSync(db)
                storage.add_storage(s)
    else:
        logger.info("Pasties will not be saved")

    '''
     for each site enabled:
     - get the configuration
     - if successfull, create a queue
     - create a thread to refresh the list of pasties to download (consumer)
     - create a thread to download the pasties (consumer)
     - if needed, create a thread to throttle all the other threads (producer)
    '''
    for site in config.sites:
        try:

            throttler = None
            if site.throttling > 0:
                logger.debug("enabling throttling on site {site}".format(site=site.name))
                throttler = ThreadThrottler(site.name, site.throttling)
                threads.append(throttler)
                throttler.setDaemon(True)

            for i in range(config.threads):
                name = "[ThreadPasties][{}][{}]".format(site.name, i+1)
                user_agent = PystemonUA(name, config.proxies_list,
                        user_agents_list = config.user_agents_list,
                        throttler=throttler, ip_addr=config.ip_addr)
                t = ThreadPasties(user_agent, queue_name=site.name, queue=site.queue)
                threads.append(t)
                t.setDaemon(True)

            # Compressed is used to guess the filename, so it's mandatory to pass it along
            name = "[PastieSite][{}]".format(site.name)
            site_ua=PystemonUA(name, config.proxies_list,
                user_agents_list = config.user_agents_list,
                throttler = throttler, ip_addr = config.ip_addr)
            t = PastieSite(site.name, site.download_url, site.archive_url, site.archive_regex,
                    site_public_url = site.public_url,
                    site_metadata_url = site.metadata_url,
                    site_update_min = site.update_min,
                    site_update_max = site.update_max,
                    site_pastie_classname = site.pastie_classname,
                    site_save_dir = config.save_dir,
                    site_archive_dir = config.archive_dir,
                    archive_compress = config.compress,
                    site_ua=site_ua,
                    site_queue=site.queue,
                    patterns=config.patterns,
                    sendmail=config.sendmail,
                    re=config.re_module)
            t.set_storage(storage)
            threads.append(t)
            t.setDaemon(True)
            sites_loaded = sites_loaded + 1
        except Exception as e:
            logger.error('Unable to initialize pastie site {0}: {1}'.format(site.name, e))

    logger.debug("Finished loading configuration, {} thread(s) to start".format(len(threads)))
    if not sites_loaded > 0:
        raise PystemonConfigEmpty("Resulting configuration ends up monitoring no site")
    return threads

def start_threads(threads):
    count = len(threads)
    logger.debug("starting {0} thread(s) ...".format(count))
    for t in threads:
        t.start()

def stop_threads(threads):
    count = len(threads)
    if not count > 0:
        return
    logger.debug("stopping {0} thread(s) ...".format(count))
    for t in threads:
        t.stop()

def join_threads(threads, timeout=None, stop_requested=False):
    count = len(threads)
    if not count > 0:
        return True
    joined = 0
    terminated = 0
    if stop_requested:
        logger.debug("joining {} threads ...".format(count))
    else:
        logger.debug("checking on {} threads ...".format(count))
    if timeout is not None:
        logger.debug("will wait maximum {}s for each thread".format(timeout))
    for t in threads:
        try:
            t.join(timeout)
            joined = joined + 1
            if not t.is_alive():
                terminated = terminated + 1
        except PystemonException:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error("failed to join thread '{0}': {1}".format(t, e))
            pass
    if stop_requested:
        logger.debug("{0}/{1} thread(s) terminated".format(terminated, count))
    else:
        logger.debug("{0}/{1} thread(s) still alive".format(count-terminated, count))
    return terminated == count

def main(config):
    res = 0

    reload_requested = True
    stop_requested = False
    threads = []

    def request_stop(signal, frame):
        raise PystemonStopRequested("stop requested")
    signal.signal(signal.SIGTERM, request_stop)

    def request_reload(signal, frame):
        raise PystemonReloadRequested("reload requested")
    signal.signal(signal.SIGHUP, request_reload)

    def request_queue_stats(signal, frame):
        raise PystemonQueueStatRequested("queues stats requested")
    signal.signal(signal.SIGUSR1, request_queue_stats)


    # wait while all the threads are running and someone sends CTRL+C
    while True:
        try:
            if not len(threads) > 0:
                raise PystemonReloadRequested("Starting up ...")
            join_threads(threads, timeout=1)
        except PystemonReloadRequested as e:
            logger.info("Pystemon[{}]: {}".format(os.getpid(), e))
            try:
                new_threads = load_config(config)
                stop_threads(threads)
                join_threads(threads, stop_requested=True)
                threads = new_threads
                start_threads(threads)
            except PystemonConfigException as e:
                if not len(threads) > 0:
                    raise
                logger.error('Pystemon[{}]: {}'.format(os.getpid(), e))
                logger.info('Pystemon[{}]: continuing with previous configuration'.format(os.getpid()))
                pass
        except (PystemonStopRequested, KeyboardInterrupt) as e:
            if isinstance(e, PystemonException):
                logger.info("Pystemon[{}]: {}".format(os.getpid(), e))
            else:
                print('')
                print("Ctrl-c received! Sending kill to threads...")
            stop_threads(threads)
            join_threads(threads, timeout=max(1, config.max_throttling / 1000), stop_requested=stop_threads)
            break
        except PystemonQueueStatRequested as e:
            logger.debug("{}".format(e))
            for site in config.sites:
                try:
                    logger.info("{}: queue size={}".format(repr(site), site.queue.qsize()))
                except:
                    pass
        except PystemonConfigException as e:
            logger.error('Pystemon[{}]: {}'.format(os.getpid(), e))
            res = 2
            break
        except Exception as e:
            logger.error('Pystemon crashed: {}'.format(e))
            res = 1
            break
    logger.info('exiting')
    exit(res)

def main_as_daemon(config):
    try:
        # Store the Fork PID
        pid = os.fork()
        if pid > 0:
            pid_file = config.pidfile
            if pid_file is not None:
                pid_file = open(pid_file, 'w')
                pid_file.write(str(pid))
                pid_file.close()
            print('pystemon started as daemon')
            print('PID: %d' % pid)
            os._exit(0)
    except OSError as error:
        logger.error('Unable to fork, can\'t run as daemon. Error: {id} {error}'.format(id=error.errno, error=error.strerror))
        os._exit(1)
    main(config)

if __name__ == "__main__":
    global logger
    parser = optparse.OptionParser("usage: %prog [options]")
    parser.add_option("-c", "--config", dest="config",
                      help="load configuration from file", metavar="FILE")
    parser.add_option("-d", "--daemon", action="store_true", dest="daemon",
                      help="runs in background as a daemon")
    parser.add_option("-k", "--kill", action="store_true", dest="kill",
                      help="kill pystemon daemon")
    parser.add_option("-s", "--stats", action="store_true", dest="stats",
                      help="display statistics about the running threads (NOT IMPLEMENTED)")
    parser.add_option("-v", action="store_true", dest="verbose",
                      help="outputs more information")
    parser.add_option("--debug", action="store_true", dest="debug", help="enable debugging output")

    (options, args) = parser.parse_args()

    if not options.config:
        # try to read out the default configuration files if -c option is not set
        # the order is the following: (1 is highest)
        # 3/ /etc/pystemon.yaml
        # 2/ ./pystemon.yaml
        # 1/ ./<name-of-the-application.yaml
        if os.path.isfile('/etc/pystemon.yaml'):
            options.config = '/etc/pystemon.yaml'
        if os.path.isfile('pystemon.yaml'):
            options.config = 'pystemon.yaml'
        filename = sys.argv[0]
        config_file = filename.replace('.py', '.yaml')
        if os.path.isfile(config_file):
            options.config = config_file
        print(options.config)
    if not os.path.isfile(options.config):
        parser.error('Configuration file not found. Please create /etc/pystemon.yaml, pystemon.yaml or specify a config file using the -c option.')
        exit(1)

    logger = logging.getLogger('pystemon')
    if options.debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if not options.daemon:
        formatter = logging.Formatter('[%(asctime)s] %(message)s')
        hdlr = logging.StreamHandler(sys.stdout)
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)

    if options.daemon:
        # send logging to syslog if using daemon
        formatter = logging.Formatter('pystemon[%(process)d]: %(message)s')
        hdlr = logging.handlers.SysLogHandler(address='/dev/log', facility=logging.handlers.SysLogHandler.LOG_DAEMON)
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)

    config = None
    try:
        config = PystemonConfig(options.config, options.debug)
    except Exception as e:
        logger.error("unable to load configuration: {}".format(e))
        os._exit(1)

    # stop the software
    if options.kill:
        pidfile = config.pidfile()
        if os.path.isfile(pidfile):
            f = open(pidfile, 'r')
            pid = f.read()
            f.close()
            os.remove(pidfile)
            print("Sending signal to pid: {}".format(pid))
            os.kill(int(pid), 2)
            os._exit(0)
        else:
            print("PID file not found. Nothing to do.")
            os._exit(0)

    # run the software
    if options.daemon:
        main_as_daemon(config)
    else:
        main(config)

