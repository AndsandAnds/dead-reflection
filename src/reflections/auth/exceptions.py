from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


class AuthServiceException(BaseServiceException):
    pass


class AuthServiceNotFoundException(BaseServiceNotFoundException):
    pass


class AuthServiceUnprocessableException(BaseServiceUnProcessableException):
    pass


