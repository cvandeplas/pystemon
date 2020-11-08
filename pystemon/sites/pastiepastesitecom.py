from bs4 import BeautifulSoup
try:
    from urllib.parse import urlencode
except ImportError:
    from urllib import urlencode

from pystemon.pastie import Pastie
import logging.handlers
logger = logging.getLogger('pystemon')

class PastiePasteSiteCom(Pastie):
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
            content_left = htmlDom.find(id='full-width')
            if not content_left:
                return self.pastie_content
            plain_confirm = content_left.find('input')['value']
            # build a form with plainConfirm = value (the cookie remains in the requests session)
            data = urlencode({'plainConfirm': plain_confirm})
            url = "http://pastesite.com/plain/{id}".format(id=self.id)
            response2 = self.download_url(url, data=data)
            self.pastie_content = response2
        return self.pastie_content


