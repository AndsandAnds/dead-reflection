VOICE_SERVICE_RUN_SESSION_EXCEPTION = {
    "message": "Failed to run voice session",
    "details": "Unexpected error while streaming voice data",
}


from reflections.commons.exceptions import BaseServiceException


class VoiceServiceException(BaseServiceException):
    def __init__(self, message: str, details: str | None = None):
        super().__init__(message, details)
