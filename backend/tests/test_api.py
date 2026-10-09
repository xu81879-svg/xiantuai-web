import os
import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from PIL import Image

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test-mvp.db"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["SEED_DEMO_USER"] = "true"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DEMO_USER_EMAIL"] = "demo@xiantu.ai"
os.environ["DEMO_USER_PASSWORD"] = "Demo123456!"
os.environ["DEMO_USER_NAME"] = "演示商家"
os.environ["PAYPAL_MOCK_MODE"] = "true"
os.environ["PUBLIC_APP_URL"] = "http://localhost:5173"

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as main_module
from app.main import app
from app.database import SessionLocal
from app.models import CreditOrder, EmailVerificationToken, User


def _login(client: TestClient) -> tuple[str, dict[str, str]]:
    response = client.post("/api/auth/login", json={"email": "demo@xiantu.ai", "password": "Demo123456!"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_auth_and_generation_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "is_qwen_configured", lambda: True)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr(main_module, "UPLOAD_DIR", upload_dir)

    def persist_test_image(_url, target_dir):
        target = target_dir / "generated-test.png"
        Image.new("RGB", (512, 512), (210, 80, 70)).save(target)
        return "/uploads/generated-test.png"

    monkeypatch.setattr(main_module, "generate_image", lambda *args, **kwargs: "https://test.invalid/generated.png")
    monkeypatch.setattr(main_module, "persist_remote_image", persist_test_image)
    monkeypatch.setattr(main_module, "quality_check_image", lambda *args: {"passed": True, "reasons": [], "source": "test"})

    with TestClient(app) as client:
        _, headers = _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            assert user is not None and user.email_verified
            user.credit_balance = 10
            db.commit()

        assert client.get("/api/auth/me", headers=headers).status_code == 200
        generation = client.post("/api/generations", headers=headers, json={"product": {"name": "测试樱桃", "origin": "山东", "spec": "500g", "tags": ["新鲜"]}, "usage": "hero", "style": "natural"})
        assert generation.status_code == 200
        task = None
        for _ in range(40):
            task = client.get(f"/api/generations/{generation.json()['id']}", headers=headers)
            assert task.status_code == 200
            if task.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert task is not None
        assert task.json()["status"] == "completed"
        assert len(task.json()["assets"]) == 1
        assert task.json()["assets"][0]["image"] == "/uploads/generated-test.png"
        assert len(client.get("/api/generations", headers=headers).json()["items"][0]["assets"]) == 1
        templates = client.get("/api/templates", headers=headers)
        assert templates.status_code == 200 and templates.json()["total"] >= 1
        help_articles = client.get("/api/help?q=千问", headers=headers)
        assert help_articles.status_code == 200 and help_articles.json()["total"] >= 1
        product_id = generation.json()["product"]["id"]
        products = client.get("/api/products?q=测试", headers=headers)
        assert products.status_code == 200 and products.json()["total"] == 1
        updated = client.put(f"/api/products/{product_id}", headers=headers, json={"name": "更新后的樱桃", "tags": ["精选"]})
        assert updated.status_code == 200 and updated.json()["name"] == "更新后的樱桃"
        assets = client.get("/api/assets", headers=headers)
        assert assets.status_code == 200 and assets.json()["total"] == 1
        assert assets.json()["items"][0]["generation_id"] == generation.json()["id"]
        assert client.delete(f"/api/products/{product_id}", headers=headers).status_code == 200


def test_credit_purchase_is_idempotent_and_generation_debits_balance(monkeypatch):
    monkeypatch.setattr(main_module, "dispatch_generation_task", lambda *_args: "test")
    with TestClient(app) as client:
        _, headers = _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            assert user is not None
            user.credit_balance = 10
            db.commit()

        before = client.get("/api/billing/me", headers=headers).json()
        assert before["credit_balance"] == 10
        purchase = client.post("/api/billing/paypal/orders", headers=headers, json={"plan_code": "starter"})
        assert purchase.status_code == 200
        purchase_data = purchase.json()
        assert purchase_data["order"]["status"] == "completed"
        assert purchase_data["credit_balance"] == 30

        duplicate_capture = client.post(
            f"/api/billing/paypal/orders/{purchase_data['order']['id']}/capture",
            headers=headers,
            json={"paypal_order_id": purchase_data["paypal_order_id"]},
        )
        assert duplicate_capture.status_code == 200
        assert duplicate_capture.json()["already_completed"] is True
        assert duplicate_capture.json()["credit_balance"] == 30

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            assert user is not None
            user.credit_balance = 1
            db.commit()

        generation = client.post(
            "/api/generations",
            headers=headers,
            json={"product": {"name": "额度测试商品", "origin": "山东", "spec": "500g", "tags": ["新鲜"]}, "usage": "hero", "style": "natural"},
        )
        assert generation.status_code == 200
        assert client.get("/api/auth/me", headers=headers).json()["credit_balance"] == 0
        exhausted = client.post(
            "/api/generations",
            headers=headers,
            json={"product": {"name": "额度耗尽商品", "origin": "山东", "spec": "500g", "tags": ["新鲜"]}, "usage": "hero", "style": "natural"},
        )
        assert exhausted.status_code == 402
        assert exhausted.json()["detail"] == "生成额度不足，请购买额度包"


def test_registration_requires_email_verification_and_grants_no_free_credits():
    email = f"new-{uuid4().hex}@example.com"
    password = "StrongerPass123!"
    with TestClient(app) as client:
        registration = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "新测试账户"})
        assert registration.status_code == 202
        response = registration.json()
        assert response["verification_required"] is True
        assert "access_token" not in response
        assert response["debug_verification_url"].startswith("http://localhost:5173/api/auth/verify-email?")
        raw_token = parse_qs(urlparse(response["debug_verification_url"]).query)["token"][0]
        login_before = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login_before.status_code == 403

        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            assert user is not None
            assert user.email_verified is False
            assert user.credit_balance == 0
            stored = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id == user.id))
            assert stored is not None and stored.token_hash != raw_token

        verified = client.post("/api/auth/verify-email", json={"token": raw_token})
        assert verified.status_code == 200 and verified.json()["verified"] is True
        assert client.post("/api/auth/verify-email", json={"token": raw_token}).status_code == 400
        login_after = client.post("/api/auth/login", json={"email": email, "password": password})
        assert login_after.status_code == 200
        assert login_after.json()["user"]["credit_balance"] == 0


