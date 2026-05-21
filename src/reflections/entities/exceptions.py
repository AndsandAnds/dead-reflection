from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


class EntitiesServiceException(BaseServiceException):
    pass


class EntitiesNotFoundException(BaseServiceNotFoundException):
    pass


class EntitiesUnprocessableException(BaseServiceUnProcessableException):
    pass
