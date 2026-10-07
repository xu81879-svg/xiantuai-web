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


def generate_image(product_name: str, origin: str, spec: str, usage: str, style: str, tone: str = "fresh", composition: str = "center", background: str = "clean", platform: str = "taobao") -> str:
    """Use Qwen-Image through DashScope's native synchronous generation endpoint."""
    layout_by_usage = {
        "hero": "电商主图：商品占画面约 65%，主体完整且有呼吸感，右侧或右上保留干净文字安全区",
        "detail": "详情页卖点图：以食材质感和局部细节为主，文字只做小型信息标注，不要堆叠段落",
        "promo": "活动素材：保持高级留白，促销信息仅作为小面积辅助层，不使用夸张爆炸贴和满版大字",
        "social": "社交媒体种草图：生活方式场景为主，文字轻量、克制、像杂志标题",
        "share": "朋友圈分享图：自然真实的商品场景，最多一组简短标题，避免广告传单感",
        "all": "整套素材中的主视觉：统一品牌摄影风格，画面简洁，信息分层而不是文字堆叠",
    }
    layout_direction = layout_by_usage.get(usage, layout_by_usage["hero"])
    product_facts = [fact for fact in (product_name, origin, spec) if fact]
    fact_text = "；".join(product_facts) if product_facts else "优质生鲜商品"
    prompt = (
        f"为‘{fact_text}’制作一张高端亚洲生鲜电商视觉素材。"
        f"用途：{usage}；风格：{style}；画面气质：{tone}；构图：{composition}；背景：{background}；发布渠道：{platform}。"
        f"{layout_direction}。"
        "这是品牌电商摄影与编辑排版，不是促销海报、传单或拼贴图。产品是唯一主角，优先呈现真实形状、成熟度、纹理和水润质感；"
        "采用现代中文无衬线字体、深灰或深绿色文字，字重中等，字号克制，行距舒适，统一左对齐，四周至少保留 8% 安全边距。"
        "画面文字最多 3 行：第一行只能是商品名称，第二、三行只能使用已提供的产地或规格；文字区域不超过画面 18%，不能压住商品，不能使用超大粗体。"
        "严禁自行编造‘直发’‘新鲜采摘’‘净重’‘爆甜’‘限时特惠’等未提供的卖点、数字或承诺；缺少信息时宁可不放文字。"
        "不要生成 Logo、价格标签、贴纸、爆炸框、边框、水印、乱码、英文装饰字或多组重复文案。"
    )
    payload = {
        "model": qwen_image_model(),
        "input": {"messages": [{"role": "user", "content": [{"text": prompt}]}]},
        "parameters": {
            "prompt_extend": True,
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
