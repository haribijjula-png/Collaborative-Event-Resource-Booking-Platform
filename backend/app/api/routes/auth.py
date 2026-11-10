from fastapi import APIRouter

from app.api.deps import DB, CurrentUser, ok
from app.schemas.schemas import (AuthOut, ChangePasswordIn, Envelope, LoginIn, Message, RefreshIn, RegisterIn, TokenOut, UserOut)
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=Envelope[UserOut], status_code=201)
def register(body: RegisterIn, db: DB):
    return ok(AuthService(db).register(body.email, body.username, body.full_name, body.password))


@router.post("/login", response_model=Envelope[AuthOut])
def login(body: LoginIn, db: DB):
    return ok(AuthService(db).login(body.email, body.password))


@router.post("/refresh", response_model=Envelope[TokenOut])
def refresh(body: RefreshIn, db: DB):
    return ok(AuthService(db).refresh(body.refresh_token))


@router.post("/logout", response_model=Envelope[Message])
def logout(body: RefreshIn, db: DB):
    AuthService(db).logout(body.refresh_token)
    return ok({"message": "Logged out."})


@router.get("/me", response_model=Envelope[UserOut])
def me(user: CurrentUser):
    return ok(user)


@router.post("/change-password", response_model=Envelope[Message])
def change_password(body: ChangePasswordIn, db: DB, user: CurrentUser):
    AuthService(db).change_password(user, body.old_password, body.new_password)
    return ok({"message": "Password changed. Please log in again."})
