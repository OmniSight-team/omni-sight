from fastapi import APIRouter, Depends

from omnisight_common import NAV_ROUTES

from app.deps import get_current_user
from app.models import User

router = APIRouter(prefix="/nav", tags=["nav"])


@router.get("")
def get_nav(current_user: User = Depends(get_current_user)) -> list[dict[str, str]]:
    return [
        {"path": route.path, "label": route.label}
        for route in NAV_ROUTES
        if current_user.role in route.roles
    ]