def test_production_registration_fails_closed_without_secure_smtp(monkeypatch):
    email = f"smtp-missing-{uuid4().hex}@example.com"
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://insecure.example.com")
    for name in ("SMTP_HOST", "SMTP_FROM", "SMTP_USERNAME", "SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(app) as client:
        response = client.post("/api/auth/register", json={"email": email, "password": "StrongerPass123!"})
        assert response.status_code == 503
        assert "尚未配置" in response.json()["detail"]
        with SessionLocal() as db:
            assert db.scalar(select(User).where(User.email == email)) is None


def test_auth_input_validation_and_failed_login_rate_limit():
    with TestClient(app) as client:
        invalid_email = client.post("/api/auth/register", json={"email": "not-an-email", "password": "StrongerPass123!"})
        assert invalid_email.status_code == 422
        short_password = client.post("/api/auth/register", json={"email": f"short-{uuid4().hex}@example.com", "password": "short"})
        assert short_password.status_code == 422

        email = f"unknown-{uuid4().hex}@example.com"
        for _ in range(8):
            failed = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword123!"})
            assert failed.status_code == 401
        limited = client.post("/api/auth/login", json={"email": email, "password": "WrongPassword123!"})
        assert limited.status_code == 429
        assert limited.headers.get("retry-after") == "300"


def test_production_refuses_mock_paypal_credit():
    with TestClient(app) as client:
        _, headers = _login(client)
        import pytest
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("ENVIRONMENT", "production")
            config = client.get("/api/billing/paypal/config", headers=headers)
            assert config.status_code == 200
            assert config.json()["mode"] == "mock"
            assert config.json()["enabled"] is False
            purchase = client.post("/api/billing/paypal/orders", headers=headers, json={"plan_code": "starter"})
            assert purchase.status_code == 503
            assert "模拟购买" in purchase.json()["detail"]


def test_generation_without_real_qwen_fails_without_placeholder_and_refunds(monkeypatch):
    monkeypatch.setattr(main_module, "is_qwen_configured", lambda: False)
    monkeypatch.setattr(main_module, "allow_mock_fallback", lambda: False)
    with TestClient(app) as client:
        _, headers = _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            assert user is not None
            user.credit_balance = 1
            db.commit()
        submitted = client.post(
            "/api/generations",
            headers=headers,
            json={"product": {"name": "未配置模型商品", "origin": "山东", "spec": "500g", "tags": []}, "usage": "hero", "style": "natural"},
        )
        assert submitted.status_code == 200
        generation_id = submitted.json()["id"]
        result = None
        for _ in range(40):
            result = client.get(f"/api/generations/{generation_id}", headers=headers)
            if result.json()["status"] in {"completed", "failed"}:
                break
            time.sleep(0.05)
        assert result is not None and result.json()["status"] == "failed"
        assert result.json()["assets"] == []
        assert client.get("/api/auth/me", headers=headers).json()["credit_balance"] == 1


def test_recognition_rejects_oversized_and_invalid_image_uploads():
    with TestClient(app) as client:
        _, headers = _login(client)
        oversized = client.post(
            "/api/products/recognize",
            headers=headers,
            files={"file": ("too-large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
        )
        assert oversized.status_code == 413
        invalid_image = client.post(
            "/api/products/recognize",
            headers=headers,
            files={"file": ("not-really.png", b"not an image", "image/png")},
        )
        assert invalid_image.status_code == 422


def test_paypal_capture_rejects_amount_mismatch_without_crediting(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PAYPAL_MOCK_MODE", "false")
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-live-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-live-secret")
    with TestClient(app) as client:
        _, headers = _login(client)
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            assert user is not None
            user.credit_balance = 7
            order = CreditOrder(user_id=user.id, plan_code="starter", provider_order_id="PAYPAL-UNIT-TEST", status="pending", credits=20, amount="5.00", currency="USD")
            db.add(order)
            db.commit()
            order_id = order.id

        monkeypatch.setattr(main_module, "capture_order", lambda _provider_id: {
            "status": "COMPLETED",
            "purchase_units": [{
                "custom_id": order_id,
                "amount": {"currency_code": "USD", "value": "4.99"},
                "payments": {"captures": [{"status": "COMPLETED", "amount": {"currency_code": "USD", "value": "4.99"}}]},
            }],
        })
        response = client.post(
            f"/api/billing/paypal/orders/{order_id}/capture",
            headers=headers,
            json={"paypal_order_id": "PAYPAL-UNIT-TEST"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "PayPal 金额校验失败"
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "demo@xiantu.ai"))
            order = db.get(CreditOrder, order_id)
            assert user is not None and user.credit_balance == 7
            assert order is not None and order.status == "pending"
