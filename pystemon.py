#!/usr/bin/env python
# encoding: utf-8

'''
@author:     Christophe Vandeplas <christophe@vandeplas.com>
@copyright:  GPLv3
Feel free to use the code, but please share the changes you've made

Features:
- flexible design, minimal effort to add another paste* site
- uses multiple threads per unique site to download the pastes
- waits a random time (within a range) before downloading the latest pastes, time customizable per site
- uses random User-Agents if requested
- uses random Proxies (SOCKS) if requested

To be implemented:
- FIXME set all the config options in the class variables
- FIXME validate parsing of config file
- FIXME use syslog logging
- FIXME runs as a daemon in background
- FIXME save files in separate directories depending on the day/week/month. Try to avoid duplicate files
- LATER let the user not save the data in the dir, but keep in memory what pastes have been saved to prevent duplicates
- TODO use random proxies

Python Dependencies
- BeautifulSoup
- PyYAML
- socksipy
'''

import optparse
import yaml
import threading
import Queue
import time
import urllib2
from BeautifulSoup import BeautifulSoup
import re
import os
import smtplib
import random
from email.MIMEMultipart import MIMEMultipart
from email.MIMEBase import MIMEBase
from email.MIMEText import MIMEText
from email import Encoders


class PasteSite():
    def __init__(self):
        self.name = 'general'
        self.download_url = '{0}'
        self.save_dir = yamlconfig['archive']['dir']
        self.update_max = 30  # TODO set by config file
        self.update_min = 10  # TODO set by config file

    def getLastPasties(self):
        print "ERROR: Please implement this function in the child class"


