from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import datetime, timedelta
import bcrypt
import sys
import os
import httpx

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from api.models.user import User, get_db, init_db
from api.models.schemas import UserRegister, UserLogin, WxLogin, ChangePassword, UserProfileUpdate, UserOut, Token

router = APIRouter(prefix="/users", tags=["users"])

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("Set SECRET_KEY in the environment or .env before starting FitHer")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天
security = HTTPBearer(auto_error=False)


def decode_user_id(token: str) -> int:
    payload = jwt.decode(
        token, SECRET_KEY, algorithms=[ALGORITHM],
        options={"require_exp": True, "require_sub": True},
    )
    return int(payload["sub"])


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> int:
    """从JWT token中提取用户ID，供其他路由复用"""
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        return decode_user_id(credentials.credentials)
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


@router.post("/register", response_model=Token)
def register(data: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(username=data.username, hashed_password=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_token(user.id), token_type="bearer")


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return Token(access_token=create_token(user.id), token_type="bearer")


def get_user_or_404(user_id: int, db: Session) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


@router.put("/save-profile", response_model=UserOut)
def save_profile(
    data: UserProfileUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = get_user_or_404(user_id, db)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me", response_model=UserOut)
def get_me(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return get_user_or_404(user_id, db)


@router.put("/profile", response_model=UserOut)
def update_profile(
    data: UserProfileUpdate,
    user_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="只能修改自己的档案")
    return save_profile(data, current_user_id, db)


@router.get("/profile/{user_id}", response_model=UserOut)
def get_profile(
    user_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="只能查看自己的档案")
    return get_user_or_404(current_user_id, db)


@router.post("/change-password")
def change_password(
    data: ChangePassword,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    user = get_user_or_404(user_id, db)

    if not user.hashed_password:
        raise HTTPException(status_code=400, detail="该账号通过微信登录，无法修改密码")

    if not verify_password(data.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码错误")

    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少6位")

    user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"message": "密码修改成功"}


init_db()

# 微信小程序登录
WX_APPID = os.getenv("WX_APPID", "")
WX_SECRET = os.getenv("WX_SECRET", "")

@router.post("/wx-login")
async def wx_login(data: WxLogin, db: Session = Depends(get_db)):
    """微信一键登录：用code换openid，自动创建或查找用户"""
    if not WX_APPID or not WX_SECRET:
        raise HTTPException(status_code=500, detail="微信小程序未配置appid/secret")
    
    # 用code向微信服务器换openid和session_key
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": WX_APPID,
                "secret": WX_SECRET,
                "js_code": data.code,
                "grant_type": "authorization_code",
            },
        )
        wx_data = resp.json()
    
    if "errcode" in wx_data:
        raise HTTPException(status_code=400, detail=f"微信登录失败: {wx_data.get('errmsg', '未知错误')}")
    
    openid = wx_data["openid"]
    
    # 查找或创建用户
    user = db.query(User).filter(User.openid == openid).first()
    if not user:
        # 自动创建用户，用户名用openid后8位
        auto_username = f"wx_{openid[:8]}"
        # 确保用户名不重复
        while db.query(User).filter(User.username == auto_username).first():
            auto_username = f"wx_{openid[:8]}_{hash(openid) % 1000}"
        user = User(username=auto_username, openid=openid)
        db.add(user)
        db.commit()
        db.refresh(user)
    
    return {"access_token": create_token(user.id), "username": user.username, "token_type": "bearer"}