from pathlib import Path

from PIL import Image

from app import qwen


def test_vision_model_prefers_multimodal_alias(monkeypatch):
    monkeypatch.setenv("QWEN_VISION_MODEL", "qwen3-vl-plus")
    monkeypatch.setenv("QWEN_MULTIMODAL_MODEL", "qwen3.8-max")
    assert qwen.qwen_vision_model() == "qwen3.8-max"


def test_data_url_is_jpeg_and_downscaled(tmp_path: Path):
    source = tmp_path / "large.png"
    Image.new("RGBA", (2400, 1800), (220, 40, 40, 255)).save(source)
    data_url = qwen._data_url(source, ".png")
    assert data_url.startswith("data:image/jpeg;base64,")


def test_recognize_product_uses_multimodal_model_and_normalizes_result(monkeypatch, tmp_path: Path):
    source = tmp_path / "product.jpg"
    Image.new("RGB", (320, 240), (220, 40, 40)).save(source)
    monkeypatch.setenv("QWEN_MULTIMODAL_MODEL", "qwen3.8-flash")
    captured = {}

    def fake_request(method, url, payload):
        captured.update({"method": method, "url": url, "payload": payload})
        return {"choices": [{"message": {"content": '{"name":"樱桃","tags":["新鲜","脆甜","当季","果大","多余"]}'}}]}

    monkeypatch.setattr(qwen, "_request_json", fake_request)
    result = qwen.recognize_product(source, ".jpg")
    assert captured["payload"]["model"] == "qwen3.8-flash"
    assert result == {"name": "樱桃", "origin": "", "spec": "", "tags": ["新鲜", "脆甜", "当季", "果大"]}
