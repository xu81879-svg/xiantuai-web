from __future__ import annotations

import base64
from io import BytesIO
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image, ImageOps


class QwenError(RuntimeError):
    """A safe, user-facing error raised when a Qwen request fails."""


def _env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def qwen_api_key() -> str:
    return _env("QWEN_API_KEY", "")


def qwen_base_url() -> str:
    return _env("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")


def qwen_image_base_url() -> str:
    configured = _env("QWEN_IMAGE_BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    base = qwen_base_url()
    if base.endswith("/compatible-mode/v1"):
        return base.removesuffix("/compatible-mode/v1") + "/api/v1"
    return base


def qwen_vision_model() -> str:
    return _env("QWEN_MULTIMODAL_MODEL", _env("QWEN_VISION_MODEL", "qwen3-vl-plus"))


def qwen_image_model() -> str:
    return _env("QWEN_IMAGE_MODEL", "qwen-image-2.0-pro")


def qwen_image_edit_model() -> str:
    return _env("QWEN_IMAGE_EDIT_MODEL", qwen_image_model())


def qwen_image_negative_prompt() -> str:
    return _env(
        "QWEN_IMAGE_NEGATIVE_PROMPT",
        "低清晰度，模糊，噪点，过度锐化，过饱和，塑料感，蜡像感，CGI，卡通，商品变形，重复商品，多个主体，悬浮，错误透视，脏乱背景，廉价促销海报，爆炸贴，贴纸，边框，水印，Logo，品牌标识，任何文字，乱码，英文装饰字，画面被裁切，过度阴影",
    )[:500]


def qwen_timeout() -> float:
    try:
        return max(5.0, float(_env("QWEN_TIMEOUT_SECONDS", "45")))
    except ValueError:
        return 45.0


def qwen_read_timeout() -> float:
    try:
        return max(30.0, float(_env("QWEN_READ_TIMEOUT_SECONDS", str(qwen_timeout()))))
    except ValueError:
        return qwen_timeout()


def is_qwen_configured() -> bool:
    return bool(qwen_api_key())


def allow_mock_fallback() -> bool:
    default = "false" if _env("ENVIRONMENT", "development") == "production" else "true"
    return _env("QWEN_MOCK_FALLBACK", default).lower() == "true"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {qwen_api_key()}",
        "Content-Type": "application/json",
    }


def _request_json(method: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            timeout = httpx.Timeout(qwen_read_timeout(), connect=10.0, write=30.0, pool=10.0)
            response = httpx.request(method, url, headers=_headers(), json=payload, timeout=timeout)
            response.raise_for_status()
            body = response.json()
            break
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:500].replace("\n", " ")
            raise QwenError(f"HTTP {exc.response.status_code}: {detail}") from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (2**attempt))
                continue
            raise QwenError(f"千问网络请求失败：{exc}") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise QwenError(str(exc)) from exc
    else:
        raise QwenError(f"千问网络请求失败：{last_error}")
    if not isinstance(body, dict):
        raise QwenError("千问返回格式不是 JSON 对象")
    if body.get("code") and body.get("message"):
        raise QwenError(f"{body['code']}: {body['message']}")
    return body


def _data_url(path: Path, suffix: str) -> str:
    """Compress the vision input without changing the stored original upload."""
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=85, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"
    except (OSError, ValueError) as exc:
        raise QwenError("商品图片无法读取或压缩") from exc


def _json_from_text(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
        if not match:
            raise QwenError("千问视觉识别结果不是有效 JSON")
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise QwenError("千问视觉识别结果不是有效 JSON") from exc
    if not isinstance(parsed, dict):
        raise QwenError("千问视觉识别结果结构不正确")
    return parsed


def recognize_product(image_path: Path, suffix: str) -> dict[str, Any]:
    """Use Qwen-VL through DashScope's OpenAI-compatible vision endpoint."""
    payload = {
        "model": qwen_vision_model(),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "识别这张生鲜商品图片，只返回 JSON，不要 Markdown。字段必须包含："
                            "name（商品名称）、origin（产地）、spec（规格）、tags（4个以内卖点标签数组）。"
                            "无法确定的字段使用空字符串。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": _data_url(image_path, suffix)}},
                ],
            }
        ],
        "temperature": 0.1,
    }
    body = _request_json("POST", f"{qwen_base_url()}/chat/completions", payload)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QwenError("千问视觉接口返回缺少识别内容") from exc
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    if not isinstance(content, str):
        raise QwenError("千问视觉接口返回内容类型不正确")
    result = _json_from_text(content)
    tags = result.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return {
        "name": str(result.get("name") or "生鲜商品"),
        "origin": str(result.get("origin") or ""),
        "spec": str(result.get("spec") or ""),
        "tags": [str(tag) for tag in tags[:4]],
    }


