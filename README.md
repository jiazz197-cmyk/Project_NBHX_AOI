# Project_NBHX_AOI / AOI 门板检测双平台 monorepo

> **平台 A（训练与标注平台，LS 1.x 二开）** + **平台 B（推理与检测平台，独立轻量前后端）**，跨机器部署。
> 两平台不共享数据库/对象存储/中间件，唯一公共层为 `packages/skillname` 与 `packages/pipeline-core`。
> 文档入口：**[`docs/README.md`](docs/README.md)**（架构与拆分方案 / MVP 计划 / P0 骨架 / 三份契约）。

## 1. 仓库与上游

```bash
git remote -v
# origin  ssh://git@10.80.153.12:2222/Carl_Jia/project_aoi.git (fetch)
# origin  ssh://git@10.80.153.12:2222/Carl_Jia/project_aoi.git (push)
```

当前仓库已切换到上述内网 GitLab 上游（默认分支 `main`）。

> **注意 SSH 端口是 2222**：`10.80.153.12` 的 22 端口是主机系统 sshd，GitLab 的 gitlab-shell 发布在
> **2222**（见 `ss -tlnp`）。GitLab 页面展示的 `git@10.80.153.12:Carl_Jia/project_aoi.git` 走 22 会认证失败，
> 必须使用带端口的 `ssh://` 写法。首次连接请先与运维核对主机指纹（本机已知 ED25519 指纹：
> `SHA256:HMXcMDJQCfUdrNVCJeTxcmavry7gMcG4ce4ogqjKOMg`）。

若需对照上游 LS 原始代码，可另行添加：

```bash
git remote add upstream git@github.com:HumanSignal/label-studio.git
```

## 2. 仓库结构（双平台 monorepo）

```text
Project_NBHX_AOI/
├── label_studio/              # 平台A 后端：LS 1.x fork（Django + DRF），上游模块只读
│   ├── manage.py
│   ├── core/ io_storages/ projects/ tasks/ data_manager/ ...   # 上游，只读
│   └── aoi/                   # 二开唯一可写区（D1 起落地）
│       ├── core/ datasets/ prelabel/ training/ review/ audit/ reports/
│       ├── workers/           # Celery：training(GPU) / default(CPU) / publish(构建并推送模型镜像)
│       └── urls.py            # /api/* 二开路由此汇总
├── web/                       # 平台A 前端：LS 1.x web（React + TS）
│   ├── apps/labelstudio/      # 主应用：页面/路由/组件（二开页面独立路由）
│   └── libs/                  # editor / datamanager / ui 等前端库
├── infer-platform/            # 平台B：独立前后端（D1 起落地，当前仓库尚未包含）
│   ├── backend/               # FastAPI + SQLite + APScheduler + ONNX Runtime + registry 拉取
│   ├── frontend/              # Vite + React + TS + Ant Design + ECharts（独立，不复用 LS 组件）
│   └── deploy/                # Dockerfile / compose / systemd / 离线包
├── packages/                  # 唯一共享层（D1 起落地，当前仓库尚未包含）
│   ├── skillname/             # 任务类型 / 缺陷 code / model_ref / 镜像 tag 词汇表（零依赖）
│   └── pipeline-core/         # 切片 / NMS 合并 / 三档判定 / load_config（numpy + pillow）
├── tests/contracts/           # 双端契约测试 + fixtures（D2 起挂 CI）
├── deploy/                    # 平台A 部署：Docker/nginx/uwsgi 运行骨架
├── docker-compose.yml         # 平台A：PostgreSQL + LS 主服务
├── docker-compose.minio.yml   # 平台A：MinIO 本地对象存储
├── docs/                      # 架构 / MVP 计划 / P0 骨架 / 契约（先读 docs/README.md）
├── pyproject.toml
├── uv.lock
└── CHANGES.md
```

> 落地状态：`label_studio/` 与 `web/` 已就绪；`infer-platform/`、`packages/`、`tests/contracts/`、`label_studio/aoi/` 按
> [`docs/P0骨架设计_双平台.md`](docs/P0骨架设计_双平台.md) 从 D1 起补充，本节结构即目标形态。

