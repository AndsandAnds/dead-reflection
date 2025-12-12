"""
Common/base exceptions.

These are intended to be subclassed by feature-level exceptions in
`<feature>/exceptions.py`.
"""


class BaseServiceException(Exception):
    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self.message)


class BaseServiceNotFoundException(BaseServiceException):
    pass


class BaseServiceUnProcessableException(BaseServiceException):
    pass


class BaseCoreException(Exception):
    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self.message)
