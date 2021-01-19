from bs4 import BeautifulSoup
from pystemon.pastie import Pastie
import logging.handlers
logger = logging.getLogger('pystemon')

class PastiePasteOrgRu(Pastie):
    '''
    Custom Pastie class for the paste.org.ru site,
    This class overloads the fetch_pastie function to extract the pastie from the page
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = self.download_url(self.url)
        if response.text:
            htmlDom = BeautifulSoup(response.text, 'lxml')
            if not htmlDom:
                return self.pastie_content
            self.pastie_content = htmlDom.find('textarea').contents.pop().encode('utf-8')
        return self.pastie_content


