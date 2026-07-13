from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.database import Base

class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    api_token = Column(String, nullable=False)
    platform = Column(String, nullable=False, default="telegram")  # telegram | vk
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="bots")
    commands = relationship("Command", back_populates="bot", cascade="all, delete-orphan")
