import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test-mvp.db"
os.environ["AUTO_CREATE_SCHEMA"] = "true"
os.environ["SEED_DEMO_USER"] = "true"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient

from app.main import app


def test_auth_and_generation_flow():
    db_path = Path("test-mvp.db")
    if db_path.exists():
        db_path.unlink()
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email": "demo@xiantu.ai", "password": "Demo123456!"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        generation = client.post("/api/generations", headers=headers, json={"product": {"name": "测试樱桃", "origin": "山东", "spec": "500g", "tags": ["新鲜"]}, "usage": "hero", "style": "natural"})
        assert generation.status_code == 200
        assert len(generation.json()["assets"]) == 5
        assert client.get("/api/generations", headers=headers).json()["items"]
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
    if db_path.exists():
        db_path.unlink()
