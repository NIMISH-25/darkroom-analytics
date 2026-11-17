import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.settings import get_settings

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
ALGO = "HS256"


def verify_credentials(username: str, password: str) -> bool:
    s = get_settings()
    return hmac.compare_digest(username.encode(), s.DEMO_USERNAME.encode()) and hmac.compare_digest(
        password.encode(), s.DEMO_PASSWORD.encode()
    )


def create_token(username: str) -> tuple[str, datetime]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=s.AUTH_TOKEN_TTL_MINUTES)
    token = jwt.encode({"sub": username, "exp": exp}, s.AUTH_SECRET, algorithm=ALGO)
    return token, exp


def current_user(token: str | None = Depends(oauth2)) -> str:
    unauth = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if not token:
        raise unauth
    try:
        data = jwt.decode(token, get_settings().AUTH_SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise unauth
    return data["sub"]
