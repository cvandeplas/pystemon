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
- uses random proxies if requested, and remove if a proxy is unreliable (fails 5 times)

Python Dependencies
- BeautifulSoup
- PyYAML

Default configuration file: /etc/pystemon.yaml or pystemon.yaml in current directory

Limitations:
- Only HTTP proxies are allowed