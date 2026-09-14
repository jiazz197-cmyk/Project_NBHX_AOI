# 平台 B 依赖清单（给 A 打包用）

> 归属：C（平台 B 后端）。
> 依据：`docs/P0骨架设计_双平台.md` §5 并行依赖输入、`docs/MVP开发计划.md` §1.1.2。
> 用途：供 A 制作离线依赖包 / 部署包（B 部署在产线工控机，可能断网）。

## 1. 运行时依赖（Python）

- Python：`>=3.10`（开发实测 3.12）；单进程 Uvicorn 1 worker，无 Celery/Redis/MinIO。
- 来源：`infer-platform/backend/pyproject.toml` + `uv.lock`（版本即锁定值）。

| 包 | 锁定版本 | 说明 |
|----|---------|------|
| fastapi | 0.141.1 | Web 框架 |
| uvicorn[standard] | 0.52.4 | ASGI 服务器（含 uvloop/httptools/watchfiles/websockets） |
| python-multipart | 0.0.32 | multipart 上传（`/inspect/image`、`/models/import`） |
| pydantic | 2.13.5 | 数据校验 |
| sqlalchemy | 2.0.52 | ORM（SQLite） |
| onnxruntime | 1.29.0 | 推理运行时（GPU 机器替换为 `onnxruntime-gpu`） |
| numpy | 2.5.2 | 数组计算 |
| pillow | 12.3.0 | 图像处理 |
| jinja2 | 3.1.6 | 日报 HTML 渲染 |
| apscheduler | 3.11.3 | 进程内定时任务 |
| httpx | 0.28.1 | HTTP 客户端（Registry v2 拉取、回传 A） |
| pyyaml | 6.0.3 | YAML 配置解析 |

> 以上各自的传递依赖（starlette、typing-extensions、uvloop 等）见 `uv.lock`。

## 2. 共享包（本地 editable 安装，不发布）

| 包 | 版本 | 说明 |
|----|------|------|
| skillname | 0.1.0 | 词汇表（零第三方依赖） |
| pipeline-core | 0.1.0 | 推理内核（`numpy` + `pillow`；`[yaml]` extra: `pyyaml`） |

安装方式：

```bash
uv pip install -e packages/skillname -e packages/pipeline-core
```

## 3. 开发依赖（仅测试，不随部署打包）

| 包 | 锁定版本 |
|----|---------|
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |

## 4. 系统 / 运行时依赖

- **CPU 推理**：无额外系统依赖（onnxruntime CPU wheel 自带运行时）。
- **GPU 推理**：需 NVIDIA CUDA 运行时，并将 `onnxruntime` 替换为 `onnxruntime-gpu`（对应 `ONNX_PROVIDER=cuda`）。
- 其余依赖均为纯 Python，无需系统级包。

## 5. 前端依赖（A 主笔，待补充）

平台 B 前端（Vite + React + TS + AntD5 + ECharts）由 A 主笔，本清单**不含前端 Node 依赖**；
待 A 落地 `infer-platform/frontend/` 后，补充 `package.json` / lock 与构建产物说明。

## 6. 离线打包要点

- **Python 依赖**：`uv export --frozen`（或 `pip download`）导出 wheels → 离线源；
- **共享包**：直接携带 `packages/skillname`、`packages/pipeline-core` 两个目录，editable 安装；
- **模型镜像**：地址/命名见 `MODEL_REGISTRY`（默认 `docker.io`），registry 与离线导出脚本由 A 负责；
- **B 运行时**：无 Redis/Celery/MinIO/Docker daemon 依赖（拉模型默认走 Registry HTTP API v2，`MODEL_PULL_MODE=oci`）。

## 7. 版本要求汇总

- Python `>=3.10`（建议 3.12）
- 单进程、无消息队列、SQLite（WAL）
- 共享包 `skillname==0.1.0`、`pipeline-core==0.1.0`
