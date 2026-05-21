from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


class McpServiceException(BaseServiceException):
    pass


class McpTokenNotFoundException(BaseServiceNotFoundException):
    pass


class McpUnprocessableException(BaseServiceUnProcessableException):
    pass
