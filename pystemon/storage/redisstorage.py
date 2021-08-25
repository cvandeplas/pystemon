import logging.handlers
import os
import redis
from pystemon.storage import PastieStorage

logger = logging.getLogger('pystemon')

class RedisStorage(PastieStorage):
    def __getconn(self):
        # LATER: implement pipelining
        return redis.StrictRedis(host=self.server, port=self.port, db=self.database)

    def __init_storage__(self, **kwargs):
        self.save_dir = kwargs['save_dir']
        self.archive_dir = kwargs['archive_dir']
        self.server = kwargs['server']
        self.port = kwargs['port']
        self.database = kwargs['database']
        self.save_all = kwargs['save-all']
        r = self.__getconn()
        r.ping()

    def __save_pastie__(self, pastie):
        directories = []
        directories.append(self.archive_dir)
        if pastie.matched:
            directories.append(self.save_dir)
        for directory in directories:
            if directory is None:
                continue
            directory = directory + os.sep + pastie.site.site
            full_path = self.format_directory(directory) + os.sep + pastie.filename
            if pastie.matched or self.save_all:
                self.__getconn().lpush('pastes', full_path)
                logger.debug('Site[{site}]: Sent pastie[{id}][{disk}] to redis.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))


