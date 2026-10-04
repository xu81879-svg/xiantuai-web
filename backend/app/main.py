from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fastapi import FastAPI
from .database import Base, SessionLocal, engine, ensure_local_storage, get_db
from .models import CreditOrder, CreditPlan, CreditTransaction, Generation, HelpArticle, PayPalWebhookEvent, Product, Template, User
from .paypal import PayPalError, approval_url, capture_order, client_id as paypal_client_id, configured as paypal_configured, create_order as paypal_create_order, mock_mode as paypal_mock_mode, show_order, verify_webhook_signature
from .qwen import QwenError, allow_mock_fallback, generate_image, is_qwen_configured, persist_remote_image, recognize_product as qwen_recognize_product
from .security import create_access_token, hash_password, read_user_id, secret_key, verify_password

APP_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = APP_DIR.parent
STORAGE_DIR = Path(os.getenv("LOCAL_STORAGE_DIR", str(PROJECT_DIR / "data")))
UPLOAD_DIR = STORAGE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="鲜图 AI API", version="1.0.0", docs_url="/docs", redoc_url="/redoc")
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
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="商家用户", min_length=1, max_length=80)

class LoginPayload(BaseModel):
    email: str
    password: str

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

class CreditOrderPayload(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)

class CreditCapturePayload(BaseModel):
    paypal_order_id: str = Field(min_length=1, max_length=100)


def serialize_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "locale": user.locale, "timezone": user.timezone, "credit_balance": user.credit_balance}


def serialize_plan(plan: CreditPlan) -> dict[str, Any]:
    return {"code": plan.code, "name": plan.name, "description": plan.description, "credits": plan.credits, "amount": plan.amount, "currency": plan.currency}


def serialize_order(order: CreditOrder) -> dict[str, Any]:
    return {"id": order.id, "plan_code": order.plan_code, "provider": order.provider, "status": order.status, "credits": order.credits, "amount": order.amount, "currency": order.currency, "created_at": order.created_at.isoformat() if order.created_at else None, "completed_at": order.completed_at.isoformat() if order.completed_at else None}


def complete_credit_order(db: Session, order: CreditOrder, user: User) -> None:
    if order.status == "completed":
        return
    order.status = "completed"
    order.completed_at = datetime.now(timezone.utc)
    user.credit_balance += order.credits
    db.add(CreditTransaction(user_id=user.id, order_id=order.id, amount=order.credits, balance_after=user.credit_balance, reason="paypal_purchase"))


def serialize_product(product: Product) -> dict[str, Any]:
    return {"id": product.id, "name": product.name, "origin": product.origin, "spec": product.spec, "tags": product.tags or [], "image_url": product.image_url, "created_at": product.created_at.isoformat() if product.created_at else None, "updated_at": product.updated_at.isoformat() if product.updated_at else None}


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security), db: Session = Depends(get_db)) -> User:
    user_id = read_user_id(credentials.credentials) if credentials else None
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user


def make_assets(product_name: str, primary_image: str | None = None) -> list[dict[str, Any]]:
    titles = [product_name, "甜蜜多汁 · 一口爆甜", "源自产地 · 自然成熟", "新鲜好物 · 限时特惠", "把新鲜带回家"]
    badges = ["电商主图", "详情页卖点", "场景图", "促销活动", "朋友圈分享"]
    kinds = ["main", "detail", "scene", "sale", "share"]
    images = [primary_image or ASSET_IMAGES[0], *ASSET_IMAGES[1:]]
    return [{"title": title, "badge": badge, "kind": kind, "image": image} for title, badge, kind, image in zip(titles, badges, kinds, images)]


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


@app.on_event("startup")
def startup() -> None:
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
                db.add(User(email=demo_email, password_hash=hash_password(demo_password), display_name=demo_name))
                db.commit()

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "xiantu-api", "qwen_configured": is_qwen_configured(), "time": datetime.now(timezone.utc).isoformat()}

@app.get("/readyz")
def ready(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database not ready") from exc

@app.post("/api/auth/register")
def register(payload: RegisterPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="请输入有效邮箱")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="邮箱已注册")
    user = User(email=email, password_hash=hash_password(payload.password), display_name=payload.display_name.strip() or "商家用户")
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": serialize_user(user)}

