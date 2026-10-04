from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx


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
    return _env("QWEN_VISION_MODEL", "qwen3-vl-plus")


def qwen_image_model() -> str:
    return _env("QWEN_IMAGE_MODEL", "qwen-image-2.0-pro")


def qwen_timeout() -> float:
    try:
        return max(5.0, float(_env("QWEN_TIMEOUT_SECONDS", "45")))
    except ValueError:
        return 45.0


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
    try:
        response = httpx.request(method, url, headers=_headers(), json=payload, timeout=qwen_timeout())
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500].replace("\n", " ")
        raise QwenError(f"HTTP {exc.response.status_code}: {detail}") from exc
    except (httpx.RequestError, ValueError) as exc:
        raise QwenError(str(exc)) from exc
    if not isinstance(body, dict):
        raise QwenError("千问返回格式不是 JSON 对象")
    if body.get("code") and body.get("message"):
        raise QwenError(f"{body['code']}: {body['message']}")
    return body


def _data_url(path: Path, suffix: str) -> str:
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(suffix.lower(), "application/octet-stream")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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


def generate_image(product_name: str, origin: str, spec: str, usage: str, style: str) -> str:
    """Use Qwen-Image through DashScope's native synchronous generation endpoint."""
    prompt = (
        f"为生鲜商品‘{product_name}’制作一张中文电商视觉素材。产地：{origin or '优质产地'}；规格：{spec or '精选装'}；"
        f"用途：{usage}；风格：{style}。主体清晰、食材新鲜有水润质感，构图适合电商展示，留出简洁文字空间，"
        "不要生成虚假品牌 Logo、乱码或水印。"
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
