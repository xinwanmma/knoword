"""认证相关路由 — 注册、登录。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import UserRegister, UserLogin, UserOut, Token
from app.core.security import (
    hash_password, verify_password, create_access_token, get_current_user,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    """用户注册。"""
    # 检查用户名是否已存在
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 检查邮箱是否已存在
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="邮箱已被注册")

    # 创建用户
    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # 生成 token
    token = create_access_token(user.id, user.is_admin)
    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=Token)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录。"""
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user.id, user.is_admin)
    return Token(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
async def get_me(current_user: User = Depends(get_current_user)):
    """获取当前用户信息。"""
    return UserOut.model_validate(current_user)


# ==================== 管理员用户管理 ====================

from app.core.security import require_admin
from sqlalchemy import func


@router.get("/admin/users", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员：获取所有用户列表。"""
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [UserOut.model_validate(u) for u in users]


@router.put("/admin/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """管理员：切换用户的管理员状态。"""
    import uuid as uuid_mod
    try:
        target_id = uuid_mod.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的用户 ID")

    # 不能修改自己的管理员状态
    if target_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的管理员状态")

    result = await db.execute(select(User).where(User.id == target_id))
    target_user = result.scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    target_user.is_admin = not target_user.is_admin
    await db.commit()
    await db.refresh(target_user)

    status_text = "管理员" if target_user.is_admin else "普通用户"
    return {"message": f"已将 {target_user.username} 设为{status_text}", "is_admin": target_user.is_admin}
