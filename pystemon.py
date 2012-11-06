#!/usr/bin/env python
# encoding: utf-8

'''
@author:     Christophe Vandeplas <christophe@vandeplas.com>
@copyright:  GPLv3
Feel free to use the code, but please share the changes you've made

To be implemented:
- FIXME set all the config options in the class variables
- FIXME validate parsing of config file
- FIXME use syslog logging
- TODO runs as a daemon in background
- TODO save files in separate directories depending on the day/week/month. Try to avoid duplicate files
'''

import optparse
import logging.handlers
import sys
import threading
import Queue
from collections import deque
import time
from datetime import datetime
import urllib2
import urllib
import socket
import re
import os
import smtplib
import random
import json
import gzip
import sqlite3
import hashlib
from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders
try:
    from BeautifulSoup import BeautifulSoup
except:
    exit('ERROR: Cannot import the BeautifulSoup Python library. Are you sure you installed it?')
try:
    import yaml
except:
    exit('ERROR: Cannot import the yaml Python library. Are you sure you installed it?')

socket.setdefaulttimeout(10)  # set a default timeout of 10 seconds to download the page (default = unlimited)


class PastieSite(threading.Thread):
    '''
    Instances of these threads are responsible to download the list of the last pastes
    and adding them to the list of pending tasks for individual pastes
    '''
    def __init__(self, name, download_url, archive_url, archive_regex):
        threading.Thread.__init__(self)
        self.kill_received = False

        self.name = name
        self.download_url = download_url
        self.archive_url = archive_url
        self.archive_regex = archive_regex
        self.save_dir = yamlconfig['archive']['dir'] + os.sep + name
        self.archive_dir = yamlconfig['archive']['dir-all'] + os.sep + name
        if yamlconfig['archive']['save'] and not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        if yamlconfig['archive']['save-all'] and not os.path.exists(self.archive_dir):
            os.makedirs(self.archive_dir)
        self.archive_compress = yamlconfig['archive']['compress']
        self.update_max = 30  # TODO set by config file
        self.update_min = 10  # TODO set by config file
        self.pastie_classname = None
        self.seen_pasties = deque('', 1000)  # max number of pasties ids in memory

    def run(self):
        while not self.kill_received:
            try:
                sleep_time = random.randint(self.update_min, self.update_max)
                # grabs site from queue
                logger.info("Downloading pasties from {name}. Next download scheduled in {time} seconds".format(name=self.name, time=sleep_time))
                # get the list of last pasties, but reverse it so we first have the old
                # entries and then the new ones
                last_pasties = self.getLastPasties()
                if last_pasties:
                    for pastie in reversed(last_pasties):
                        queues[self.name].put(pastie)  # add pastie to queue
            # catch unknown errors
            except Exception, e:
                logger.error("Thread for {name} crashed unexpectectly, recovering...: {e}".format(name=self.name, e=e))
            time.sleep(sleep_time)

    def getLastPasties(self):
        # reset the pasties list
        pasties = []
        # populate queue with data
        htmlPage, headers = downloadUrl(self.archive_url)
        if not htmlPage:
            logger.warning("No HTML content for page {url}".format(url=self.archive_url))
            return False
        pasties_ids = re.findall(self.archive_regex, htmlPage)
        if pasties_ids:
            for pastie_id in pasties_ids:
                # check if the pastie was already downloaded, and remember that we've seen it
                if self.seenPastie(pastie_id):
                    # do not append the seen things again in the queue
                    continue
                # pastie was not downloaded yet. Add it to the queue
                if self.pastie_classname:
                    class_name = globals()[self.pastie_classname]
                    pastie = class_name(self, pastie_id)
                else:
                    pastie = Pastie(self, pastie_id)
                pasties.append(pastie)
            logger.info("Found {amount} new pasties for site {site}".format(amount=len(pasties), site=self.name))
            return pasties
        logger.error("No last pasties matches for regular expression site:{site} regex:{regex}. Error in your regex? Dumping htmlPage \n {html}".format(site=self.name, regex=self.archive_regex, html=htmlPage.encode('utf8')))
        return False

    def seenPastie(self, pastie_id):
        ''' check if the pastie was already downloaded. '''
        # first look in memory if we have already seen this pastie
        if self.seen_pasties.count(pastie_id):
            return True
        # look on the filesystem.  # LATER remove this filesystem lookup as it will give problems on long term
        if yamlconfig['archive']['save-all']:
            # check if the pastie was already saved on the disk
            if os.path.exists(self.archive_dir + os.sep + self.pastieIdToFilename(pastie_id)):
                return True
        # TODO look in the database if it was already seen

    def seenPastieAndRemember(self, pastie):
        ''' check if the pastie was already downloaded, and remember that we've seen it '''
        seen = False
        if self.seenPastie(pastie.id):
            seen = True
        else:
            # we have not yet seen the pastie
            # keep in memory that we've seen it
            # appendleft for performance reasons (faster later when we iterate over the deque)
            self.seen_pasties.appendleft(pastie.id)
        # add / update the pastie in the database
        if db:
            db.queue.put(pastie)
        return seen

    def pastieIdToFilename(self, pastie_id):
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
        self.md5 = None
        self.url = self.site.download_url.format(id=self.id)

    def hashPastie(self):
        if self.pastie_content:
            try:
                self.md5 = hashlib.md5(self.pastie_content.encode('utf-8')).hexdigest()
                logger.debug('Pastie {site} {id} has md5: "{md5}"'.format(site=self.site.name, id=self.id, md5=self.md5))
            except Exception, e:
                logger.error('Pastie {site} {id} md5 problem: {e}'.format(site=self.site.name, id=self.id, e=e))

    def fetchPastie(self):
        self.pastie_content, headers = downloadUrl(self.url)
        return self.pastie_content

    def savePastie(self, directory):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, sannot save')
        full_path = directory + os.sep + self.site.pastieIdToFilename(self.id)
        if self.site.archive_compress:
            with gzip.open(full_path, 'w') as f:
                f.write(self.pastie_content.encode('utf8'))  # TODO error checking
        else:
            with open(full_path, 'w') as f:
                f.write(self.pastie_content.encode('utf8'))  # TODO error checking

    def fetchAndProcessPastie(self):
        # double check if the pastie was already downloaded, and remember that we've seen it
        if self.site.seenPastie(self.id):
            return None
        # download pastie
        self.fetchPastie()
        # save the pastie on the disk
        if self.pastie_content:
            # take checksum
            self.hashPastie()
            # keep in memory that the pastie was seen successfully
            self.site.seenPastieAndRemember(self)
            # Save pastie to archive dir if configured
            if yamlconfig['archive']['save-all']:
                self.savePastie(self.site.archive_dir)
            # search for data in pastie
            self.searchContent()
        return self.pastie_content

    def searchContent(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, cannot search')
            return False
        # search for the regexes in the htmlPage
        for regex in yamlconfig['search']:
            #if not 'search' in regex: # TODO move this in the configuration file validation
            #    logger.warning('No search key in configuration: {0}'.format(regex))
            #    continue

            # LATER first compile regex, then search using compiled version
            regex_flags = re.IGNORECASE
            if 'regex-flags' in regex:
                regex_flags = eval(regex['regex-flags'])
            m = re.findall(regex['search'], self.pastie_content, regex_flags)
            if m:
                # the regex matches the text
                # ignore if not enough counts
                if 'count' in regex and len(m) < regex['count']:
                    continue
                # ignore if exclude
                if 'exclude' in regex and re.search(regex['exclude'], self.pastie_content, regex_flags):
                    continue
                # we have a match, add to match list
                self.matches.append(regex)
        if self.matches:
            self.actionOnMatch()

    def actionOnMatch(self):
        alert = "Found hit for {matches} in pastie {url}".format(matches=self.matchesToText(), url=self.url)
        logger.info(alert)
        # store info in DB
        if db:
            db.queue.put(self)
        # Save pastie to disk if configured
        if yamlconfig['archive']['save']:
            self.savePastie(self.site.save_dir)
        # Send email alert if configured
        if yamlconfig['email']['alert']:
            self.sendEmailAlert()

    def matchesToText(self):
        descriptions = []
        for match in self.matches:
            if 'description' in match:
                descriptions.append(match['description'])
            else:
                descriptions.append(match['search'])
        if descriptions:
            return unicode(descriptions)
        else:
            return ''

    def matchesToRegex(self):
        descriptions = []
        for match in self.matches:
            descriptions.append(match['search'])
        if descriptions:
            return unicode(descriptions)
        else:
            return ''

    def sendEmailAlert(self):
        msg = MIMEMultipart()
        alert = "Found hit for {matches} in pastie {url}".format(matches=self.matchesToText(), url=self.url)
        # headers
        msg['Subject'] = yamlconfig['email']['subject'].format(subject=alert)
        msg['From'] = yamlconfig['email']['from']
        msg['To'] = yamlconfig['email']['to']
        # message body
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expressions that matched:   {matches}
The paste has also been attached to this email.

# LATER below follows a small exerpt from the paste to give you direct context

        '''.format(site=self.site.name, url=self.url, matches=self.matchesToRegex())
        msg.attach(MIMEText(message))
        # original paste as attachment
        part = MIMEBase('application', "octet-stream")
        part.set_payload(self.pastie_content)
        Encoders.encode_base64(part)
	part.add_header('Content-Disposition', 'attachment; filename="%s%s"' % (self.id, yamlconfig['email']['extension']))
        msg.attach(part)
        # send out the mail
        try:
            s = smtplib.SMTP(yamlconfig['email']['server'], yamlconfig['email']['port'])
            if 'username' in yamlconfig['email'] and yamlconfig['email']['username']:
                s.login(yamlconfig['email']['username'], yamlconfig['email']['password'])
            s.sendmail(yamlconfig['email']['from'], yamlconfig['email']['to'], msg.as_string())
            s.close()
        except smtplib.SMTPException, e:
            logger.error("ERROR: unable to send email: {0}".format(e))
        except Exception, e:
            logger.error("ERROR: unable to send email. Are your email setting correct?: {e}".format(e=e))


class PastiePasteSiteCom(Pastie):
    '''
    Custom Pastie class for the pastesite.com site
    This class overloads the fetchPastie function to do the form submit to get the raw pastie
    '''
    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetchPastie(self):
        validation_form_page, headers = downloadUrl(self.url)
        if validation_form_page:
            htmlDom = BeautifulSoup(validation_form_page)
            if not htmlDom:
                return self.pastie_content
            content_left = htmlDom.find(id='full-width')
            if not content_left:
                return self.pastie_content
            plain_confirm = content_left.find('input')['value']
            # build a form with plainConfirm = value and the cookie
            data = urllib.urlencode({'plainConfirm': plain_confirm})
            url = "http://pastesite.com/plain/{id}".format(id=self.id)
            cookie = headers.dict['set-cookie']
            self.pastie_content, headers = downloadUrl(url, data, cookie)
        return self.pastie_content


class PastieCdvLt(Pastie):
    '''
    Custom Pastie class for the cdv.lt site
    This class overloads the fetchPastie function to do the form submit to get the raw pastie
    '''
    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetchPastie(self):
        downloaded_page, headers = downloadUrl(self.url)
        if downloaded_page:
            # make the json valid: strip json1(  )
            downloaded_page = u'[' + downloaded_page[6:-2] + u']'
            # convert to json object
            json_pastie = json.loads(downloaded_page)
            if json_pastie:
                # and extract the code
                self.pastie_content = json_pastie[0]['code_record']
        return self.pastie_content


class PastieSniptNet(Pastie):
    '''
    Custom Pastie class for the snipt.net site
    This class overloads the fetchPastie function to do the form submit to get the raw pastie
    '''
    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetchPastie(self):
        downloaded_page, headers = downloadUrl(self.url)
        if downloaded_page:
            htmlDom = BeautifulSoup(downloaded_page)
            # search for <textarea class="raw">
            textarea = htmlDom.first('textarea', {'class': 'raw'})
            if textarea:
                # replace html entities like &gt;
                decoded = BeautifulSoup(textarea.contents[0], convertEntities=BeautifulSoup.HTML_ENTITIES)
                self.pastie_content = decoded.contents[0]
        return self.pastie_content


class ThreadPasties(threading.Thread):
    '''
    Instances of these threads are responsible to download all the individual pastes
    by checking their queue if there are pending tasks
    '''
    def __init__(self, queue, queue_name):
        threading.Thread.__init__(self)
        self.queue = queue
        self.name = queue_name
        self.kill_received = False

    def run(self):
        while not self.kill_received:
            try:
                # grabs pastie from queue
                pastie = self.queue.get()
                pastie_content = pastie.fetchAndProcessPastie()
                logger.debug("Queue {name} size: {size}".format(size=self.queue.qsize(), name=self.name))
                if pastie_content:
                    logger.debug("Saved new pastie from {0} with id {1}".format(self.name, pastie.id))
                else:
                    # pastie already downloaded OR error ?
                    pass
                # signals to queue job is done
                self.queue.task_done()
            # catch unknown errors
            except Exception, e:
                logger.error("ThreadPasties for {name} crashed unexpectectly, recovering...: {e}".format(name=self.name, e=e))


def main():
    global queues
    global threads
    global db
    queues = {}
    threads = []

    # start a thread to handle the DB data
    db = None
    if yamlconfig['db'] and yamlconfig['db']['sqlite3'] and yamlconfig['db']['sqlite3']['enable']:
        db = Sqlite3Database(yamlconfig['db']['sqlite3']['file'])
        db.setDaemon(True)
        threads.append(db)
        db.start()
    #test()
    # spawn a pool of threads per PastieSite, and pass them a queue instance
    for site in yamlconfig['site']:
        queues[site] = Queue.Queue()
        for i in range(yamlconfig['threads']):
            t = ThreadPasties(queues[site], site)
            t.setDaemon(True)
            threads.append(t)
            t.start()

    # build threads to download the last pasties
    for site_name in yamlconfig['site']:
        t = PastieSite(site_name,
                      yamlconfig['site'][site_name]['download-url'],
                      yamlconfig['site'][site_name]['archive-url'],
                      yamlconfig['site'][site_name]['archive-regex'])
        if 'update-min' in yamlconfig['site'][site_name] and yamlconfig['site'][site_name]['update-min']:
            t.update_min = yamlconfig['site'][site_name]['update-min']
        if 'update-max' in yamlconfig['site'][site_name] and yamlconfig['site'][site_name]['update-max']:
            t.update_max = yamlconfig['site'][site_name]['update-max']
        if 'pastie-classname' in yamlconfig['site'][site_name] and yamlconfig['site'][site_name]['pastie-classname']:
            t.pastie_classname = yamlconfig['site'][site_name]['pastie-classname']
        threads.append(t)
        t.setDaemon(True)
        t.start()

    # wait while all the threads are running and someone sends CTRL+C
    while True:
        try:
            for t in threads:
                t.join(1)
        except KeyboardInterrupt:
            print ''
            print "Ctrl-c received! Sending kill to threads..."
            for t in threads:
                t.kill_received = True
            exit(0)  # quit immediately


user_agents_list = []


def loadUserAgentsFromFile(filename):
    global user_agents_list
    try:
        f = open(filename)
    except Exception, e:
        logger.error('Configuration problem: user-agent-file "{file}" not found or not readable: {e}'.format(file=filename, e=e))
    for line in f:
        line = line.strip()
        if line:
            user_agents_list.append(line)
    logger.debug('Found {count} UserAgents in file "{file}"'.format(file=filename, count=len(user_agents_list)))


def getRandomUserAgent():
    global proxies_list
    if user_agents_list:
        return random.choice(user_agents_list)
    return None


proxies_failed = []
proxies_lock = threading.Lock()
proxies_list = []


def loadProxiesFromFile(filename):
    global proxies_list
    try:
        f = open(filename)
    except Exception, e:
        logger.error('Configuration problem: proxyfile "{file}" not found or not readable: {e}'.format(file=filename, e=e))
    for line in f:
        line = line.strip()
        if line:  # LATER verify if the proxy line has the correct structure
            proxies_list.append(line)
    logger.debug('Found {count} proxies in file "{file}"'.format(file=filename, count=len(proxies_list)))


def getRandomProxy():
    global proxies_list
    proxy = None
    proxies_lock.acquire()
    if proxies_list:
        proxy = random.choice(proxies_list)
    proxies_lock.release()
    return proxy


def failedProxy(proxy):
    proxies_failed.append(proxy)
    if proxies_failed.count(proxy) >= 5 and proxies_list.count(proxy) >= 1:
        logger.info("Removing proxy {0} from proxy list because of to many errors errors.".format(proxy))
        proxies_lock.acquire()
        proxies_list.remove(proxy)
        proxies_lock.release()


class NoRedirectHandler(urllib2.HTTPRedirectHandler):
    '''
    This class is only necessary to not follow HTTP redirects in webpages.
    It is used by the downloadUrl() function
    '''
    def http_error_302(self, req, fp, code, msg, headers):
        infourl = urllib2.addinfourl(fp, headers, req.get_full_url())
        infourl.status = code
        infourl.code = code
        return infourl
    http_error_301 = http_error_303 = http_error_307 = http_error_302


def downloadUrl(url, data=None, cookie=None):
    try:
        opener = None
        # Random Proxy if set in config
        random_proxy = getRandomProxy()
        if random_proxy:
            proxyh = urllib2.ProxyHandler({'http': random_proxy})
            opener = urllib2.build_opener(proxyh, NoRedirectHandler())
        # We need to create an opener if it didn't exist yet
        if not opener:
            opener = urllib2.build_opener(NoRedirectHandler())
        # Random User-Agent if set in config
        user_agent = getRandomUserAgent()
        opener.addheaders = [('Accept-Charset', 'utf-8')]
        if user_agent:
            opener.addheaders.append(('User-Agent', user_agent))
        if cookie:
            opener.addheaders.append(('Cookie', cookie))
        logger.debug("Downloading url: {url} with proxy: {proxy} and user-agent: {ua}".format(url=url, proxy=random_proxy, ua=user_agent))
        if data:
            response = opener.open(url, data)
        else:
            response = opener.open(url)
        htmlPage = unicode(response.read(), errors='replace')
        # If we receive a "slow down" message, follow Pastebin recommendation!
        if 'Please slow down' in htmlPage:
            logger.warning("Slow down message received. Waiting 5 seconds")
            time.sleep(5)
            return downloadUrl(url)
        return htmlPage, response.headers
    except urllib2.HTTPError:
        logger.warning("ERROR: HTTP Error ############################# " + url)
        return None, None
    except urllib2.URLError:
        logger.debug("ERROR: URL Error ############################# " + url)
        if random_proxy:  # remove proxy from the list if needed
            failedProxy(random_proxy)
            logger.warning("Failed to download the page because of proxy error {0} trying again.".format(url))
            return downloadUrl(url)
    except socket.timeout:
        logger.debug("ERROR: timeout ############################# " + url)
        if random_proxy:  # remove proxy from the list if needed
            failedProxy(random_proxy)
            logger.warning("Failed to download the page because of proxy error {0} trying again.".format(url))
            return downloadUrl(url)
        return None, None
    except Exception, e:
        logger.error("ERROR: Other HTTPlib error: {e}".format(e=e))
        return None, None
    # do NOT try to download the url again here, as we might end in enless loop


class Sqlite3Database(threading.Thread):
    def __init__(self, filename):
        threading.Thread.__init__(self)
        self.kill_received = False
        self.queue = Queue.Queue()
        self.filename = filename
        self.db_conn = None
        self.c = None

    def run(self):
        self.db_conn = sqlite3.connect(self.filename)
        # create the db if it doesn't exist
        self.c = self.db_conn.cursor()
        try:
            # LATER maybe create a table per site. Lookups will be faster as less text-searching is needed
            self.c.execute('''
                CREATE TABLE IF NOT EXISTS pasties (
                    site TEXT,
                    id TEXT,
                    md5 TEXT,
                    url TEXT,
                    local_path TEXT,
                    timestamp DATE,
                    matches TEXT
                    )''')
            self.db_conn.commit()
        except sqlite3.DatabaseError, e:
            logger.error('Problem with the SQLite database {0}: {1}'.format(self.filename, e))
            return None
        # loop over the queue
        while not self.kill_received:
            try:
                # grabs pastie from queue
                pastie = self.queue.get()
                # add the pastie to the DB
                self.addOrUpdate(pastie)
                # signals to queue job is done
                self.queue.task_done()
            # catch unknown errors
            except Exception, e:
                logger.error("Thread for SQLite crashed unexpectectly, recovering...: {e}".format(e=e))

    def addOrUpdate(self, pastie):
        data = {'site': pastie.site.name,
                'id': pastie.id
                }
        self.c.execute('SELECT count(id) FROM pasties WHERE site=:site AND id=:id', data)
        pastie_in_db = self.c.fetchone()
        #logger.debug('State of Database for pastie {site} {id} - {state}'.format(site=pastie.site.name, id=pastie.id, state=pastie_in_db))
        if pastie_in_db and pastie_in_db[0]:
            self.update(pastie)
        else:
            self.add(pastie)

    def add(self, pastie):
        try:
            data = {'site': pastie.site.name,
                    'id': pastie.id,
                    'md5': pastie.md5,
                    'url': pastie.url,
                    'local_path': pastie.site.archive_dir + os.sep + pastie.site.pastieIdToFilename(pastie.id),
                    'timestamp': datetime.now(),
                    'matches': pastie.matchesToText()
                    }
            self.c.execute('INSERT INTO pasties VALUES (:site, :id, :md5, :url, :local_path, :timestamp, :matches)', data)
            self.db_conn.commit()
        except sqlite3.DatabaseError, e:
            logger.error('Cannot add pastie {site} {id} in the SQLite database: {error}'.format(site=pastie.site.name, id=pastie.id, error=e))
        logger.debug('Added pastie {site} {id} in the SQLite database.'.format(site=pastie.site.name, id=pastie.id))

    def update(self, pastie):
        try:
            data = {'site': pastie.site.name,
                    'id': pastie.id,
                    'md5': pastie.md5,
                    'url': pastie.url,
                    'local_path': pastie.site.archive_dir + os.sep + pastie.site.pastieIdToFilename(pastie.id),
                    'timestamp': datetime.now(),
                    'matches': pastie.matchesToText()
                    }
            self.c.execute('''UPDATE pasties SET md5 = :md5,
                                            url = :url,
                                            local_path = :local_path,
                                            timestamp  = :timestamp,
                                            matches = :matches
                     WHERE site = :site AND id = :id''', data)
            self.db_conn.commit()
        except sqlite3.DatabaseError, e:
            logger.error('Cannot add pastie {site} {id} in the SQLite database: {error}'.format(site=pastie.site.name, id=pastie.id, error=e))
        logger.debug('Updated pastie {site} {id} in the SQLite database.'.format(site=pastie.site.name, id=pastie.id))


def parseConfigFile(configfile):
    global yamlconfig
    try:
        yamlconfig = yaml.load(file(configfile))
    except yaml.YAMLError, exc:
        logger.error("Error in configuration file:")
        if hasattr(exc, 'problem_mark'):
            mark = exc.problem_mark
            logger.error("error position: (%s:%s)" % (mark.line + 1, mark.column + 1))
            exit(1)
    # TODO verify validity of config parameters
    if yamlconfig['proxy']['random']:
        loadProxiesFromFile(yamlconfig['proxy']['file'])
    if yamlconfig['user-agent']['random']:
        loadUserAgentsFromFile(yamlconfig['user-agent']['file'])


if __name__ == "__main__":
    global logger
    parser = optparse.OptionParser("usage: %prog [options]")
    parser.add_option("-c", "--config", dest="config",
                      help="load configuration from file", metavar="FILE")
    parser.add_option("-d", "--daemon", action="store_true", dest="daemon",
                      help="runs in background as a daemon (NOT IMPLEMENTED)")
    parser.add_option("-s", "--stats", action="store_true", dest="stats",
                      help="display statistics about the running threads (NOT IMPLEMENTED)")
    parser.add_option("-v", action="store_true", dest="verbose",
                      help="outputs more information")

    (options, args) = parser.parse_args()

    if not options.config:
        # try to read out the default configuration files if -c option is not set
        if os.path.isfile('/etc/pystemon.yaml'):
            options.config = '/etc/pystemon.yaml'
        if os.path.isfile('pystemon.yaml'):
            options.config = 'pystemon.yaml'
    if not os.path.isfile(options.config):
        parser.error('Configuration file not found. Please create /etc/pystemon.yaml, pystemon.yaml or specify a config file using the -c option.')
        exit(1)

    logger = logging.getLogger('pystemon')
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    if options.verbose:
        logger.setLevel(logging.DEBUG)

    if options.daemon:
        # send logging to syslog if using daemon
        logger.addHandler(logging.handlers.SysLogHandler(facility=logging.handlers.SysLogHandler.LOG_DAEMON))
        # FIXME run application in background

    parseConfigFile(options.config)
    # run the software
    main()
