from fastapi import APIRouter, Depends

from omnisight_common import Role

from app.deps import require_role
from app.models import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/ping")
def admin_ping(current_user: User = Depends(require_role(Role.ADMIN))) -> dict[str, str]:
    return {"status": "ok", "admin": current_user.email}
