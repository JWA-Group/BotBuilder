from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Literal

PlatformType = Literal["telegram", "vk"]


class BotCreate(BaseModel):
    name: str
    api_token: str
    user_id: int  # позже заменить на Depends(get_current_user)
    platform: PlatformType = "telegram"

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, v):
        if v is None or v == "":
            return "telegram"
        p = str(v).strip().lower()
        if p not in ("telegram", "vk"):
            raise ValueError("platform must be 'telegram' or 'vk'")
        return p


class BotOut(BaseModel):
    id: int
    name: str
    api_token: str
    platform: str = "telegram"
    created_at: datetime

    model_config = {"from_attributes": True}
