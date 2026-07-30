from pydantic import BaseModel, field_validator
from datetime import datetime

PlatformType = str


class BotCreate(BaseModel):
    name: str = ""
    api_token: str
    user_id: int  # позже заменить на Depends(get_current_user)
    platform: PlatformType = "telegram"
    kind: str = "scenario"

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, v):
        return "telegram"

    @field_validator("kind", mode="before")
    @classmethod
    def normalize_kind(cls, v):
        value = str(v or "scenario").strip().lower()
        return "moderator" if value in ("moderator", "moderation", "channel") else "scenario"

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        return str(v or "").strip()


class BotOut(BaseModel):
    id: int
    name: str
    api_token: str
    platform: str = "telegram"
    kind: str = "scenario"
    created_at: datetime

    model_config = {"from_attributes": True}