## 3. 平台 A：训练与标注平台（已就绪）

定位：数据资产与模型生产的唯一主数据源；复用 LS 账户与登录/标注/上传/审核/导出能力（**角色与权限自研，LS 原生角色框架不可用**），二开集中在
「缺陷字典 / 数据集版本 / 预标签 / 训练 / 模型发布 / 复审回流」。**不管理工位、相机、推理实例，不主动连接 B**。
技术栈：Django + DRF、PostgreSQL、MinIO、Redis + Celery、Docker（构建并推送模型镜像）。

### 3.1 后端本地开发

要求：Python 3.10+，uv，PostgreSQL + MinIO（默认）。

默认说明：本仓库已不再默认 SQLite。`core.settings.label_studio` 未显式设置 `DJANGO_DB` 时默认走 **PostgreSQL**；未显式关闭 MinIO 时默认连接 `http://localhost:9000`，上传图片会落到 MinIO bucket `aoi-images`。

```bash
# 1. 安装后端依赖
uv sync --frozen

# 2. 准备环境变量
cp .env.example .env
# 仓库根目录的 .env 会被 Django 自动读取（django-environ，无需 export），
# 真实 shell 环境变量优先；修改 .env 后需重启后端生效。
# 默认即 PostgreSQL + MinIO，并已开启本地开发所需的 FRONTEND_HMR / DEBUG。
# 注意：POSTGRE_NAME 必须与 PostgreSQL 容器中实际存在的库一致（默认 postgres）。

# 3. 初始化数据库
uv run python label_studio/manage.py migrate

# 4. 启动开发栈（Ctrl+C 一并退出）
uv run python label_studio/manage.py runserver 0.0.0.0:8082
#    ↑ D5 起图片导入为异步任务：runserver 会自动带起一个受限 Celery worker（随服务启停、
#      文件热重载时自动重建）。想单独观察 worker 日志可 AOI_AUTOSTART_CELERY=false 关闭，
#      然后 make run-celery；或用 make run-dev 一条命令并发拉起 Django + worker。
```

后端默认开发地址：`http://localhost:8082`

> 本地裸跑前请确保 PostgreSQL 和 MinIO 已启动，且 MinIO 中已创建 `aoi-images` bucket。
> **D5 起**图片导入依赖 Redis + Celery worker（`uv run ... runserver` 已默认自动带起，无需手动单独启动；
> docker-compose 部署时 `worker` 服务随 compose 自动启动。broker `CELERY_BROKER_URL`
> 默认 `redis://localhost:6379/1`，与 LS 自带 django_rq 的 DB 0 隔离）；
> 模型发布变量（`MODEL_REGISTRY`、`MODEL_IMAGE_REPO`、`MODEL_REGISTRY_USER`、`MODEL_REGISTRY_PASSWORD`、`INTERNAL_TOKEN`）在骨架落地后追加到 `.env`；
> **D3 起**发布服务另有 `AOI_PUBLISH_MODE`（`fake` 离线假推送 / `registry` 走 Registry v2 真推）、
> `AOI_REGISTRY_PROXY`（只作用于 registry 出网的代理，内网示例 `http://127.0.0.1:7897`）、
> `AOI_PUBLISH_ARTIFACTS_DIR`（产物落盘目录，默认 `tmp/publish`，已被 `.gitignore` 忽略）。
> 全部配置键见 `docs/P0骨架设计_双平台.md` §6，仓库/账号分配见 `docs/docker-registry-setup.md`。

### 3.2 前端本地开发

要求：Bun 1.3+。

```bash
cd web
bun install
bun run dev
```

Vite 开发服务器监听 `http://localhost:8010`，但它只是**模块/HMR 服务器，不是浏览器入口**：

- 后端 `.env` 中 `FRONTEND_HMR=true`（默认开启）时，Django 页面会自动从
  `http://localhost:8010/react-app/main.tsx` 加载前端模块与样式；
