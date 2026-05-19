# Wolfpack AI

> 一个**AI 狼人杀对局观测台** — 用不同的 LLM 模型扮演狼、预言家、女巫、村民, 实时观看它们的发言、思考过程和工具调用. 信息密度比传统狼人杀 app 高一档, 主战场是"看 AI 互相欺骗".

## 核心特性

### 多 Agent 博弈
- **完整对局闭环** — 狼夜商量 / 预言家查验 / 女巫救毒 / 白天发言 / 投票 / 遗言
- **God 即 Supervisor** — LLM 上帝以 Phase 粒度调度对局, 所有 phase 通过工具调用触发
- **信息隔离** — 每个 Player 有独立 history; wolf_chat / lovers 等 Channel 自带成员名单, 谁能看什么由 Channel 决定
- **6 人板默认配置** — 2 狼 + 1 预言家 + 1 女巫 + 2 村民, 角色/模型一对一可配

### 多模型混搭
统一走 Novita 的 Anthropic 兼容端点, 同一局可让不同 player 用不同模型:

| 模型 | 特点 |
|---|---|
| `deepseek/deepseek-v4-pro` | 主力推理, thinking block 表现稳 |
| `deepseek/deepseek-v4-flash` | 便宜快, 适合村民/狼 |
| `pa/claude-opus-4-7` | 推理藏在 text 里, 适合神职 |
| `zai-org/glm-5.1` | 推理最详尽, 适合预言家 |
| `xiaomimimo/mimo-v2.5-pro` | (暂未默认启用, 工具调用偶尔 400) |

### 实时事件流 (SSE)
对局事件 + Player 内心状态全部走同一条 SSE:

| 事件类型 | 触发 |
|---|---|
| `phase_change` | 阶段切换 (night_start / wolf_night / day_speech / ...) |
| `speech` / `vote` / `vote_result` / `night_result` / `last_words` / `game_end` | 业务事件 |
| `player_state` | Player 状态变化 (thinking / tool_calling / idle) |
| `token_chunk` | 真打字机 token-level 流 |
| `inner_view` | act 跑完一次性汇总 thinking + tool_calls + text |

### 完整复盘
对局结束后, 每个 player + god 的完整 LLM history (含 thinking / tool_calls / tool_result) 归档到 SQLite, 提供 REST endpoint 复盘:
- `GET /games/{id}/events` — 公开事件流
- `GET /games/{id}/players/{pid}/history` — 某 player 内心戏
- `GET /games/{id}/histories` — 上帝视角 (含 god 调度日志)

## 技术栈

### 后端 (已实现)
- **FastAPI + uvicorn** — Web 框架
- **LangChain + LangGraph** — `create_agent` 编译图, 走 `astream_events` 拿 token 级事件
- **SQLAlchemy 2.0 async + alembic** — SQLite 持久化, migration 接管 schema
- **pydantic-settings** — 配置统一入口
- **EventBus (asyncio.Queue)** — 进程内 pub/sub, SSE 端点订阅
- **loguru** — 日志

### 前端 (规划中)
- **Vite + React 19 + TypeScript**
- **Tailwind 4 + radix-ui** (shadcn)
- **Zustand** (多 store) + **react-router 7**
- **motion / lucide-react / sonner / use-stick-to-bottom / react-markdown**
- 视觉调性: **博弈室 × 实验室仪表盘** (暗调炭灰 + 狼血红/烛火金/月光青强调色, Fraunces 衬线 + JetBrains Mono)

### 交付形态
- **Electron 桌面应用** (参考 krow-app)
- 后端打包: **Nuitka** 出单文件 binary, electron-builder `extraResources` 塞进 .dmg/.exe

## 快速开始

### 环境要求
- Python 3.12+
- macOS / Linux / Windows
- Novita API key (https://novita.ai/)

### 一键启动

```bash
git clone https://github.com/guyi-a/wolfpack-ai.git
cd wolfpack-ai

# 配置 API key
cp backend/.env.example backend/.env
# 编辑 backend/.env, 填入 ANTHROPIC_API_KEY (用 Novita key)

# 一键启动 (会自动创建 venv + 装依赖 + 起后端)
./start-dev.sh        # Mac / Linux
# 或 Windows:
start-dev.bat
```

启动后访问:

| URL | 用途 |
|---|---|
| http://localhost:8080 | 后端根 |
| http://localhost:8080/docs | Swagger API 文档 |
| http://localhost:8080/healthz | 健康检查 |
| http://localhost:8080/demo/game.html | **视觉调性 demo** (静态 HTML 预览) |

### 手动启动 (开发用)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate                 # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                     # 编辑填 key
python main.py                           # 跑在 8080, DEBUG=false
# 或开发热重载:
WOLFPACK_DEBUG=true python main.py
```

## 主要 API

### 配置
- `GET /models` — 已注册的 LLM 模型清单
- `GET /games/default-config` — 默认 6 人板配置 (4 个模型混搭)

### 对局
- `POST /games` — 创建对局 (body = `GameConfig`, status=pending)
- `POST /games/{id}/start` — 启动对局 (后台异步跑)
- `GET /games` — 列出最近对局
- `GET /games/{id}` — 单局详情 (含 players)

### 事件流
- `GET /games/{id}/stream` — **SSE 实时事件流** (先回放 SQLite 历史, 再接续 EventBus)
- `GET /games/{id}/events` — 复盘公开事件 (可按 channel 过滤)

### 内心戏复盘
- `GET /games/{id}/players/{pid}/history` — 某 player 的完整 LLM history
- `GET /games/{id}/histories` — 所有 player + god 的 history

## 项目结构

```
wolfpack-ai/
├── README.md                    # 本文档
├── CLAUDE.md                    # 设计/架构决策备忘 (gitignore)
├── start-dev.sh / .bat          # 一键启动脚本
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── requirements.txt
│   ├── .env.example
│   ├── alembic/                 # schema migration
│   ├── app/
│   │   ├── server.py            # FastAPI app
│   │   ├── routers/             # health / meta / game / stream
│   │   ├── models/              # SQLAlchemy 表
│   │   ├── schemas/             # Pydantic 入出参
│   │   ├── crud/                # ORM 操作封装
│   │   ├── infra/               # settings / db / event_bus
│   │   ├── core/                # game_state / channel / phase / judge / game_runtime
│   │   └── agent/
│   │       ├── base.py          # Player 基类 (async, astream_events, 推流式事件)
│   │       ├── contexts/        # history / store / adapter (跨模型)
│   │       ├── infra/           # llm_factory / agent_factory
│   │       ├── config/          # models.json (支持模型清单)
│   │       └── roles/           # villager / seer / witch / wolf / god
│   ├── tests/                   # 8 个端到端 + 1 个流式 mock
│   └── wolfpack-data/           # 运行时数据 (gitignore)
└── examples/
    └── frontend-demo/           # 视觉调性 HTML 预览 (gitignore, 仅本地参考)
```

## 状态

- ✅ **后端完整闭环** — 跑通完整对局, SQLite 持久化, SSE 实时流, 复盘 API
- 🚧 **前端开发中** — 设计方案已定 (见 [CLAUDE.md](./CLAUDE.md) 前端设计方案节)
- 📦 **Electron 套壳** — 后续, 前端起来后做

## License

MIT
