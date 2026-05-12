from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    password: str


class UpdateNoteRequest(BaseModel):
    title: str | None = None
    content: str
    tags: list[str] | None = None


class WebSettingsUpdateRequest(BaseModel):
    language: str | None = None
    role: str | None = None


class UserProfileUpdateRequest(BaseModel):
    region: str
    species_focus: str


class OnboardingRequest(BaseModel):
    language: str
    specialization: str
    subjects: list[str]


class SearchResponse(BaseModel):
    id: UUID
    title: str | None
    content: str
    kind: str
    tags: list[str]
    topic_id: UUID | None
    created_at: datetime


class FlashcardReviewRequest(BaseModel):
    action: str
