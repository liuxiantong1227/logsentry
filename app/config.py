"""配置（全部走环境变量）。"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()        #让.env文件里的变量生效
except ImportError:    #如果dotenv库不存在，则不进行任何操作
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings:
    """项目配置。字段值优先取环境变量,取不到就用默认值。"""

    # 数据库:默认 SQLite,放在 data/ 目录下
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'logsentry.db'}"
    )

    # 大模型配置(OpenAI 兼容协议)
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    # 注意:环境变量"存在但为空"时,getenv 的默认值不会生效,
    # 所以这里用 `or` 兜底,保证 .env 里留空的变量能回退到默认值
    llm_base_url: str = os.getenv("LLM_BASE_URL") or "https://api.deepseek.com/v1"
    llm_model: str = os.getenv("LLM_MODEL") or "deepseek-chat"

    # 异常检测:超过基线多少倍就告警
    anomaly_ratio: float = float(os.getenv("ANOMALY_RATIO", "1.5"))

    # 定时调度开关(测试时可以关掉)
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"

    @property
    def llm_enabled(self) -> bool:
        """是否配置了大模型 Key。没配也照样能跑(会自动降级)。"""
        return bool(self.llm_api_key)


settings = Settings()

