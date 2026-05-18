"""LLM 工厂: 按模型名返回 LangChain ChatAnthropic 实例.

所有模型统一走 Novita 的 anthropic 兼容协议 (env: backend/.env).
支持的模型清单维护在 app/agent/config/models.json,
新增模型只需在 json 的 models 列表加一条,无需改代码.
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic

_THIS_DIR = Path(__file__).resolve().parent          # backend/app/agent/infra
_AGENT_DIR = _THIS_DIR.parent                        # backend/app/agent
_BACKEND_DIR = _THIS_DIR.parent.parent.parent        # backend
_ENV_PATH = _BACKEND_DIR / ".env"
_MODELS_CONFIG = _AGENT_DIR / "config" / "models.json"

load_dotenv(_ENV_PATH)


def _load_supported_models() -> list[str]:
    with open(_MODELS_CONFIG, encoding="utf-8") as f:
        return json.load(f)["models"]


def get_chat_model(model_name: str, **kwargs) -> ChatAnthropic:
    """按模型名返回 LangChain ChatAnthropic, 走 Novita anthropic 协议.

    Args:
        model_name: 模型 ID, 必须在 app/agent/config/models.json 的 models 列表里.
        **kwargs: 透传给 ChatAnthropic 构造器 (temperature / max_tokens 等).
    """
    supported = _load_supported_models()
    if model_name not in supported:
        raise ValueError(
            f"未知模型 {model_name!r}. 已配置: {supported}. "
            f"请先在 {_MODELS_CONFIG.relative_to(_BACKEND_DIR)} 添加."
        )
    return ChatAnthropic(
        model=model_name,
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ["ANTHROPIC_BASE_URL"],
        **kwargs,
    )


if __name__ == "__main__":
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"):
        v = os.environ.get(k)
        if not v:
            raise SystemExit(f"缺少 env {k} (检查 {_ENV_PATH})")
        shown = "***" + v[-6:] if "KEY" in k else v
        print(f"  {k:22s} = {shown}")
    print(f"  models.json: {_load_supported_models()}")
