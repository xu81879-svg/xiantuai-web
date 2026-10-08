import os

os.environ["DATABASE_URL"] = "sqlite:///./test-mvp.db"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["SEED_DEMO_USER"] = "true"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["DEMO_USER_EMAIL"] = "demo@xiantu.ai"
os.environ["DEMO_USER_PASSWORD"] = "Demo123456!"
os.environ["DEMO_USER_NAME"] = "演示商家"
os.environ["PAYPAL_MOCK_MODE"] = "true"

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import User


def test_auth_and_generation_flow():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "demo@xiantu.ai", "password": "Demo123456!"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        generation = client.post("/api/generations", headers=headers, json={"product": {"name": "测试樱桃", "origin": "山东", "spec": "500g", "tags": ["新鲜"]}, "usage": "hero", "style": "natural"})
        assert generation.status_code == 200
        assert generation.json()["status"] == "queued"
        task = client.get(f"/api/generations/{generation.json()['id']}", headers=headers)
        assert task.status_code == 200
        assert task.json()["status"] == "completed"
        assert len(task.json()["assets"]) == 5
        generation_items = client.get("/api/generations", headers=headers).json()["items"]
        assert generation_items and len(generation_items[0]["assets"]) == 5
        templates = client.get("/api/templates", headers=headers)
        assert templates.status_code == 200
        assert templates.json()["total"] >= 1
        help_articles = client.get("/api/help?q=千问", headers=headers)
        assert help_articles.status_code == 200
        assert help_articles.json()["total"] >= 1
        product_id = generation.json()["product"]["id"]
        products = client.get("/api/products?q=测试", headers=headers)
        assert products.status_code == 200
        assert products.json()["total"] == 1
        updated = client.put(f"/api/products/{product_id}", headers=headers, json={"name": "更新后的樱桃", "tags": ["精选"]})
        assert updated.status_code == 200
        assert updated.json()["name"] == "更新后的樱桃"
        assets = client.get("/api/assets", headers=headers)
        assert assets.status_code == 200
        assert assets.json()["total"] == 5
        assert assets.json()["items"][0]["generation_id"] == generation.json()["id"]
        deleted = client.delete(f"/api/products/{product_id}", headers=headers)
        assert deleted.status_code == 200


def test_credit_purchase_is_idempotent_and_generation_debits_balance():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "demo@xiantu.ai", "password": "Demo123456!"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with SessionLocal() as db:
            user = db.get(User, login.json()["user"]["id"])
            assert user is not None
            user.credit_balance = 10
            db.commit()

        before = client.get("/api/auth/me", headers=headers).json()
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
            user = db.get(User, login.json()["user"]["id"])
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
