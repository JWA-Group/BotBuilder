from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from ..db.database import Base


class Command(Base):
    __tablename__ = "commands"

    id = Column(Integer, primary_key=True, index=True)
    command = Column(String, nullable=False)
    description = Column(String)
    reply = Column(String)
    bot_id = Column(Integer, ForeignKey("bots.id"))

    bot = relationship("Bot", back_populates="commands")
