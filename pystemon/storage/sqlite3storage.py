
import logging.handlers
import os
import sqlite3
import threading
from datetime import datetime
from pystemon.storage import PastieStorage

logger = logging.getLogger('pystemon')

class Sqlite3Storage(PastieStorage):
    def __connect__(self):
        thread_id = threading.current_thread().ident
        try:
            with self.lock:
                cursor = self.connections[thread_id]
        except KeyError:
            logger.debug('Re-opening Sqlite database {0} in thread[{1}]'.format(self.filename, thread_id))
            # autocommit and write ahead logging
            # works well because we have only 1 writer for n readers
            db_conn = sqlite3.connect(self.filename, isolation_level=None)
            db_conn.execute('pragma journal_mode=wal')
            cursor = db_conn.cursor()
            with self.lock:
                self.connections[thread_id] = cursor
        return cursor

    def __init_storage__(self, **kwargs):
        self.filename = kwargs['file']
        self.lookup = kwargs.get('lookup', False)
        logger.info('Opening Sqlite database {0}'.format(self.filename))
        self.connections = {}
        self.lock = threading.Lock()
        # create the db if it doesn't exist
        try:
            # LATER maybe create a table per site. Lookups will be faster as less text-searching is needed
            self.__connect__().execute('''
                CREATE TABLE IF NOT EXISTS pasties (
                    site TEXT,
                    id TEXT,
                    md5 TEXT,
                    url TEXT,
                    local_path TEXT,
                    timestamp DATE,
                    matches TEXT
                    )''')
            # self.db_conn.commit()
        except sqlite3.DatabaseError as e:
            raise Exception('Problem with SQLite database {0}: {1}'.format(self.filename, e))

    def __save_pastie__(self, pastie):
        if self.__seen_pastie__(pastie.id, site_name=pastie.site.name):
            self.__update(pastie)
        else:
            self.__add(pastie)

    def __seen_pastie__(self, pastie_id, **kwargs):
        try:
            cursor = self.__connect__()
            site_name = kwargs['sitename']
            data = {'site': site_name, 'id': pastie_id}
            cursor.execute('SELECT count(id) FROM pasties WHERE site=:site AND id=:id', data)
            pastie_in_db = cursor.fetchone()
            logger.debug('seen {0} in sqlite?: {1}'.format(
                pastie_id, pastie_in_db and pastie_in_db[0]))
            return pastie_in_db and pastie_in_db[0]
        except KeyError:
            pass
        return False

    def __add(self, pastie):
        try:
            data = {'site': pastie.site.name,
                    'id': pastie.id,
                    'md5': pastie.md5,
                    'url': pastie.url,
                    'local_path': pastie.site.archive_dir + os.sep + pastie.filename,
                    'timestamp': datetime.now(),
                    'matches': pastie.matches_to_text()
                    }
            self.__connect__().execute('INSERT INTO pasties VALUES (:site, :id, :md5, :url, :local_path, :timestamp, :matches)', data)
            # self.db_conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error('Cannot add pastie {site} {id} in the SQLite database: {error}'.format(site=pastie.site.name, id=pastie.id, error=e))
            raise
        logger.debug('Added pastie {site} {id} in the SQLite database.'.format(site=pastie.site.name, id=pastie.id))

    def __update(self, pastie):
        try:
            data = {'site': pastie.site.name,
                    'id': pastie.id,
                    'md5': pastie.md5,
                    'url': pastie.url,
                    'local_path': pastie.site.archive_dir + os.sep + pastie.filename,
                    'timestamp': datetime.now(),
                    'matches': pastie.matches_to_text()
                    }
            self.__connect__().execute('''UPDATE pasties SET md5 = :md5,
                                            url = :url,
                                            local_path = :local_path,
                                            timestamp  = :timestamp,
                                            matches = :matches
                     WHERE site = :site AND id = :id''', data)
            # self.db_conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error('Cannot add pastie {site} {id} in the SQLite database: {error}'.format(site=pastie.site.name, id=pastie.id, error=e))
            raise
        logger.debug('Updated pastie {site} {id} in the SQLite database.'.format(site=pastie.site.name, id=pastie.id))



