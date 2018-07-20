#!/usr/bin/env python
# encoding: utf-8

'''
@author:     Christophe Vandeplas <christophe@vandeplas.com>
@copyright:  AGPLv3
             http://www.gnu.org/licenses/agpl.html

To be implemented:
- FIXME set all the config options in the class variables
- FIXME validate parsing of config file
- FIXME use syslog logging
- TODO save files in separate directories depending on the day/week/month. Try to avoid duplicate files
'''

from bs4 import BeautifulSoup
try:
    from queue import Queue
    from queue import Full
    from queue import Empty
except ImportError:
    from Queue import Queue
    from Queue import Full
    from Queue import Empty
from collections import deque
from datetime import datetime
try:
    from email.mime.multipart import MIMEMultipart
except ImportError:
    from email.MIMEMultipart import MIMEMultipart

try:
    from email.mime.text import MIMEText
except ImportError:
    from email.MIMEText import MIMEText
import gzip
import hashlib
import logging.handlers
import optparse
import os
import random
import json
import smtplib
import socket
import sys
import traceback
import threading
# LATER: multiprocessing to parse regex
import time
from io import open
import requests

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

retries_client = 5
retries_server = 100

socket.setdefaulttimeout(10)  # set a default timeout of 10 seconds to download the page (default = unlimited)
true_socket = socket.socket


def make_bound_socket(source_ip):
    def bound_socket(*a, **k):
        sock = true_socket(*a, **k)
        sock.bind((source_ip, 0))
        return sock
    return bound_socket

class PastieSite(threading.Thread):
    '''
    Instances of these threads are responsible for downloading the list of
    the most recent pastes and added those to the download queue.
    '''

    def __init__(self, name, download_url, archive_url, archive_regex, **kwargs):
        threading.Thread.__init__(self)
        self.kill_received = False
        self.name = name
        self.download_url = download_url
        self.public_url = download_url
        self.archive_url = archive_url
        self.archive_regex = archive_regex
        try:
            self.ip_addr = yamlconfig['network']['ip']
            # true_socket = socket.socket
            socket.socket = make_bound_socket(self.ip_addr)
        except Exception:
            logger.debug("Using default IP address")
        try:
            self.save_dir = kwargs['site_save_dir'] + os.sep + name
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)
        except KeyError: pass
        try:
            self.archive_dir = kwargs['site_archive_dir'] + os.sep + name
            if not os.path.exists(self.archive_dir):
                os.makedirs(self.archive_dir)
        except KeyError: pass
        self.archive_compress = kwargs.get('archive_compress', False)
        self.update_min = kwargs['site_update_min']
        self.update_max = kwargs['site_update_max']
        self.pastie_classname = kwargs['site_pastie_classname']
        self.seen_pasties = deque('', 1000)  # max number of pasties ids in memory
        self.storage = None

    def run(self):
        logger.info('Thread for PastieSite {0} started'.format(self.name))
        while not self.kill_received:
            sleep_time = random.randint(self.update_min, self.update_max)
            try:
                # grabs site from queue
                logger.info(
                    'Downloading list of new pastes from {name}. '
                    'Will check again in {time} seconds'.format(
                        name=self.name, time=sleep_time))
                # get the list of last pasties, but reverse it
                # so we first have the old entries and then the new ones
                last_pasties = self.get_last_pasties()
                if last_pasties:
                    #self.__toto__(last_pasties)
                    l = len(last_pasties)
                    while last_pasties:
                        pastie = last_pasties.pop()
                        queues[self.name].put(pastie)  # add pastie to queue
                        del(pastie)
                    logger.info("Found {amount} new pasties for site {site}. There are now {qsize} pasties to be downloaded.".format(
                        amount=l,
                        site=self.name,
                        qsize=queues[self.name].qsize()))
            # catch unknown errors
            except Exception as e:
                msg = 'Thread for {name} crashed unexpectectly, '\
                      'recovering...: {e}'.format(name=self.name, e=e)
                logger.error(msg)
                logger.error(traceback.format_exc())
            finally:
                time.sleep(sleep_time)

    def set_storage(self, storage):
        self.storage = storage

    def save_pastie(self, pastie):
        if self.storage is not None:
            try:
                self.storage.save_pastie(pastie)
            except Exception as e:
                logger.error('Unable to save pastie {0}: {1}'.format(pastie.id,e))

    def get_last_pasties(self):
        # reset the pasties list
        pasties = []
        # populate queue with data
        response = download_url(self.archive_url)
        if not response:
            logger.warning("Failed to download page {url}".format(url=self.archive_url))
            return False
        htmlPage = response.text
        if not htmlPage:
            logger.warning("No HTML content for page {url}".format(url=self.archive_url))
            return False
        pasties_ids = re.findall(self.archive_regex, htmlPage)
        if pasties_ids:
            for pastie_id in pasties_ids:
                # check if the pastie was already downloaded
                # and remember that we've seen it
                if self.seen_pastie_and_remember(pastie_id):
                    # do not append the seen things again in the queue
                    continue
                # pastie was not downloaded yet. Add it to the queue
                if self.pastie_classname:
                    class_name = globals()[self.pastie_classname]
                    pastie = class_name(self, pastie_id)
                else:
                    pastie = Pastie(self, pastie_id)
                pasties.append(pastie)
            return pasties
        logger.error("No last pasties matches for regular expression site:{site} regex:{regex}. Error in your regex? Dumping htmlPage \n {html}".format(site=self.name, regex=self.archive_regex, html=htmlPage))
        return False

    def seen_pastie(self, pastie_id, **kwargs):
        ''' check if the pastie was already downloaded. '''
        logger.debug('Site[{0}]: Checking if pastie[{1}] was aldready seen'.format(self.name, pastie_id))
        # first look in memory if we have already seen this pastie
        if self.seen_pasties.count(pastie_id):
            logger.debug('Site[{0}]: Pastie[{1}] already in memory'.format(self.name, pastie_id))
            return True
        if self.storage is not None:
            if self.storage.seen_pastie(pastie_id, **kwargs):
                logger.debug('Site[{s}]: Pastie[{id}] found in storage'.format(s=self.name,id=pastie_id))
                return True
        logger.debug('Site[{0}]: Pastie[{1}] is unknown'.format(self.name, pastie_id))
        return False

    def seen_pastie_and_remember(self, pastie_id):
        '''
        Check if the pastie was already downloaded
        and remember that we've seen it
        '''
        if self.seen_pastie(pastie_id,
            url=self.public_url.format(id=pastie_id),
            sitename=self.name,
            filename=self.pastie_id_to_filename(pastie_id)):
            return True
        # We have not yet seen the pastie.
        # Keep in memory that we've seen it using
        # appendleft for performance reasons.
        # (faster later when we iterate over the deque)
        logger.debug('Site[{0}]: Marking pastie[{1}] as seen'.format(self.name, pastie_id))
        return self.seen_pasties.appendleft(pastie_id)

    def pastie_id_to_filename(self, pastie_id):
        filename = pastie_id.replace('/', '_')
        if self.archive_compress:
            filename = filename + ".gz"
        return filename

