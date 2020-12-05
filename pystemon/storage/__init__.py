
import logging.handlers
import time
import random
import threading
import traceback
import os
from datetime import datetime
import importlib

try:
    from queue import Queue
    from queue import Full
    from queue import Empty
except ImportError:
    from Queue import Queue
    from Queue import Full
    from Queue import Empty

logger = logging.getLogger('pystemon')

class StorageScheduler():
    def __init__(self, storage, **kwargs):
        self.storage = storage
        self.name = self.storage.name

    def save_pastie(self, pastie, timeout):
        raise NotImplementedError

    def seen_pastie(self, pastie_id, **kwargs):
        raise NotImplementedError


class StorageSync(StorageScheduler):
    def save_pastie(self, pastie, timeout):
        self.storage.save_pastie(pastie)

    def seen_pastie(self, pastie_id, **kwargs):
        return self.storage.seen_pastie(pastie_id, **kwargs)


# LATER: implement an async class
class StorageThread(threading.Thread, StorageScheduler):
    def __init__(self, storage, **kwargs):
        threading.Thread.__init__(self)
        StorageScheduler.__init__(self, storage, **kwargs)
        try:
            size = int(kwargs['queue_size'])
        except Exception:
            size = 0
        self.queue = Queue(size)
        self.kill_received = False

    def run(self):
        logger.info('{0}: Thread for saving pasties started'.format(self.name))
        # loop over the queue
        while not self.kill_received:
            # pastie = None
            try:
                # grabs pastie from queue
                pastie = self.queue.get(True, 5)
                # save the pasties in each storage
                self.storage.save_pastie(pastie)
            except Empty:
                pass
            # catch unknown errors
            except Exception as e:
                logger.error("{0}: Thread for saving pasties crashed unexpectectly, recovering...: {1}".format(self.name, e))
                logger.debug(traceback.format_exc())
            finally:
                # to be on the safe side of gf
                del(pastie)
                # signals to queue job is done
                self.queue.task_done()
        logger.info('{0}: Thread for saving pasties terminated'.format(self.name))

    def save_pastie(self, pastie, timeout):
        try:
            logger.debug('{0}: queueing pastie {1} for saving'.format(self.name, pastie.id))
            self.queue.put(pastie, True, timeout)
        except Full:
            logger.error('{0}: unable to save pastie[{1}]: queue is full'.format(self.name, pastie.id))

    # should work as there is 1 write for n readers (and currently n = 1)
    def seen_pastie(self, pastie_id, **kwargs):
        return self.storage.seen_pastie(pastie_id, **kwargs)


class StorageDispatcher():
    def __init__(self):
        self.__storage = []
        self.lock = threading.Lock()

    def add_storage(self, thread_storage):
        self.__storage.append(thread_storage)

    def save_pastie(self, pastie, timeout=5):
        for t in self.__storage:
            t.save_pastie(pastie, timeout)

    def seen_pastie(self, pastie_id, **kwargs):
        for t in self.__storage:
            if t.seen_pastie(pastie_id, **kwargs):
                logger.debug('{0}: Pastie[{1}] found'.format(t.name, pastie_id))
                return True
        logger.debug('Pastie[{0}] unknown'.format(pastie_id))
        return False


class PastieStorage():

    @staticmethod
    def load_storage(storage_name, **kwargs):
        modname = None
        storage = None
        if kwargs.get('save') or kwargs.get('save-all'):
            logger.debug("[{0}]: initializing ...".format(storage_name))
        else:
            logger.debug("[{0}]: skipping disabled storage".format(storage_name))
            return
        try:
            classname = kwargs['storage-classname']
            modname = classname.lower()
            filename = "pystemon.storage."+modname
            logger.debug("[{0}]: loading '{1}' from '{2}'".format(storage_name, classname, filename))
            module = importlib.import_module(filename)
            logger.debug("[{0}]: '{1}' successfully loaded".format(storage_name, classname))
            storage_class = getattr(module, classname)
            storage = storage_class(**kwargs)
        except Exception as e:
            logger.error("[{0}]: unable to load storage module: {1}".format(storage_name, e))
            raise e
        return storage

    def __init__(self, **kwargs):
        self.name = kwargs.get('name', self.__class__.__name__)
        self.lookup = kwargs.get('lookup', False)
        try:
            logger.debug('{0}: initializing storage backend'.format(self.name))
            self.__init_storage__(**kwargs)
        except Exception as e:
            logger.error('{0}: unable to initialize storage backend: {1}'.format(self.name, e))
            raise

    def format_directory(self, directory):
        d = datetime.now()
        year = str(d.year)
        month = str(d.month)
        # prefix month and day with "0" if it is only one digit
        if len(month) < 2:
            month = "0" + month
        day = str(d.day)
        if len(day) < 2:
            day = "0" + day
        return directory + os.sep + year + os.sep + month + os.sep + day

    def __init_storage__(self, **kwargs):
        raise NotImplementedError

    def __save_pastie__(self, pastie):
        raise NotImplementedError

    def save_pastie(self, pastie):
        try:
            start = time.time()
            logger.debug('{0}: saving pastie[{1}]'.format(self.name, pastie.id))
            self.__save_pastie__(pastie)
            delta = time.time() - start
            logger.debug('{0}: pastie[{1}] saved in {2}s'.format(self.name, pastie.id, delta))
        except Exception as e:
            logger.error('{0}: unable to save pastie[{1}]: {2}'.format(self.name, pastie.id, e))
            raise

    def __seen_pastie__(self, pastie_id, **kwargs):
        raise NotImplementedError

    def seen_pastie(self, pastie_id, **kwargs):
        if not self.lookup:
            return False
        try:
            start = time.time()
            logger.debug('{0}: looking up pastie[{1}]'.format(self.name, pastie_id))
            res = self.__seen_pastie__(pastie_id, **kwargs)
            delta = time.time() - start
            logger.debug('{0}: pastie[{1}] looked-up in {2}s'.format(self.name, pastie_id, delta))
            return res
        except Exception as e:
            logger.error('{0}: unable to lookup pastie[{1}]: {2}'.format(self.name, pastie_id, e))
            raise

