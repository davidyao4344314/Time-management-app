"""HTTP input contracts and safe conversation errors."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationError(ValueError):
    pass


class ConversationNotFound(ConversationError):
    pass


class ConversationConflict(ConversationError):
    pass


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = Field(default=None, max_length=100)


class SendMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    message: str = Field(min_length=1, max_length=12000)

    @field_validator('request_id')
    @classmethod
    def valid_request(cls, value):
        UUID(value)
        return value

    @field_validator('message')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Enter a message.')
        return value.strip()


class ConversationSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    memory_sharing_enabled: bool
