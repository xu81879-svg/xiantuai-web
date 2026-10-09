from __future__ import annotations

import os
import io
import logging
import hashlib
import secrets
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

import jwt
from fastapi import Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fastapi import FastAPI
from .database import Base, SessionLocal, engine, ensure_local_storage, get_db
from .emailing import EmailDeliveryError, send_verification_email, smtp_configured
from .models import CreditOrder, CreditPlan, CreditTransaction, EmailVerificationToken, Generation, HelpArticle, PayPalWebhookEvent, Product, Template, User
from .paypal import PayPalError, approval_url, capture_order, checkout_enabled as paypal_checkout_enabled, client_id as paypal_client_id, configured as paypal_configured, create_order as paypal_create_order, mock_mode as paypal_mock_mode, payment_mode as paypal_payment_mode, show_order, verify_webhook_signature
from .qwen import QwenError, allow_mock_fallback, compile_generation_plan, generate_image, is_qwen_configured, persist_remote_image, quality_check_image, recognize_product as qwen_recognize_product
from .rate_limit import enforce_auth_rate_limit, enforce_resource_rate_limit
from .security import PASSWORDS, create_access_token, hash_password, read_user_id, secret_key, verify_password

logger = logging.getLogger("xiantu.pipeline")
DUMMY_PASSWORD_HASH = PASSWORDS.hash("non-user-constant-work-password")

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = APP_DIR.parent
STORAGE_DIR = Path(os.getenv("LOCAL_STORAGE_DIR", str(PROJECT_DIR / "data")))
UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    ensure_local_storage()
    secret_key()
    if os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true":
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_catalog(db)
        seed_credit_plans(db)
        if os.getenv("SEED_DEMO_USER", "true").lower() == "true":
            demo_email = os.getenv("DEMO_USER_EMAIL", "demo@xiantu.ai")
            demo_password = os.getenv("DEMO_USER_PASSWORD", "")
            demo_name = os.getenv("DEMO_USER_NAME", "演示商家")
            if not demo_password:
                raise RuntimeError("DEMO_USER_PASSWORD must be configured when SEED_DEMO_USER=true")
            if not db.scalar(select(User).where(User.email == demo_email)):
                db.add(User(email=demo_email, password_hash=hash_password(demo_password), display_name=demo_name, email_verified=True))
                db.commit()
    yield


app = FastAPI(title="鲜图 AI API", version="1.0.0", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan)
origins = [item.strip() for item in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
security = HTTPBearer(auto_error=False)

ASSET_IMAGES = [
    "https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=900&q=88",
    "https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=550&q=88",
    "https://images.unsplash.com/photo-1471943311424-646960669fbc?auto=format&fit=crop&w=550&q=88",
    "https://images.unsplash.com/photo-1577003833619-76bbd7f82948?auto=format&fit=crop&w=550&q=88",
    "https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=550&q=88",
]

class RegisterPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(default="商家用户", min_length=1, max_length=80)

class LoginPayload(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

class EmailPayload(BaseModel):
    email: EmailStr

class EmailVerificationPayload(BaseModel):
    token: str = Field(min_length=20, max_length=256)

class ProductPayload(BaseModel):
    name: str = Field(default="崂山大樱桃", max_length=120)
    origin: str = Field(default="山东·青岛崂山", max_length=160)
    spec: str = Field(default="500g", max_length=80)
    tags: list[str] = Field(default_factory=lambda: ["果大", "脆甜", "新鲜", "当季"])
    image_url: str | None = None

class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    origin: str | None = Field(default=None, max_length=160)
    spec: str | None = Field(default=None, max_length=80)
    tags: list[str] | None = None
    image_url: str | None = None

class GenerationPayload(BaseModel):
    product_id: str | None = None
    product: ProductPayload | None = None
    usage: str = Field(default="hero", max_length=40)
    style: str = Field(default="natural", max_length=40)
    tone: str = Field(default="fresh", max_length=40)
    composition: str = Field(default="center", max_length=40)
    background: str = Field(default="clean", max_length=40)
    platform: str = Field(default="taobao", max_length=40)

class CreditOrderPayload(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)

class CreditCapturePayload(BaseModel):
    paypal_order_id: str = Field(min_length=1, max_length=100)


def serialize_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "email_verified": user.email_verified, "display_name": user.display_name, "locale": user.locale, "timezone": user.timezone, "credit_balance": user.credit_balance}


def serialize_plan(plan: CreditPlan) -> dict[str, Any]:
    return {"code": plan.code, "name": plan.name, "description": plan.description, "credits": plan.credits, "amount": plan.amount, "currency": plan.currency}


def serialize_order(order: CreditOrder) -> dict[str, Any]:
    return {"id": order.id, "plan_code": order.plan_code, "provider": order.provider, "status": order.status, "credits": order.credits, "amount": order.amount, "currency": order.currency, "created_at": order.created_at.isoformat() if order.created_at else None, "completed_at": order.completed_at.isoformat() if order.completed_at else None}


def complete_credit_order(db: Session, order: CreditOrder, user: User) -> None:
    if order.status == "completed":
        return
    db.execute(update(User).where(User.id == user.id).values(credit_balance=User.credit_balance + order.credits))
    db.refresh(user)
    order.status = "completed"
    order.completed_at = datetime.now(timezone.utc)
    db.add(CreditTransaction(user_id=user.id, order_id=order.id, amount=order.credits, balance_after=user.credit_balance, reason="paypal_purchase"))


def serialize_product(product: Product) -> dict[str, Any]:
    return {"id": product.id, "name": product.name, "origin": product.origin, "spec": product.spec, "tags": product.tags or [], "image_url": product.image_url, "created_at": product.created_at.isoformat() if product.created_at else None, "updated_at": product.updated_at.isoformat() if product.updated_at else None}


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security), db: Session = Depends(get_db)) -> User:
    user_id = read_user_id(credentials.credentials) if credentials else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = db.get(User, user_id)
    if not user or not user.is_active or not user.email_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user