class Pastie():
    def __init__(self, site, pastie_id):
        self.site = site
        self.id = pastie_id
        self.pastie_content = None
        self.url = self.site.download_url.format(self.id)

    def fetchPastie(self):
        self.pastie_content = downloadUrl(self.url)
        return self.pastie_content

    def savePastie(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, sannot save')
        f = open(self.site.save_dir + os.sep + self.id, 'w')
        f.write(self.pastie_content)  # TODO error checking

    def pastieAlreadySeen(self):
        if yamlconfig['archive']['save']:
            # check if the pastie was already saved on the disk
            if os.path.exists(self.site.save_dir + os.sep + self.id):
                return True
        # TODO check memory-list of recently seen pasties

    def fetchAndProcessPastie(self):
        # check if the pastie was already downloaded
        if self.pastieAlreadySeen():
            return None
        # download pastie
        self.pastie_content = self.fetchPastie()
        # save the pastie on the disk
        if self.pastie_content:
            # Save pastie to disk if configured
            if yamlconfig['archive']['save']:
                self.savePastie()
            # search for data in pastie
            self.searchContent()
        return self.pastie_content

    def searchContent(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, cannot search')
            return False
        # search for the regexes in the htmlPage
        for regex in yamlconfig['regex-search']:
            # TODO first compile regex, then search using compiled version
            m = re.search(regex, self.pastie_content)
            if m:
                #print regex
                self.alertOnMatch(regex)

    def alertOnMatch(self, regex):
        alert = "Found hit for {regex} in pastie {url}".format(regex=regex, url=self.site.download_url.format(self.id))
        print alert
        # Send email alert if configured
        if yamlconfig['email']['alert']:
            self.sendEmailAlert(regex)

    def sendEmailAlert(self, regex):
        msg = MIMEMultipart()
        alert = "Found hit for {regex} in pastie {url}".format(regex=regex, url=self.site.download_url.format(self.id))
        # headers
        msg['Subject'] = yamlconfig['email']['subject'].format(subject=alert)
        msg['From'] = yamlconfig['email']['from']
        msg['To'] = yamlconfig['email']['to']
        # message body
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expression that matched:    {regex}
The paste has also been attached to this email.

# LATER below follows a small exerpt from the paste to give you direct context

        '''.format(site=self.site.name, url=self.url, regex=regex)
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
            print "ERROR: unable to send email"


class PastebinComSite(PasteSite):
    def __init__(self):
        PasteSite.__init__(self)
        self.name = 'pastebin.com'
        self.download_url = 'http://pastebin.com/raw.php?i={0}'
        self.archive_url = 'http://pastebin.com/archive'
        self.save_dir = self.save_dir + os.sep + self.name
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

    def getLastPasties(self):
        # reset the pasties list
        self.pasties = []
        # populate queue with data
        htmlPage = downloadUrl(self.archive_url)
        if not htmlPage:
            return False
        htmlDom = BeautifulSoup(htmlPage)
        content_left = htmlDom.find(id='content_left')
        allLinks = content_left.findAll('a', {'href': True})
        for link in allLinks:
            if len(link['href']) == 9:
                self.pasties.append(Pastie(self, link['href'][1:]))
        return self.pasties


class PastieOrgSite(PasteSite):
    def __init__(self):
        PasteSite.__init__(self)
        self.name = 'pastie.org'
        self.download_url = 'http://pastie.org/pastes/{0}/text'
        self.archive_url = 'http://pastie.org/pastes'
        self.save_dir = self.save_dir + os.sep + self.name
        self.pasties = []
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

    def getLastPasties(self):
        # reset the pasties list
        self.pasties = []
        #populate queue with data
        htmlPage = downloadUrl(self.archive_url)
        if not htmlPage:
            return False
        htmlDom = BeautifulSoup(htmlPage)
        allLinks = htmlDom.findAll('a', href=re.compile("/pastes/[0-9][0-9]+"))
        for link in allLinks:
            paste_id = link['href'].split('/')[-1]
            if paste_id:
                self.pasties.append(Pastie(self, paste_id))
        return self.pasties


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
                #print "Saved new pastie from {0} with id {1}".format(pb.name, pastie.id)
                print "Queue {name} size: {size}".format(size=self.queue.qsize(), name=self.name)
            else:
                # pastie already downloaded OR error ?
                pass
            # signals to queue job is done
            self.queue.task_done()


class ThreadSites(threading.Thread):
    '''
    Instances of these threads are responsible to download the list of the last pastes
    and adding them to the list of pending tasks for individual pastes
    '''
    def __init__(self, site_name):
        threading.Thread.__init__(self)
        self.site_name = site_name
        self.kill_received = False
        class_name = globals()[self.site_name + 'Site']
        self.site = class_name()

    def run(self):
        while not self.kill_received:
            # grabs site from queue
            print "Downloading pasties from {0}".format(self.site.name)
            # get the list of last pasties, but reverse it so we first have the old
            # entries and then the new ones
            for pastie in reversed(self.site.getLastPasties()):
                queues[self.site_name].put(pastie)  # add pastie to queue

            sleep_time = random.randint(yamlconfig['site'][self.site_name]['update-min'], yamlconfig['site'][self.site_name]['update-max'])
            print "Sleeping {name} for {time} seconds".format(name=self.site_name, time=sleep_time)
            time.sleep(sleep_time)


def main():
    global queues
    global threads
    queues = {}
    threads = []

    # spawn a pool of threads per PasteSite, and pass them a queue instance
    for site in yamlconfig['site']:
        queues[site] = Queue.Queue()
        for i in range(yamlconfig['threads']):
            t = ThreadPasties(queues[site], site)
            t.setDaemon(True)
            threads.append(t)
            t.start()

    # build threads to download the last pasties
    for site in yamlconfig['site']:
        t = ThreadSites(site)
        threads.append(t)
        t.setDaemon(True)
        t.start()

    # wait while all the threads are running and someone sends CTRL+C
    while True:
        try:
            threads = [t.join(1) for t in threads if t is not None and t.isAlive()]
        except KeyboardInterrupt:
            print ''
            print "Ctrl-c received! Sending kill to threads..."
            for t in threads:
                t.kill_received = True
            exit(0)  # quit immediately


def getRandomUserAgent():
    return random.choice(yamlconfig['user-agent']['list'])


def downloadUrl(url):
    try:
        # Random Proxy if set in config
        if yamlconfig['proxy']['random']:
            # FIXME implement random proxy
            pass
        # Random User-Agent if set in config
        if yamlconfig['user-agent']['random']:
            headers = {'User-Agent': getRandomUserAgent()}
            request = urllib2.Request(url, None, headers)
        else:
            request = urllib2.Request(url)
        htmlPage = urllib2.urlopen(request).read()
        return htmlPage
    except urllib2.HTTPError:
        print "ERROR: HTTP Error ############################# " + url
        return False


def parseConfigFile(configfile):
    global yamlconfig
    try:
        yamlconfig = yaml.load(file(configfile))
    except yaml.YAMLError, exc:
        print "Error in configuration file:",
        if hasattr(exc, 'problem_mark'):
            mark = exc.problem_mark
            print "error position: (%s:%s)" % (mark.line + 1, mark.column + 1)
            exit(1)
        print ''
    # TODO verify validity of config parameters


if __name__ == "__main__":
    parser = optparse.OptionParser("usage: %prog [options]")
    parser.add_option("-c", "--config", dest="config",
                      help="load configuration from file", metavar="FILE")
    parser.add_option("-d", "--daemon", action="store_true",
                      help="runs in background as a daemon (NOT IMPLEMENTED)")
    parser.add_option("-s", "--stats", action="store_true", dest="stats",
                      help="display statistics about the running threads (NOT IMPLEMENTED)")
    parser.add_option("-v", action="store_true", dest="verbose",
                      help="outputs more information (NOT IMPLEMENTED)")

    (options, args) = parser.parse_args()

    if not options.config:
        # try to read out the default configuration files if -c option is not set
        if os.path.isfile('/etc/pystemon.yaml'):
            options.config = '/etc/pystemon.yaml'
        if os.path.isfile('pystemon.yaml'):
            options.config = 'pystemon.yaml'
    if not os.path.isfile(options.config):
        print options.config
        parser.error('Configuration file not found. Please create /etc/pystemon.yaml, pystemon.yaml or specify a config file using the -c option.')
        exit(1)
    parseConfigFile(options.config)

    # run the software
    main()