@app.post("/api/auth/login")
def login(payload: LoginPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
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
    return {"client_id": paypal_client_id(), "currency": os.getenv("PAYPAL_CURRENCY", "USD"), "enabled": bool(paypal_client_id() and paypal_configured())}

@app.get("/api/billing/me")
def billing_me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    orders = db.scalars(select(CreditOrder).where(CreditOrder.user_id == user.id).order_by(CreditOrder.created_at.desc()).limit(20)).all()
    return {"credit_balance": user.credit_balance, "orders": [serialize_order(order) for order in orders]}

@app.post("/api/billing/paypal/orders")
def create_paypal_order(payload: CreditOrderPayload, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
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
        complete_credit_order(db, order, user)
        db.commit()
        return {"order": serialize_order(order), "credit_balance": user.credit_balance, "demo": True}
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
    if purchase_unit.get("custom_id") not in {None, order.id} and purchase_unit.get("reference_id") != order.id:
        raise HTTPException(status_code=400, detail="PayPal 订单归属校验失败")
    paypal_amount = (purchase_unit.get("amount") or {})
    if paypal_amount and (paypal_amount.get("currency_code") != order.currency or str(paypal_amount.get("value")) != order.amount):
        raise HTTPException(status_code=400, detail="PayPal 金额校验失败")
    capture = (purchase_unit.get("payments") or {}).get("captures") or [{}]
    capture_status = capture[0].get("status")
    if capture_status != "COMPLETED":
        raise HTTPException(status_code=402, detail="PayPal 扣款未完成")
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
            if amount and (amount.get("currency_code") != order.currency or str(amount.get("value")) != order.amount):
                raise HTTPException(status_code=400, detail="PayPal Webhook 金额校验失败")
            webhook_user = db.get(User, order.user_id)
            if webhook_user:
                complete_credit_order(db, order, webhook_user)
    previous.processed = True
    db.commit()
    return {"received": True, "event_id": event_id, "processed": event_type == "PAYMENT.CAPTURE.COMPLETED"}

@app.post("/api/products/recognize")
async def recognize_product(file: UploadFile = File(...), user: User = Depends(current_user)) -> dict[str, Any]:
    suffix = Path(file.filename or "upload.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG、WEBP 图片")
    stored_name = f"{uuid4().hex}{suffix}"
    target = UPLOAD_DIR / stored_name
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    result = {"name": "崂山大樱桃", "origin": "山东·青岛崂山", "spec": "500g", "tags": ["果大", "脆甜", "新鲜", "当季"]}
    if is_qwen_configured():
        try:
            result = {**result, **qwen_recognize_product(target, suffix)}
        except QwenError as exc:
            if not allow_mock_fallback():
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
def create_generation(payload: GenerationPayload, user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
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
    primary_image = None
    if is_qwen_configured():
        try:
            remote_image = generate_image(product.name, product.origin, product.spec, payload.usage, payload.style)
            primary_image = persist_remote_image(remote_image, UPLOAD_DIR)
        except QwenError as exc:
            if not allow_mock_fallback():
                raise HTTPException(status_code=502, detail=f"千问生图失败：{exc}") from exc
    assets = make_assets(product.name, primary_image)
    user.credit_balance -= 1
    generation = Generation(owner_id=user.id, product_id=product.id, usage=payload.usage, style=payload.style, status="completed", assets=assets)
    db.add(generation)
    db.add(CreditTransaction(user_id=user.id, amount=-1, balance_after=user.credit_balance, reason="generation"))
    db.commit()
    db.refresh(generation)
    return {"id": generation.id, "status": generation.status, "usage": generation.usage, "style": generation.style, "product": serialize_product(product), "assets": assets}

@app.get("/api/generations")
def list_generations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    items = db.scalars(select(Generation).where(Generation.owner_id == user.id).order_by(Generation.created_at.desc())).all()
    return {"items": [{"id": item.id, "status": item.status, "usage": item.usage, "style": item.style, "count": len(item.assets or []), "assets": item.assets or [], "product_id": item.product_id, "product_name": item.product.name if item.product else None, "created_at": item.created_at.isoformat() if item.created_at else None} for item in items]}

@app.get("/api/assets")
def list_assets(q: str | None = Query(default=None, max_length=80), limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    generations = db.scalars(select(Generation).where(Generation.owner_id == user.id).order_by(Generation.created_at.desc())).all()
    items = []
    for generation in generations:
        product = db.get(Product, generation.product_id) if generation.product_id else None
        for asset in generation.assets or []:
            item = {**asset, "id": f"{generation.id}:{asset.get('kind', 'asset')}", "generation_id": generation.id, "product_id": generation.product_id, "product_name": product.name if product else None, "created_at": generation.created_at.isoformat() if generation.created_at else None}
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
