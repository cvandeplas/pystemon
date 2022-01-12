
import logging.handlers
import os
import gzip
from pystemon.storage import PastieStorage

logger = logging.getLogger('pystemon')

class FileStorage(PastieStorage):

    def format_directory(self, directory):
        full_path = PastieStorage.format_directory(self, directory)
        if not os.path.isdir(full_path):
            logger.debug("{}: creating directory: {}".format(self.name, full_path))
            os.makedirs(full_path)
        return full_path

    def __init_storage__(self, **kwargs):
        self.lookup = True
        self.save_dir = kwargs.get('dir')
        if self.save_dir is not None:
            logger.debug("{}:  saving directory: {}".format(self.name, self.save_dir))
            if not os.path.exists(self.save_dir):
                logger.debug("{}: creating saving directory '{}'".format(self.name, self.save_dir))
                os.makedirs(self.save_dir)
        self.archive_dir = kwargs.get('dir-all')
        if self.archive_dir is not None:
            logger.debug("{}:  saving directory: {}".format(self.name, self.archive_dir))
            if not os.path.exists(self.archive_dir):
                logger.debug("{}: creating archive directory '{}'".format(self.name, self.archive_dir))
                os.makedirs(self.archive_dir)
        self.compress = kwargs.get('compress', False)

    def __save_pastie__(self, pastie):
        directories = []
        full_path = None
        directories.append(self.archive_dir)
        if pastie.matched:
            directories.append(self.save_dir)
        for directory in directories:
            if directory is None:
                continue
            directory = directory + os.sep + pastie.site.site
            full_path = self.format_directory(directory) + os.sep + pastie.filename
            logger.debug('Site[{site}]: Writing pastie[{id}][{disk}] to disk.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))
            if self.compress:
                with gzip.open(full_path, 'wb') as f:
                    f.write(pastie.pastie_content)
            else:
                with open(full_path, 'wb') as f:
                    f.write(pastie.pastie_content)
            # Writing pastie metadata in a separate file if they exist
            if pastie.pastie_metadata:
                logger.debug('Site[{site}]: Writing pastie[{id}][{disk}] metadata to disk.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))
                with open(full_path + ".metadata", 'wb') as f:
                    f.write(pastie.pastie_metadata)
            logger.debug('Site[{site}]: Wrote pastie[{id}][{disk}] to disk.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))
        return full_path

    def __seen_pastie__(self, pastie_id, **kwargs):
        try:
            # check if the pastie was already saved on the disk
            pastie_filename = kwargs['filename']
            site = kwargs['site']
            for d in [self.save_dir, self.archive_dir]:
                if d is None:
                    continue
                fullpath = self.format_directory(d + os.sep + site)
                fullpath = fullpath + os.sep + pastie_filename
                logger.debug('{0}: checking if file {1} exists'.format(self.name, fullpath))
                if os.path.exists(fullpath):
                    logger.debug('{0}: file {1} exists'.format(self.name, fullpath))
                    return True
        except KeyError:
            pass
        return False

