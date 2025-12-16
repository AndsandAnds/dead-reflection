from __future__ import annotations

from reflections.commons.exceptions import BaseServiceException


class ConversationsServiceException(BaseServiceException):
    pass


CONVERSATION_NOT_FOUND = "conversation_not_found"


