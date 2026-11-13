from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..db import get_session
from ..models import User
from ..schemas import LoginIn
from ..security import create_token, current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email.strip().lower())).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sai email hoặc mật khẩu")
    token, exp = create_token(user)
    return {"access_token": token, "token_type": "bearer", "expires_at": exp, "user": {"email": user.email, "role": user.role}}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"email": user.email, "role": user.role}
