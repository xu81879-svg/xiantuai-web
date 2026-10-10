from pathlib import Path
import asyncio
import json

import pytest

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
    assert any("单一 SKU" in constraint for constraint in hero.constraints)
    assert hero.visual is not None and hero.visual.background == "clean"


@pytest.mark.parametrize(
    "options, expected_fragment",
    [
        ({"background": "table"}, "背景必须"),
        ({"background": "farm"}, "背景必须"),
        ({"background": "festival"}, "背景必须"),
        ({"style": "farm"}, "场景或装饰"),
        ({"style": "sale"}, "场景或装饰"),
        ({"tone": "sale"}, "促销醒目"),
        ({"composition": "flat-lay"}, "必须居中"),
    ],
)
def test_hero_visual_plan_rejects_background_and_prop_conflicts(options, expected_fragment):
    with pytest.raises(qwen.VisualPlanError, match=expected_fragment):
        qwen.select_visual_plan("hero", **options)


def test_non_hero_visual_plan_allows_scene_backgrounds():
    plan = qwen.select_visual_plan("social", style="farm", background="farm", composition="rule-of-thirds")
    assert plan.background == "farm"
    assert plan.usage_label == "营销图"
    assert "生活方式摄影" in plan.usage_direction


def test_detail_usage_direction_is_compiled_into_prompt():
    plan = qwen.compile_generation_plan("牛心柿子", "", "", [], "detail", style="premium", background="table")
    prompt = qwen.build_image_prompt("牛心柿子", ["橙红果皮"], plan)
    assert "突出经确认的商品细节" in prompt


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

    async def fake_request(method, url, payload, *, timings=None):
        captured.update({"method": method, "url": url, "payload": payload})
        if timings is not None:
            timings["model_attempts"] = 1
        return {"choices": [{"message": {"content": '{"name":"樱桃","tags":["新鲜","脆甜","当季","果大","多余"],"confidence":0.94,"evidence":"果实颜色和形态清晰"}'}}]}

    monkeypatch.setattr(qwen, "_arequest_json", fake_request)
    result = asyncio.run(qwen.recognize_product(source, ".jpg"))
    assert captured["payload"]["model"] == "qwen3.8-flash"
    assert result == {"name": "樱桃", "origin": "", "spec": "", "tags": ["新鲜", "脆甜", "当季", "果大"], "recognition_confidence": 0.94, "recognition_evidence": "果实颜色和形态清晰"}
    prompt = captured["payload"]["messages"][0]["content"][0]["text"]
    assert "杏桃专属鉴别" in prompt
    assert "负向权重" in prompt
    assert "杏/桃待确认" in prompt


def test_async_recognition_request_retries_transient_network_error_once(monkeypatch):
    calls = []
    delays = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class AsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def request(self, *_args, **_kwargs):
            calls.append(1)
            if len(calls) == 1:
                raise qwen.httpx.ConnectError("temporary network failure")
            return Response()

    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(qwen.httpx, "AsyncClient", AsyncClient)
    monkeypatch.setattr(qwen, "qwen_recognition_max_retries", lambda: 1)
    monkeypatch.setattr(qwen, "qwen_recognition_timeout", lambda: 30.0)
    monkeypatch.setattr(qwen.asyncio, "sleep", fake_sleep)
    timings = {}

    body = asyncio.run(qwen._arequest_json("POST", "https://qwen.test", {}, timings=timings))

    assert body == {"ok": True}
    assert len(calls) == 2
    assert delays == [0.25]
    assert timings["model_attempts"] == 2


def test_recognize_product_caps_unsupported_peach_confidence(monkeypatch, tmp_path: Path):
    source = tmp_path / "apricot.jpg"
    Image.new("RGB", (320, 240), (220, 120, 40)).save(source)

    async def fake_request(*args, **kwargs):
        return {"choices": [{"message": {"content": '{"name":"桃子","confidence":0.92,"evidence":"橙黄色圆形果实"}'}}]}

    monkeypatch.setattr(qwen, "_arequest_json", fake_request)
    result = asyncio.run(qwen.recognize_product(source, ".jpg"))
    assert result["recognition_confidence"] == 0.55
    assert "证据不足" in result["recognition_evidence"]


