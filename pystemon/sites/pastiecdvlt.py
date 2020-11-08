import json
from pystemon.pastie import Pastie
import logging.handlers
logger = logging.getLogger('pystemon')

class PastieCdvLt(Pastie):
    '''
    Custom Pastie class for the cdv.lt site
    This class overloads the fetch_pastie function to do the form submit
    to get the raw pastie
    '''

    def __init__(self, site, pastie_id):
        Pastie.__init__(self, site, pastie_id)

    def fetch_pastie(self):
        response = self.download_url(self.url)
        downloaded_page = response.text
        if downloaded_page:
            # convert to json object
            json_pastie = json.loads(downloaded_page)
            if json_pastie:
                # and extract the code
                self.pastie_content = json_pastie['snippet']['snippetData']
        return self.pastie_content

