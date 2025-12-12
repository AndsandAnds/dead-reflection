from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceUnProcessableException,
)

MEMORY_SERVICE_EXCEPTION = {
    "message": "Memory service error",
    "details": "Failed to process memory operation",
}


class MemoryServiceException(BaseServiceException):
    pass


class MemoryUnprocessableException(BaseServiceUnProcessableException):
    pass
