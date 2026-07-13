from pydantic import BaseModel

class CommandBase(BaseModel):
    command: str
    description: str
    reply: str

class CommandCreate(CommandBase):
    pass

class CommandInDB(CommandBase):
    id: int
    bot_id: int

    model_config = {"from_attributes": True}
