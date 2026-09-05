import jwt
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from omnisight_common import Role

from app.db import get_db
from app.models import User
from app.security import create_access_token, decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)

INVALID_TOKEN_MESSAGE = "invalid or expired token"
INSUFFICIENT_ROLE_MESSAGE = "insufficient role"

# Header carrying a renewed token on every authenticated request, so a token's
# effective lifetime slides forward with activity instead of expiring on a
# fixed clock from login. An idle token (no requests for its lifetime) is
# never renewed and simply expires.
RENEWED_TOKEN_HEADER = "X-Access-Token"


def get_current_user(
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_TOKEN_MESSAGE)

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_TOKEN_MESSAGE)

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_TOKEN_MESSAGE)

    response.headers[RENEWED_TOKEN_HEADER] = create_access_token(user.id, user.role.value)
    return user


def require_role(*allowed_roles: Role):
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=INSUFFICIENT_ROLE_MESSAGE)
        return current_user

    return dependency