def make_assets(product_name: str, primary_image: str | None = None, origin: str = "", spec: str = "", tags: list[str] | None = None) -> list[dict[str, Any]]:
    if not primary_image or not primary_image.startswith("/uploads/"):
        raise QwenError("没有可用的真实生成图片，任务不能标记为完成")
    filename = Path(primary_image).name
    if not filename or not (UPLOAD_DIR / filename).is_file():
        raise QwenError("生成图片未持久化，任务不能标记为完成")
    return [{
        "title": product_name,
        "badge": "AI 生成主图",
        "kind": "main",
        "image": primary_image,
        "product_name": product_name,
        "product_origin": origin,
        "product_spec": spec,
        "product_tags": (tags or [])[:4],
    }]


def product_reference_path(product: Product) -> Path | None:
    """Resolve only files from our upload volume; never treat user text as a path."""
    image_url = (product.image_url or "").strip()
    if not image_url.startswith("/uploads/"):
        return None
    candidate = (UPLOAD_DIR / Path(image_url).name).resolve()
    return candidate if candidate.parent == UPLOAD_DIR.resolve() and candidate.is_file() else None


def pipeline_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def persist_pipeline_state(db: Session, generation: Generation, state: dict[str, Any]) -> None:
    generation.pipeline_state = state
    db.commit()


def dispatch_generation_task(generation_id: str, product_id: str, options: dict[str, str]) -> str:
    if os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL"):
        try:
            from .tasks import run_generation_task
            run_generation_task.delay(generation_id, product_id, options)
            return "celery"
        except Exception:
            logger.exception("pipeline.celery_dispatch_failed generation=%s; falling back to thread", generation_id)
    threading.Thread(target=run_generation_pipeline, args=(generation_id, product_id, options), daemon=True, name=f"pipeline-{generation_id[:8]}").start()
    return "thread"


