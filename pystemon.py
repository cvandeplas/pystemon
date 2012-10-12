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
import yaml
import threading
import Queue
from collections import deque
import time
import urllib2
import urllib
import socket
import re
import os
import smtplib
import random
from BeautifulSoup import BeautifulSoup
from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders
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
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.update_max = 30  # TODO set by config file
        self.update_min = 10  # TODO set by config file
        self.pastie_classname = None
        self.seen_pasties = deque('', 1000)  # max number of pasties ids in memory

    def run(self):
        while not self.kill_received:
            # grabs site from queue
            logger.info("Downloading pasties from {0}".format(self.name))
            # get the list of last pasties, but reverse it so we first have the old
            # entries and then the new ones
            for pastie in reversed(self.getLastPasties()):
                queues[self.name].put(pastie)  # add pastie to queue
            sleep_time = random.randint(self.update_min, self.update_max)
            logger.info("Sleeping {name} for {time} seconds".format(name=self.name, time=sleep_time))
            time.sleep(sleep_time)

    def getLastPasties(self):
        # reset the pasties list
        pasties = []
        # populate queue with data
        htmlPage, headers = downloadUrl(self.archive_url)
        if not htmlPage:
            return False
        pasties_ids = re.findall(self.archive_regex, htmlPage)
        if pasties_ids:
            for pastie_id in pasties_ids:
                if self.pastie_classname:
                    class_name = globals()[self.pastie_classname]
                    pastie = class_name(self, pastie_id)
                else:
                    pastie = Pastie(self, pastie_id)
                pasties.append(pastie)
            logger.debug("Found {amount} pasties for site {site}".format(amount=len(pasties_ids), site=self.name))
            return pasties
        logger.warn("No last pasties matches for regular expression site:{site} regex:{regex}".format(site=self.name, regex=self.archive_regex))
        return False

    def seenPastie(self, pastie_id):
        ''' check if the pastie was already downloaded, and remember that we've seen it '''
        # first look in memory if we have already seen this pastie
        if self.seen_pasties.count(pastie_id):
            return True
        # look on the filesystem.  # LATER remove this filesystem lookup as it will give problems on long term
        if yamlconfig['archive']['save']:
            # check if the pastie was already saved on the disk
            if os.path.exists(self.save_dir + os.sep + pastie_id):
                return True

        # we have not yet seen the pastie
        # keep in memory that we've seen it
        # appendleft for performance reasons (faster later when we iterate over the deque)
        self.seen_pasties.appendleft(pastie_id)
        return False


