from sqlalchemy import Column, Integer, String, DateTime, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from ..db.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    login = Column(String, unique=True, nullable=False)  # email или логин
    password_hash = Column(String, nullable=True)  # null для Google-пользователей
    email = Column(String, unique=True, nullable=True, index=True)
    email_verified = Column(Boolean, default=False)
    verification_token = Column(String, nullable=True)
    google_id = Column(String, unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    bots = relationship("Bot", back_populates="user")
