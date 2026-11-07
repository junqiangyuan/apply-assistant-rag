from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from app.core.config import settings
from app.core.exceptions import UnauthorizedError


def hash_password(plain: str) -> str:
    ## 增加重复密码的破解难度
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str) -> str:
    if not settings.jwt_secret:
        return UnauthorizedError("服务端未配置 JWT secret 无法签发 token")
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    if not settings.jwt_secret:
        return UnauthorizedError("服务端未配置 JWT secret")
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError as exc:
        raise UnauthorizedError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise UnauthorizedError("无效的访问凭证") from exc
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise UnauthorizedError("无效的访问凭证")
    return subject
