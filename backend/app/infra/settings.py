"""Wolfpack 后端配置统一入口.

读取 env (含 backend/.env) 加载基础配置. 字段可以被环境变量覆盖,
便于:
  - 开发时改 .env
  - 产版时 Electron Main 注入 WOLFPACK_DATA_DIR / WOLFPACK_PORT 等

字段全部走 pydantic-settings, 类型校验 + 默认值清晰.
"""

from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


# backend/ 目录 (settings.py 在 backend/app/infra/, 上溯两级)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """全局配置.

    环境变量前缀 WOLFPACK_ (e.g. WOLFPACK_DATA_DIR / WOLFPACK_PORT),
    .env 文件位于 backend/.env (跟 LangChain 用的同一个).
    """

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="WOLFPACK_",
        extra="ignore",   # 忽略 .env 里非本类字段 (e.g. ANTHROPIC_API_KEY)
    )

    # ---- 运行模式 ----
    debug: bool = False
    # 是否打印 SQL (echo). debug=True 也默认关掉, 避免 SWR 轮询刷屏
    debug_sql: bool = False
    # 是否打印每条 HTTP 请求 (uvicorn access log)
    access_log: bool = False

    # ---- HTTP 服务 ----
    host: str = "127.0.0.1"   # 桌面 app 只听 loopback, 防止外部访问
    port: int = 8080

    # ---- CORS ----
    # 前端 Vite 默认 5173. Electron Renderer 加载 file:// 时 origin 是 null,
    # 所以加 "*" 兜底 (反正后端只听 loopback, 外部访问不到).
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "*",
        ]
    )

    # ---- 数据目录 ----
    # 开发: backend/wolfpack-data/ (gitignore)
    # 产版: Electron Main 注入 WOLFPACK_DATA_DIR 指到 user data dir
    data_dir: Path = Field(default=_BACKEND_DIR / "wolfpack-data")

    @computed_field
    @property
    def db_path(self) -> Path:
        return self.data_dir / "wolfpack.db"

    @computed_field
    @property
    def database_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @computed_field
    @property
    def replays_dir(self) -> Path:
        return self.data_dir / "replays"

    def ensure_dirs(self) -> None:
        """创建 data_dir + 子目录 (服务启动时调一次)."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.replays_dir.mkdir(parents=True, exist_ok=True)


# 单例模式: 全局共享一份配置
settings = Settings()


if __name__ == "__main__":
    print(f"data_dir     : {settings.data_dir}")
    print(f"db_path      : {settings.db_path}")
    print(f"database_url : {settings.database_url}")
    print(f"replays_dir  : {settings.replays_dir}")
    print(f"host         : {settings.host}")
    print(f"port         : {settings.port}")
    print(f"debug        : {settings.debug}")
    settings.ensure_dirs()
    print(f"\n✓ 目录已确保创建")
