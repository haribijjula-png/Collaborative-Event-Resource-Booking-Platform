from datetime import datetime
from typing import Annotated

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import E
from app.db.session import get_db
from app.models import models as m
from app.services.auth import AuthService

bearer = HTTPBearer(auto_error=False)
DB = Annotated[Session, Depends(get_db)]


def get_current_user(db: DB, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> m.User:
    if not creds:
        raise E(401, "UNAUTHORIZED", "Authentication required.")
    return AuthService(db).authenticate_access(creds.credentials)


CurrentUser = Annotated[m.User, Depends(get_current_user)]


def require_super_admin(user: CurrentUser) -> m.User:
    if not user.is_super_admin:
        raise E(403, "FORBIDDEN", "Super admin access required.")
    return user


class Pagination:
    def __init__(self, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
        self.page, self.page_size = page, page_size


Pg = Annotated[Pagination, Depends()]


def ok(data=None):
    return {"success": True, "data": data}
