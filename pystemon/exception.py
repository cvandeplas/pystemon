
class PystemonException(Exception):
    pass

class PystemonConfigException(PystemonException):
    pass

class PystemonConfigEmpty(PystemonConfigException):
    pass

class PystemonKillReceived(PystemonException):
    pass

class PystemonStopRequested(PystemonException):
    pass

class PystemonReloadRequested(PystemonException):
    pass

class PystemonQueueStatRequested(PystemonException):
    pass
