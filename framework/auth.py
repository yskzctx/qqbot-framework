"""面板认证：密码哈希存储 + 内存会话 token。

- 首次使用：面板引导设置密码（POST /api/setup），哈希后写入 config.json
- 之后每次打开面板都要重新输密码（token 只存于页面内存，不落浏览器存储）
"""
import hashlib
import secrets


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, _ = stored.split("$")
    except (ValueError, AttributeError):
        return False
    return secrets.compare_digest(hash_password(password, salt), stored)


def new_session_token() -> str:
    return secrets.token_hex(16)
