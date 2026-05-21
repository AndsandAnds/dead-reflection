from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


class CalendarServiceException(BaseServiceException):
    pass


class CalendarNotConfiguredException(BaseServiceException):
    """Raised when CALENDAR_BRIDGE_URL isn't set — feature isn't enabled."""

    pass


class CalendarNotAuthorizedException(BaseServiceException):
    """Bridge is reachable but the user hasn't granted Calendar access yet."""

    pass


class CalendarNotFoundException(BaseServiceNotFoundException):
    pass


class CalendarUnprocessableException(BaseServiceUnProcessableException):
    pass
