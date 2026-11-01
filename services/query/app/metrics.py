"""`GET /metrics/sm1` (OMNI-713): SM-1 as measured on Colab, read from the result file committed
beside this module. The API measures nothing: `scripts/measure_sm1.py` wrote the file."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user
from app.models import User
from app.schemas import Sm1Out

router = APIRouter(prefix="/metrics", tags=["metrics"])

SM1_RESULT = Path(__file__).with_name("sm1_result.json")
NOT_MEASURED = "SM-1 has not been measured yet"


@router.get("/sm1", response_model=Sm1Out)
def sm1(_user: User = Depends(get_current_user)) -> Sm1Out:
    if not SM1_RESULT.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_MEASURED)
    return Sm1Out(**json.loads(SM1_RESULT.read_text(encoding="utf-8")))
