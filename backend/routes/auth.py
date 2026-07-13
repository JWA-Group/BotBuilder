import re
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from ..db.database import get_db
from ..models.user import User
from ..schemas.user import UserCreate, UserLogin, UserOut, RegisterOut
from ..utils.crypto import hash_password, verify_password
from ..core.security import create_access_token, verify_email_token

router = APIRouter()

EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _valid_email(s: str) -> bool:
    return bool(s and EMAIL_RE.match(s.strip()))


@router.post("/register", response_model=RegisterOut)
async def register(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    email = user.email.strip().lower()
    if not _valid_email(email):
        raise HTTPException(status_code=400, detail="Некорректный email")
    if len(user.password) < 6:
        raise HTTPException(status_code=400, detail="Пароль не менее 6 символов")

    result = await db.execute(select(User).where(
        (User.email == email) | (User.login == email)
    ))
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    new_user = User(
        login=email,
        email=email,
        password_hash=hash_password(user.password),
        email_verified=True,
        verification_token=None,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return RegisterOut.model_validate(new_user)


@router.get("/verify-email")
async def verify_email_endpoint(token: str, db: AsyncSession = Depends(get_db)):
    email = verify_email_token(token)
    if not email:
        return RedirectResponse(
            url="/auth/verify-email.html?error=invalid&msg=Ссылка истекла или неверна",
            status_code=302,
        )
    result = await db.execute(
        select(User).where(User.email == email, User.verification_token == token)
    )
    user = result.scalars().first()
    if not user:
        return RedirectResponse(
            url="/auth/verify-email.html?error=not_found",
            status_code=302,
        )
    user.email_verified = True
    user.verification_token = None
    await db.commit()
    return RedirectResponse(
        url="/auth/verify-email.html?success=1",
        status_code=302,
    )


@router.post("/login")
async def login(user: UserLogin, db: AsyncSession = Depends(get_db)):
    login_val = user.login.strip()
    result = await db.execute(
        select(User).where(
            (User.login == login_val) | (User.email == login_val)
        )
    )
    db_user = result.scalars().first()
    if not db_user or not db_user.password_hash:
        raise HTTPException(status_code=401, detail="Неверные данные")
    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Неверные данные")
    access_token = create_access_token(data={"sub": str(db_user.id)})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "login": db_user.login,
            "email": db_user.email,
            "email_verified": db_user.email_verified or False,
        },
    }


@router.get("/google")
async def google_login(request: Request):
    """Редирект на Google OAuth. Вызывается из фронта."""
    from backend.routes.oauth import oauth, GOOGLE_CLIENT_ID
    if not GOOGLE_CLIENT_ID:
        from urllib.parse import quote
        return RedirectResponse(
            url="/auth/login.html?error=oauth&msg=" + quote("Google OAuth не настроен"),
            status_code=302,
        )
    from backend.core.config import get_app_base_url
    base = get_app_base_url().rstrip("/")
    redirect_uri = f"{base}/api/auth/google/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """Callback после авторизации в Google."""
    from urllib.parse import quote
    from authlib.integrations.starlette_client import OAuthError
    from backend.routes.oauth import oauth, GOOGLE_CLIENT_ID

    if not GOOGLE_CLIENT_ID or not hasattr(oauth, "google"):
        return RedirectResponse(url="/auth/login.html?error=oauth", status_code=302)

    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        return RedirectResponse(
            url=f"/auth/login.html?error=oauth&msg={quote(str(e.error or 'Unknown'))}",
            status_code=302,
        )
    userinfo = token.get("userinfo")
    if not userinfo:
        return RedirectResponse(url="/auth/login.html?error=no_userinfo", status_code=302)

    email = (userinfo.get("email") or "").strip().lower()
    google_id = userinfo.get("sub")
    name = userinfo.get("name") or userinfo.get("given_name") or email.split("@")[0]

    if not email:
        return RedirectResponse(
            url="/auth/login.html?error=no_email&msg=Email не предоставлен",
            status_code=302,
        )

    result = await db.execute(
        select(User).where(User.google_id == google_id)
    )
    user = result.scalars().first()
    if not user:
        result = await db.execute(
            select(User).where((User.email == email) | (User.login == email))
        )
        user = result.scalars().first()
        if user:
            user.google_id = google_id
            user.email_verified = True
            await db.commit()
            await db.refresh(user)
        else:
            user = User(
                login=email,
                email=email,
                google_id=google_id,
                email_verified=True,
                password_hash="",  # Google-пользователи без пароля (NOT NULL в старой схеме)
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

    access_token = create_access_token(data={"sub": str(user.id)})
    redirect_url = "/auth/oauth-callback.html"
    redirect_url += f"?token={access_token}&user_id={user.id}&login={user.login}"
    return RedirectResponse(url=redirect_url, status_code=302)
