"""AI 服务：OpenAI 兼容接口（/v1/chat/completions）。

模块内调用：
    reply = await app.ai.chat([{"role": "user", "content": "你好"}])
配置在面板「AI 配置」页填写，保存到 config.json 的 ai 段。
"""
import logging

import aiohttp

log = logging.getLogger("ai")


class AIService:
    def __init__(self, app):
        self.app = app

    @property
    def cfg(self) -> dict:
        return self.app.config["ai"]

    def ready(self) -> bool:
        return bool(self.cfg.get("api_base") and self.cfg.get("api_key") and self.cfg.get("model"))

    def _url(self) -> str:
        base = (self.cfg.get("api_base") or "").rstrip("/")
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"

    async def chat(self, messages: list, temperature: float | None = None,
                   max_tokens: int | None = None) -> str:
        """调用 OpenAI 兼容接口，返回回复文本。未配置或请求失败抛异常。"""
        if not self.ready():
            raise RuntimeError("AI 未配置：请在面板「AI 配置」填写 API 地址、密钥和模型 ID")
        payload = {
            "model": self.cfg["model"],
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {"Authorization": f"Bearer {self.cfg['api_key']}",
                   "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(self._url(), json=payload, headers=headers) as resp:
                body = await resp.json(content_type=None)
                if resp.status != 200:
                    raise RuntimeError(f"AI 接口返回 {resp.status}: {str(body)[:300]}")
                try:
                    return body["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError(f"AI 接口返回格式异常: {str(body)[:300]}")
