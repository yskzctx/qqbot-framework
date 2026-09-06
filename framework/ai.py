"""AI 服务：多配置管理 + OpenAI 兼容全接口调用。

面板「AI 配置」可创建多个配置（不同厂商/模型），任意切换激活。
模块内调用：
    reply = await bot.app.ai.chat([...])                    # 对话（支持图片视觉，见下）
    path  = await bot.app.ai.tts("你好")                    # 文字转语音 -> 本地文件
    urls  = await bot.app.ai.images("一只猫")               # 文生图 -> URL 列表
    data  = await bot.app.ai.raw("embeddings", {...})       # 任意 /v1/ 端点透传

图片（视觉）用法——chat 的 content 直接用段结构，透传给模型：
    await bot.app.ai.chat([{
        "role": "user",
        "content": [
            {"type": "text", "text": "这张图里是什么"},
            {"type": "image_url", "image_url": {"url": "https://.../pic.jpg"}}
        ]}])
需要模型本身支持视觉（如 gpt-4o、glm-4v 等），框架不做限制。
"""
import base64
import logging
import os
import time

import aiohttp

log = logging.getLogger("ai")


class AIService:
    def __init__(self, app):
        self.app = app

    # ---------- 配置 ----------

    @property
    def cfg(self) -> dict:
        return self.app.config["ai"]

    def profiles(self) -> dict:
        return self.cfg.get("profiles", {})

    def active_name(self) -> str:
        return self.cfg.get("active", "")

    def active(self) -> dict:
        return self.profiles().get(self.active_name(), {})

    def ready(self) -> bool:
        p = self.active()
        return bool(p.get("api_base") and p.get("api_key") and p.get("model"))

    def profile_names(self) -> list:
        """全部 AI 配置名列表（供模块/面板做选择）。"""
        return list(self.profiles().keys())

    def profile_ready(self, name: str) -> bool:
        p = self.profiles().get(name, {})
        return bool(p.get("api_base") and p.get("api_key") and p.get("model"))

    # ---------- 核心调用 ----------

    def _url(self, endpoint: str, profile: dict) -> str:
        base = (profile.get("api_base") or "").rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/{endpoint}"
        return f"{base}/v1/{endpoint}"

    @staticmethod
    def _headers(profile: dict) -> dict:
        return {"Authorization": f"Bearer {profile.get('api_key', '')}",
                "Content-Type": "application/json"}

    def _require_ready(self, profile: dict):
        if not (profile.get("api_base") and profile.get("api_key") and profile.get("model")):
            raise RuntimeError("当前 AI 配置不完整：请在面板「AI 配置」填写 API 地址、密钥和模型 ID")

    async def chat(self, messages: list, temperature: float | None = None,
                   max_tokens: int | None = None, model: str | None = None,
                   profile: str | None = None) -> str:
        """对话。messages 支持 OpenAI 全格式（含图片视觉的段结构，透传给模型）。

        profile: 指定使用哪个 AI 配置（缺省用激活配置）——
                 模块可让每个功能各自选择不同的 AI。
        """
        p = dict(self.profiles().get(profile or "", {}) or self.active())
        if profile and profile not in self.profiles():
            raise RuntimeError(f"AI 配置 '{profile}' 不存在（可用: {', '.join(self.profile_names())}）")
        if model:
            p["model"] = model
        self._require_ready(profile)
        payload = {"model": p["model"], "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        data = await self._post(p, "chat/completions", payload)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise RuntimeError(f"AI 接口返回格式异常: {str(data)[:300]}")

    async def tts(self, text: str, voice: str = "alloy", speed: float = 1.0) -> str:
        """文字转语音（/v1/audio/speech），返回本地音频文件路径（mp3）。

        模块拿到路径后可通过 send_record / send_group_record 发送语音。
        """
        profile = self.active()
        self._require_ready(profile)
        payload = {"model": profile["model"], "input": text, "voice": voice, "speed": speed}
        data = await self._post_raw(profile, "audio/speech", payload)
        path = os.path.join(self.app.module_data_dir("ai_tts"),
                            f"tts_{int(time.time() * 1000)}.mp3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    async def images(self, prompt: str, n: int = 1, size: str = "1024x1024") -> list:
        """文生图（/v1/images/generations），返回 URL（或 b64）列表。"""
        profile = self.active()
        self._require_ready(profile)
        data = await self._post(profile, "images/generations",
                                {"model": profile["model"], "prompt": prompt, "n": n, "size": size})
        out = []
        for item in data.get("data", []):
            out.append(item.get("url") or
                       ("base64://" + item["b64_json"] if item.get("b64_json") else None))
        return [u for u in out if u]

    async def raw(self, endpoint: str, payload: dict) -> dict:
        """任意 /v1/ 端点透传（embeddings、moderations、audio/transcriptions 等）。"""
        profile = self.active()
        self._require_ready(profile)
        return await self._post(profile, endpoint.lstrip("/"), payload)

    # ---------- 底层 ----------

    async def _post(self, profile: dict, endpoint: str, payload: dict) -> dict:
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._url(endpoint, profile), json=payload,
                                    headers=self._headers(profile)) as resp:
                text = await resp.text()
                if resp.status != 200:
                    raise RuntimeError(f"AI 接口返回 {resp.status}: {text[:300]}")
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    raise RuntimeError(f"AI 接口返回非 JSON: {text[:300]}")

    async def _post_raw(self, profile: dict, endpoint: str, payload: dict) -> bytes:
        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._url(endpoint, profile), json=payload,
                                    headers=self._headers(profile)) as resp:
                body = await resp.read()
                if resp.status != 200:
                    raise RuntimeError(f"AI 接口返回 {resp.status}: {body[:300]}")
                return body
