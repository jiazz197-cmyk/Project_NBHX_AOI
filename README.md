<div align="center">

# Project_NBHX_AOI

**AOI 门板检测双平台 —— 数据集 · 标注 · 训练 · 模型发布 · 产线推理 的完整开源链路**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Django](https://img.shields.io/badge/Django-DRF-44B78B.svg)](https://www.djangoproject.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-%E2%9A%A1-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/frontend-React%2018-61DAFB.svg)](web/)

*平台 A（训练与标注平台，Label Studio 1.x 二开）+ 平台 B（推理与检测平台，独立轻量前后端），跨机器部署。*

[快速开始](#-快速开始) · [架构](#-架构) · [测试](#-测试) · [文档](#-文档) · [路线图](#-路线图) · [贡献](#-贡献) · [许可证](#-许可证)

</div>

---

## ✨ 特性

- **数据资产主数据源**：缺陷字典（可发布版本快照）、数据集管理、图片导入（md5 全局去重、Celery 异步）、数据集版本与划分
- **标注项目自动创建**：`POST /api/datasets` 服务端按模板创建 Label Studio 项目，开箱即标
- **预标签三桶分流**：模型预标签按置信度分为高/中/低三桶（宁错不漏），低桶强制人工复核
- **模型发布流水线**：模型库勾选（支持多选批量，逐条独立）→ `model.onnx + sha256 + model.yaml` → `FROM scratch` 单层镜像 → Registry v2 直推；**digest 以仓库回执为准、同内容可复现**，仓库不回回执即失败
- **已上传记录管理**：下线 / 软删 / 恢复（软删只清 A 侧记录，仓库镜像保留，B 仍可拉取）
- **复审工作流**：桶过滤 + 工作项账本 + 暗房灯箱终裁 + 坏图处理，终裁结论回写检测事实
- **产线推理平台（B）**：无用户体系、本地磁盘自包含；工位模板配置、ONNX Runtime 推理、三档判定、检测记录、错图统计与日报
- **契约先行**：双平台接口由三份契约文档冻结，`tests/contracts/` 契约测试双端锁定，红则阻断合并

## 🏗️ 架构

```text
┌─────────────────── 平台 A（中心侧，Label Studio 1.x 二开）───────────────────┐
│  账户(LS) + 自研 RBAC · 数据集与缺陷字典 · 打标签 · 预标签 · 训练 · 模型注册/审批/发布  │
│  Django + DRF · PostgreSQL · MinIO · Redis + Celery · Docker(推镜像)          │
└───────────────────────────────────┬─────────────────────────────────────────┘
                          模型镜像  │  ↑ 错图回传（可疑图/坏图，outbox 重试）
                                   ▼  │
┌────────────────── 镜像仓库（OCI/Docker Registry v2）──────────────────────────┐
└───────────────────────────────────┬─────────────────────────────────────────┘
                                   ▼
┌─────────────────── 平台 B（产线侧，自包含轻量平台）──────────────────────────┐
│  无 RBAC/用户体系 · 工位与模板(GUI) · 拉取模型 → ONNX Runtime 推理 → 三档判定   │
│  FastAPI + SQLite(WAL) + APScheduler · 本地磁盘 · React + AntD + ECharts      │
└────────────────────────────────────────────────────────────────────────────┘
```

- **两平台不共享数据库/对象存储/中间件**，模型只经镜像仓库传递；**A 从不主动连接 B**（无实例管理、无心跳、无方案下发）。
- 唯一公共层：[`packages/skillname`](packages/skillname)（任务类型/缺陷 code/model_ref/镜像 tag 词汇表）与 [`packages/pipeline-core`](packages/pipeline-core)（切片/NMS 合并/三档判定）。

## 📦 仓库结构

```text
project_aoi/
├── label_studio/              # 平台 A 后端：LS 1.x fork（Django + DRF），上游模块只读
│   └── aoi/                   # ★ 二开唯一可写区：core/ datasets/ prelabel/ training/ review/ audit/ reports/
├── web/                       # 平台 A 前端：LS 1.x web（React + TS）
│   └── apps/labelstudio/src/  # ★ 二开页面：pages/Datasets · Review · Training · System
├── infer-platform/            # 平台 B：backend（FastAPI）+ frontend（Vite + React + AntD）+ deploy/
├── packages/                  # 唯一共享层：skillname · pipeline-core（零依赖/仅 numpy+pillow）
├── tests/contracts/           # 双端契约测试 + fixtures
├── deploy/                    # 平台 A 部署骨架（Docker/nginx/uwsgi）
├── docker-compose.yml         # 平台 A：PostgreSQL + LS 主服务
├── docker-compose.minio.yml   # 平台 A：MinIO 对象存储
└── docs/                      # 架构 / MVP 计划 / P0 骨架 / 三份契约（入口 docs/README.md）
```

## 🚀 快速开始

### 一键 Docker（推荐，最接近交付形态）

```bash
git clone <your-fork-url> project_aoi && cd project_aoi

# 1. 准备环境变量
cp .env.example .env
# 编辑 .env，至少确认：
#   DJANGO_DB=default
#   POSTGRE_USER=postgres  POSTGRE_PASSWORD=postgres  POSTGRE_NAME=postgres
#   MINIO_STORAGE_ENDPOINT=http://minio:9000
#   MINIO_STORAGE_BUCKET_NAME=aoi-images
#   MINIO_STORAGE_ACCESS_KEY=minioadmin    # 与 MINIO_ROOT_USER 一致
#   MINIO_STORAGE_SECRET_KEY=minioadmin    # 与 MINIO_ROOT_PASSWORD 一致
#   INTERNAL_TOKEN=<32+ 随机字节>           # B→A 回传令牌：python -c "import secrets;print(secrets.token_urlsafe(32))"

# 2. 启动 PostgreSQL + MinIO + Label Studio
docker compose -f docker-compose.yml -f docker-compose.minio.yml up -d --build

# 3. 在 MinIO 控制台（http://localhost:9009）创建 bucket：aoi-images
```

启动后访问服务端口即可注册登录（首个注册用户为管理员）。生产部署请关闭 `DEBUG`/`FRONTEND_HMR` 并修改全部默认口令。

### 本地开发（平台 A）

要求：Python 3.10+、[uv](https://docs.astral.sh/uv/)、Bun 1.3+、本地 PostgreSQL 与 MinIO（bucket `aoi-images`）。

```bash
# 后端
uv sync --frozen
cp .env.example .env          # 仓库根 .env 会被 Django 自动读取（django-environ）
uv run python label_studio/manage.py migrate
uv run python label_studio/manage.py runserver 0.0.0.0:8082
#   ↑ runserver 会自动带起一个受限 Celery worker（图片导入为异步任务）；
#     也可 AOI_AUTOSTART_CELERY=false 后 make run-celery，或 make run-dev 一条命令并发拉起

# 前端（另开终端）
cd web && bun install && bun run dev
```

- 后端地址：`http://localhost:8082`（**浏览器入口始终是它**；Vite 的 `:8010` 只是 HMR 模块服务器，
  直接打开会因缺少 Django 注入的 `window.APP_SETTINGS` 而白屏）
- 前端改动由 Vite 热更新，刷新 `:8082` 即可看到

### 本地开发（平台 B）

```bash
cd infer-platform/backend
uv sync
uv pip install -e ../../packages/skillname -e ../../packages/pipeline-core   # 共享包 editable 安装
uv run uvicorn app.main:app --reload --port 8990    # SQLite 与图片落在 ./data

cd ../frontend
bun install && bun run dev                           # Vite 代理 /api 到 :8990
```

### 生产构建（平台 A）

```bash
cd web && bun install && bun run build && cd ..
make frontend-build-collect      # 等价于 bun run build + manage.py collectstatic
docker compose build
```

## 🧪 测试

契约测试是本仓库的质量主防线（红则阻断合并）。**A/B 两侧按各自运行手册跑，不能混在同一个 pytest 进程**
（A 侧是 Django 工程、B 侧是 FastAPI 自包含环境）：

```bash
# 平台 A 契约（需本地 PostgreSQL；DJANGO_SETTINGS_MODULE 已在 pyproject 配好）
PYTHONPATH=label_studio uv run pytest tests/contracts -q \
  --ignore=tests/contracts/test_platform_b_api.py --ignore=tests/contracts/test_cross_platform.py

# 平台 B 契约 + 跨端契约
cd infer-platform/backend
uv sync && uv pip install -e ../../packages/skillname -e ../../packages/pipeline-core
uv run pytest ../../tests/contracts/test_platform_b_api.py ../../tests/contracts/test_cross_platform.py -q

# 上游全量单测（注意：需 test 依赖组，且 fork 已知 label_studio/fsm 收集失败，先 --ignore）
uv run --group test pytest label_studio -q -m "not integration_tests" --ignore=label_studio/fsm

# Lint
uv run ruff check label_studio/aoi tests/contracts     # Python（改动文件同时过 ruff format）
cd web && bun --bun run biome check apps/labelstudio/src   # 前端
```

契约变更走「**四件套**」：改契约文档 + 改 stub + 改 fixture + 双方契约测试通过（冻结期外）。

## 📚 文档

| 文档 | 内容 |
|---|---|
| [`docs/README.md`](docs/README.md) | 文档索引与阅读顺序 |
| [`docs/双平台架构与拆分方案.md`](docs/双平台架构与拆分方案.md) | 拆分动因、职责边界、部署拓扑、跨机链路 |
| [`docs/contracts/跨平台契约_A-B.md`](docs/contracts/跨平台契约_A-B.md) | 模型镜像发布/拉取、`model.yaml`、错图回传、认证与幂等 |
| [`docs/contracts/平台A_接口与数据契约.md`](docs/contracts/平台A_接口与数据契约.md) | LS 复用边界、aoi 表、`/api/*`、训练/复审/预标 |
| [`docs/contracts/平台B_接口与数据契约.md`](docs/contracts/平台B_接口与数据契约.md) | 平台 B 表、`/api/v1/*`、推理链路、统计口径、日报 |
| [`docs/P0骨架设计_双平台.md`](docs/P0骨架设计_双平台.md) | 骨架结构、stub 行为、全部配置键 |
| [`docs/MVP开发计划.md`](docs/MVP开发计划.md) | 里程碑、排期、风险 |
| [`docs/docker-registry-setup.md`](docs/docker-registry-setup.md) | 模型镜像仓库的搭建与账号分配 |

## 🗺️ 路线图

- ✅ **已完成** — 仓库骨架与契约冻结；RBAC 与页面门控；数据集/缺陷字典/导入包裹/标注项目自动创建；ingest 落对象存储；模型发布真实推送（A 侧）与已上传管理；复审/训练页
- 🚧 **进行中** — 平台 B 模型拉取真实打通（Registry v2 manifest/层解包/校验/注册 + 远端 tag 列表一键拉取）；相机适配器壳（DirectorySource）+ outbox 回传真实联调；双机联调
- 📅 **计划** — 训练流水线与真模型接入（复用现有发布流水线）；工位与相机页联调；离线交付包；MJPEG/RTSP 视频流与车间大屏（二期）

细节与排期见 [`docs/MVP开发计划.md`](docs/MVP开发计划.md)。

## 🤝 贡献

欢迎 Issue 与 PR。提交前请了解本仓库的两条硬约束：

1. **上游模块只读**：`label_studio/`（除 `aoi/`）与 `web/libs/` 等上游代码不做修改；二开一律落在
   `label_studio/aoi/` 与 `web/apps/labelstudio/src/`，跨模块需求通过上游注入点/钩子实现。
2. **契约冻结**：跨平台接口以 `docs/contracts/` 为准，破坏性变更必须走四件套（文档 + stub + fixture + 双端测试）。

```bash
# 提交前自查
uv run ruff format --check <改动的 py 文件>
cd web && bun --bun run biome check <改动的前端文件>
```

## 📄 许可证

本项目基于 [Apache License 2.0](LICENSE) 开源。

- 本仓库 fork 自 [Label Studio](https://github.com/HumanSignal/label-studio)（Apache-2.0），修改与新增代码
  同样以 Apache-2.0 提供；上游原有版权与许可声明保留于 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。
- 版权声明：`Copyright 2026 The Project_NBHX_AOI Authors`（见 [NOTICE](NOTICE)）。

## 🙏 致谢

- [Label Studio](https://github.com/HumanSignal/label-studio)（HumanSignal）— 平台 A 的基座：标注、任务管理、前端 editor 与多租户工程能力
- [FastAPI](https://fastapi.tiangolo.com/) · [ONNX Runtime](https://onnxruntime.ai/) · [Ant Design](https://ant.design/) · [ECharts](https://echarts.apache.org/) — 平台 B 的轻量技术栈