class Pastie():
    def __init__(self, site, pastie_id):
        self.site = site
        self.id = pastie_id
        self.pastie_content = None
        self.url = self.site.download_url.format(id=self.id)

    def fetchPastie(self):
        self.pastie_content, headers = downloadUrl(self.url)
        return self.pastie_content

    def savePastie(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, sannot save')
        f = open(self.site.save_dir + os.sep + self.id, 'w')
        f.write(self.pastie_content)  # TODO error checking

    def fetchAndProcessPastie(self):
        # check if the pastie was already downloaded, and remember that we've seen it
        if self.site.seenPastie(self.id):
            return None
        # download pastie
        self.fetchPastie()
        # save the pastie on the disk
        if self.pastie_content:
            # Save pastie to disk if configured
            if yamlconfig['archive']['save']:
                self.savePastie()
            # search for data in pastie
            self.searchContent()
        return self.pastie_content

    def searchContent(self):
        matches = []
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, cannot search')
            return False
        # TODO only alert once per pastie
        # search for the regexes in the htmlPage
        for regex in yamlconfig['regex-search']:
            # TODO first compile regex, then search using compiled version
            m = re.search(regex, self.pastie_content)
            if m:
                matches.append(regex)
                #print regex
        if matches:
            self.alertOnMatch(matches)

    def alertOnMatch(self, matches):
        alert = "Found hit for {matches} in pastie {url}".format(matches=matches, url=self.url)
        logger.info(alert)
        # Send email alert if configured
        if yamlconfig['email']['alert']:
            self.sendEmailAlert(matches)

    def sendEmailAlert(self, matches):
        msg = MIMEMultipart()
        alert = "Found hit for {matches} in pastie {url}".format(matches=matches, url=self.url)
        # headers
        msg['Subject'] = yamlconfig['email']['subject'].format(subject=alert)
        msg['From'] = yamlconfig['email']['from']
        msg['To'] = yamlconfig['email']['to']
        # message body
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expression that matched:    {matches}
The paste has also been attached to this email.

# LATER below follows a small exerpt from the paste to give you direct context

        '''.format(site=self.site.name, url=self.url, matches=matches)
        msg.attach(MIMEText(message))
        # original paste as attachment
        part = MIMEBase('application', "octet-stream")
        part.set_payload(self.pastie_content)
        Encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="%s"' % self.id)
        msg.attach(part)
        # send out the mail
        try:
            s = smtplib.SMTP(yamlconfig['email']['server'])
            s.sendmail(yamlconfig['email']['from'], yamlconfig['email']['to'], msg.as_string())
            s.close()
        except smtplib.SMTPException:
            logger.error("unable to send email")


class PastiePasteSiteCom(Pastie):
    '''
    Custom Pastie class for the pastesite.com site
    This class overloads the fetchPastie function to do the form submit to get the raw pastie
    '''
    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetchPastie(self):
        validation_form_page, headers = downloadUrl(self.url)
        htmlDom = BeautifulSoup(validation_form_page)
        content_left = htmlDom.find(id='full-width')
        plain_confirm = content_left.find('input')['value']
        # build a form with plainConfirm = value and the cookie
        data = urllib.urlencode({'plainConfirm': plain_confirm})
        url = "http://pastesite.com/plain/{id}".format(id=self.id)
        cookie = headers.dict['set-cookie']
        self.pastie_content, headers = downloadUrl(url, data, cookie)
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
            # grabs pastie from queue
            pastie = self.queue.get()
            pastie_content = pastie.fetchAndProcessPastie()
            if pastie_content:
                logger.debug("Saved new pastie from {0} with id {1}".format(self.name, pastie.id))
                logger.info("Queue {name} size: {size}".format(size=self.queue.qsize(), name=self.name))
            else:
                # pastie already downloaded OR error ?
                pass
            # signals to queue job is done
            self.queue.task_done()


def main():
    global queues
    global threads
    queues = {}
    threads = []

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


def getRandomUserAgent():
    if yamlconfig['user-agent']['random'] and yamlconfig['user-agent']['list']:
        return random.choice(yamlconfig['user-agent']['list'])
    return None


def getRandomProxy():
    proxy = None
    proxies_lock.acquire()
    if yamlconfig['proxy']['random'] and yamlconfig['proxy']['list']:
        proxy = random.choice(yamlconfig['proxy']['list'])
    proxies_lock.release()
    return proxy


proxies_failed = []
proxies_lock = threading.Lock()


def failedProxy(proxy):
    proxies_failed.append(proxy)
    if proxies_failed.count(proxy) >= 5 and yamlconfig['proxy']['list'].count(proxy) >= 1:
        logger.info("Removing proxy {0} from proxy list because of to many errors errors.".format(proxy))
        proxies_lock.acquire()
        yamlconfig['proxy']['list'].remove(proxy)
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
            proxy = urllib2.ProxyHandler({'http': random_proxy})
            opener = urllib2.build_opener(proxy, NoRedirectHandler())
        # We need to create an opener if it didn't exist yet
        if not opener:
            opener = urllib2.build_opener(NoRedirectHandler())
        # Random User-Agent if set in config
        user_agent = getRandomUserAgent()
        if user_agent:
            opener.addheaders = [('User-Agent', user_agent)]
        if cookie:
            opener.addheaders.append(('Cookie', cookie))
        logger.debug("Downloading url: {url} with proxy:{proxy} and user-agent:{ua}".format(url=url, proxy=random_proxy, ua=user_agent))
        if data:
            response = opener.open(url, data)
        else:
            response = opener.open(url)
        htmlPage = response.read()
        # If we receive a "slow down" message, follow Pastebin recommendation!
        if 'Please slow down' in htmlPage:
            logger.warn("Slow down message received. Waiting 5 seconds")
            time.sleep(5)
            return downloadUrl(url)
        return htmlPage, response.headers
    except urllib2.HTTPError:
        logger.warn("ERROR: HTTP Error ############################# " + url)
        return None
    except urllib2.URLError:
        logger.debug("ERROR: URL Error ############################# " + url)
        if random_proxy:  # remove proxy from the list if needed
            failedProxy(random_proxy)
            logger.warn("Failed to download the page because of proxy error {0} trying again.".format(url))
            return downloadUrl(url)
    except socket.timeout:
        logger.debug("ERROR: timeout ############################# " + url)
        if random_proxy:  # remove proxy from the list if needed
            failedProxy(random_proxy)
            logger.warn("Failed to download the page because of proxy error {0} trying again.".format(url))
            return downloadUrl(url)
    # do NOT try to download the url again here, as we might end in enless loop


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
    parseConfigFile(options.config)

    logger = logging.getLogger('pystemon')
    logger.setLevel(logging.INFO)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    if options.verbose:
        logger.setLevel(logging.DEBUG)

    if options.daemon:
        # send logging to syslog if using daemon
        logger.addHandler(logging.handlers.SysLogHandler(facility=logging.handlers.SysLogHandler.LOG_DAEMON))
        # FIXME run application in background

    # run the software
    main()
