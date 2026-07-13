from sqlalchemy import Column, Integer, String, ForeignKey, Boolean, DateTime, Text
from sqlalchemy.orm import relationship
from datetime import datetime

from ..db.database import Base


class Template(Base):
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=False)
    name = Column(String, nullable=False)
    is_private = Column(Boolean, default=True, nullable=False)
    scenario_data = Column(Text, nullable=True)  # JSON сценария (blocks, connections, tags)
    created_at = Column(DateTime, default=datetime.utcnow)
