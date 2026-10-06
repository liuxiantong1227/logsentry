"""LLM 客户端（含降级）。"""
import logging

from app.config import settings

log = logging.getLogger(__name__)


class LLMClient:
    """OpenAI 兼容协议的轻量封装。"""

    def __init__(self) -> None:
        self._client = None

    @property
    def available(self) -> bool:
        """是否具备调用条件。没配 Key 时业务方应走降级分支。"""
        return settings.llm_enabled

    def _get_client(self):
        """延迟初始化:没配 Key 就不 import openai,避免无谓依赖。"""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                timeout=60.0,
            )
        return self._client

    def chat(self, system: str, user: str,
             temperature: float = 0.2, max_tokens: int = 900) -> dict:
        """调用对话接口。返回统一结构,永不抛异常。"""
        if not self.available:
            return {"ok": False, "text": "", "tokens": 0, "error": "未配置 LLM_API_KEY"}
        try:
            resp = self._get_client().chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = getattr(resp, "usage", None)
            return {
                "ok": True,
                "text": resp.choices[0].message.content or "",
                "tokens": int(getattr(usage, "total_tokens", 0) or 0),
                "error": "",
            }
        except Exception as exc:
            # 关键:外部依赖异常不能把主流程带崩,统一转成结构化结果
            log.warning("LLM 调用失败: %s", exc)
            return {"ok": False, "text": "", "tokens": 0, "error": str(exc)[:200]}