def run_generation_pipeline(generation_id: str, product_id: str, options: dict[str, str]) -> None:
    """Run the long Qwen pipeline outside the HTTP request lifecycle."""
    with SessionLocal() as db:
        generation = db.get(Generation, generation_id)
        product = db.get(Product, product_id)
        if not generation or not product:
            logger.error("pipeline.task_missing generation=%s product=%s", generation_id, product_id)
            return
        started_at = pipeline_now()
        state: dict[str, Any] = {"status": "processing", "worker": "celery" if os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") else "thread", "started_at": started_at, "current_stage": "model", "stages": {"model": {"status": "active", "started_at": started_at}}}
        generation.status = "processing"
        generation.pipeline_state = state
        db.commit()
        quality_report: dict[str, Any] = {"passed": True, "retries": 0, "reasons": [], "source": "not_run"}
        try:
            plan = compile_generation_plan(product.name, product.origin, product.spec, product.tags, options["usage"])
            if not is_qwen_configured():
                raise QwenError("真实生图服务未配置；任务失败且额度已退回")
            primary_image = None
            reference_image = product_reference_path(product)
            for attempt in range(2):
                logger.info("pipeline.generate attempt=%s task=%s product=%s usage=%s engine=%s", attempt + 1, generation_id, product.name, options["usage"], plan.engine)
                remote_image = generate_image(product.name, product.origin, product.spec, options["usage"], options["style"], options["tone"], options["composition"], options["background"], options["platform"], reference_image=reference_image, tags=product.tags)
                primary_image = persist_remote_image(remote_image, UPLOAD_DIR)
                quality_report = quality_check_image(UPLOAD_DIR / Path(primary_image).name, product.name, options["usage"])
                quality_report["retries"] = attempt
                logger.info("pipeline.quality task=%s passed=%s source=%s retries=%s reasons=%s", generation_id, quality_report.get("passed"), quality_report.get("source"), attempt, " | ".join(quality_report.get("reasons", [])))
                if quality_report.get("passed") or attempt == 1:
                    break
                logger.warning("pipeline.retry task=%s reason=quality_check_failed", generation_id)
            pipeline = {"product_understanding": {"category": plan.category, "selling_points": plan.selling_points, "structure": plan.structure}, "usage_identification": plan.image_usage, "engine": plan.engine, "prompt_compiler": "compiled", "quality_check": quality_report}
            finished_at = pipeline_now()
            state["status"] = "completed"
            state["current_stage"] = "completed"
            state["finished_at"] = finished_at
            state["stages"]["model"] = {"status": "completed", "started_at": started_at, "ended_at": finished_at, "detail": "图片模型已返回素材"}
            state["stages"]["quality"] = {"status": "completed", "started_at": finished_at, "ended_at": finished_at, "detail": "质量检查完成", "result": quality_report}
            pipeline["state"] = state
            assets = make_assets(product.name, primary_image, product.origin, product.spec, product.tags)
            if assets:
                assets[0]["pipeline"] = pipeline
            generation.assets = assets
            generation.pipeline_state = state
            generation.status = "completed"
            db.commit()
            logger.info("pipeline.completed task=%s status=completed", generation_id)
        except Exception as exc:
            generation.status = "failed"
            generation.error_message = str(exc)[:500]
            state["status"] = "failed"
            state["current_stage"] = "failed"
            state["finished_at"] = pipeline_now()
            state["error"] = str(exc)[:500]
            state["stages"]["model"] = {"status": "failed", "started_at": started_at, "ended_at": state["finished_at"], "detail": str(exc)[:200]}
            generation.pipeline_state = state
            user = db.get(User, generation.owner_id)
            if user:
                db.execute(update(User).where(User.id == user.id).values(credit_balance=User.credit_balance + 1))
                db.refresh(user)
                db.add(CreditTransaction(user_id=user.id, amount=1, balance_after=user.credit_balance, reason="generation_refund"))
            db.commit()
            logger.exception("pipeline.failed task=%s error=%s", generation_id, exc)


def seed_catalog(db: Session) -> None:
    if not db.scalar(select(Template.id)):
        db.add_all([
            Template(id="fresh-main", title="自然生鲜主图", category="电商主图", description="突出新鲜质感与商品主体，适合商品首图。", preview_url=ASSET_IMAGES[0], usage="hero", style="natural", sort_order=10),
            Template(id="premium-detail", title="精品详情卖点", category="详情页", description="适合展示规格、口感与品质卖点。", preview_url=ASSET_IMAGES[1], usage="detail", style="premium", sort_order=20),
            Template(id="farm-scene", title="产地直采场景", category="场景图", description="用自然环境强化产地与真实感。", preview_url=ASSET_IMAGES[2], usage="social", style="farm", sort_order=30),
            Template(id="festival-sale", title="节日促销活动", category="活动营销", description="适合节日、限时特惠和活动海报。", preview_url=ASSET_IMAGES[3], usage="promo", style="sale", sort_order=40),
            Template(id="xiaohongshu", title="清新种草笔记", category="社交媒体", description="适合小红书和朋友圈的生活方式内容。", preview_url=ASSET_IMAGES[4], usage="share", style="japanese", sort_order=50),
        ])
    if not db.scalar(select(HelpArticle.id)):
        db.add_all([
            HelpArticle(id="getting-started", category="快速开始", question="如何生成第一套商品素材？", answer="登录后上传商品图片，确认商品名称、产地和规格，选择图片用途与风格，点击一键生成整套图片。", sort_order=10),
            HelpArticle(id="recognition", category="商品识别", question="商品图片识别支持哪些格式？", answer="当前支持 JPG、JPEG、PNG 和 WEBP。配置千问 API Key 后，系统会使用 Qwen-VL 识别商品信息。", sort_order=20),
            HelpArticle(id="generation", category="生成素材", question="生成的图片保存在哪里？", answer="生成记录会保存到数据库，图片会保存到应用上传目录。Railway 上线时请为 /app/data 配置 Volume。", sort_order=30),
            HelpArticle(id="qwen", category="AI 服务", question="如何配置千问 API？", answer="在 Railway Variables 配置 QWEN_API_KEY、QWEN_BASE_URL、QWEN_IMAGE_BASE_URL 和模型名称。", sort_order=40),
            HelpArticle(id="account", category="账户与数据", question="商品和素材是否按商家隔离？", answer="是。商品、生成记录和素材查询均按当前登录用户隔离。", sort_order=50),
        ])
    db.commit()

def seed_credit_plans(db: Session) -> None:
    if db.scalar(select(CreditPlan.code)):
        return
    db.add_all([
        CreditPlan(code="starter", name="尝鲜包", description="适合第一次体验，生成 20 张素材", credits=20, amount="5.00", currency="USD", sort_order=10),
        CreditPlan(code="pro", name="专业包", description="适合日常经营，生成 100 张素材", credits=100, amount="19.00", currency="USD", sort_order=20),
        CreditPlan(code="business", name="商家包", description="适合批量营销，生成 300 张素材", credits=300, amount="49.00", currency="USD", sort_order=30),
    ])
    db.commit()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "xiantu-api",
        "database_backend": engine.url.get_backend_name(),
        "qwen_configured": is_qwen_configured(),
        "storage_writable": os.access(UPLOAD_DIR, os.W_OK),
        "time": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/readyz")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database not ready") from exc

