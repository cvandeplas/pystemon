import logging.handlers
logger = logging.getLogger('pystemon')

class PastieSearch():
    def __init__(self, engine, regex):
        # set the re.FLAGS
        if 'regex-flags' in regex:
            self.regex_flags = regex['regex-flags']
            self.flags = eval(self.regex_flags)
        else:
            self.regex_flags = None
            self.flags = engine.IGNORECASE
        # compile the search regex
        self.search = regex['search']
        try:
            self.re_search = engine.compile(self.search.encode(), self.flags)
        except Exception as e:
            raise ValueError("invalid search regex: %s" % e)
        # compile the exclude regex
        self.exclude = regex.get('exclude')
        if self.exclude is not None:
            try:
                self.re_exclude = engine.compile(self.exclude.encode(), self.flags)
            except Exception as e:
                raise ValueError("invalid exclude regex: %s" % e)
        # get the description
        self.description = regex.get('description')
        # get the count and convert it to integer
        if 'count' in regex:
            self.count = int(regex['count'])
        else:
            self.count = -1
        # get the optional to and split it
        self.to = regex.get('to')
        if self.to is not None:
            self.ato = self.to.split(",")
        else:
            self.ato = []
        # add any extra things stored in yaml
        self.extra = {}
        for (k, v) in regex.items():
            if k in ['search', 'description', 'exclude', 'count', 'regex-flags', 'to']:
                continue
            self.extra[k] = v
        self.h = None
        logger.debug("[{0}]: compiled into: {1}".format(self.search, self.re_search))

    def __str__(self):
        return self.to_text()

    def __repr__(self):
        return self.to_regex()

    def match(self, string):
        m = self.re_search.findall(string)
        if not m:
            return False
        # the regex matches the text
        # ignore if not enough counts
        if (self.count > 0) and (len(m) < self.count):
            return False
        # ignore if exclude
        if self.exclude is not None:
            if self.re_exclude.search(string):
                return False
        # we have a match
        return True

    def to_text(self):
        if self.description is None:
            return self.search
        return self.description

    def to_regex(self):
        return self.search

    def to_dict(self):
        if self.h is None:
            self.h = {'search': self.search}
            if self.description is not None:
                self.h['description'] = self.description
            if self.exclude is not None:
                self.h['exclude'] = self.exclude
            if self.count >= 0:
                self.h['count'] = self.count
            if self.to is not None:
                self.h['to'] = self.to
            if self.regex_flags is not None:
                self.h['regex-flags'] = self.regex_flags
            for (k, v) in self.extra.items():
                self.h[k] = v
        return self.h



