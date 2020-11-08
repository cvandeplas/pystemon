from bs4 import BeautifulSoup
from pystemon.pastie import Pastie
import logging.handlers
logger = logging.getLogger('pystemon')

class PastieSlexyOrg(Pastie):
    '''
    Custom Pastie class for the pastesite.com site
    This class overloads the fetch_pastie function to do the form
    submit to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = self.download_url(self.url)
        validation_form_page = response.text
        if validation_form_page:
            htmlDom = BeautifulSoup(validation_form_page, 'lxml')
            if not htmlDom:
                return self.pastie_content
            a = htmlDom.find('a', {'target': '_blank'})
            if not a:
                return self.pastie_content
            url = "https://slexy.org{}".format(a['href'])
            response2 = self.download_url(url)
            self.pastie_content = response2.content
        return self.pastie_content