def generate_image(product_name: str, origin: str, spec: str, usage: str, style: str, tone: str = "fresh", composition: str = "center", background: str = "clean", platform: str = "taobao", reference_image: Path | None = None) -> str:
    """Generate from text, or edit a supplied product image while preserving its identity."""
    usage_direction = {
        "hero": "正方形电商主图，商品完整可见，占画面约 70%，主体清晰突出，四周保留均衡留白",
        "detail": "详情页质感特写，靠近商品表现表皮纹理、汁水和新鲜度，背景干净，不切断商品关键部位",
        "promo": "节奏明快但克制的商业摄影，商品仍是唯一主角，使用色彩或道具营造节庆感，不使用促销贴纸",
        "social": "自然的生活方式摄影，场景真实、有呼吸感，商品清晰突出，像高端生活方式杂志而不是广告传单",
        "share": "真实温暖的分享场景，光线自然，画面简洁有生活感，商品保持清晰和可识别",
        "all": "整套素材的统一主视觉，使用稳定的品牌商业摄影语言，画面干净、真实、克制",
    }
    style_direction = {
        "natural": "自然生鲜商业摄影，清透日光，真实色彩，突出新鲜和水润质感",
        "premium": "高端精品商业摄影，柔和侧光，精致材质，低饱和高级配色，细节锐利但不生硬",
        "japanese": "清新日系杂志摄影，柔和漫射光，米白和浅木色背景，留白充足，轻盈自然",
        "farm": "可信的产地自然摄影，真实农场或果园环境，光线自然，避免夸张风景和人工合成感",
        "sale": "高级节庆商业摄影，色彩有吸引力但不过饱和，道具少而精，避免廉价促销视觉",
    }
    tone_direction = {
        "fresh": "清新、明亮、真实",
        "premium": "沉稳、精致、高级",
        "warm": "温暖、亲切、自然",
        "sale": "醒目、有节奏、但仍然高级",
    }
    composition_direction = {
        "center": "主体居中，视觉重心稳定，轮廓完整",
        "rule-of-thirds": "三分构图，主体偏向一侧，画面平衡且有自然留白",
        "close-up": "近景特写，强调真实材质、纹理和光泽",
        "flat-lay": "整洁的俯拍平铺，元素数量少，层次清楚，避免杂乱",
    }
    background_direction = {
        "clean": "纯净的浅色摄影背景或柔和渐变背景",
        "farm": "真实、克制的产地环境，背景自然虚化",
        "table": "干净的餐桌生活场景，少量天然材质道具",
        "festival": "简洁的节日氛围背景，少量高级装饰，不喧宾夺主",
    }
    product_facts = [fact.strip() for fact in (product_name, origin, spec) if fact and fact.strip()]
    fact_text = "、".join(product_facts) if product_facts else "优质生鲜商品"
    prompt = (
        "你是一名顶级食品商业摄影师和电商视觉总监。"
        f"请为‘{fact_text}’生成一张真实、高级、可直接用于电商的商品摄影图。"
        f"用途要求：{usage_direction.get(usage, usage_direction['hero'])}。"
        f"风格要求：{style_direction.get(style, style_direction['natural'])}。"
        f"气质：{tone_direction.get(tone, tone_direction['fresh'])}；"
        f"构图：{composition_direction.get(composition, composition_direction['center'])}；"
        f"背景：{background_direction.get(background, background_direction['clean'])}；"
        f"渠道审美：{platform}。"
        "产品必须是画面唯一主角，形状、大小、颜色、成熟度和表面纹理要自然可信；使用专业摄影的柔和主光、真实阴影、清晰细节和自然景深。"
        "整体应像真实相机拍摄的高端食品广告，避免 3D 渲染、塑料质感、过度磨皮、过饱和和廉价滤镜。"
        "画面内绝对不要生成任何文字、数字、字母、Logo、品牌标识、水印、价格、标签或装饰性字体；所有标题和商品信息由网页界面后期叠加。"
        "不要添加未提供的卖点、产地、规格、包装承诺或夸张道具；不要复制商品，不要出现多个主商品，不要让主体漂浮或被裁切。"
    )
    content: list[dict[str, str]] = []
    if reference_image:
        if not reference_image.is_file():
            raise QwenError("商品参考图不存在")
        content.append({"image": _data_url(reference_image, reference_image.suffix.lower())})
        prompt = (
            "第一张输入图片是用户上传的真实商品图，必须把它作为唯一且权威的商品参考。"
            "严格保留商品的品种、数量、外形轮廓、比例、颜色、成熟度、表皮纹理、连接关系和所有可见细节；"
            "不要重新想象商品，不要替换成相似商品，不要改变商品身份。只允许改变摄影环境、光线、构图和少量不遮挡商品的天然道具。"
            "商品必须保持完整可识别，不能被裁切、变形、重复或添加包装。"
            + prompt
        )
    content.append({"text": prompt})
    payload = {
        "model": qwen_image_edit_model() if reference_image else qwen_image_model(),
        "input": {"messages": [{"role": "user", "content": content}]},
        "parameters": {
            "negative_prompt": qwen_image_negative_prompt(),
            "prompt_extend": False,
            "watermark": False,
            "size": _env("QWEN_IMAGE_SIZE", "1024*1024"),
        },
    }
    body = _request_json(
        "POST",
        f"{qwen_image_base_url()}/services/aigc/multimodal-generation/generation",
        payload,
    )
    try:
        content = body["output"]["choices"][0]["message"]["content"]
        image_url = content[0]["image"]
    except (KeyError, IndexError, TypeError) as exc:
        raise QwenError("千问生图接口返回缺少图片地址") from exc
    if not isinstance(image_url, str) or not image_url.startswith(("http://", "https://")):
        raise QwenError("千问生图接口返回了无效图片地址")
    return image_url


def persist_remote_image(image_url: str, upload_dir: Path) -> str:
    """Download Qwen's expiring URL into the application's durable upload path."""
    try:
        response = httpx.get(image_url, timeout=qwen_timeout())
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise QwenError(f"生成图片下载失败: {exc}") from exc
    filename = f"qwen-{uuid4().hex}.png"
    target = upload_dir / filename
    target.write_bytes(response.content)
    return f"/uploads/{filename}"
