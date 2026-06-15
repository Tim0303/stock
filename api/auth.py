"""auth.py — 自建登入/註冊 + 試用/訂閱閘門（argon2 + JWT HttpOnly cookie）。

設計：
- 密碼 argon2-cffi 雜湊；access JWT(~15m)+refresh JWT(~7d) 皆放 HttpOnly cookie（無狀態，不建 session 表）。
- Email 驗證、密碼重設（token 只存 SHA-256，原始在信中）。
- CSRF double-submit：登入時下發可讀 csrf_token cookie，前端不安全方法帶 X-CSRF-Token。
- 閘門 gate_request(request)：供 app.py middleware 對所有 /api 資料端點上鎖（公開：health/auth/docs）。
- rate-limit：slowapi，key=X-Real-IP（nginx 設）。
所有帳號/訂閱讀寫走 stock_auth 連線（db_auth），與股票唯讀連線分離。
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

import db_auth
from email_sender import send_email

# ── 設定 ──────────────────────────────────────────────────────────────────────
JWT_SECRET = os.environ.get("JWT_SECRET", "")
JWT_ALG = "HS256"
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "14"))
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:7004").rstrip("/")
VERIFY_TTL = timedelta(days=2)
RESET_TTL = timedelta(hours=1)

ph = PasswordHasher()


def _rate_key(request: Request) -> str:
    return request.headers.get("X-Real-IP") or get_remote_address(request)


limiter = Limiter(key_func=_rate_key)
router = APIRouter(prefix="/api/auth", tags=["auth"])

# 不需上閘門的 /api 路徑（middleware 用）
PUBLIC_PREFIXES = ("/api/health", "/api/auth/", "/api/docs", "/api/redoc", "/api/openapi.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ── JWT / cookie ──────────────────────────────────────────────────────────────
def _issue(user_id: str, email: str, kind: str, ttl: timedelta) -> str:
    now = _now()
    return jwt.encode(
        {"sub": user_id, "email": email, "type": kind,
         "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp()),
         "jti": secrets.token_hex(8)},
        JWT_SECRET, algorithm=JWT_ALG,
    )


def _decode(token: str, kind: str) -> dict | None:
    try:
        claims = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None
    return claims if claims.get("type") == kind else None


def _set_auth_cookies(resp: Response, user_id: str, email: str) -> None:
    common = dict(httponly=True, secure=COOKIE_SECURE, samesite="lax", path="/")
    resp.set_cookie("access_token", _issue(user_id, email, "access", ACCESS_TTL),
                    max_age=int(ACCESS_TTL.total_seconds()), **common)
    resp.set_cookie("refresh_token", _issue(user_id, email, "refresh", REFRESH_TTL),
                    max_age=int(REFRESH_TTL.total_seconds()), **common)
    # CSRF：可讀（非 httponly），double-submit 用
    resp.set_cookie("csrf_token", secrets.token_urlsafe(24),
                    max_age=int(REFRESH_TTL.total_seconds()),
                    httponly=False, secure=COOKIE_SECURE, samesite="lax", path="/")


def _clear_auth_cookies(resp: Response) -> None:
    for name in ("access_token", "refresh_token", "csrf_token"):
        resp.delete_cookie(name, path="/")


# ── 使用者 / 訂閱 ─────────────────────────────────────────────────────────────
def _subscription_view(user_id: str) -> dict | None:
    rows = db_auth.auth_query(
        """SELECT status, plan, trial_end, current_period_end
           FROM subscriptions WHERE user_id=%s
           ORDER BY (status IN ('trialing','active','past_due')) DESC, updated_at DESC LIMIT 1""",
        (user_id,))
    return rows[0] if rows else None


def _access_state(user_id: str) -> tuple[bool, str | None, dict | None]:
    """回 (allow, reason, subscription)。reason: None / 'unverified' / 'inactive'。lazy 試用到期轉 expired。"""
    urows = db_auth.auth_query("SELECT email_verified, disabled FROM app_users WHERE id=%s", (user_id,))
    if not urows or urows[0]["disabled"]:
        return False, "disabled", None
    sub = _subscription_view(user_id)
    if not urows[0]["email_verified"]:
        return False, "unverified", sub
    if not sub:
        return False, "inactive", None
    now = _now()
    st = sub["status"]
    if st == "trialing":
        if sub["trial_end"] and sub["trial_end"] > now:
            return True, None, sub
        # 試用到期 → lazy 標 expired
        db_auth.auth_execute(
            "UPDATE subscriptions SET status='expired', updated_at=now() WHERE user_id=%s AND status='trialing'",
            (user_id,))
        sub = {**sub, "status": "expired"}
        return False, "inactive", sub
    if st == "active" and (sub["current_period_end"] is None or sub["current_period_end"] > now):
        return True, None, sub
    return False, "inactive", sub


# ── middleware 閘門 ───────────────────────────────────────────────────────────
def _deny(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"error": code, "detail": detail}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def gate_request(request: Request) -> JSONResponse | None:
    """app.py middleware 呼叫：None=放行；否則回 401/402/403 JSONResponse。"""
    path = request.url.path
    if any(path == p or path.startswith(p) for p in PUBLIC_PREFIXES):
        return None
    if not path.startswith("/api/"):
        return None
    if not db_auth.auth_enabled() or not JWT_SECRET:
        return _deny(503, "auth_unconfigured", "認證未設定")
    claims = _decode(request.cookies.get("access_token", ""), "access")
    if not claims:
        return _deny(401, "unauthenticated", "請先登入")
    # CSRF：不安全方法須 double-submit 相符
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        hdr = request.headers.get("X-CSRF-Token", "")
        cookie = request.cookies.get("csrf_token", "")
        if not hdr or hdr != cookie:
            return _deny(403, "csrf", "CSRF 驗證失敗")
    allow, reason, _ = _access_state(claims["sub"])
    if allow:
        return None
    if reason == "unverified":
        return _deny(403, "email_unverified", "請先完成 Email 驗證")
    return _deny(402, "subscription_inactive", "試用已結束或訂閱未生效，請前往帳戶頁")


# ── 請求模型 ──────────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenIn(BaseModel):
    token: str


class EmailIn(BaseModel):
    email: str


class ResetIn(BaseModel):
    token: str
    password: str


def _norm_email(raw: str) -> str | None:
    try:
        return validate_email(raw, check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def _valid_password(pw: str) -> bool:
    return isinstance(pw, str) and 8 <= len(pw) <= 200


# ── 端點 ──────────────────────────────────────────────────────────────────────
@router.post("/register")
@limiter.limit("5/minute;30/hour")
def register(request: Request, body: RegisterIn):
    """建帳號＋14天試用＋寄驗證信。永遠回 200 防帳號列舉。"""
    email = _norm_email(body.email)
    generic = {"ok": True, "message": "若 Email 有效，將寄出驗證信"}
    if not email or not _valid_password(body.password):
        return JSONResponse(generic, status_code=200, headers={"Cache-Control": "no-store"})
    exists = db_auth.auth_query("SELECT id FROM app_users WHERE lower(email)=%s", (email,))
    if exists:
        send_email(email, "您已有帳號",
                   f"您的 Email 已註冊過。若忘記密碼，請至 {APP_BASE_URL}/forgot 重設。")
        return JSONResponse(generic, status_code=200, headers={"Cache-Control": "no-store"})
    pw_hash = ph.hash(body.password)
    rows = db_auth.auth_execute(
        "INSERT INTO app_users (email, password_hash) VALUES (%s,%s) RETURNING id", (email, pw_hash))
    uid = rows[0]["id"]
    db_auth.auth_execute(
        "INSERT INTO subscriptions (user_id, status, plan, trial_end) "
        "VALUES (%s,'trialing','trial', now() + (%s||' days')::interval)", (uid, TRIAL_DAYS))
    raw = secrets.token_urlsafe(32)
    db_auth.auth_execute(
        "INSERT INTO email_verification_tokens (token_hash, user_id, expires_at) VALUES (%s,%s,%s)",
        (_sha256(raw), uid, _now() + VERIFY_TTL))
    send_email(email, "請驗證您的 Email",
               f"歡迎！請點此完成驗證並啟用 {TRIAL_DAYS} 天免費試用：\n{APP_BASE_URL}/verify-email?token={raw}")
    return JSONResponse(generic, status_code=200, headers={"Cache-Control": "no-store"})


@router.post("/login")
@limiter.limit("10/minute;60/hour")
def login(request: Request, body: LoginIn, response: Response):
    email = _norm_email(body.email)
    bad = JSONResponse({"error": "invalid_credentials", "detail": "Email 或密碼錯誤"},
                       status_code=401, headers={"Cache-Control": "no-store"})
    if not email:
        ph.hash("dummy")  # 等化時間
        return bad
    rows = db_auth.auth_query(
        "SELECT id, email, password_hash, disabled FROM app_users WHERE lower(email)=%s", (email,))
    if not rows:
        ph.hash("dummy")
        return bad
    u = rows[0]
    try:
        ph.verify(u["password_hash"], body.password)
    except VerifyMismatchError:
        return bad
    if u["disabled"]:
        return bad
    db_auth.auth_execute("UPDATE app_users SET last_login_at=now() WHERE id=%s", (u["id"],))
    _set_auth_cookies(response, str(u["id"]), u["email"])
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    _clear_auth_cookies(response)
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/refresh")
def refresh(request: Request, response: Response):
    claims = _decode(request.cookies.get("refresh_token", ""), "refresh")
    if not claims:
        return JSONResponse({"error": "unauthenticated"}, status_code=401,
                            headers={"Cache-Control": "no-store"})
    _set_auth_cookies(response, claims["sub"], claims["email"])
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.post("/verify-email")
@limiter.limit("10/minute")
def verify_email(request: Request, body: TokenIn):
    rows = db_auth.auth_execute(
        """UPDATE email_verification_tokens SET used_at=now()
           WHERE token_hash=%s AND used_at IS NULL AND expires_at>now() RETURNING user_id""",
        (_sha256(body.token),))
    if not rows:
        return JSONResponse({"error": "invalid_token", "detail": "連結無效或已過期"},
                            status_code=400, headers={"Cache-Control": "no-store"})
    db_auth.auth_execute("UPDATE app_users SET email_verified=true, updated_at=now() WHERE id=%s",
                         (rows[0]["user_id"],))
    return {"ok": True}


@router.post("/request-reset")
@limiter.limit("5/minute;20/hour")
def request_reset(request: Request, body: EmailIn):
    """永遠回 200 防列舉。"""
    email = _norm_email(body.email)
    generic = {"ok": True, "message": "若帳號存在，將寄出重設信"}
    if email:
        rows = db_auth.auth_query("SELECT id FROM app_users WHERE lower(email)=%s", (email,))
        if rows:
            raw = secrets.token_urlsafe(32)
            db_auth.auth_execute(
                "INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES (%s,%s,%s)",
                (_sha256(raw), rows[0]["id"], _now() + RESET_TTL))
            send_email(email, "重設密碼",
                       f"請點此重設密碼（1 小時內有效）：\n{APP_BASE_URL}/reset-password?token={raw}")
    return JSONResponse(generic, status_code=200, headers={"Cache-Control": "no-store"})


@router.post("/reset")
@limiter.limit("5/minute;20/hour")
def reset(request: Request, body: ResetIn, response: Response):
    if not _valid_password(body.password):
        return JSONResponse({"error": "weak_password", "detail": "密碼至少 8 碼"},
                            status_code=400, headers={"Cache-Control": "no-store"})
    rows = db_auth.auth_execute(
        """UPDATE password_reset_tokens SET used_at=now()
           WHERE token_hash=%s AND used_at IS NULL AND expires_at>now() RETURNING user_id""",
        (_sha256(body.token),))
    if not rows:
        return JSONResponse({"error": "invalid_token", "detail": "連結無效或已過期"},
                            status_code=400, headers={"Cache-Control": "no-store"})
    uid = rows[0]["user_id"]
    db_auth.auth_execute("UPDATE app_users SET password_hash=%s, updated_at=now() WHERE id=%s",
                         (ph.hash(body.password), uid))
    # 失效該用戶其它未用 reset token
    db_auth.auth_execute(
        "UPDATE password_reset_tokens SET used_at=now() WHERE user_id=%s AND used_at IS NULL", (uid,))
    _clear_auth_cookies(response)  # 強制重新登入
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    claims = _decode(request.cookies.get("access_token", ""), "access")
    if not claims:
        return JSONResponse({"authenticated": False}, status_code=401,
                            headers={"Cache-Control": "no-store"})
    allow, reason, sub = _access_state(claims["sub"])
    payload = {
        "authenticated": True,
        "email": claims.get("email"),
        "email_verified": reason != "unverified",
        "access": allow,
        "subscription": (
            {"status": sub["status"], "plan": sub["plan"],
             "trial_end": sub["trial_end"].isoformat() if sub.get("trial_end") else None,
             "current_period_end": sub["current_period_end"].isoformat() if sub.get("current_period_end") else None}
            if sub else None),
    }
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
