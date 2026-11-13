import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session
from .models import Device, User

_bearer = HTTPBearer(auto_error=False)


# --- Mật khẩu người dùng (bcrypt) ---
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


# --- API key thiết bị: key ngẫu nhiên dài nên sha256 là đủ ---
def new_device_key() -> str:
    return secrets.token_urlsafe(32)


def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


# --- JWT ---
def create_token(user: User) -> tuple[str, int]:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.jwt_expire_hours)
    token = jwt.encode({"sub": user.email, "role": user.role, "exp": exp}, s.jwt_secret, algorithm="HS256")
    return token, int(exp.timestamp() * 1000)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token không hợp lệ hoặc đã hết hạn") from e


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: Session = Depends(get_session),
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thiếu JWT", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(cred.credentials)
    user = session.exec(select(User).where(User.email == claims.get("sub"))).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tài khoản không tồn tại")
    return user


def current_device(
    x_device_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Device:
    if not x_device_key:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Thiếu X-Device-Key")
    device = session.exec(select(Device).where(Device.key_hash == hash_device_key(x_device_key))).first()
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API key không hợp lệ")
    return device


def ws_user(token: str | None = Query(default=None)) -> dict | None:
    if not token:
        return None
    try:
        return decode_token(token)
    except HTTPException:
        return None
