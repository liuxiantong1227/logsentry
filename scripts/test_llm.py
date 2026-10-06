"""一次性测试:验证大模型 API 是否连通。

用法:
    python scripts/test_llm.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

from app.config import settings


def main() -> int:
    if not settings.llm_enabled:
        print("未配置 LLM_API_KEY,请检查项目根目录的 .env 文件")
        return 1

    print("base_url :", settings.llm_base_url)
    print("model    :", settings.llm_model)
    print("正在调用大模型 ...\n")

    client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    try:
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": "你是一个简洁的助手,回答控制在两句话以内。"},
                {"role": "user", "content": "用一句话解释什么是 P95 延迟。"},
            ],
            temperature=0.2,
            max_tokens=100,
        )
    except Exception as exc:
        print("调用失败:", type(exc).__name__)
        print("   ", exc)
        return 1

    print("=== AI 回复 ===")
    print(resp.choices[0].message.content)
    print("\n=== token 用量 ===")
    print("  输入 prompt_tokens     :", resp.usage.prompt_tokens)
    print("  输出 completion_tokens :", resp.usage.completion_tokens)
    print("  合计 total_tokens      :", resp.usage.total_tokens)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())