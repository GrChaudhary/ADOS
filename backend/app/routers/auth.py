"""
Login + session identity + user management — backend/app/rbac.py,
backend/app/user_store.py. Replaces the shared SERVICE_AUTH_TOKEN as the
real per-user identity source for every other router.
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .. import user_store
from ..rbac import Role, User, create_access_token, get_current_user, require_role

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user: User


class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: str
    role: Role
    approval_limit_usd: float = 0.0


class ResetPasswordRequest(BaseModel):
    new_password: str


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user = user_store.verify_login(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    return LoginResponse(token=create_access_token(user), user=user)


@router.get("/me", response_model=User)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/users", response_model=List[User], dependencies=[Depends(require_role(Role.ADMIN))])
async def list_users():
    return user_store.list_users()


@router.post("/users", response_model=User, dependencies=[Depends(require_role(Role.ADMIN))])
async def create_user(body: CreateUserRequest):
    if user_store.username_exists(body.username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Username '{body.username}' already exists")
    return user_store.create_user(
        username=body.username,
        password=body.password,
        display_name=body.display_name,
        role=body.role,
        approval_limit_usd=body.approval_limit_usd,
    )


@router.post("/users/{username}/reset-password", dependencies=[Depends(require_role(Role.ADMIN))])
async def reset_password(username: str, body: ResetPasswordRequest):
    if not user_store.reset_password(username, body.new_password):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Username '{username}' not found")
    return {"username": username, "status": "password reset"}
