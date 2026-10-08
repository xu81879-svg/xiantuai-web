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


def test_generation_plan_selects_engine_by_usage():
    hero = qwen.compile_generation_plan("崂山杏", "山东·青岛崂山", "500g", ["果面光泽"], "hero")
    detail = qwen.compile_generation_plan("崂山杏", "山东·青岛崂山", "500g", ["果肉细腻"], "detail")
    promo = qwen.compile_generation_plan("崂山杏", "山东·青岛崂山", "500g", [], "promo")
    assert (hero.image_usage, hero.engine) == ("主图", "版式引擎")
    assert (detail.image_usage, detail.engine) == ("详情图", "场景引擎")
    assert (promo.image_usage, promo.engine) == ("营销图", "创意引擎")
    assert "单一 SKU" in hero.constraints


def test_quality_check_has_file_level_gate(tmp_path: Path):
    source = tmp_path / "tiny.png"
    Image.new("RGB", (128, 128), (255, 255, 255)).save(source)
    result = qwen.quality_check_image(source, "崂山杏", "hero")
    assert result["passed"] is False
    assert "512" in result["reasons"][0]


def test_recognize_product_uses_multimodal_model_and_normalizes_result(monkeypatch, tmp_path: Path):
    source = tmp_path / "product.jpg"
    Image.new("RGB", (320, 240), (220, 40, 40)).save(source)
    monkeypatch.setenv("QWEN_MULTIMODAL_MODEL", "qwen3.8-flash")
    captured = {}

    def fake_request(method, url, payload):
        captured.update({"method": method, "url": url, "payload": payload})
        return {"choices": [{"message": {"content": '{"name":"樱桃","tags":["新鲜","脆甜","当季","果大","多余"],"confidence":0.94,"evidence":"果实颜色和形态清晰"}'}}]}

    monkeypatch.setattr(qwen, "_request_json", fake_request)
    result = qwen.recognize_product(source, ".jpg")
    assert captured["payload"]["model"] == "qwen3.8-flash"
    assert result == {"name": "樱桃", "origin": "", "spec": "", "tags": ["新鲜", "脆甜", "当季", "果大"], "recognition_confidence": 0.94, "recognition_evidence": "果实颜色和形态清晰"}
    prompt = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "特别注意区分杏和桃" in prompt
    assert "杏/桃待确认" in prompt


def test_generate_apricot_prompt_emphasizes_fresh_gloss(monkeypatch):
    captured = {}

    def fake_request(method, url, payload):
        captured["payload"] = payload
        return {"output": {"choices": [{"message": {"content": [{"type": "image", "image": "https://example.com/apricot.png"}]}}]}}

    monkeypatch.setattr(qwen, "_request_json", fake_request)
    qwen.generate_image("崂山杏", "山东·青岛崂山", "500g", "hero", "natural")
    prompt = captured["payload"]["input"]["messages"][0]["content"][0]["text"]
    assert "清透光泽与新鲜感" in prompt
    assert "不能变成蜡质塑料反光" in prompt
    assert "极轻薄且均匀的天然绒毛" in prompt
    assert "黄橙色细腻果肉" in prompt


def test_generate_image_uses_controlled_commercial_prompt(monkeypatch):
    captured = {}

    def fake_request(method, url, payload):
        captured.update({"method": method, "url": url, "payload": payload})
        return {"output": {"choices": [{"message": {"content": [{"image": "https://example.com/generated.png"}]}}]}}

    monkeypatch.setenv("QWEN_IMAGE_MODEL", "qwen-image-2.0-pro")
    monkeypatch.setattr(qwen, "_request_json", fake_request)

    image_url = qwen.generate_image("崂山大樱桃", "山东·青岛崂山", "500g", "hero", "natural")

    parameters = captured["payload"]["parameters"]
    prompt = captured["payload"]["input"]["messages"][0]["content"][0]["text"]
    assert image_url == "https://example.com/generated.png"
    assert parameters["prompt_extend"] is False
    assert "negative_prompt" in parameters
    assert "绝对不要生成任何文字" in prompt
    assert "产品必须是画面唯一主角" in prompt
    assert "圆润体积与立体感" in prompt
    assert "接触阴影" in prompt
    assert "电商主图硬约束" in prompt
    assert "无缝纯白或极浅灰背景" in prompt
    assert "不得切开水果" in prompt
    assert "圆润体积与立体感" in prompt


def test_generate_image_uses_uploaded_reference_for_product_fidelity(monkeypatch, tmp_path: Path):
    source = tmp_path / "uploaded-product.jpg"
    Image.new("RGB", (640, 480), (220, 40, 40)).save(source)
    captured = {}

    def fake_request(method, url, payload):
        captured.update({"method": method, "url": url, "payload": payload})
        return {"output": {"choices": [{"message": {"content": [{"image": "https://example.com/edited.png"}]}}]}}

    monkeypatch.setenv("QWEN_IMAGE_EDIT_MODEL", "qwen-image-2.0-pro")
    monkeypatch.setattr(qwen, "_request_json", fake_request)

    image_url = qwen.generate_image("崂山大樱桃", "山东·青岛崂山", "500g", "hero", "premium", reference_image=source)

    content = captured["payload"]["input"]["messages"][0]["content"]
    assert captured["payload"]["model"] == "qwen-image-2.0-pro"
    assert content[0]["image"].startswith("data:image/jpeg;base64,")
    assert "唯一且权威的商品参考" in content[1]["text"]
    assert "严格保留商品的品种" in content[1]["text"]
    assert image_url == "https://example.com/edited.png"
