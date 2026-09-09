# Project_NBHX_AOI / Label Studio 二开仓库

> AOI 门板检测平台的 LS 1.x 二开仓库骨架。
> 定位：以 **Label Studio 作为唯一主应用**，复用账户/标注/上传/审核/预标/导出等原生能力；
> 二开增量集中在「缺陷字典/数据集版本/训练/复审/检测方案模板」以及 sidecar 计算侧。

## 1. 仓库与上游

```bash
git remote -v
# origin  git@github.com:jiazz197-cmyk/Project_NBHX_AOI.git (fetch)
# origin  git@github.com:jiazz197-cmyk/Project_NBHX_AOI.git (push)
```

当前仓库已切换到上述新上游。若需对照上游 LS 原始代码，可另行添加：

```bash
git remote add upstream git@github.com:HumanSignal/label-studio.git
```

## 2. 前后端分离结构

本仓库当前是 LS 二开源码仓库，前后端物理分离但共用同一仓库：

```text
label-studio/
├── label_studio/            # Django 后端主程序
│   ├── manage.py
│   ├── core/                # 核心配置/中间件/存储等
│   ├── io_storages/         # 仅保留 localfiles 等本地存储
│   ├── projects/ tasks/ data_manager/ ...
│   └── ...
├── web/                     # React + TS 前端（LS web）
│   ├── apps/labelstudio/    # 主应用：页面/路由/组件
│   ├── libs/                # editor / datamanager / ui 等前端库
│   ├── package.json
│   └── bun.lock
├── deploy/                  # Docker/nginx/uwsgi 运行骨架
├── docker-compose.yml       # PostgreSQL + LS 主服务
├── docker-compose.minio.yml # MinIO 本地对象存储
├── pyproject.toml
├── uv.lock
└── CHANGES.md
```

运行形态：

- **后端**：Django + DRF，负责账号、项目、任务、标注、数据管理、二开 API。
- **前端**：React/TS，开发时通过 Vite 独立启动，代理 `/api`、`/static` 到 Django。
- **生产/交付**：前端构建产物交给 Django/Nginx 托管，仍保持前后端分离的代码结构。
- **后续 monorepo 演进**：可进一步拆为 `backend/label_studio` + `frontend/web`，当前阶段先保持 LS 原生仓库结构，便于锁上游 tag 和 diff。
- **sidecar / workers / packages**：按 `docs/` 的 P0/MVP 规划后续补充；当前仓库先保留 LS 主应用源码与构建骨架。

## 3. 本地开发启动

### 3.1 后端

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

# 4. 启动 Django
uv run python label_studio/manage.py runserver 0.0.0.0:8080
```

后端默认开发地址：`http://localhost:8080`

> 本地裸跑前请确保 PostgreSQL 和 MinIO 已启动，且 MinIO 中已创建 `aoi-images` bucket。

### 3.2 前端

要求：Bun 1.3+。

```bash
cd web
bun install
bun run dev
```

Vite 开发服务器监听 `http://localhost:8010`，但它只是**模块/HMR 服务器，不是浏览器入口**：

- 后端 `.env` 中 `FRONTEND_HMR=true`（默认开启）时，Django 页面会自动从
  `http://localhost:8010/react-app/main.tsx` 加载前端模块与样式；
- **浏览器入口始终是后端地址 `http://localhost:8080`**，打开后即可联调；
- **不要直接打开 `http://localhost:8010`**：该地址返回的是 Vite 的裸 `index.html`，
  缺少 Django 注入的 `window.APP_SETTINGS` 与挂载 DOM（`.app-wrapper`/`#main-content`），
  React 会在渲染前抛 `ReferenceError`，表现为白屏；
- `vite.config.ts` 中的 `/api`、`/static` 代理只在“直接打开 8010”这一不受支持的场景下
  才会被用到；正常联调时页面本身由 8080 提供，请求同源直达 Django。

前端代码改动由 Vite 自动热更新（HMR），刷新 `http://localhost:8080` 页面即可看到效果。

### 3.3 使用 PostgreSQL + MinIO（推荐接近交付形态）

`docker-compose.yml` 提供 PostgreSQL；启动本地开发栈时叠加 `docker-compose.minio.yml` 启用 MinIO。两者共同构成默认的 PG + MinIO 开发环境。

```bash
# 1. 准备环境变量
cp .env.example .env
# 编辑 .env，至少确认：
#   DJANGO_DB=default
#   POSTGRE_HOST=db
#   POSTGRE_USER=postgres
#   POSTGRE_PASSWORD=...
#   POSTGRE_NAME=postgres
#   MINIO_STORAGE_ENDPOINT=http://minio:9000
#   MINIO_STORAGE_BUCKET_NAME=aoi-images
#   MINIO_STORAGE_ACCESS_KEY=minioadmin
#   MINIO_STORAGE_SECRET_KEY=minioadmin
# 注意：全容器/交付形态下请关闭本地开发开关（.env 默认值）：
#   FRONTEND_HMR=false
#   DEBUG=false

# 2. 启动 PostgreSQL + MinIO + Label Studio
docker compose -f docker-compose.yml -f docker-compose.minio.yml up -d --build

# 3. 在 MinIO 控制台创建 bucket：aoi-images
#    控制台默认 http://localhost:9009
```

启用后，Label Studio 的上传文件/图片默认存储会切到 MinIO bucket `aoi-images`；用户、项目、标注等业务数据仍在 PostgreSQL。

## 4. 生产构建

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

## 5. 二开新增页面的位置（LS 内）

按 MVP 方案，不新增独立前端，而是扩展 LS 的 Menubar：

| LS 菜单 | 路由 | 新页面/能力 |
|---|---|---|
| 检测 | `/inspect` | 检测工作台：手动上传/触发工位检测、相机快照预览、结果列表与详情 |
| 检测 > 相机/工位 | `/inspect/cameras`（建议） | 相机/工位实时快照、软触发、推理状态、不可检测提示 |
| 系统 | `/system` | 系统管理：工位注册、用户/角色、审计等 |
| 系统 > 工位管理 | `/system/stations`（建议） | 工位/相机参数管理、启停、健康状态 |

MVP 只做 1~2fps 快照轮询预览，不接 RTSP/WebRTC 独立视频前端。

## 6. 说明

- `label_studio/` 与 `web/` 是二开核心，尽量保持 LS 原生语义。
- 详细技术规划见仓库同级 `docs/` 下的 MVP 计划与技术手册。
