
class PystemonException(Exception):
    pass

class PystemonConfigException(PystemonException):
    pass

class PystemonKillReceived(PystemonException):
    pass

class PystemonStopRequested(PystemonException):
    pass

class PystemonReloadRequested(PystemonException):
    pass

