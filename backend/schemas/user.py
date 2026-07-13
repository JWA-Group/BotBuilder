from pydantic import BaseModel

class UserCreate(BaseModel):
    email: str  # email для регистрации
    password: str

class UserLogin(BaseModel):
    login: str  # email или логин
    password: str

class UserOut(BaseModel):
    id: int
    login: str
    email: str | None = None
    email_verified: bool = False

    model_config = {"from_attributes": True}


class RegisterOut(UserOut):
    """Ответ регистрации: при сбое SMTP возвращается ссылка для подтверждения."""
    verify_link: str | None = None
