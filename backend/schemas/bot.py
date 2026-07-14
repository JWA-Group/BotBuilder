from pydantic import BaseModel, field_validator
from datetime import datetime

PlatformType = str


class BotCreate(BaseModel):
    name: str
    api_token: str
    user_id: int  # позже заменить на Depends(get_current_user)
    platform: PlatformType = "telegram"

    @field_validator("platform", mode="before")
    @classmethod
    def normalize_platform(cls, v):
        return "telegram"


class BotOut(BaseModel):
    id: int
    name: str
    api_token: str
    platform: str = "telegram"
    created_at: datetime

    model_config = {"from_attributes": True}