def _issue_verification_token(db: Session, user: User) -> str | None:
    db.execute(delete(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id, EmailVerificationToken.consumed_at.is_(None)))
    raw_token = secrets.token_urlsafe(32)
    db.add(EmailVerificationToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),
    ))
    db.flush()
    return send_verification_email(user.email, raw_token)


def _consume_verification_token(db: Session, raw_token: str) -> User:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    verification = db.scalar(select(EmailVerificationToken).where(
        EmailVerificationToken.token_hash == token_hash,
        EmailVerificationToken.consumed_at.is_(None),
        EmailVerificationToken.expires_at > now,
    ).with_for_update())
    if not verification:
        raise HTTPException(status_code=400, detail="验证链接无效或已过期")
    user = db.get(User, verification.user_id)
    if not user:
        raise HTTPException(status_code=400, detail="验证链接无效或已过期")
    verification.consumed_at = now
    user.email_verified = True
    db.commit()
    return user


@app.post("/api/auth/register", status_code=status.HTTP_202_ACCEPTED)
def register(payload: RegisterPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.email).strip().lower()
    enforce_auth_rate_limit(request, "register", email)
    if os.getenv("ENVIRONMENT", "development").lower() == "production" and not smtp_configured():
        raise HTTPException(status_code=503, detail="邮箱验证服务尚未配置，请联系管理员")
    user = db.scalar(select(User).where(User.email == email))
    debug_url: str | None = None
    try:
        if user and not user.email_verified:
            debug_url = _issue_verification_token(db, user)
            db.commit()
        elif not user:
            user = User(
                email=email,
                password_hash=hash_password(payload.password),
                display_name=payload.display_name.strip() or "商家用户",
                email_verified=False,
                credit_balance=0,
            )
            db.add(user)
            db.flush()
            debug_url = _issue_verification_token(db, user)
            db.commit()
    except EmailDeliveryError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except IntegrityError:
        db.rollback()
        debug_url = None
    response: dict[str, Any] = {"verification_required": True, "message": "如果该邮箱可用，请查看验证邮件；验证后即可登录。"}
    if debug_url and os.getenv("ENVIRONMENT", "development").lower() != "production":
        response["debug_verification_url"] = debug_url
    return response


@app.post("/api/auth/resend-verification", status_code=status.HTTP_202_ACCEPTED)
def resend_verification(payload: EmailPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.email).strip().lower()
    enforce_auth_rate_limit(request, "resend_verification", email)
    if os.getenv("ENVIRONMENT", "development").lower() == "production" and not smtp_configured():
        raise HTTPException(status_code=503, detail="邮箱验证服务尚未配置，请联系管理员")
    user = db.scalar(select(User).where(User.email == email))
    debug_url = None
    if user and not user.email_verified:
        try:
            debug_url = _issue_verification_token(db, user)
            db.commit()
        except EmailDeliveryError as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    response: dict[str, Any] = {"message": "如果该邮箱存在且尚未验证，我们会发送验证邮件。"}
    if debug_url and os.getenv("ENVIRONMENT", "development").lower() != "production":
        response["debug_verification_url"] = debug_url
    return response


