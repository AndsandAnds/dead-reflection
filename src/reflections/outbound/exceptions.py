from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceUnProcessableException,
)


class OutboundServiceException(BaseServiceException):
    pass


class OutboundForbiddenException(BaseServiceException):
    """Raised when a non-admin user attempts an outbound HTTP call."""

    pass


class OutboundUnprocessableException(BaseServiceUnProcessableException):
    pass
