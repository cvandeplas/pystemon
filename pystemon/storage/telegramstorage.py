
import logging.handlers
import requests
from pystemon.storage import PastieStorage

logger = logging.getLogger('pystemon')

class TelegramStorage(PastieStorage):

    def __init_storage__(self, **kwargs):
        self.token = kwargs.get('token')
        self.chat_ids = kwargs.get('chat-ids')

    def __save_pastie__(self, pastie):
        if pastie.matched:
            message = '''
I found a hit for a regular expression on one of the pastebin sites.

The site where the paste came from :        {site}
The original paste was located here:        {url}
And the regular expressions that matched:   {matches}

Below (after newline) is the content of the pastie:

{content}

        '''.format(site=pastie.site.name, url=pastie.public_url, matches=pastie.matches_to_regex(), content=pastie.pastie_content.decode('utf8'))

            url = 'https://api.telegram.org/bot{0}/sendMessage'.format(self.token)
            for chat_id in self.chat_ids:
                try:
                    logger.debug('Sending message to telegram {} for pastie_id {}'.format(url, pastie.id))
                    requests.post(url, data={'chat_id': chat_id, 'text': message})
                except Exception as e:
                    logger.warning("Failed to alert through telegram: {0}".format(e))