- **浏览器入口始终是后端地址 `http://localhost:8082`**，打开后即可联调；
- **不要直接打开 `http://localhost:8010`**：该地址返回的是 Vite 的裸 `index.html`，
  缺少 Django 注入的 `window.APP_SETTINGS` 与挂载 DOM（`.app-wrapper`/`#main-content`），
  React 会在渲染前抛 `ReferenceError`，表现为白屏；
- `vite.config.ts` 中的 `/api`、`/static` 代理只在“直接打开 8010”这一不受支持的场景下
  才会被用到；正常联调时页面本身由 8080 提供，请求同源直达 Django。

前端代码改动由 Vite 自动热更新（HMR），刷新 `http://localhost:8082` 页面即可看到效果。

### 3.3 使用 PostgreSQL + MinIO（推荐接近交付形态）

`docker-compose.yml` 提供 PostgreSQL；启动本地开发栈时叠加 `docker-compose.minio.yml` 启用 MinIO。两者共同构成默认的 PG + MinIO 开发环境。

```bash
# 1. 准备环境变量
cp .env.example .env
# 编辑 .env，至少确认：
#   DJANGO_DB=default
#   POSTGRE_USER=postgres
#   POSTGRE_PASSWORD=postgres
#   POSTGRE_NAME=postgres
#   （POSTGRE_HOST 不用改：app 服务已固定 POSTGRE_HOST=db；
#     docker-compose.yml 会把 POSTGRE_* 映射为 db 容器的 POSTGRES_*，
#     即 app 与 db 共用 .env 里这一套凭据，不再硬编码。）
#   MINIO_STORAGE_ENDPOINT=http://minio:9000
#   MINIO_STORAGE_BUCKET_NAME=aoi-images
#   MINIO_STORAGE_ACCESS_KEY=minioadmin   # 必须与 MINIO_ROOT_USER 一致
#   MINIO_STORAGE_SECRET_KEY=minioadmin   # 必须与 MINIO_ROOT_PASSWORD 一致
#   INTERNAL_TOKEN=<32+ 随机字节>         # B→A 错图回传令牌；容器形态必填（未配置则 /api/ingest 一律 40100）
#     生成：python -c "import secrets;print(secrets.token_urlsafe(32))"
# 注意：全容器/交付形态下请关闭本地开发开关（.env 默认值）：
#   FRONTEND_HMR=false
#   DEBUG=false        # compose 默认已是 false；DEBUG=true 且未配 INTERNAL_TOKEN 时会回落到开发默认令牌
# 交付前务必修改 Postgres/MinIO 的默认口令（POSTGRE_PASSWORD / MINIO_ROOT_PASSWORD）。
# 若沿用旧的 ./postgres-data 卷（此前为 trust 认证），Postgres 只在数据目录首次初始化时应用密码，
# 需要改密码或重建卷（docker compose down -v 会删除数据，谨慎）。

# 2. 启动 PostgreSQL + MinIO + Label Studio
docker compose -f docker-compose.yml -f docker-compose.minio.yml up -d --build

# 3. 在 MinIO 控制台创建 bucket：aoi-images
#    控制台默认 http://localhost:9009
```

> 若宿主机已有 PostgreSQL/MinIO 占用 5432/9000（例如独立的基础设施 compose 栈），
> 这套 compose 会端口冲突，二选一即可。

启用后，Label Studio 的上传文件/图片默认存储会切到 MinIO bucket `aoi-images`；用户、项目、标注等业务数据仍在 PostgreSQL。

### 3.4 生产构建

```bash
# 1. 构建前端静态资源
cd web
bun install
bun run build

# 2. 收集 Django 静态文件
cd ..
DJANGO_SETTINGS_MODULE=core.settings.label_studio \
  uv run python label_studio/manage.py collectstatic --no-input

# 3. 使用 Docker 构建完整交付镜像
docker compose build
```

## 4. 平台 B：推理与检测平台（规划中，D1 起落地）

定位：产线侧自包含的在线推理与运行监控平台，**无 RBAC、无用户体系、无登录认证**；从镜像仓库拉取 A 发布的 YOLO 模型，
**自行配置工位与工位模板（GUI）**，按模板推理并产出错图统计、信息统计、日报与错图回传。