@app.post("/api/auth/verify-email")
def verify_email(payload: EmailVerificationPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = _consume_verification_token(db, payload.token)
    return {"verified": True, "email": user.email}


@app.get("/api/auth/verify-email")
def verify_email_link(token: str = Query(min_length=20, max_length=256), db: Session = Depends(get_db)) -> RedirectResponse:
    _consume_verification_token(db, token)
    app_url = os.getenv("PUBLIC_APP_URL", "http://localhost:5173").rstrip("/")
    return RedirectResponse(f"{app_url}/?email_verified=1", status_code=303)


@app.post("/api/auth/login")
def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = str(payload.email).strip().lower()
    enforce_auth_rate_limit(request, "login", email)
    user = db.scalar(select(User).where(User.email == email))
    verified = verify_password(payload.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not verified:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    if not user.email_verified:
        raise HTTPException(status_code=403, detail="请先验证邮箱；如未收到邮件，可重新发送验证链接")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="登录已失效")
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": serialize_user(user)}

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict[str, Any]:
    return serialize_user(user)

@app.get("/api/billing/plans")
def billing_plans(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    plans = db.scalars(select(CreditPlan).where(CreditPlan.is_active.is_(True)).order_by(CreditPlan.sort_order)).all()
    return {"items": [serialize_plan(plan) for plan in plans], "credit_balance": user.credit_balance}

@app.get("/api/billing/paypal/config")
def paypal_config(user: User = Depends(current_user)) -> dict[str, Any]:
    mode = paypal_payment_mode()
    messages = {
        "mock": "演示模式：不会实际扣款，生产环境已禁用模拟入账。",
        "unconfigured": "PayPal 尚未配置真实凭据。",
        "sandbox": "PayPal Sandbox 测试模式，不会进行真实扣款。",
        "live": "PayPal Live 已配置。",
        "custom": "PayPal 使用自定义网关；生产环境仅接受 PayPal Live 官方端点。",
    }
    return {"client_id": paypal_client_id(), "currency": os.getenv("PAYPAL_CURRENCY", "USD"), "mode": mode, "enabled": paypal_checkout_enabled(), "message": messages.get(mode, "PayPal 当前不可用。")}

@app.get("/api/billing/me")
def billing_me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    orders = db.scalars(select(CreditOrder).where(CreditOrder.user_id == user.id).order_by(CreditOrder.created_at.desc()).limit(20)).all()
    return {"credit_balance": user.credit_balance, "orders": [serialize_order(order) for order in orders]}

@app.post("/api/billing/paypal/orders")
def create_paypal_order(payload: CreditOrderPayload, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    production = os.getenv("ENVIRONMENT", "development").lower() == "production"
    if paypal_mock_mode() and production:
        raise HTTPException(status_code=503, detail="生产环境已禁用模拟购买，未收到真实 PayPal 付款不会增加额度")
    if not paypal_mock_mode() and not paypal_checkout_enabled():
        raise HTTPException(status_code=503, detail="PayPal Live 尚未正确配置，当前不能创建真实支付订单")
    plan = db.get(CreditPlan, payload.plan_code)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="额度包不存在")
    order = CreditOrder(user_id=user.id, plan_code=plan.code, provider="paypal", status="pending", credits=plan.credits, amount=plan.amount, currency=plan.currency)
    db.add(order)
    db.flush()
    if paypal_mock_mode():
        order.provider_order_id = f"mock-{order.id}"
        complete_credit_order(db, order, user)
        db.commit()
        return {"order": serialize_order(order), "paypal_order_id": order.provider_order_id, "credit_balance": user.credit_balance, "demo": True}
    if not paypal_configured():
        db.rollback()
        raise HTTPException(status_code=503, detail="PayPal 尚未配置，请联系管理员")
    try:
        public_url = os.getenv("PUBLIC_APP_URL", "").rstrip("/")
        if not public_url:
            raise PayPalError("PUBLIC_APP_URL is not configured")
        paypal_order = paypal_create_order(local_order_id=order.id, plan_name=plan.name, amount=plan.amount, currency=plan.currency, return_url=f"{public_url}/?paypal_order_id={order.id}", cancel_url=f"{public_url}/?paypal_cancelled=1")
        order.provider_order_id = paypal_order.get("id")
        if not order.provider_order_id or not approval_url(paypal_order):
            raise PayPalError("PayPal 响应缺少有效订单 ID 或审批链接")
        db.commit()
        return {"order": serialize_order(order), "paypal_order_id": order.provider_order_id, "approval_url": approval_url(paypal_order), "demo": False}
    except PayPalError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

@app.post("/api/billing/paypal/orders/{order_id}/capture")
def capture_paypal_order(order_id: str, payload: CreditCapturePayload, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    order = db.scalar(select(CreditOrder).where(CreditOrder.id == order_id, CreditOrder.user_id == user.id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    if order.status == "completed":
        return {"order": serialize_order(order), "credit_balance": user.credit_balance, "already_completed": True}
    if order.provider_order_id != payload.paypal_order_id:
        raise HTTPException(status_code=400, detail="PayPal 订单不匹配")
    if paypal_mock_mode():
        if os.getenv("ENVIRONMENT", "development").lower() == "production":
            raise HTTPException(status_code=503, detail="生产环境已禁用模拟入账")
        complete_credit_order(db, order, user)
        db.commit()
        return {"order": serialize_order(order), "credit_balance": user.credit_balance, "demo": True}
    if not paypal_checkout_enabled():
        raise HTTPException(status_code=503, detail="PayPal Live 尚未正确配置，不能确认订单")
    try:
        result = capture_order(payload.paypal_order_id)
    except PayPalError as exc:
        # The browser may have lost the response after PayPal captured funds.
        # Query the authoritative order state before reporting a failure.
        try:
            result = show_order(payload.paypal_order_id)
        except PayPalError:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if result.get("status") != "COMPLETED":
        order.status = "failed"
        db.commit()
        raise HTTPException(status_code=402, detail="PayPal 支付尚未完成")
    purchase_unit = (result.get("purchase_units") or [{}])[0]
    if order.id not in {purchase_unit.get("custom_id"), purchase_unit.get("reference_id")}:
        raise HTTPException(status_code=400, detail="PayPal 订单归属校验失败")
    paypal_amount = purchase_unit.get("amount") or {}
    if paypal_amount.get("currency_code") != order.currency or str(paypal_amount.get("value")) != order.amount:
        raise HTTPException(status_code=400, detail="PayPal 金额校验失败")
    capture = (purchase_unit.get("payments") or {}).get("captures") or [{}]
    capture_data = capture[0]
    capture_status = capture_data.get("status")
    capture_amount = capture_data.get("amount") or {}
    if capture_status != "COMPLETED":
        raise HTTPException(status_code=402, detail="PayPal 扣款未完成")
    if capture_amount.get("currency_code") != order.currency or str(capture_amount.get("value")) != order.amount:
        raise HTTPException(status_code=400, detail="PayPal 捕获金额校验失败")
    complete_credit_order(db, order, user)
    db.commit()
    return {"order": serialize_order(order), "credit_balance": user.credit_balance, "demo": False}

@app.post("/api/webhooks/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    event = await request.json()
    headers = request.headers
    try:
        verified = verify_webhook_signature(
            event=event,
            transmission_id=headers.get("paypal-transmission-id", ""),
            transmission_time=headers.get("paypal-transmission-time", ""),
            cert_url=headers.get("paypal-cert-url", ""),
            auth_algo=headers.get("paypal-auth-algo", ""),
            transmission_sig=headers.get("paypal-transmission-sig", ""),
        )
    except PayPalError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not verified:
        raise HTTPException(status_code=400, detail="PayPal Webhook 验签失败")
    event_id = event.get("id")
    event_type = event.get("event_type", "")
    if not event_id:
        raise HTTPException(status_code=400, detail="PayPal Webhook 缺少事件 ID")
    previous = db.get(PayPalWebhookEvent, event_id)
    if previous and previous.processed:
        return {"received": True, "duplicate": True}
    if not previous:
        previous = PayPalWebhookEvent(id=event_id, event_type=event_type, processed=False)
        db.add(previous)
        db.flush()
    if event_type == "PAYMENT.CAPTURE.COMPLETED":
        resource = event.get("resource") or {}
        related_ids = ((resource.get("supplementary_data") or {}).get("related_ids") or {})
        provider_order_id = related_ids.get("order_id") or resource.get("custom_id")
        order = db.scalar(select(CreditOrder).where(CreditOrder.provider_order_id == provider_order_id).with_for_update()) if provider_order_id else None
        if order and order.status != "completed":
            amount = resource.get("amount") or {}
            if amount.get("currency_code") != order.currency or str(amount.get("value")) != order.amount:
                raise HTTPException(status_code=400, detail="PayPal Webhook 金额校验失败")
            webhook_user = db.get(User, order.user_id)
            if webhook_user:
                complete_credit_order(db, order, webhook_user)
    previous.processed = True
    db.commit()
    return {"received": True, "event_id": event_id, "processed": event_type == "PAYMENT.CAPTURE.COMPLETED"}

@app.post("/api/products/recognize")
async def recognize_product(request: Request, file: UploadFile = File(...), user: User = Depends(current_user)) -> dict[str, Any]:
    enforce_resource_rate_limit(request, "recognition", user.id)
    supplied_suffix = Path(file.filename or "upload.jpg").suffix.lower()
    if supplied_suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WEBP 图片")
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="图片不能超过 10 MB")
    if not contents:
        raise HTTPException(status_code=422, detail="上传的图片为空")
    suffix_by_format = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
    try:
        with Image.open(io.BytesIO(contents)) as image:
            image_format = image.format
            if image.width * image.height > 30_000_000:
                raise HTTPException(status_code=413, detail="图片像素总量过大")
            image.verify()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="上传内容不是有效图片") from exc
    suffix = suffix_by_format.get(image_format or "")
    if not suffix:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WEBP 图片内容")
    stored_name = f"{uuid4().hex}{suffix}"
    target = UPLOAD_DIR / stored_name
    target.write_bytes(contents)
    result = {"name": "崂山大樱桃", "origin": "山东·青岛崂山", "spec": "500g", "tags": ["果大", "脆甜", "新鲜", "当季"], "recognition_confidence": 0.45, "recognition_evidence": "暂未完成可靠的视觉识别，请手动确认"}
    if not is_qwen_configured() and not allow_mock_fallback():
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=503, detail="商品识别服务尚未配置")
    if is_qwen_configured():
        try:
            result = {**result, **qwen_recognize_product(target, suffix)}
        except QwenError as exc:
            if not allow_mock_fallback():
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=502, detail=f"千问识别失败：{exc}") from exc
    return {**result, "image_url": f"/uploads/{stored_name}", "filename": file.filename, "user_id": user.id}

@app.post("/api/products")
def create_product(payload: ProductPayload, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    product = Product(owner_id=user.id, name=payload.name.strip(), origin=payload.origin.strip(), spec=payload.spec.strip(), tags=payload.tags, image_url=payload.image_url)
    db.add(product)
    db.commit()
    db.refresh(product)
    return serialize_product(product)

@app.get("/api/products")
def list_products(q: str | None = Query(default=None, max_length=80), limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    statement = select(Product).where(Product.owner_id == user.id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(Product.name.ilike(term) | Product.origin.ilike(term))
    filtered = db.scalars(statement.order_by(Product.created_at.desc())).all()
    return {"items": [serialize_product(item) for item in filtered[offset:offset + limit]], "total": len(filtered), "limit": limit, "offset": offset}

@app.put("/api/products/{product_id}")
def update_product(product_id: str, payload: ProductUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    product = db.scalar(select(Product).where(Product.id == product_id, Product.owner_id == user.id))
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(product, key, value)
    db.commit()
    db.refresh(product)
    return serialize_product(product)

@app.delete("/api/products/{product_id}")
def delete_product(product_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    product = db.scalar(select(Product).where(Product.id == product_id, Product.owner_id == user.id))
    if not product:
        raise HTTPException(status_code=404, detail="商品不存在")
    db.delete(product)
    db.commit()
    return {"deleted": True, "id": product_id}

@app.post("/api/generations")
def create_generation(payload: GenerationPayload, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    enforce_resource_rate_limit(request, "generation", user.id)
    if user.credit_balance < 1:
        raise HTTPException(status_code=402, detail="生成额度不足，请购买额度包")
    product = db.get(Product, payload.product_id) if payload.product_id else None
    if product and product.owner_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问该商品")
    if not product and payload.product:
        product = Product(owner_id=user.id, name=payload.product.name.strip(), origin=payload.product.origin.strip(), spec=payload.product.spec.strip(), tags=payload.product.tags, image_url=payload.product.image_url)
        db.add(product)
        db.flush()
    if not product:
        raise HTTPException(status_code=422, detail="请提供商品信息")
    assets: list[dict[str, Any]] = []
    debit_result = db.execute(
        update(User)
        .where(User.id == user.id, User.credit_balance > 0)
        .values(credit_balance=User.credit_balance - 1)
    )
    if debit_result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=402, detail="生成额度不足，请购买额度包")
    db.refresh(user)
    worker = "celery" if os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") else "thread"
    generation = Generation(owner_id=user.id, product_id=product.id, usage=payload.usage, style=payload.style, status="queued", assets=assets, pipeline_state={"status": "queued", "worker": worker, "queued_at": pipeline_now(), "current_stage": "queued", "stages": {}})
    db.add(generation)
    db.add(CreditTransaction(user_id=user.id, amount=-1, balance_after=user.credit_balance, reason="generation"))
    db.commit()
    db.refresh(generation)
    dispatch_generation_task(generation.id, product.id, payload.model_dump(exclude={"product", "product_id"}))
    return {"id": generation.id, "status": generation.status, "usage": generation.usage, "style": generation.style, "product": serialize_product(product), "assets": [], "pipeline": generation.pipeline_state}

@app.get("/api/generations/{generation_id}")
def get_generation(generation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    generation = db.scalar(select(Generation).where(Generation.id == generation_id, Generation.owner_id == user.id))
    if not generation:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    pipeline = (generation.assets[0].get("pipeline") if generation.assets else None) or generation.pipeline_state or {"status": generation.status}
    return {"id": generation.id, "status": generation.status, "usage": generation.usage, "style": generation.style, "product": serialize_product(generation.product) if generation.product else None, "assets": generation.assets or [], "pipeline": pipeline, "error_message": generation.error_message}

@app.get("/api/generations")
def list_generations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    items = db.scalars(select(Generation).where(Generation.owner_id == user.id).order_by(Generation.created_at.desc())).all()
    return {"items": [{"id": item.id, "status": item.status, "usage": item.usage, "style": item.style, "count": len(item.assets or []), "assets": item.assets or [], "pipeline": item.pipeline_state, "product_id": item.product_id, "product_name": item.product.name if item.product else None, "created_at": item.created_at.isoformat() if item.created_at else None} for item in items]}

@app.get("/api/assets")
def list_assets(q: str | None = Query(default=None, max_length=80), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    generations = db.scalars(select(Generation).where(Generation.owner_id == user.id).order_by(Generation.created_at.desc())).all()
    items = []
    for generation in generations:
        product = db.get(Product, generation.product_id) if generation.product_id else None
        for asset in generation.assets or []:
            item = {**asset, "id": f"{generation.id}:{asset.get('kind', 'asset')}", "generation_id": generation.id, "product_id": generation.product_id, "product_name": product.name if product else None, "product_origin": product.origin if product else asset.get("product_origin", ""), "product_spec": product.spec if product else asset.get("product_spec", ""), "product_tags": (product.tags or [])[:4] if product else asset.get("product_tags", []), "created_at": generation.created_at.isoformat() if generation.created_at else None}
            if not q or q.strip().lower() in f"{item.get('title', '')} {item.get('badge', '')} {item.get('product_name', '')}".lower():
                items.append(item)
    return {"items": items[offset:offset + limit], "total": len(items), "limit": limit, "offset": offset}

@app.get("/api/templates")
def list_templates(q: str | None = Query(default=None, max_length=80), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    statement = select(Template).where(Template.is_active.is_(True)).order_by(Template.sort_order.asc())
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(Template.title.ilike(term) | Template.category.ilike(term) | Template.description.ilike(term))
    items = db.scalars(statement).all()
    return {"items": [{"id": item.id, "title": item.title, "category": item.category, "description": item.description, "preview_url": item.preview_url, "usage": item.usage, "style": item.style} for item in items], "total": len(items)}

@app.get("/api/help")
def list_help(q: str | None = Query(default=None, max_length=80), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    statement = select(HelpArticle).where(HelpArticle.is_published.is_(True)).order_by(HelpArticle.sort_order.asc())
    if q and q.strip():
        term = f"%{q.strip()}%"
        statement = statement.where(HelpArticle.question.ilike(term) | HelpArticle.answer.ilike(term) | HelpArticle.category.ilike(term))
    items = db.scalars(statement).all()
    return {"items": [{"id": item.id, "category": item.category, "question": item.question, "answer": item.answer} for item in items], "total": len(items)}

# Production static serving: the Docker build copies frontend/dist here.
STATIC_DIR = PROJECT_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        if path.startswith(("api/", "uploads/", "docs", "redoc", "openapi.json", "assets/", "static/")):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")