class Pastie():

    def __init__(self, site, pastie_id):
        self.site = site
        self.id = pastie_id
        self.pastie_content = None
        self.matches = []
        self.matched = False
        self.md5 = None
        self.url = self.site.download_url.format(id=self.id)
        self.public_url = self.site.public_url.format(id=self.id)
        self.filename = self.site.pastie_id_to_filename(self.id)

    def hash_pastie(self):
        if self.pastie_content:
            try:
                self.md5 = hashlib.md5(self.pastie_content).hexdigest()
                logger.debug('Pastie {site} {id} has md5: "{md5}"'.format(site=self.site.name, id=self.id, md5=self.md5))
            except Exception as e:
                logger.error('Pastie {site} {id} md5 problem: {e}'.format(site=self.site.name, id=self.id, e=e))

    def fetch_pastie(self):
        response = download_url(self.url)
        if response is not None:
            response = response.content
            self.pastie_content = response
        return response

    def __fetch_pastie__(self):
        logger.debug('fetching pastie {0}'.format(self.id))
        try:
            self.fetch_start_time = time.time()
            content = self.fetch_pastie()
            delta = self.fetch_end_time = time.time()
            if content is None:
                logger.debug('failed to fetch pastie {id}'.format(id=self.id))
            else:
                delta = self.fetch_end_time - self.fetch_start_time
                logger.debug('fetched pastie {id}: {s}s, {b}B'.format(id=self.id, s=delta, b=len(content)))
        except Exception as e:
            logger.error('ERROR: Failed to fetch pastie {site} {id}: {e}'.format(
                site=self.site.name,
                id=self.id,
                e=e))

    def save_pastie(self):
        self.site.save_pastie(self)

    def fetch_and_process_pastie(self):
        # download pastie
        self.__fetch_pastie__()
        content = self.pastie_content
        # check pastie
        if self.pastie_content is None:
            return
        try:
            # take checksum
            self.hash_pastie()
            # search for data in pastie
            self.search_content()
        except Exception as e:
            logger.error('ERROR: unable to process pastie {0} for site {1}: {2}'.format(
                self.id, self.site.name, e))
            return
        try:
            self.save_pastie()
        except Exception as e:
            logger.error('ERROR: unable to save pastie {0} for site {1}: {2}'.format(
                self.id, self.site.name, e))
        try:
            if self.matches:
                # alerting
                self.action_on_match()
            else:
                # only debugging for now
                self.action_on_miss()
        except Exception as e:
            logger.error("ERROR: on post-action for pastie {0}: {1}".format(self.id,e))

    def search_content(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, cannot search')
        logger.debug('Looking for matches in pastie {url}'.format(url=self.public_url))
        # search for the regexes in the htmlPage
        for regex in patterns:
            if regex.match(self.pastie_content):
                # we have a match, add to match list
                self.matches.append(regex)
                self.matched = True

    def action_on_match(self):
        msg = 'Found hit for {matches} in pastie {url}'.format(
            matches=self.matches_to_text(), url=self.public_url)
        logger.info(msg)
        # Send email alert if configured
        if yamlconfig['email']['alert']:
            self.send_email_alert()

    def action_on_miss(self):
        msg = 'No match found for pastie {url}'.format(url=self.public_url)
        logger.debug(msg)

    def matches_to_text(self):
        descriptions = []
        for match in self.matches:
            descriptions.append(match.to_text())
        if descriptions:
            return '[{}]'.format(', '.join([description for description in descriptions]))
        else:
            return ''

    def matches_to_regex(self):
        descriptions = []
        for match in self.matches:
            descriptions.append(match.to_regex())
        if descriptions:
            return '[{}]'.format(', '.join([description for description in descriptions]))
        else:
            return ''

    def matches_to_dict(self):
        res = []
        for match in self.matches:
            res.append(match.to_dict())
        return res

    def save_mongo(self):
        content = self.pastie_content
        hash = hashlib.md5()
        hash.update(content)
        data = {"hash": hash.hexdigest()}
        if self.matches:
            data['matches'] = self.matches_to_dict()
            data['content'] = content
        if mongo_save_meta['save']:
            if mongo_save_meta.get('timestamp',False):
                data['timestamp'] = datetime.utcnow()
            if mongo_save_meta.get('url',False):
                data['url'] = self.public_url
            if mongo_save_meta.get('site',False):
                data['site'] = self.site.name
        mongo_col.insert(data)

    def send_email_alert(self):
        msg = MIMEMultipart()
        alert = "Found hit for {matches} in pastie {url}".format(matches=self.matches_to_text(), url=self.public_url)
        # headers
        msg['Subject'] = yamlconfig['email']['subject'].format(subject=alert)
        msg['From'] = yamlconfig['email']['from']
        # build the list of recipients
        recipients = []
        recipients.append(yamlconfig['email']['to'])  # first the global alert email
        for match in self.matches:                    # per match, the custom additional email
            if match.to is not None:
                recipients.extend(match.ato)
        msg['To'] = ','.join(recipients)  # here the list needs to be comma separated
        # message body including full paste rather than attaching it
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expressions that matched:   {matches}

Below (after newline) is the content of the pastie:

{content}

        '''.format(site=self.site.name, url=self.public_url, matches=self.matches_to_regex(), content=self.pastie_content.decode('utf8'))
        msg.attach(MIMEText(message))
        # send out the mail
        try:
            s = smtplib.SMTP(yamlconfig['email']['server'], yamlconfig['email']['port'])
            if yamlconfig['email']['tls']:
                s.starttls()
            # login to the SMTP server if configured
            if 'username' in yamlconfig['email'] and yamlconfig['email']['username']:
                s.login(yamlconfig['email']['username'], yamlconfig['email']['password'])
            # send the mail
            s.sendmail(yamlconfig['email']['from'], recipients, msg.as_string())
            s.close()
        except smtplib.SMTPException as e:
            logger.error("ERROR: unable to send email: {0}".format(e))
        except Exception as e:
            logger.error("ERROR: unable to send email. Are your email setting correct?: {e}".format(e=e))


class PastiePasteSiteCom(Pastie):
    '''
    Custom Pastie class for the pastesite.com site
    This class overloads the fetch_pastie function to do the form
    submit to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = download_url(self.url)
        validation_form_page = response.text
        if validation_form_page:
            htmlDom = BeautifulSoup(validation_form_page, 'lxml')
            if not htmlDom:
                return self.pastie_content
            content_left = htmlDom.find(id='full-width')
            if not content_left:
                return self.pastie_content
            plain_confirm = content_left.find('input')['value']
            # build a form with plainConfirm = value (the cookie remains in the requests session)
            data = urlencode({'plainConfirm': plain_confirm})
            url = "http://pastesite.com/plain/{id}".format(id=self.id)
            response2 = download_url(url, data)
            self.pastie_content = response2
        return self.pastie_content


class PastieSlexyOrg(Pastie):
    '''
    Custom Pastie class for the pastesite.com site
    This class overloads the fetch_pastie function to do the form
    submit to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = download_url(self.url)
        validation_form_page = response.text
        if validation_form_page:
            htmlDom = BeautifulSoup(validation_form_page, 'lxml')
            if not htmlDom:
                return self.pastie_content
            a = htmlDom.find('a', {'target': '_blank'})
            if not a:
                return self.pastie_content
            url = "https://slexy.org{}".format(a['href'])
            response2 = download_url(url)
            self.pastie_content = response2.content
        return self.pastie_content


class PastieCdvLt(Pastie):
    '''
    Custom Pastie class for the cdv.lt site
    This class overloads the fetch_pastie function to do the form submit
    to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = download_url(self.url)
        downloaded_page = response.text
        if downloaded_page:
            # convert to json object
            json_pastie = json.loads(downloaded_page)
            if json_pastie:
                # and extract the code
                self.pastie_content = json_pastie['snippet']['snippetData']
        return self.pastie_content


class PastieSniptNet(Pastie):
    '''
    Custom Pastie class for the snipt.net site
    This class overloads the fetch_pastie function to do the form submit
    to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = download_url(self.url)
        downloaded_page = response.text
        if downloaded_page:
            htmlDom = BeautifulSoup(downloaded_page)
            # search for <textarea class="raw">
            textarea = htmlDom.find('textarea', {'class': 'raw'})
            if textarea and textarea.contents:
                # replace html entities like &gt;
                decoded = BeautifulSoup(
                    textarea.contents[0],
                    convertEntities=BeautifulSoup.HTML_ENTITIES)
                self.pastie_content = decoded.contents[0]
        return self.pastie_content


class ThreadPasties(threading.Thread):
    '''
    Instances of these threads are responsible for downloading the pastes
    found in the queue.
    '''

    def __init__(self, queue, queue_name):
        threading.Thread.__init__(self)
        self.queue = queue
        self.name = queue_name
        self.kill_received = False

    def run(self):
        while not self.kill_received:
            # grabs pastie from queue
            pastie = self.queue.get()
            try:
                pastie.fetch_and_process_pastie()
                logger.debug("Queue {name} size: {size}".format(
                    size=self.queue.qsize(), name=self.name))
            # catch unknown errors
            except Exception as e:
                msg = "ThreadPasties for {name} crashed unexpectectly, "\
                      "recovering...: {e}".format(name=self.name, e=e)
                logger.error(msg)
                logger.debug(traceback.format_exc())
            finally:
                # just to be on the safe side of the gc
                del(pastie)
                # signals to queue job is done
                self.queue.task_done()

class PastieSearch():
    def __init__(self, regex):
        # set the re.FLAGS
        if 'regex-flags' in regex:
            self.regex_flags = regex['regex-flags']
            self.flags = eval(self.regex_flags)
        else:
            self.regex_flags = None
            self.flags = re.IGNORECASE
        # compile the search regex
        self.search = regex['search']
        try:
            self.re_search = re.compile(self.search.encode(), self.flags)
        except Exception as e:
            raise ValueError("invalid search regex: %s" % e)
        # compile the exclude regex
        self.exclude = regex.get('exclude')
        if self.exclude is not None:
            try:
                self.re_exclude = re.compile(self.exclude.encode(), self.flags)
            except Exception as e:
                raise ValueError("invalid exclude regex: %s" % e)
        # get the description
        self.description = regex.get('description')
        # get the count and convert it to integer
        if 'count' in regex:
            self.count = int(regex['count'])
        else:
            self.count = -1
        # get the optional to and split it
        self.to = regex.get('to')
        if self.to is not None:
            self.ato = self.to.split(",")
        else:
            self.ato = []
        # add any extra things stored in yaml
        self.extra={}
        for (k, v) in regex.items():
          if k in ['search', 'description', 'exclude', 'count', 'regex-flags', 'to']:
              continue
          self.extra[k]=v
        self.h = None

    def match(self, string):
        m = self.re_search.findall(string)
        if not m:
            return False
        # the regex matches the text
        # ignore if not enough counts
        if (self.count > 0) and (len(m) < self.count):
            return False
        # ignore if exclude
        if self.exclude is not None:
            if self.re_exclude.search(string):
                return False
        # we have a match
        return True

    def to_text(self):
        if self.description is None:
            return self.search
        return self.description

    def to_regex(self):
        return self.search

    def to_dict(self):
        if self.h is None:
            self.h = {'search':self.search}
            if self.description is not None:
                self.h['description'] = self.description
            if self.exclude is not None:
                self.h['exclude'] = self.exclude
            if self.count >= 0:
                self.h['count'] = self.count
            if self.to is not None:
                self.h['to'] = self.to
            if self.regex_flags is not None:
                self.h['regex-flags'] = self.regex_flags
            for (k,v) in self.extra.items():
                self.h[k] = v
        return self.h

def main(storage_engines):
    global queues
    global threads
    global patterns
    queues = {}
    threads = []
    patterns = []

    # load the regular expression engine
    engine = yamlconfig.get('engine', 're')
    if engine == 're':
        import re
    elif engine == 'regex':
        try:
            global re
            logger.debug("Loading alternative 'regex' engine ...")
            import regex as re
            re.DEFAULT_VERSION = re.VERSION1
            logger.debug("Successfully loaded 'regex' engine")
        except ImportError as e:
            exit("ERROR: Unable to import 'regex' engine: %s" % e)
    else:
        exit("ERROR: Invalid regex engine '%s' specified" % engine)

    # compile all search patterns
    strict = yamlconfig.get('strict_regex', False)
    for regex in yamlconfig['search']:
        try:
            search = regex['search']
            ps = PastieSearch(regex)
            patterns.append(ps)
        except KeyError:
            if strict:
               exit("Error: Missing search pattern")
            else:
               logger.error("Error: skipping empty search pattern entry")
        except Exception as e:
            if strict:
               exit("Error: Unable to parse regex '%s': %s" % (search, e))
            else:
               logger.error("Error: Unable to parse regex '%s': %s" % (search, e))

    # start thread for proxy file listener
    if yamlconfig['proxy']['random']:
        t = ThreadProxyList(yamlconfig['proxy']['file'])
        threads.append(t)
        t.setDaemon(True)
        t.start()

    save_thread = yamlconfig.get('save-thread', False)
    storage = StorageDispatcher()
    if storage_engines:
        if save_thread:
            logger.info("Pasties will be saved asynchronously")
        else:
            logger.info("Pasties will be saved synchronously")
    else:
        logger.info("Pasties will not be saved")
    for db in storage_engines:
        # start the threads handling database storage if needed
        if save_thread:
            t = StorageThread(db)
            threads.append(t)
            storage.add_storage(t)
            t.setDaemon(True)
            t.start()
        # save pasties synchronously
        else:
            s = StorageSync(db)
            storage.add_storage(s)

    # spawn a pool of threads per PastieSite, and pass them a queue instance
    for site in yamlconfig['site']:
        queues[site] = Queue()
        for i in range(yamlconfig['threads']):
            t = ThreadPasties(queues[site], site)
            threads.append(t)
            t.setDaemon(True)
            t.start()

    sites = []
    # build threads to download the last pasties
    for (site_name, site_config) in yamlconfig['site'].items():
        try:
            site_download_url = site_config['download-url']
            site_archive_url = site_config['archive-url']
            site_archive_regex = site_config['archive-regex']
            t = PastieSite(site_name, site_download_url, site_archive_url, site_archive_regex,
                    site_public_url = site_config.get('public-url'),
                    site_update_min = site_config.get('update-min', 10),
                    site_update_max = site_config.get('update-max', 30),
                    site_pastie_classname = site_config.get('pastie-classname'),
                    site_save_dir = yamlconfig['archive'].get('dir'),
                    site_archive_dir = yamlconfig['archive'].get('dir-all'),
                    archive_compress = yamlconfig['archive'].get('compress', False))
            t.set_storage(storage)
            threads.append(t)
            t.setDaemon(True)
            t.start()
            sites.append(t)
        except Exception as e:
            logger.error('Unable to initialize pastie site {0}: {1}'.format(site_name, e))

    # wait while all the threads are running and someone sends CTRL+C
    while True:
        try:
            for t in threads:
                t.join(1)
        except KeyboardInterrupt:
            print('')
            print("Ctrl-c received! Sending kill to threads...")
            for t in threads:
                t.kill_received = True
            logger.info('exiting')
            exit(0)  # quit immediately


user_agents_list = []

def load_user_agents_from_file(filename):
    global user_agents_list
    try:
        f = open(filename)
    except Exception as e:
        logger.error('Configuration problem: user-agent-file "{file}" not found or not readable: {e}'.format(file=filename, e=e))
    for line in f:
        line = line.strip()
        if line:
            user_agents_list.append(line)
    logger.debug('Found {count} UserAgents in file "{file}"'.format(file=filename, count=len(user_agents_list)))


def get_random_user_agent():
    global user_agents_list
    if user_agents_list:
        return random.choice(user_agents_list)
    return 'Python-urllib/2.7'


proxies_failed = []
proxies_lock = threading.Lock()
proxies_list = []


class ThreadProxyList(threading.Thread):
    '''
    Threaded file listener for proxy list file. Modification to the file results
    in updating the proxy list.
    '''
    global proxies_list

    def __init__(self, filename):
        threading.Thread.__init__(self)
        self.filename = filename
        self.last_mtime = 0
        self.kill_received = False

    def run(self):
        logger.info('ThreadProxyList started')
        while not self.kill_received:
            mtime = os.stat(self.filename).st_mtime
            if mtime != self.last_mtime:
                logger.debug('Proxy configuration file changed. Reloading proxy list.')
                proxies_lock.acquire()
                load_proxies_from_file(self.filename)
                self.last_mtime = mtime
                proxies_lock.release()


def load_proxies_from_file(filename):
    global proxies_list
    try:
        f = open(filename)
    except Exception as e:
        logger.error('Configuration problem: proxyfile "{file}" not found or not readable: {e}'.format(file=filename, e=e))
    for line in f:
        line = line.strip()
        if line:  # LATER verify if the proxy line has the correct structure
            proxies_list.add(line)
    logger.debug('Found {count} proxies in file "{file}"'.format(file=filename, count=len(proxies_list)))


def get_random_proxy():
    global proxies_list
    proxy = None
    proxies_lock.acquire()
    if proxies_list:
        proxy = random.choice(tuple(proxies_list))
    proxies_lock.release()
    return proxy


def failed_proxy(proxy):
    proxies_failed.append(proxy)
    if proxies_failed.count(proxy) >= 2 and proxy in proxies_list:
        logger.info("Removing proxy {0} from proxy list because of to many errors errors.".format(proxy))
        proxies_lock.acquire()
        try:
            proxies_list.remove(proxy)
        except ValueError:
            pass
        proxies_lock.release()
        logger.info("Proxies left: {0}".format(len(proxies_list)))

def __parse_http__(url, session, random_proxy):
    try:
        response = session.get(url, stream=True)
        response.raise_for_status()
        res = {'response':response}
    except HTTPError as e:
        failed_proxy(random_proxy)
        logger.warning("!!Proxy error on {0}.".format(url))
        if 404 == e.code:
            htmlPage = e.read()
            logger.warning("404 from proxy received for {url}".format(url=url))
            res = {'loop_client':True, 'wait':60}
        elif 500 == e.code:
            htmlPage = e.read()
            logger.warning("500 from proxy received for {url}".format(url=url))
            res = {'loop_server':True, 'wait':60}
        elif 504 == e.code:
            htmlPage = e.read()
            logger.warning("504 from proxy received for {url}".format(url=url))
            res = {'loop_server':True, 'wait':60}
        elif 502 == e.code:
            htmlPage = e.read()
            logger.warning("502 from proxy received for {url}".format(url=url))
            res = {'loop_server':True, 'wait':60}
        elif 403 == e.code:
            htmlPage = e.read()
            if 'Please slow down' in htmlPage or 'has temporarily blocked your computer' in htmlPage or 'blocked' in htmlPage:
                logger.warning("Slow down message received for {url}".format(url=url))
                res = {'loop_server':True, 'wait':60}
            else:
                logger.warning("403 from proxy received for {url}, aborting".format(url=url))
                res = {'abort':True}
        else:
            logger.warning("ERROR: HTTP Error ##### {e} ######################## {url}".format(e=e, url=url))
            res = {'abort':True}
    return res

def __download_url__(url, session, random_proxy):
    try:
        res = __parse_http__(url, session, random_proxy)
    except URLError as e:
        logger.debug("ERROR: URL Error ##### {e} ######################## ".format(e=e, url=url))
        if random_proxy:  # remove proxy from the list if needed
            failed_proxy(random_proxy)
            logger.warning("Failed to download the page because of proxy error: {0}".format(url))
            res = {'loop_server':True}
        elif 'timed out' in e.reason:
            logger.warning("Timed out or slow down for {url}".format(url=url))
            res = {'loop_server':True, 'wait':60}
    except socket.timeout:
        logger.debug("ERROR: timeout ##### {e} ######################## ".format(e=e, url=url))
        if random_proxy:  # remove proxy from the list if needed
            failed_proxy(random_proxy)
            logger.warning("Failed to download the page because of socket error {0}:".format(url))
            res = {'loop_server':True}
    except requests.ConnectionError as e:
        logger.debug("ERROR: connection failed ##### {e} ######################## ".format(e=e, url=url))
        if random_proxy:  # remove proxy from the list if needed
            failed_proxy(random_proxy)
        logger.warning("Failed to download the page because of connection error: {0}".format(url))
        logger.error(traceback.format_exc())
        res = {'loop_server':True, 'wait':60}
    except Exception as e:
        logger.debug("ERROR: Other HTTPlib error ##### {e} ######################## ".format(e=e, url=url))
        if random_proxy:  # remove proxy from the list if needed
            failed_proxy(random_proxy)
        logger.warning("Failed to download the page because of other HTTPlib error proxy error: {0}".format(url))
        logger.error(traceback.format_exc())
        res = {'loop_server':True}
    # do NOT try to download the url again here, as we might end in enless loop
    return res

''' let's not recurse where exceptions can raise exceptions can raise exceptions can...'''
def download_url(url, data=None, cookie=None):
    response = None
    loop_client = 0
    loop_server = 0
    wait = 0
    while (response is None) and (loop_client<retries_client) and (loop_server<retries_server):
        try:
            session = requests.Session()
            random_proxy = get_random_proxy()
            if random_proxy:
                session.proxies = {'http': random_proxy}
            user_agent = get_random_user_agent()
            session.headers.update({'User-Agent': user_agent, 'Accept-Charset': 'utf-8'})
            if cookie:
                session.headers.update({'Cookie': cookie})
            if data:
                session.headers.update(data)
        except Exception as e:
            logger.error("ERROR: unable to initialize session, aborting: {0}".format(e))
            return None
        if wait > 0:
            logger.debug("Waiting {s}s before retrying {url}".format(s=wait, url=url))
            time.sleep(wait)
        logger.debug('Downloading url: {url} with proxy: {proxy} and user-agent: {ua}'.format(url=url, proxy=random_proxy, ua=user_agent))
        if (loop_client > 0) or (loop_server > 0):
            logger.warning("Retry client={lc}/{tc}, server={ls}/{ts} for {url}".format(
                lc=loop_client, tc=retries_client,
                ls=loop_server, ts=retries_server,
                url=url
            ))
        res = __download_url__(url, session, random_proxy)
        response = res.get('response', None)
        if res.get('abort', False):
            break
        if res.get('loop_client', False):
            loop_client += 1
        if res.get('loop_server', False):
            loop_server += 1
        wait = res.get('wait', 0)

    if response is None:
        # Client errors (40x): if more than 5 recursions, give up on URL (used for 404 case)
        if loop_client >= retries_client:
            logger.error("ERROR: too many client errors, giving up on {0}".format(url))
        # Server errors (50x): if more than 100 recursions, give up on URL
        elif loop_server >= retries_server:
            logger.error("ERROR: too many server errors, giving up on {0}".format(url))
        else:
            logger.error("ERROR: too many errors, giving up on {0}".format(url))

    return response

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
        except:
            size = 0
        self.queue = Queue(size)
        self.kill_received = False

    def run(self):
        logger.info('{0}: Thread for saving pasties started'.format(self.name))
        # loop over the queue
        while not self.kill_received:
            #pastie = None
            try:
                # grabs pastie from queue
                pastie = self.queue.get(True, 5)
                # save the pasties in each storage
                self.storage.save_pastie(pastie)
            except Empty: pass
            # catch unknown errors
            except Exception as e:
                logger.error("{0}: Thread for saving pasties crashed unexpectectly, recovering...: {1}".format(self.name,e))
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

class FileStorage(PastieStorage):

    def format_directory(self, directory):
        full_path = PastieStorage.format_directory(self, directory)
        if not os.path.isdir(full_path):
            os.makedirs(full_path)
        return full_path

    def __init_storage__(self, **kwargs):
        self.save_dir = kwargs.get('save_dir')
        if self.save_dir is not None:
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)
        self.archive_dir = kwargs.get('archive_dir')
        if self.archive_dir is not None:
            if not os.path.exists(self.archive_dir):
                os.makedirs(self.archive_dir)

    def __save_pastie__(self, pastie):
        directories = []
        res = []
        directories.append(self.archive_dir)
        if pastie.matched:
            directories.append(self.save_dir)
        for directory in directories:
            if directory is None:
                continue
            directory = directory + os.sep + pastie.site.name
            full_path = self.format_directory(directory) + os.sep + pastie.filename
            logger.debug('Site[{site}]: Writing pastie[{id}][{disk}] to disk.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))
            if pastie.site.archive_compress:
                f = gzip.open(full_path, 'wb')
            else:
                f = open(full_path, 'wb')
            f.write(pastie.pastie_content)
            f.close()
            logger.debug('Site[{site}]: Wrote pastie[{id}][{disk}] to disk.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))
        return full_path

    def __seen_pastie__(self, pastie_id, **kwargs):
        try:
            # check if the pastie was already saved on the disk
            pastie_filename = kwargs['filename']
            site_name = kwargs['sitename']
            for d in [self.save_dir, self.archive_dir]:
                if d is None:
                    continue
                fullpath = self.format_directory(d + os.sep + site_name)
                fullpath = fullpath + os.sep + pastie_filename
                logger.debug('{0}: checking if file {1} exists'.format(self.name, fullpath))
                if os.path.exists(fullpath):
                    logger.debug('{0}: file {1} exists'.format(self.name, fullpath))
                    return True
        except KeyError: pass
        return False

class RedisStorage(PastieStorage):

    def __getconn(self):
        # LATER: implement pipelining
        return redis.StrictRedis(host=self.server, port=self.port, db=self.database)

    def __init_storage__(self, **kwargs):
        self.save_dir = kwargs['save_dir']
        self.archive_dir = kwargs['archive_dir']
        self.server= kwargs['redis_server']
        self.port = kwargs['redis_port']
        self.database = kwargs['redis_database']
        self.queue_all = kwargs['redis_queue_all']
        r = self.__getconn()
        r.ping()

    def __save_pastie__(self, pastie):
        directories = []
        res = []
        directories.append(self.archive_dir)
        if pastie.matched:
            directories.append(self.save_dir)
        for directory in directories:
            if directory is None:
                continue
            directory = directory + os.sep + pastie.site.name
            full_path = self.format_directory(directory) + os.sep + pastie.filename
            if pastie.matched or self.queue_all:
                self.__getconn().lpush('pastes', full_path)
                logger.debug('Site[{site}]: Sent pastie[{id}][{disk}] to redis.'.format(site=pastie.site.name, id=pastie.id, disk=full_path))

class MongoStorage(PastieStorage):

    def __init_storage__(self, **kwargs):
        self.url = kwargs['url']
        self.database = kwargs['database']
        self.collection = kwargs['collection']
        self.user = kwargs.get('user')
        self.password = kwargs.get('password')
        self.save_all = kwargs.get('save_all', False)
        self.save_site = kwargs.get('save_site', False)
        self.save_url = kwargs.get('save_url', False)
        self.save_id = kwargs.get('save_pastie_id', False)
        self.save_timestamp = kwargs.get('save_timestamp', False)
        self.save_content_on_miss = kwargs.get('save_content_on_miss', False)
        self.save_matched = kwargs.get('save_matched', False)
        self.save_filename = kwargs.get('save_filename', False)
        self.client = MongoClient(self.url)
        self.db = self.client[self.database]
        if self.user and self.password:
            try:
                self.db.authenticate(name=self.user, password=self.password)
            except Exception as e:
                logger.error("ERROR: authentication to mongodb failed")
                raise
        self.client.server_info()
        self.col = self.db[self.collection]

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
                return self.col.find_one({'pastie_id':pastie_id, 'site':site})
            if self.save_url:
                url=kwargs['url']
                return self.col.find_one({'url':url})
            logger.error('{0}: Not enough meta-data saved, disabling lookup'.format(self.name))
            self.lookup = False
        except KeyError: pass
        except TypeError as e:
            logger.error('{0}: Invalid query parameters: {1}'.format(self.name, e))
            pass
        except Exception as e:
            logger.error('{0}: Invalid query, disabling lookup: {1}'.format(self.name, e))
            self.lookup = False
        return False

class Sqlite3Storage(PastieStorage):

    def __connect__(self):
        thread_id = threading.current_thread().ident
        try:
            with self.lock:
                cursor = self.connections[thread_id]
        except KeyError:
            logger.debug('Re-opening Sqlite databse {0} in thread[{1}]'.format(
               self.filename, thread_id))
            # autocommit and write ahead logging
            # works well because we have only 1 writter for n readers
            db_conn = sqlite3.connect(self.filename, isolation_level=None)
            db_conn.execute('pragma journal_mode=wal')
            cursor = db_conn.cursor()
            with self.lock:
                self.connections[thread_id] = cursor
        return cursor

    def __init_storage__(self, **kwargs):
        self.filename = kwargs['filename']
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
            #self.db_conn.commit()
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
        except KeyError: pass
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
            #self.db_conn.commit()
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
            self.__conect__().execute('''UPDATE pasties SET md5 = :md5,
                                            url = :url,
                                            local_path = :local_path,
                                            timestamp  = :timestamp,
                                            matches = :matches
                     WHERE site = :site AND id = :id''', data)
            #self.db_conn.commit()
        except sqlite3.DatabaseError as e:
            logger.error('Cannot add pastie {site} {id} in the SQLite database: {error}'.format(site=pastie.site.name, id=pastie.id, error=e))
            raise
        logger.debug('Updated pastie {site} {id} in the SQLite database.'.format(site=pastie.site.name, id=pastie.id))

def parse_config_file(configfile):
    global yamlconfig
    try:
        yamlconfig = yaml.load(open(configfile))
    except yaml.YAMLError as exc:
        logger.error("Error in configuration file:")
        if hasattr(exc, 'problem_mark'):
            mark = exc.problem_mark
            logger.error("error position: (%s:%s)" % (mark.line + 1, mark.column + 1))
            exit(1)
    # TODO verify validity of all config parameters
    for includes in yamlconfig.get("includes", []):
        yamlconfig.update(yaml.load(open(includes)))
    if yamlconfig['proxy']['random']:
        load_proxies_from_file(yamlconfig['proxy']['file'])
    if yamlconfig['user-agent']['random']:
        load_user_agents_from_file(yamlconfig['user-agent']['file'])

    # initialize database backends
    storage_engines = []
    archive = yamlconfig.get('archive', {})
    save_dir = None
    archive_dir = None
    try:
        if archive['save'] or archive['save-all']:
            if archive['save']:
               save_dir=archive['dir']
            else:
               save_dir=None
            if archive['save-all']:
               archive_dir=archive['dir-all']
            else:
               archive_dir=None
        if archive['save'] or archive['save-all']:
            storage_engines.append(FileStorage(
                lookup=True,
                save_dir=save_dir,
                archive_dir=archive_dir))
    except Exception as e:
        exit('ERROR: Unable to initialize file storage: {0}'.format(e))

    try:
        if (save_dir is not None) or (archive_dir is not None):
            redis_config = yamlconfig.get('redis', {})
            if redis_config.get('queue', False):
                global redis
                import redis
                redis_server=redis_config['server']
                redis_port=redis_config['port']
                redis_database=redis_config['database']
                redis_queue_all=redis_config.get('queue-all', False)
                redis_lookup=redis_config.get('lookup', False)
                redis_save_dir=save_dir
                redis_archive_dir=archive_dir
                storage_engines.append(RedisStorage(
                    redis_server=redis_server,
                    redis_port=redis_port,
                    redis_database=redis_database,
                    redis_queue_all=redis_queue_all,
                    lookup=redis_lookup,
                    save_dir=save_dir,
                    archive_dir=archive_dir))
    except ImportError:
        exit('ERROR: Cannot import the redis Python library. Are you sure it is installed?')
    except KeyError as e:
        exit('ERROR: Missing configuration directive for redis: {0}'.format(e))
    except Exception as e:
        exit('ERROR: Unable to initialize redis storage: {0}'.format(e))

    try:
        if yamlconfig['db'] and yamlconfig['db']['sqlite3'] and yamlconfig['db']['sqlite3']['enable']:
            global sqlite3
            import sqlite3
            storage_engines.append(Sqlite3Storage(
                filename=yamlconfig['db']['sqlite3']['file'],
                lookup=yamlconfig['db']['sqlite3'].get('lookup', False)))
    except KeyError:
        logger.debug("No sqlite3 database requested")
    except ImportError:
        exit('ERROR: Cannot import the sqlite3 Python library. Are you sure it is compiled in python?')
    except Exception as e:
        exit('ERROR: Cannot initialize the sqlite3 database: {0}'.format(e))

    try:
        mongo_config = yamlconfig.get('mongo', {})
        save_all = mongo_config.get('save-all', False)
        if mongo_config.get('save', False) or save_all:
            try:
                global MongoClient
                from pymongo import MongoClient
                global PyMongoError
                from pymongo.errors import PyMongoError
                mongo_url = mongo_config['url']
                mongo_database = mongo_config['database']
                mongo_collection = mongo_config['collection']
                mongo_user = mongo_config.get('user')
                mongo_password = mongo_config.get('password')
                mongo_profile = mongo_config.get('save-profile', {})
                mongo_save_site = mongo_profile.get('site', False)
                mongo_save_url = mongo_profile.get('url', False)
                mongo_save_pastie_id = mongo_profile.get('id', False)
                mongo_save_timestamp = mongo_profile.get('timestamp', False)
                mongo_save_content_on_miss = mongo_profile.get('content-on-miss', False)
                mongo_save_matched = mongo_profile.get('matched', False)
                mongo_lookup_seen = mongo_config.get('lookup', False)
                storage_engines.append(MongoStorage(
                    url=mongo_url, database=mongo_database, collection=mongo_collection,
                    user=mongo_user, password=mongo_password,
                    save_all=save_all,
                    save_site=mongo_save_site,
                    save_url=mongo_save_url,
                    save_pastie_id=mongo_save_pastie_id,
                    save_matched=mongo_save_matched,
                    save_timestamp=mongo_save_timestamp,
                    save_content_on_miss=mongo_save_content_on_miss,
                    lookup=mongo_lookup_seen))
            except PyMongoError as e:
                exit('ERROR: Unable to contact db: %s' % e)
    except ImportError:
        exit('ERROR: Cannot import PyMongo. Are you sure it is installed ?')
    except KeyError as e:
        exit('ERROR: Missing configuration directive for mongo: {0}'.format(e))
    except Exception as e:
        exit('ERROR: Unable to initialize mongo storage: {0}'.format(e))

    return storage_engines

def main_as_daemon(storage_engines):
    try:
        # Store the Fork PID
        pid = os.fork()

        if pid > 0:
            pid_file = open('pid', 'w')
            pid_file.write(str(pid))
            pid_file.close()
            print('pystemon started as daemon')
            print('PID: %d' % pid)
            os._exit(0)

    except OSError as error:
        logger.error('Unable to fork, can\'t run as daemon. Error: {id} {error}'.format(id=error.errno, error=error.strerror))
        os._exit(1)

    logger.info('Starting up ...')
    main(storage_engines)


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

    storage_engines = parse_config_file(options.config)
    # run the software
    if options.kill:
        if os.path.isfile('pid'):
            f = open('pid', 'r')
            pid = f.read()
            f.close()
            os.remove('pid')
            print("Sending signal to pid: {}".format(pid))
            os.kill(int(pid), 2)
            os._exit(0)
        else:
            print("PID file not found. Nothing to do.")
            os._exit(0)
    if options.daemon:
        main_as_daemon(storage_engines)
    else:
        main(storage_engines)
