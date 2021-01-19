import logging.handlers
import os
from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pystemon.storage import PastieStorage

logger = logging.getLogger('pystemon')

class MongoStorage(PastieStorage):
    def __init_storage__(self, **kwargs):
        try:
            self.url = kwargs['url']
            self.database = kwargs['database']
            self.collection = kwargs['collection']
        except KeyError as e:
            raise RuntimeError("missing mandatory parameter '{}'".format(e))
        self.user = kwargs.get('user')
        self.password = kwargs.get('password')
        self.save_all = kwargs.get('save-all', False)
        profile = kwargs.get('save-profile', {})
        self.save_content_on_miss = profile.get('content-on-miss', False)
        self.save_timestamp = profile.get('timestamp', False)
        self.save_url = profile.get('url', False)
        self.save_site = profile.get('site', False)
        self.save_id = profile.get('id', False)
        self.save_matched = profile.get('matched', False)
        self.save_filename = profile.get('filename', False)
        try:
            self.client = MongoClient(self.url)
            self.db = self.client[self.database]
            if self.user and self.password:
                self.db.authenticate(name=self.user, password=self.password)
            self.client.server_info()
            self.col = self.db[self.collection]
        except PyMongoError as e:
            logger.error('Unable to contact db: %s' % e)
            raise
        except Exception as e:
            logger.error('ERROR: %s' % e)
            raise

    def __save_pastie__(self, pastie):
        if (not pastie.matched) and (not self.save_all):
            return
        data = {'hash': pastie.md5}
        if self.save_timestamp:
            data['timestamp'] = datetime.utcnow()
        if self.save_url:
            data['url'] = pastie.public_url
        if self.save_site:
            data['site'] = pastie.site.name
        if self.save_id:
            data['pastie_id'] = pastie.id
        if self.save_matched:
            data['matched'] = pastie.matched
        if self.save_filename:
            data['filename'] = pastie.filename
        if pastie.matched:
            data['content'] = pastie.pastie_content
            data['matches'] = pastie.matches_to_dict()
        elif self.save_content_on_miss:
            data['content'] = pastie.pastie_content
        self.col.insert(data)

    def __seen_pastie__(self, pastie_id, **kwargs):
        # check if the pastie was already saved in mongo
        try:
            if self.save_id and self.save_site:
                site = kwargs['site']
                return self.col.find_one({'pastie_id': pastie_id, 'site': site})
            if self.save_url:
                url = kwargs['url']
                return self.col.find_one({'url': url})
            logger.error('{0}: Not enough meta-data saved, disabling lookup'.format(self.name))
            self.lookup = False
        except KeyError:
            pass
        except TypeError as e:
            logger.error('{0}: Invalid query parameters: {1}'.format(self.name, e))
            pass
        except Exception as e:
            logger.error('{0}: Invalid query, disabling lookup: {1}'.format(self.name, e))
            self.lookup = False
        return False

