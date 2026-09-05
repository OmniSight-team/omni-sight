from pydantic import BaseModel

from omnisight_common import Role


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


class UserResponse(BaseModel):
    id: int
    email: str
    role: Role
