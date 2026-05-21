from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceUnProcessableException,
)


class VaultServiceException(BaseServiceException):
    pass


class VaultUnprocessableException(BaseServiceUnProcessableException):
    pass
