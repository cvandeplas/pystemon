from bs4 import BeautifulSoup
from pystemon.pastie import Pastie
import logging.handlers
logger = logging.getLogger('pystemon')

class PastieSniptNet(Pastie):
    '''
    Custom Pastie class for the snipt.net site
    This class overloads the fetch_pastie function to do the form submit
    to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = self.download_url(self.url)
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

