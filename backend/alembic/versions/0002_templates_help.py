"""templates and help center content

Revision ID: 0002_templates_help
Revises: 0001_initial
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "0002_templates_help"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "templates",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("preview_url", sa.Text(), nullable=False),
        sa.Column("usage", sa.String(length=40), nullable=False),
        sa.Column("style", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "help_articles",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("question", sa.String(length=255), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    templates = sa.table(
        "templates",
        sa.column("id", sa.String), sa.column("title", sa.String), sa.column("category", sa.String),
        sa.column("description", sa.String), sa.column("preview_url", sa.Text), sa.column("usage", sa.String),
        sa.column("style", sa.String), sa.column("is_active", sa.Boolean), sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(templates, [
        {"id": "fresh-main", "title": "自然生鲜主图", "category": "电商主图", "description": "突出新鲜质感与商品主体，适合商品首图。", "preview_url": "https://images.unsplash.com/photo-1528825871115-3581a5387919?auto=format&fit=crop&w=900&q=88", "usage": "hero", "style": "natural", "is_active": True, "sort_order": 10, "created_at": now},
        {"id": "premium-detail", "title": "精品详情卖点", "category": "详情页", "description": "适合展示规格、口感与品质卖点。", "preview_url": "https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=900&q=88", "usage": "detail", "style": "premium", "is_active": True, "sort_order": 20, "created_at": now},
        {"id": "farm-scene", "title": "产地直采场景", "category": "场景图", "description": "用自然环境强化产地与真实感。", "preview_url": "https://images.unsplash.com/photo-1471943311424-646960669fbc?auto=format&fit=crop&w=900&q=88", "usage": "social", "style": "farm", "is_active": True, "sort_order": 30, "created_at": now},
        {"id": "festival-sale", "title": "节日促销活动", "category": "活动营销", "description": "适合节日、限时特惠和活动海报。", "preview_url": "https://images.unsplash.com/photo-1577003833619-76bbd7f82948?auto=format&fit=crop&w=900&q=88", "usage": "promo", "style": "sale", "is_active": True, "sort_order": 40, "created_at": now},
        {"id": "xiaohongshu", "title": "清新种草笔记", "category": "社交媒体", "description": "适合小红书和朋友圈的生活方式内容。", "preview_url": "https://images.unsplash.com/photo-1592924357228-91a4daadcfea?auto=format&fit=crop&w=900&q=88", "usage": "share", "style": "japanese", "is_active": True, "sort_order": 50, "created_at": now},
    ])
    articles = sa.table(
        "help_articles",
        sa.column("id", sa.String), sa.column("category", sa.String), sa.column("question", sa.String),
        sa.column("answer", sa.Text), sa.column("is_published", sa.Boolean), sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(articles, [
        {"id": "getting-started", "category": "快速开始", "question": "如何生成第一套商品素材？", "answer": "登录后上传商品图片，确认商品名称、产地和规格，选择图片用途与风格，点击“一键生成整套图片”。生成结果会自动保存到素材库和生成记录。", "is_published": True, "sort_order": 10, "created_at": now},
        {"id": "recognition", "category": "商品识别", "question": "商品图片识别支持哪些格式？", "answer": "当前支持 JPG、JPEG、PNG 和 WEBP。生产环境配置千问 API Key 后，系统会使用 Qwen-VL 识别商品名称、产地、规格和卖点。", "is_published": True, "sort_order": 20, "created_at": now},
        {"id": "generation", "category": "生成素材", "question": "生成的图片保存在哪里？", "answer": "生成记录会保存到数据库，图片会保存到应用上传目录。Railway 上线时请为 /app/data 配置 Volume，后续建议迁移到对象存储。", "is_published": True, "sort_order": 30, "created_at": now},
        {"id": "qwen", "category": "AI 服务", "question": "如何配置千问 API？", "answer": "在 Railway Variables 配置 QWEN_API_KEY、QWEN_BASE_URL、QWEN_IMAGE_BASE_URL、QWEN_VISION_MODEL 和 QWEN_IMAGE_MODEL。生产环境将 QWEN_MOCK_FALLBACK 设置为 false。", "is_published": True, "sort_order": 40, "created_at": now},
        {"id": "account", "category": "账户与数据", "question": "商品和素材是否按商家隔离？", "answer": "是。商品、生成记录和素材查询均按当前登录用户隔离，删除商品不会删除已经生成的素材记录。", "is_published": True, "sort_order": 50, "created_at": now},
    ])


def downgrade() -> None:
    op.drop_table("help_articles")
    op.drop_table("templates")
