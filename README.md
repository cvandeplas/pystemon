pystemon
========

Monitoring tool for PasteBin-alike sites written in Python

Copyleft GPLv3 - Christophe Vandeplas - christophe@vandeplas.com
Feel free to use the code, but please share the changes you've made

Features:
- flexible design, minimal effort to add another paste* site
- uses multiple threads per unique site to download the pastes
- waits a random time (within a range) before downloading the latest pastes, time customizable per site
- uses random User-Agents if requested
- uses random Proxies if requested

Python Dependencies
- BeautifulSoup
- PyYAML
- socksipy

Default configuration file: /etc/pystemon.yaml or pystemon.yaml in current directory

Limitations:
- HTTPS pastie sites are NOT supported if proxies are used (because of a limitation of urllib2)