| 项 | 选型 |
|---|---|
| 后端 | FastAPI + Uvicorn（单进程）+ SQLAlchemy + SQLite（WAL）+ APScheduler |
| 推理 | ONNX Runtime（CUDA EP / CPU）+ `pipeline-core` |
| 模型获取 | OCI/Docker Registry HTTP API v2（httpx + tarfile，无需 Docker daemon） |
| 存储 | 本地磁盘（图片/权重/日报），**无 MinIO/Redis/Celery 依赖** |
| 前端 | Vite + React + TS + Ant Design 5 + ECharts（独立前端，不复用 LS 组件） |
| 交付 | `infer-platform/deploy/` 下 Docker Compose 或 systemd |

本地开发（骨架落地后）：

```bash
# 后端：默认监听 8990，SQLite 与图片落在 ./data
cd infer-platform/backend
uv sync
uv run uvicorn app.main:app --reload --port 8990

# 前端：Vite 开发服务器代理 /api 到 http://localhost:8990
cd infer-platform/frontend
bun install && bun run dev
```

平台间链路（跨机器，详见 [`docs/contracts/跨平台契约_A-B.md`](docs/contracts/跨平台契约_A-B.md)）：

- **A → 镜像仓库**：在模型库中**勾选模型**（支持多选批量，逐条独立）→ `POST /api/train/models/publish` 构建并推送模型镜像（`/model/model.onnx` + `model.yaml` + `.sha256`）；已上传记录可**下线 / 软删 / 恢复**（软删只清 A 侧记录，仓库镜像保留）；
- **镜像仓库 → B**：`GET /api/v1/models/remote` 列出远端可用 tag → **一键拉取** → `POST /api/v1/models/pull` 拉 manifest/层 → 解包 → sha256 校验 → 解析 `model.yaml` → 注册；
- **B → A**：错图回传（`POST /api/ingest/findings`，仅可疑图/坏图，outbox 重试）。
- **A 从不主动连接 B**：无实例管理、无心跳、无方案下发。

## 5. 页面与入口

### 5.1 平台 A（LS Menubar 内，复用 LS 组件）

| 菜单 | 路由 | 内容 |
|---|---|---|
| 数据集 | `/datasets` | 缺陷字典、导入、数据集版本与划分 |
| 训练 | `/training` | 基模/训练任务/门禁/模型注册与审批/模型发布状态 |
| 复审 | `/review` | 检测事实、复审工作项、终裁、建议清单、坏图 |
| 系统 | `/system` | 用户/角色（自研 RBAC）、审计 |

### 5.2 平台 B（独立前端，5 页）

| 页面 | 路由 | 内容 |
|---|---|---|
| 概览 | `/` | 检测量、三档分布、错图率、缺陷 TopN、节拍、时延、工位/模型/模板状态 |
| 检测记录 | `/inspections` | 列表/筛选/图片与框预览；错图统计（坏图按 `error_code`、可疑图按 `object_code`） |
| 日报 | `/reports` | 日报列表/详情/HTML+CSV 导出 |
| 工位与相机 | `/stations` | 工位增删改、相机配置、启停、软触发、快照 + **工位模板编辑** |
| 系统 | `/system` | 健康、**模型库（拉取/离线导入/删除）**、回传队列、保留策略 |

> 相机/推理不再放进 LS 工作台：平台 B 只做 1~2fps 快照与结果展示，MJPEG/RTSP/WebRTC 视频流与车间大屏属二期。

## 6. 说明

- `label_studio/` 与 `web/` 是平台 A 二开核心，上游模块只读，二开集中在 `label_studio/aoi/` 与 `web/apps/labelstudio/src/pages/`。
- `infer-platform/` 与 `packages/` 尚未落地；落地顺序、目录与 stub 行为以 `docs/P0骨架设计_双平台.md` 为准。
- 平台间不共享数据库/对象存储/中间件，模型只经镜像仓库传递；公共代码只有 `packages/skillname` 与 `packages/pipeline-core`。
- 详细技术规划见 [`docs/README.md`](docs/README.md)：架构拆分方案、MVP 开发计划、P0 骨架设计、三份接口与数据契约。
