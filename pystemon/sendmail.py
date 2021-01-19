
import logging.handlers
import smtplib
try:
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email.mime.text import MIMEText
    from email import encoders as Encoders
except ImportError:
    from email.MIMEMultipart import MIMEMultipart
    from email.MIMEBase import MIMEBase
    from email.MIMEText import MIMEText
    from email import Encoders

logger = logging.getLogger('pystemon')

class PystemonSendmail():

    def __init__(self, mailfrom, mailto, subject,
            server='127.0.0.1', port=25, tls=False, username=None, password=None, size_limit=1024*1024):
        self.mailfrom = mailfrom
        self.mailto = mailto
        self.subject = subject
        self.server = server
        self.port = port
        self.tls = tls
        self.username = username
        self.password = password
        self.size_limit = size_limit

    def __repr__(self):
        return 'PystemonSendmail[from={}][to={}]'.format(self.mailfrom, self.mailto)

    def is_same_as(self, other):
        res = False
        try:
            res = (isinstance(other, PystemonSendmail)
                    and
                    (self.mailfrom == other.mailfrom)
                    and
                    (self.mailto == other.mailto)
                    and
                    (self.subject == other.subject)
                    and
                    (self.server == other.server)
                    and
                    (self.port == other.port)
                    and
                    (self.tls == other.tls)
                    and
                    (self.username == other.username)
                    and
                    (self.password == other.password)
                    and
                    (self.size_limit == other.size_limit))
        except Exception as e:
            logger.error("Unable to compare PystemonSendmail instances: {}".format(e))
            pass
        return res

    def send_pastie_alert(self, pastie):
        msg = MIMEMultipart()
        alert = "Found hit for {matches} in pastie {url}".format(matches=pastie.matches_to_text(), url=pastie.public_url)
        # headers
        msg['Subject'] = self.subject.format(subject=alert)
        msg['From'] = self.mailfrom
        # build the list of recipients
        recipients = []
        recipients.append(self.mailto)  # first the global alert email
        for match in pastie.matches:    # per match, the custom additional email
            if match.to is not None:
                recipients.extend(match.ato)
        msg['To'] = ','.join(recipients)  # here the list needs to be comma separated
        if len(pastie.pastie_content) > self.size_limit:
            part = MIMEBase('application', "text/plain")
            part.set_payload(pastie.pastie_content.decode('utf8'))
            Encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="{id}.txt"'.format(id=pastie.id))
            msg.attach(part)
            content = "*** Content to large to be displayed, see attachment ***"
        else:
            content = pastie.pastie_content.decode('utf8')
        # message body including full paste if not to large rather than attaching it
        message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expressions that matched:   {matches}

Below (after newline) is the content of the pastie:

{content}

        '''.format(site=pastie.site.name, url=pastie.public_url, matches=pastie.matches_to_regex(), content=content)
        msg.attach(MIMEText(message))
        # send out the mail
        try:
            s = smtplib.SMTP(self.server, self.port)
            if self.tls:
                s.starttls()
            # login to the SMTP server if configured
            if self.username:
                s.login(self.username, self.password)
            # send the mail
            s.sendmail(self.mailfrom, recipients, msg.as_string())
            s.close()
        except smtplib.SMTPException as e:
            logger.error("ERROR: unable to send email: {0}".format(e))
        except Exception as e:
            logger.error("ERROR: unable to send email. Are your email setting correct?: {e}".format(e=e))

