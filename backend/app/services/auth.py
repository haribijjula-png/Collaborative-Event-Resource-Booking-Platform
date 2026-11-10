from datetime import datetime, timezone

import jwt
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import E, Conflict
from app.core.security import (create_access_token, create_refresh_token, decode_token, hash_password, verify_password)
from app.models import models as m
from app.repositories.repos import RefreshTokenRepo, UserRepo


def _unauth(code, msg):
    return E(401, code, msg)


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepo(db)
        self.tokens = RefreshTokenRepo(db)

    def register(self, email, username, full_name, password) -> m.User:
        if self.users.by_email(email):
            raise Conflict("A user with this email already exists.", code="EMAIL_ALREADY_EXISTS")
        if self.users.by_username(username):
            raise Conflict("This username is taken.", code="USERNAME_ALREADY_EXISTS")
        user = m.User(email=email.lower(), username=username, full_name=full_name, hashed_password=hash_password(password))
        try:
            self.users.add(user)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Email or username already exists.", code="USER_ALREADY_EXISTS")
        return user

    def _issue(self, user: m.User) -> dict:
        access, exp = create_access_token(user.id)
        refresh, jti, rexp = create_refresh_token(user.id)
        self.tokens.add(m.RefreshToken(user_id=user.id, jti=jti, expires_at=rexp))
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_at": exp, "_jti": jti}

    def login(self, email, password) -> dict:
        user = self.users.by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise _unauth("INVALID_CREDENTIALS", "Incorrect email or password.")
        if not user.is_active:
            raise E(403, "USER_INACTIVE", "This account has been deactivated.")
        out = self._issue(user)
        self.db.commit()
        out.pop("_jti")
        out["user"] = user
        return out

    def refresh(self, refresh_token: str) -> dict:
        try:
            payload = decode_token(refresh_token)
        except jwt.ExpiredSignatureError:
            raise _unauth("TOKEN_EXPIRED", "Refresh token has expired.")
        except jwt.InvalidTokenError:
            raise _unauth("INVALID_TOKEN", "Invalid refresh token.")
        if payload.get("type") != "refresh":
            raise _unauth("INVALID_TOKEN", "Invalid token type.")
        row = self.tokens.by_jti(payload["jti"], for_update=True)
        if not row:
            raise _unauth("INVALID_TOKEN", "Unknown refresh token.")
        if row.revoked:
            # Reuse of a rotated token => assume theft, revoke the whole family.
            self.tokens.revoke_all(row.user_id)
            self.db.commit()
            raise _unauth("TOKEN_REUSED", "Refresh token was already used. Please log in again.")
        user = self.users.get(row.user_id)
        if not user or not user.is_active:
            raise E(403, "USER_INACTIVE", "This account has been deactivated.")
        new = self._issue(user)
        row.revoked = True
        row.replaced_by = new.pop("_jti")
        self.db.commit()
        return new

    def logout(self, refresh_token: str) -> None:
        try:
            payload = decode_token(refresh_token)
        except jwt.InvalidTokenError:
            return  # idempotent
        row = self.tokens.by_jti(payload.get("jti", ""))
        if row:
            row.revoked = True
            self.db.commit()

    def authenticate_access(self, token: str) -> m.User:
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            raise _unauth("TOKEN_EXPIRED", "Access token has expired.")
        except jwt.InvalidTokenError:
            raise _unauth("INVALID_TOKEN", "Invalid access token.")
        if payload.get("type") != "access":
            raise _unauth("INVALID_TOKEN", "Invalid token type.")
        user = self.users.get(int(payload["sub"]))
        if not user:
            raise _unauth("INVALID_TOKEN", "User no longer exists.")
        if not user.is_active:
            raise E(403, "USER_INACTIVE", "This account has been deactivated.")
        return user

    def change_password(self, user: m.User, old, new):
        if not verify_password(old, user.hashed_password):
            raise E(400, "INVALID_PASSWORD", "Current password is incorrect.")
        user.hashed_password = hash_password(new)
        self.tokens.revoke_all(user.id)  # force re-login everywhere
        self.db.commit()
