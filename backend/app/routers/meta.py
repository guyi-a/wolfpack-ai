"""Meta / 配置类接口.

不带状态, 给前端拉"基础元数据":
  - GET /models             — 当前后端支持的所有 LLM 模型
  - GET /games/default-config — 默认开局配置 (前端 prefill)
"""

from fastapi import APIRouter

from app.agent.infra.llm_factory import _load_supported_models
from app.schemas.game import GameConfig, PlayerConfig


router = APIRouter(tags=["meta"])


@router.get(
    "/models",
    summary="后端支持的所有 LLM 模型清单",
)
def list_models() -> dict:
    """前端配置页用. 直接读 app/agent/config/models.json."""
    return {"models": _load_supported_models()}


@router.get(
    "/games/default-config",
    response_model=GameConfig,
    summary="默认开局配置 (6 人板, 多模型混搭)",
)
def default_config() -> GameConfig:
    """默认配置展示项目"多模型混搭"卖点:
    - 1 号 狼   : deepseek-v4-pro (主力推理)
    - 2 号 女巫  : claude-opus-4-7 (claude 演神职)
    - 3 号 预言家: glm-5.1 (推理最详尽)
    - 4 号 狼   : mimo-v2.5-pro (反派多样性)
    - 5 号 村民  : deepseek-v4-flash (便宜模型演村民)
    - 6 号 村民  : deepseek-v4-pro
    - god       : deepseek-v4-pro (调度稳定)
    """
    return GameConfig(
        god_model="deepseek/deepseek-v4-pro",
        players=[
            PlayerConfig(player_id="1", role="wolf",     model="deepseek/deepseek-v4-pro"),
            PlayerConfig(player_id="2", role="witch",    model="pa/claude-opus-4-7"),
            PlayerConfig(player_id="3", role="seer",     model="zai-org/glm-5.1"),
            PlayerConfig(player_id="4", role="wolf",     model="xiaomimimo/mimo-v2.5-pro"),
            PlayerConfig(player_id="5", role="villager", model="deepseek/deepseek-v4-flash"),
            PlayerConfig(player_id="6", role="villager", model="deepseek/deepseek-v4-pro"),
        ],
    )
