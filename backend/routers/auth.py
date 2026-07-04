import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core import models
from backend.core.database import get_db
from backend.core.security import get_password_hash, verify_password
from backend.services.audit_service import log_audit

# ==========================================
# --- JWT 鉴权基础配置与依赖 ---
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-keep-it-safe")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15  # Access Token 有效期改短为 15 分钟
REFRESH_TOKEN_EXPIRE_DAYS = 7  # Refresh Token 有效期设为 7 天

# tokenUrl 指明了 Swagger UI 等工具要去哪个接口获取 Token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def _create_jwt_token(data: dict, expires_delta: timedelta, token_type: Optional[str] = None):  # noqa: E501
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + expires_delta})
    if token_type:
        to_encode["type"] = token_type
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    return _create_jwt_token(data, expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))  # noqa: E501


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None):
    return _create_jwt_token(data, expires_delta or timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS), "refresh")  # noqa: E501


# 核心鉴权依赖：拦截并解析 Token，返回当前登录的用户对象
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):  # noqa: E501
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="无效的鉴权凭证或 Token 已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: Optional[str] = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user


router = APIRouter(prefix="/auth", tags=["Auth"])


@router.get("/me")
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
    }  # noqa: E501


# ==========================================
# --- 标准账号密码登录与改密 API ---
# ==========================================


@router.post("/login")
def login_for_access_token(
    response: Response,
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()  # noqa: E501
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwt_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )  # noqa: E501
    refresh_token = create_refresh_token(
        data={"sub": user.username},
        expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    )  # noqa: E501

    is_production = os.getenv("QUANT_ENV") == "production"
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=is_production,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )  # noqa: E501

    # 记录审计日志
    log_audit(
        db=db,
        action="login",
        detail={"username": user.username, "method": "password"},
        request=request,
        user_id=user.id,
    )

    return {
        "status": "success",
        "access_token": jwt_token,
        "token_type": "bearer",
        "user": {"username": user.username, "email": getattr(user, "email", None)},
    }  # noqa: E501


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/change-password")
def change_password(
    password_request: ChangePasswordRequest,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(password_request.old_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    current_user.hashed_password = get_password_hash(password_request.new_password)
    db.commit()

    # 记录审计日志
    log_audit(
        db=db,
        action="change_password",
        detail={"username": current_user.username},
        request=request,
        user_id=current_user.id,
    )

    return {"status": "success", "message": "密码修改成功"}


# ==========================================
# --- Google OAuth2 前端令牌验证 API ---
# ==========================================


class GoogleTokenRequest(BaseModel):
    credential: str


@router.post("/google/verify")
def verify_google_token(
    request: Request,
    token_request: GoogleTokenRequest,
    response: Response = None,
    db: Session = Depends(get_db),
):
    try:
        client_id = os.getenv("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID")

        # 1. 验证前端传来的 Google ID Token
        idinfo = id_token.verify_oauth2_token(
            # 💡 依赖 main.py 中配置的全局 socket.setdefaulttimeout(15.0) 防死锁挂起
            token_request.credential,
            google_requests.Request(),
            client_id,
        )

        # 2. 验证通过，提取用户信息
        email = idinfo.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Google Auth Failed: No email provided")  # noqa: E501

        # 兼容性处理：防止 models.User 没有 email 字段导致 500 崩溃
        has_email_column = hasattr(models.User, "email")

        # 3. 在我们自己的数据库里查找用户，如果没有则自动帮他注册
        if has_email_column:
            user = db.query(models.User).filter(models.User.email == email).first()
        else:
            user = db.query(models.User).filter(models.User.username == email.split("@")[0]).first()  # noqa: E501

        if not user:
            base_username = email.split("@")[0]
            existing_user = db.query(models.User).filter(models.User.username == base_username).first()  # noqa: E501
            username = base_username if not existing_user else f"{base_username}_{str(hash(email))[-4:]}"  # noqa: E501

            user_kwargs = {
                "username": username,
                # bcrypt 限制输入最大 72 字节，改用安全的随机短字符串作为占位密码
                "hashed_password": get_password_hash(secrets.token_urlsafe(32)),
            }
            if has_email_column:
                user_kwargs["email"] = email

            user = models.User(**user_kwargs)
            db.add(user)
            db.commit()
            db.refresh(user)

        # 4. 签发系统内部使用的短效 Access Token 和 长效 Refresh Token
        jwt_token = create_access_token(
            data={"sub": user.username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        )

        refresh_token = create_refresh_token(
            data={"sub": user.username},
            expires_delta=timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        )

        # 5. 设置 HttpOnly Cookie 并直接返回 JSON
        is_production = os.getenv("ENV") == "production"
        response.set_cookie(
            key="refresh_token",
            value=refresh_token,
            httponly=True,
            secure=is_production,  # 生产环境建议开启 HTTPS
            samesite="lax",  # 允许带跳转的请求携带 Cookie
            max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
            path="/",
        )

        # 记录审计日志
        log_audit(
            db=db,
            action="login",
            detail={"username": user.username, "method": "google", "email": email},
            request=request,
            user_id=user.id,
        )

        return {
            "status": "success",
            "access_token": jwt_token,
            "user": {"username": user.username, "email": email},
        }

    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid Google token")

    except Exception as e:
        import traceback

        traceback.print_exc()  # 打印详细崩溃堆栈到后端终端
        # 把真实错误信息抛出到浏览器，不再展示全白 500 页面
        raise HTTPException(status_code=500, detail=f"Google Callback Error: {str(e)}")


# ==========================================
# --- Token 刷新与注销 API ---
# ==========================================
@router.post("/refresh")
async def refresh_access_token(refresh_token: Optional[str] = Cookie(None), db: Session = Depends(get_db)):  # noqa: E501
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh Token missing in cookies")

    try:
        payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type")

        username: Optional[str] = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired Refresh Token")

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": new_access_token}


@router.post("/logout")
async def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    # 尝试获取当前用户（可选）
    user_id = None
    try:
        # 从 cookie 中获取 refresh token
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token:
            payload = jwt.decode(refresh_token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username:
                user = db.query(models.User).filter(models.User.username == username).first()  # noqa: E501
                if user:
                    user_id = user.id
    except:  # noqa: E722
        pass  # 忽略解析错误，允许用户未认证时登出

    # 记录审计日志（如果用户已认证）
    if user_id:
        log_audit(
            db=db,
            action="logout",
            detail={"username": username} if username else {},
            request=request,
            user_id=user_id,
        )

    # 清理客户端存留的 Refresh Token Cookie
    response.delete_cookie(key="refresh_token", path="/")
    return {"message": "Logged out successfully"}
