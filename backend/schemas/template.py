from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class TemplateCreate(BaseModel):
    name: str
    bot_id: int
    is_private: bool = True


class TemplateOut(BaseModel):
    id: int
    user_id: int
    bot_id: int
    name: str
    is_private: bool
    created_at: datetime

    model_config = {"from_attributes": True}
