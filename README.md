pystemon
========
Monitoring tool for PasteBin-alike sites written in Python

Copyleft GPLv3 - Christophe Vandeplas - christophe@vandeplas.com
Feel free to use the code, but please share the changes you've made

Features:
---------
* search for regular expressions in pasties
* (optional) only trigger on X hits in the same pastie
* (optional) exclude matching pasties if exclusion regex matches
* flexible design, minimal effort to add another paste* site
* uses multiple threads per unique site to download the pastes
* waits a random time (within a range) before downloading the latest pastes, time customizable per site
* (optional) uses random User-Agents
* (optional) uses random proxies
* removes a proxy if it is unreliable (fails 5 times)
* use custom download functions for complex pastie sites
* (optional) compress saved files with Gzip. (no zip to limit external dependencies)

Python Dependencies
-------------------
* PyYAML
* BeautifulSoup

Limitations:
------------
* Only HTTP proxies are allowed
* Only HTTP urls will use proxies

Usage: pystemon.py [options]
-----
Options:
      -h, --help            show this help message and exit
      -c FILE, --config=FILE
                            load configuration from file
      -d, --daemon          runs in background as a daemon (NOT IMPLEMENTED)
      -s, --stats           display statistics about the running threads (NOT
                            IMPLEMENTED)
      -v                    outputs more information
  
Default configuration file: /etc/pystemon.yaml or pystemon.yaml in current directory
 