def test_recognize_product_keeps_peach_confidence_with_specific_evidence(monkeypatch, tmp_path: Path):
    source = tmp_path / "peach.jpg"
    Image.new("RGB", (320, 240), (220, 120, 40)).save(source)

    async def fake_request(*args, **kwargs):
        return {"choices": [{"message": {"content": '{"name":"桃子","confidence":0.92,"evidence":"密集绒毛、深长果缝和扁圆肩部"}'}}]}

    monkeypatch.setattr(qwen, "_arequest_json", fake_request)
    result = asyncio.run(qwen.recognize_product(source, ".jpg"))
    assert result["recognition_confidence"] == 0.92


def test_generate_apricot_prompt_emphasizes_fresh_gloss(monkeypatch):
    captured = {}

    def fake_request(method, url, payload):
        captured["payload"] = payload
        return {"output": {"choices": [{"message": {"content": [{"type": "image", "image": "https://example.com/apricot.png"}]}}]}}

    monkeypatch.setattr(qwen, "_request_json", fake_request)
    qwen.generate_image("崂山杏", "山东·青岛崂山", "500g", "hero", "natural")
    prompt = captured["payload"]["input"]["messages"][0]["content"][0]["text"]
    assert "真实细腻果皮" in prompt
    assert "轻微天然绒毛" in prompt
    assert "蜡质塑料反光" in prompt


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
    assert "绝不渲染任何文字" in prompt
    assert "产品必须是画面唯一主角" in prompt
    assert "圆润体积与立体感" in prompt
    assert "接触阴影" in prompt
    assert "电商主图硬约束" in prompt
    assert "纯白或极浅灰" in prompt
    assert "不得切开" in prompt
    assert "主体底部保留自然接触阴影" in prompt
    assert "产品必须是画面唯一主角" in prompt
    assert "山东·青岛崂山" not in prompt and "500g" not in prompt


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
    assert "权威商品参考" in content[1]["text"]
    assert "保持商品身份、数量、轮廓" in content[1]["text"]
    assert image_url == "https://example.com/edited.png"


def test_generate_image_prompt_does_not_mix_hero_with_table_props(monkeypatch):
    with pytest.raises(qwen.VisualPlanError, match="背景必须"):
        qwen.generate_image("牛心柿子", "青岛", "2500g", "hero", "natural", background="table")


def test_quality_check_fails_closed_when_vision_is_unavailable(monkeypatch, tmp_path: Path):
    source = tmp_path / "valid.png"
    Image.new("RGB", (512, 512), (240, 240, 240)).save(source)
    monkeypatch.setattr(qwen, "is_qwen_configured", lambda: False)
    result = qwen.quality_check_image(source, "牛心柿子", "hero")
    assert result["passed"] is False
    assert "vision_qa_unavailable" in result["hard_failures"]


def test_quality_check_requires_every_hard_check_to_be_literal_true(monkeypatch, tmp_path: Path):
    source = tmp_path / "valid.png"
    Image.new("RGB", (512, 512), (240, 240, 240)).save(source)
    monkeypatch.setattr(qwen, "is_qwen_configured", lambda: True)
    plan = qwen.compile_generation_plan("牛心柿子", "", "", [], "hero")
    assert plan.visual is not None
    good = {key: True for key in plan.visual.hard_checks}
    good.update({"passed": True, "reasons": []})
    monkeypatch.setattr(qwen, "_request_json", lambda *args: {"choices": [{"message": {"content": json.dumps(good, ensure_ascii=False)}}]})
    accepted = qwen.quality_check_image(source, "牛心柿子", "hero", plan=plan)
    assert accepted["passed"] is True

    bad = dict(good)
    bad["forbidden_props_absent"] = False
    monkeypatch.setattr(qwen, "_request_json", lambda *args: {"choices": [{"message": {"content": json.dumps(bad, ensure_ascii=False)}}]})
    rejected = qwen.quality_check_image(source, "牛心柿子", "hero", plan=plan)
    assert rejected["passed"] is False
    assert "forbidden_props_absent" in rejected["hard_failures"]


def test_quality_check_does_not_truthify_string_false(monkeypatch, tmp_path: Path):
    source = tmp_path / "valid.png"
    Image.new("RGB", (512, 512), (240, 240, 240)).save(source)
    monkeypatch.setattr(qwen, "is_qwen_configured", lambda: True)
    plan = qwen.compile_generation_plan("牛心柿子", "", "", [], "hero")
    response = {key: True for key in plan.visual.hard_checks}
    response.update({"passed": "false", "reasons": []})
    monkeypatch.setattr(qwen, "_request_json", lambda *args: {"choices": [{"message": {"content": json.dumps(response)}}]})
    result = qwen.quality_check_image(source, "牛心柿子", "hero", plan=plan)
    assert result["passed"] is False
