from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import jwt
from fastapi import Depends, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from fastapi import FastAPI
from .database import Base, SessionLocal, engine, ensure_local_storage, get_db
from .models import Generation, Product, User
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


def serialize_user(user: User) -> dict[str, Any]:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "locale": user.locale, "timezone": user.timezone}


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

@app.on_event("startup")
def startup() -> None:
    ensure_local_storage()
    secret_key()
    if os.getenv("AUTO_CREATE_SCHEMA", "true").lower() == "true":
        Base.metadata.create_all(bind=engine)
    if os.getenv("SEED_DEMO_USER", "true").lower() == "true":
        with SessionLocal() as db:
            if not db.scalar(select(User).where(User.email == "demo@xiantu.ai")):
                db.add(User(email="demo@xiantu.ai", password_hash=hash_password("Demo123456!"), display_name="演示商家"))
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
    generation = Generation(owner_id=user.id, product_id=product.id, usage=payload.usage, style=payload.style, status="completed", assets=assets)
    db.add(generation)
    db.commit()
    db.refresh(generation)
    return {"id": generation.id, "status": generation.status, "usage": generation.usage, "style": generation.style, "product": serialize_product(product), "assets": assets}

@app.get("/api/generations")
def list_generations(user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    items = db.scalars(select(Generation).where(Generation.owner_id == user.id).order_by(Generation.created_at.desc())).all()
    return {"items": [{"id": item.id, "status": item.status, "usage": item.usage, "style": item.style, "count": len(item.assets or []), "created_at": item.created_at.isoformat() if item.created_at else None} for item in items]}

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
