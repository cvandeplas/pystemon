import logging.handlers
import hashlib
import time

logger = logging.getLogger('pystemon')

class Pastie():

    def __init__(self, site, pastie_id):
        self.site = site
        self.id = pastie_id
        self.pastie_content = None
        self.pastie_metadata = None
        self.matches = []
        self.matched = False
        self.md5 = None
        self.url = self.site.download_url.format(id=self.id)
        self.public_url = self.site.public_url.format(id=self.id)
        self.metadata_url = None
        if self.site.metadata_url is not None:
            self.metadata_url = self.site.metadata_url.format(id=self.id)
        self.filename = self.site.pastie_id_to_filename(self.id)
        self.user_agent = None

    def hash_pastie(self):
        if self.pastie_content:
            try:
                self.md5 = hashlib.md5(self.pastie_content).hexdigest()
                logger.debug('Pastie {site} {id} has md5: "{md5}"'.format(site=self.site.name, id=self.id, md5=self.md5))
            except Exception as e:
                logger.error('Pastie {site} {id} md5 problem: {e}'.format(site=self.site.name, id=self.id, e=e))

    def download_url(self, url, **kwargs):
        return self.user_agent.download_url(url, **kwargs)

    def fetch_pastie(self):
        if self.metadata_url is not None:
            response = self.download_url(self.metadata_url)
            if response is not None:
                response = response.content
                self.pastie_metadata = response
        response = self.download_url(self.url)
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

    '''
    This is the entry point of the PastieSite to download the pastie
    To have a stable ABI, this function should save all required
     elements in the pastie, such as the UA.
    '''
    def fetch_and_process_pastie(self, user_agent):
        self.user_agent = user_agent
        # download pastie
        self.__fetch_pastie__()
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
            logger.error("ERROR: on post-action for pastie {0}: {1}".format(self.id, e))

    def search_content(self):
        if not self.pastie_content:
            raise SystemExit('BUG: Content not set, cannot search')
        logger.debug('Looking for matches in pastie {url}'.format(url=self.public_url))
        # search for the regexes in the htmlPage
        for regex in self.site.patterns:
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
        if len(self.pastie_content) > yamlconfig['email']['size-limit']:
            part = MIMEBase('application', "text/plain")
            part.set_payload(self.pastie_content.decode('utf8'))
            Encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="{id}.txt"'.format(id=self.id))
            msg.attach(part)
            content = "*** Content to large to be displayed, see attachment ***"
        else:
            content = self.pastie_content.decode('utf8')
        # message body including full paste if not to large rather than attaching it
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expressions that matched:   {matches}

Below (after newline) is the content of the pastie:

{content}

        '''.format(site=self.site.name, url=self.public_url, matches=self.matches_to_regex(), content=content)
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


