from __future__ import annotations

from reflections.commons.exceptions import (
    BaseServiceException,
    BaseServiceNotFoundException,
    BaseServiceUnProcessableException,
)


class ArtifactsServiceException(BaseServiceException):
    pass


class ArtifactsNotConfiguredException(BaseServiceException):
    """Raised when CATALOG_BRIDGE_URL isn't set."""

    pass


class VolumeOfflineException(BaseServiceException):
    """Volume is registered but its mount point isn't reachable right now."""

    pass


class ArtifactsNotFoundException(BaseServiceNotFoundException):
    pass


class ArtifactsUnprocessableException(BaseServiceUnProcessableException):
    pass
