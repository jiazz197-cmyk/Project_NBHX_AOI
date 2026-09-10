# 平台 A 接口与数据契约（训练与标注平台，LS 二开）

> 归属：**B 主笔**（主数据源 / 业务接口 / 二开包裹）；消费：A 侧前端、Celery workers、平台 B（仅经跨平台契约）。
> 冻结基线：D2；变更窗口：D9 / D15。跨平台接口（模型镜像发布/拉取、错图回传）见 `跨平台契约_A-B.md`，不在此重复。
> 技术栈：Django + DRF（LS 1.x fork）、PostgreSQL 15、MinIO、Redis 7 + Celery 5。

---

## 0. 范围与原则

- 平台 A 是**数据与模型生产的唯一主数据源**：缺陷字典、数据集、标注、预标注、训练、模型注册与**模型发布**；**不管理工位/相机/推理实例，不参与产线运行**。
- LS 原生能力**能用则用**（§1）；二开只做四个业务新域（datasets / prelabel / training / review）+ 三个支撑 app（core / audit / reports）+ 薄包裹。
- 平台 B 不直连 A 的数据库/对象存储；**A 也不主动连接 B**。所有跨平台交互走 `跨平台契约_A-B.md`（A 发布模型镜像 → B 拉取；B 回传错图）。
- **sidecar 已取消**：原 sidecar 的 ML backend 协议与预标推理归 A 自身（Django + Celery GPU worker + `pipeline-core`）。

---

## 1. LS 原生复用对照表

| 平台功能 | LS 原生能力（直接复用） | aoi 二开薄包裹 | MVP 决策 |
|---|---|---|---|
| 登录/令牌/账户 | LS users + token API（JWT HS256，claims 含 `user_id`） | 仅复用账户表与登录链 | **复用** |
| 角色/权限（RBAC） | LS 原生角色/组织权限框架**不可用** | **自研**：`aoi_core` 角色/权限点/授权表 + DRF 权限类（§3.1） | **自研** |
| 标注项目/任务 | `projects/tasks/annotations` 原生 | label config 由缺陷字典渲染注入 | **复用** |
| 框标注交互 | 标注编辑器（RectangleLabels） | 零改动（红线） | **复用** |
| 数据浏览 | Data Manager | 零重构（红线） | **复用** |
| 标注审核 | LS OSS 1.24 **无 Review 流程**（D2 实测） | **自研**：预标三桶判定 → 人工复审 → 终裁/回流（§10） | **自研（D2 裁定）** |
| 文件上传/存储 | LS 文件存储（MinIO）+ `/data/` 鉴权访问；**D2 实测无服务端缩略图、默认不预签名** | aoi 导入包裹：去重/质检/元数据登记 + **缩略图 + 预签名 URL** | 复用+包裹 |
| 预标回写 | `ml/` MLBackend 连接器 + Batch predictions | **A 侧自实现 ML backend 协议**（`aoi/prelabel`） | 复用+自实现 |
| 数据集导出 | `data_export`（YOLO/COCO）；D2 实测 YOLO 产物 `images/ + labels/ + classes.txt + notes.json`（**无 data.yaml**） | aoi 版本绑定 + 测试集红线 + `classes.txt` 顺序校验；训练包裹按需生成 `data.yaml` | **复用+包裹** |
| 前端框架 | web/apps 组件库/路由/auth store/i18n | Menubar 入口 + 二开页面 | 复用+加页 |
| 审计（部分） | LS activity log | `aoi/audit` 关键操作追加写 | 复用+补充 |

**结论**：账户与登录、标注、上传通道、预标通道、导出通道可直接复用（角色与权限必须自研，复审自研）；上传的缩略图/预签名、YOLO 的 `data.yaml` 由 aoi 包裹补足。二开的主战场是「自研 RBAC / 字典 / 数据集版本 / 预标注 / 训练 / 复审回流」+ 薄包裹 + **模型发布**。

---

## 2. 通用工程约定

### 2.1 术语与枚举（权威定义在 `packages/skillname`）

| 术语 | 定义 |
|---|---|
| `skillname` | 任务类型：`ObjectDetection`（MVP 唯一）→ LS 控件 `RectangleLabels` |
| `object_fault_type_XX` | 缺陷对象 code，XX 两位数字（01~99），由缺陷字典配置 |
| `model_ref` | 模型注册版本号，格式 `{seq}-{framework}@ds{version}`，如 `3-yolo@ds1` |
| `model.yaml` | 随模型镜像发布的**模型能力描述**（skillname/类别/推荐阈值/张量信息），见跨平台契约 §2.3 |
| `station_code` | B 侧工位 code；A 只作**不透明字符串**存储（A 没有工位主数据） |
| `verdict` | 初检判定：`auto_pass` / `recheck` / `manual`（语义在 `pipeline-core`） |
| `source` | 图片来源：`manual_real` / `camera` / `reflux_review` / `prelabel_model_{id}` |
| `kind` | 回传类型：`suspicious`（可疑图）/ `bad`（坏图） |

> 枚举值**不得**在 A 侧硬编码副本；统一 `from skillname import ...`。
> `label_config` 由缺陷字典运行时渲染，结构遵循 LS 官方预设模板（`label_studio/annotation_templates/**/config.yml` 的 `View/Image/RectangleLabels/Label` 形态），控件名 `defect` 为 AOI 约定（D2 裁定保持）；产出必须通过 LS 原生 `core.label_config.validate_label_config`。

### 2.2 网络与路由

| 路径 | 上游 | 说明 |
|---|---|---|
| `/` | web（LS 前端静态 + 二开页面） | SPA 路由回退 `/index.html` |
| `/api/*` | ls-backend:8000（经 nginx） | LS 原生 + aoi 二开全部接口（同一 DRF 根） |
| `/data/*`、`/upload/*` | ls-backend | LS 媒体/上传文件（预签名下载） |
| `/healthz` | ls-backend | compose healthcheck |

> 平台 B 在**另一台机器**，不经过 A 的 nginx；A↔B 由跨平台契约定义。

### 2.3 统一响应信封与错误码

成功：`{"code":0,"message":"ok","request_id":"req-...","data":{...}}`
失败：HTTP 状态码 + 同信封（`data.detail.fields` 给字段级错误）。

| HTTP | code | 含义 |
|---|---|---|
| 400 | 40010 | 坏图/文件不可读/校验失败 |
| 401 | 40100 | 未认证/令牌过期 |
| 403 | 40300 | 无权限（角色/权限点不满足） |
| 404 | 40401 | 资源不存在 |
| 409 | 40900 | 状态冲突（重复发布/重复批次/幂等冲突） |
| 422 | 42200 | 业务校验失败（`detail.fields`） |
| 429 | 42900 | 限流 |
| 500 | 50000 | 内部错误 |
| 503 | 50300 | 依赖不可用（registry 不可达/存储异常） |

### 2.4 鉴权

- **前端/脚本 → A（D3 认证链路标准化）**：`POST /api/auth/login`（`email` + `password`，匿名可访问）签发 **access + refresh JWT**；业务接口带 `Authorization: Bearer <access>`，由 **DRF 认证类**校验（`aoi.common.authentication.AoiJWTAuthentication` → simplejwt `JWTAuthentication`，见 `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`）。算法 HS256，签名密钥取 `settings.SECRET_KEY`（simplejwt 默认；显式配置见 `core/settings/base.py::SIMPLE_JWT`），claims 含 `user_id`、`token_type`。
- **凭据校验只复用 LS**：与浏览器登录 `LoginForm` **同源**——先走 `settings.USER_AUTH` 钩子（LDAP 等自定义后端），再回退 Django 认证后端；账号不存在/密码错误/账号停用一律 `40100`，不区分原因。
- **浏览器 → A**：LS 原生会话登录 `/user/login/`（`sessionid` + `session['last_login']`）**保持不变**，`SessionAuthentication` 仍是第三顺位认证类；`admin/`、密码重置、邀请等上游链路不受影响。
- **令牌管理（上游端点，语义不变）**：`POST /api/token/` 签发 PAT（返回 refresh JWT；同一用户已有有效 token → 409）、`POST /api/token/refresh/`（refresh → access）、`POST /api/token/blacklist/`、`POST /api/token/rotate/`；`POST /api/auth/logout` 把 refresh 加入黑名单（**幂等**：无效/已吊销同样 200，`revoked=false`）。
- **已废弃的机制（D3）**：上游 `jwt_auth.middleware.JWTAuthenticationMiddleware` 已从 `MIDDLEWARE` 移除——Bearer 不再由 Django 中间件赋值 `request.user`，因此 JWT 在 DRF 侧有完整的 `request.auth`、一致的 401 语义、可进 OpenAPI；`X-Api-Key: <jwt>` 仍由 `XApiKeySupportMiddleware` 改写为 `Authorization: Bearer` 后走同一认证类。
- **RBAC 自研**：LS 开源版的组织/角色权限框架不可用（能力不完整且语义与 AOI 三角色不匹配），**不作为权限依据**；不修改 LS 原生 users/组织表，授权关系存 `aoi_core.user_role`（`user_id` 逻辑引用 LS users，不建外键）。
- **B → A（错图回传）**：`X-Internal-Token: <INTERNAL_TOKEN>`；`instance_code` / `station_code` 由 B 在回传体中给出，供审计与溯源。
- **LS → A 预标端点（D2 实测）**：LS 调用 `aoi/prelabel/{task_id}/*` 时**不携带 `X-Internal-Token`/Authorization**，仅带 `User-Agent: heartex/...`；因此默认放行，请求若带内部头则必须正确。置 `AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=true` 可强制 40100（需配合网关注入头或 LS Basic Auth）；生产建议该端点仅在内网暴露。
- **A → 镜像仓库（模型发布）**：`MODEL_REGISTRY_USER` / `MODEL_REGISTRY_PASSWORD`，见跨平台契约 §1.2。**A 不直接连接 B**。
- 权限点（模块级）：`datasets.*`、`training.*`、`review.*`、`system.*`；动作 `view/create/update/cancel/approve/publish`；三角色 `operator`（操作员）/ `admin`（管理员）/ `super_admin`（超级管理员）——**仅用于平台 A**；默认权限矩阵见 §3.1。

### 2.5 公共请求约定

- 请求头：`X-Request-ID`（nginx 生成并贯穿日志）；`Idempotency-Key`（导入/训练/激活/下发等写操作必带）。
- 时间 ISO8601 UTC；编码 UTF-8；分页 `?page=&page_size=`，响应 `{total, items}`。
- 文件上传 multipart：字段 `file`/`files`，单图 ≤100MB；MVP 不做分片断点。

---

## 3. 数据模型（PostgreSQL 主数据源）

> LS 原生表（projects/tasks/annotations/ml/users）**只读复用、不修改语义**（红线）；aoi 业务表独立 schema。平台 B 不直连本库。

### 3.1 `aoi_core`（自研 RBAC）

> LS 原生角色/组织权限框架不可用，**不作为权限依据**；只复用 LS 账户表与登录/JWT。授权模型、权限点与判定全部在 `aoi_core`。

```sql
CREATE TABLE aoi_core.role (
  id SERIAL PRIMARY KEY,
  code VARCHAR(32) UNIQUE NOT NULL,          -- operator/admin/super_admin
  name_cn VARCHAR(64) NOT NULL,
  description TEXT, is_builtin BOOLEAN DEFAULT TRUE
);

CREATE TABLE aoi_core.permission (
  id SERIAL PRIMARY KEY,
  code VARCHAR(64) UNIQUE NOT NULL,          -- datasets.view / training.approve / ...
  module VARCHAR(32) NOT NULL,               -- datasets/training/review/system
  action VARCHAR(32) NOT NULL,               -- view/create/update/cancel/approve/publish
  name_cn VARCHAR(64)
);

CREATE TABLE aoi_core.role_permission (
  role_id INT REFERENCES aoi_core.role(id) ON DELETE CASCADE,
  permission_id INT REFERENCES aoi_core.permission(id) ON DELETE CASCADE,
  PRIMARY KEY(role_id, permission_id)
);

CREATE TABLE aoi_core.user_role (
  user_id INT NOT NULL,                      -- 逻辑引用 LS users.id，不建外键（上游表只读）
  role_id INT NOT NULL REFERENCES aoi_core.role(id) ON DELETE CASCADE,
  granted_by INT, granted_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(user_id, role_id)
);
```

- **权限点注册**：启动时由 `aoi/core/permissions.py` 的常量全量 upsert 到 `aoi_core.permission`，新增权限点无需手写数据迁移。
- **判定入口（P1 errata）**：DRF 权限类由 `aoi.common.permissions.aoi_permission('training.publish')` 生成（返回**类**，可放进 `permission_classes`；不要放实例——DRF 会无参实例化每一项）；每个 aoi 视图通过 `aoi_perm` / `aoi_perm_by_method` 声明自己的权限点，D4 只改 `AoiPermission.has_permission` 的实现。判定链 `user_role → role_permission → permission.code`；结果按用户缓存 5 分钟，授权变更时主动失效。
- **三角色定义**：`operator`（操作员）负责日常标注与复审；`admin`（管理员）负责数据集/训练/模型发布/复审等业务全量操作；`super_admin`（超级管理员）在管理员之上增加角色与用户授权、审计。**三角色只在平台 A 使用**，平台 B 无 RBAC、无用户认证。
- **默认权限矩阵**（`✅` 允许，`—` 拒绝）：

| 权限点 | `operator`（操作员） | `admin`（管理员） | `super_admin`（超级管理员） |
|---|---|---|---|
| `datasets.view` | ✅ | ✅ | ✅ |
| `datasets.create` / `datasets.update`（导入/标注） | ✅ | ✅ | ✅ |
| `datasets.export` | — | ✅ | ✅ |
| `prelabel.*` | — | ✅ | ✅ |
| `training.view` | ✅ | ✅ | ✅ |
| `training.create` / `cancel` / `approve` | — | ✅ | ✅ |
| `training.publish`（发布模型镜像） | — | ✅ | ✅ |
| `review.view` / `review.finalize` | ✅ | ✅ | ✅ |
| `system.roles` / `system.users`（角色与授权） | — | — | ✅ |
| `system.audit` | — | — | ✅ |

- **接口**：`GET /api/core/permissions` 返回当前用户 `{user_id, roles:[...], perms:[...]}`；`super_admin` 可 `CRUD /api/core/roles`、`POST /api/core/users/{id}/roles` 分配角色。
- **不共享**：RBAC 属 A 侧业务权限，**不进 `packages/`**；平台 B 无用户体系。
- **审计**：角色/授权变更写 `aoi_audit.audit_log`。

### 3.2 `aoi_datasets`

```sql
CREATE TABLE aoi_datasets.image (
  id SERIAL PRIMARY KEY,
  object_key VARCHAR(128) UNIQUE NOT NULL,   -- images/{md5}.jpg
  md5 CHAR(32) NOT NULL,
  source VARCHAR(24) NOT NULL,               -- manual_real/camera/reflux_review/prelabel_model_{id}
  station_code VARCHAR(32), seq BIGINT, captured_at TIMESTAMPTZ,
  width INT, height INT, size_bytes BIGINT,
  qc_status VARCHAR(16) DEFAULT 'pending',   -- pending/ok/rejected
  qc_reason VARCHAR(128),
  status VARCHAR(16) DEFAULT 'active', trace_id VARCHAR(64)
);

CREATE TABLE aoi_datasets.defect_class (
  id SERIAL PRIMARY KEY,
  code VARCHAR(32) UNIQUE NOT NULL,          -- object_fault_type_XX
  name_cn VARCHAR(64) NOT NULL,
  risk_level SMALLINT NOT NULL,              -- 3=高 2=中 1=低
  aliases JSONB DEFAULT '[]', active BOOLEAN DEFAULT TRUE
);

CREATE TABLE aoi_datasets.defect_dict_version (
  id SERIAL PRIMARY KEY,
  version VARCHAR(16) NOT NULL,
  snapshot JSONB NOT NULL,                   -- {labels:{code:{index,color}}}
  published_by INT, published_at TIMESTAMPTZ
);

CREATE TABLE aoi_datasets.dataset (
  id SERIAL PRIMARY KEY, name VARCHAR(128),
  cur_version VARCHAR(16), ls_project_id INT, created_by INT
);

CREATE TABLE aoi_datasets.dataset_version (
  id SERIAL PRIMARY KEY,
  dataset_id INT, version VARCHAR(16) NOT NULL,
  status VARCHAR(16) DEFAULT 'draft',        -- draft/published/archived
  phase VARCHAR(16) DEFAULT 'draft',         -- D2 三桶复审流程：draft/labeling/training/prelabeling/reviewing/published/archived
  split_seed INT, split_stats JSONB, class_dist JSONB, source_stats JSONB,
  dict_version VARCHAR(16), note TEXT, created_by INT,
  UNIQUE(dataset_id, version)
);

CREATE TABLE aoi_datasets.dataset_item (
  version_id INT, image_id INT, subset VARCHAR(8),   -- train/val/test
  PRIMARY KEY(version_id, image_id)
);

CREATE TABLE aoi_datasets.prelabel_task (
  id SERIAL PRIMARY KEY,
  dataset_id INT,
  backend_url VARCHAR(256),                  -- {A}/api/prelabel/{task_id}（A 自实现）
  model_ref VARCHAR(64), route_config JSONB, -- 三桶阈值（默认取自 model.yaml 的 recommended）
  status VARCHAR(16) DEFAULT 'queued',       -- P1：queued/running/succeeded/failed/canceled，服务端控制
  route_bucket JSONB,                        -- A 侧产出，只读（客户端不可写）
  created_by INT
);
```

### 3.3 `aoi_training`

```sql
CREATE TABLE aoi_training.base_model (
  id SERIAL PRIMARY KEY,
  name VARCHAR(64) UNIQUE NOT NULL,          -- yolov8s.pt
  framework VARCHAR(16) NOT NULL,            -- yolo
  task_type VARCHAR(32) NOT NULL,            -- skillname：ObjectDetection
  weights_key TEXT,                          -- 基础权重对象键
  params_schema JSONB, active BOOLEAN DEFAULT TRUE
);

CREATE TABLE aoi_training.preset (
  id SERIAL PRIMARY KEY,
  name VARCHAR(64) UNIQUE NOT NULL,
  framework VARCHAR(16) NOT NULL, task_type VARCHAR(32) NOT NULL,
  base_model VARCHAR(64), params JSONB, class_subset JSONB,
  created_by INT, active BOOLEAN DEFAULT TRUE
);

CREATE TABLE aoi_training.train_job (
  id SERIAL PRIMARY KEY,
  dataset_version VARCHAR(16) NOT NULL,
  framework VARCHAR(16) NOT NULL,            -- MVP 仅 yolo
  task_type VARCHAR(32) NOT NULL,            -- skillname
  preset JSONB NOT NULL,                     -- 含 class_subset
  status VARCHAR(16) DEFAULT 'queued',       -- queued/running/succeeded/failed/canceled
  celery_task_id VARCHAR(128),
  metrics JSONB, artifact_path TEXT, error_message TEXT,
  created_by INT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ
);

CREATE TABLE aoi_training.model (
  id SERIAL PRIMARY KEY,
  version VARCHAR(64) UNIQUE NOT NULL,       -- {seq}-{framework}@ds{version}
  framework VARCHAR(16), dataset_version VARCHAR(16),
  task_type VARCHAR(32) NOT NULL,            -- ObjectDetection（skillname）
  base_model VARCHAR(64), weights_key TEXT,
  class_names JSONB NOT NULL,                -- 索引序：["object_fault_type_01", ...]
  cover_classes JSONB NOT NULL,              -- ["object_fault_type_XX", ...]
  precision VARCHAR(8) DEFAULT 'fp32',
  input_shape JSONB, tensor_names JSONB,     -- {"input":"images","output":"output0"}
  eval_metrics JSONB,
  gate_status VARCHAR(16) DEFAULT 'pending', -- pending/passed/failed
  llm_review JSONB,                          -- 预留：LLM 参数复审报告
  lifecycle VARCHAR(16) DEFAULT 'candidate', -- candidate/approved/published/retired
  config_snapshot JSONB                      -- 含 model.yaml 快照（跨平台契约 §2.3）
);

CREATE TABLE aoi_training.model_publish (    -- 模型发布到镜像仓库（A→registry）
  id SERIAL PRIMARY KEY,
  model_ref VARCHAR(64) NOT NULL,
  registry VARCHAR(128) NOT NULL,            -- docker.io / registry.corp:5000
  image VARCHAR(256) NOT NULL,               -- <org>/aoi-model
  tag VARCHAR(128) NOT NULL,                 -- 3-yolo-ds1 / 3-yolo-ds1-fp16
  digest VARCHAR(128),                       -- sha256:...
  status VARCHAR(16) DEFAULT 'queued',       -- queued/building/pushing/published/failed
  attempts INT DEFAULT 0, error_message TEXT,
  published_by INT, created_at TIMESTAMPTZ DEFAULT now(), published_at TIMESTAMPTZ,
  UNIQUE(model_ref, tag)                     -- P1 errata：按 tag 唯一，fp16 才能单独发布
);
```

### 3.4 `aoi_review`

```sql
CREATE TABLE aoi_review.inspection_fact (
  id BIGSERIAL PRIMARY KEY,
  image_id INT,
  station_code VARCHAR(32) NOT NULL,         -- B 侧不透明 code
  station_name VARCHAR(64),                  -- B 回传的展示名（可空）
  seq BIGINT, channel_id INT, template_version INT,
  result_json JSONB NOT NULL,                -- {boxes, verdict, verdict_reasons, tiling_meta}
  verdict VARCHAR(16),                       -- 冗余便于查询
  instance_code VARCHAR(32),                 -- B 实例 code，如 B01（回传 meta.instance_code）
  latency_ms INT,
  status VARCHAR(16) DEFAULT 'initial',      -- initial/rechecking/finalized
  captured_at TIMESTAMPTZ, received_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(station_code, seq)                  -- 可疑图回传幂等（坏图走 bad_image）
);

CREATE TABLE aoi_review.review_workitem (
  id BIGSERIAL PRIMARY KEY,
  fact_id BIGINT,                            -- source=ingest 时指向 inspection_fact；预标来源为 NULL
  source VARCHAR(16) NOT NULL DEFAULT 'ingest',  -- ingest（B 回传）/ prelabel（A 预标三桶）
  dataset_version_id INT,                    -- source=prelabel：数据集版本
  image_id INT,                              -- source=prelabel：aoi_datasets.image.id
  ls_task_id INT,                            -- source=prelabel：LS task id（打开编辑器）
  ls_prediction_id BIGINT,                   -- source=prelabel：LS Prediction.id
  model_ref VARCHAR(64),                     -- 产生预标的模型
  bucket VARCHAR(8),                         -- high/medium/low（UI 三桶）
  verdict VARCHAR(16),                       -- auto_pass/recheck/manual（pipeline-core 原始值）
  bucket_reason JSONB,                       -- {reasons,scores,thresholds}
  forced BOOLEAN DEFAULT FALSE,              -- 低桶强制人工重标
  route VARCHAR(16) NOT NULL,                -- vlm/manual；MVP 统一 manual
  recheck_result JSONB,                      -- 预留：VLM 复审输出
  hv_key TEXT,                               -- 预留：高价值数据桶对象键
  status VARCHAR(16) DEFAULT 'pending',      -- pending/processing/finalized/failed
  assignee_id INT, final_verdict VARCHAR(32),
  final_reason VARCHAR(16),                  -- 误检/漏检/新缺陷/标注问题/光照异常
  finalized_at TIMESTAMPTZ
);

CREATE TABLE aoi_review.final_fact (
  id BIGSERIAL PRIMARY KEY,
  fact_id BIGINT, workitem_id BIGINT,
  source VARCHAR(16),                        -- ingest/prelabel
  dataset_version_id INT, image_id INT, ls_task_id INT,
  annotation_id BIGINT,                      -- 复审后写回的 LS Annotation.id
  action VARCHAR(24),                        -- accepted_prediction/edited/relabeled/no_defect/unlabelable
  verdict VARCHAR(32),                       -- defect_confirmed/false_alarm/uncertain
  class_id INT, boxes JSONB, decided_by INT, decided_at TIMESTAMPTZ
);

CREATE TABLE aoi_review.feedback_suggestion (
  id SERIAL PRIMARY KEY,
  workitem_id BIGINT, image_id INT,
  rule_code VARCHAR(8),                      -- R1~R4
  suggestion TEXT,
  status VARCHAR(16) DEFAULT 'suggested',    -- suggested/confirmed/rejected
  confirmed_by INT, confirmed_at TIMESTAMPTZ
);

CREATE TABLE aoi_review.bad_image (
  id SERIAL PRIMARY KEY,
  station_code VARCHAR(32) NOT NULL, station_name VARCHAR(64), seq BIGINT, captured_at TIMESTAMPTZ,
  error_code VARCHAR(16),                    -- capture_failed/decode_failed/timeout/model_error/disk_error
  image_key TEXT, instance_code VARCHAR(32),
  handled BOOLEAN DEFAULT FALSE, handled_by INT, note TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(station_code, seq)                  -- 回传幂等
);
```

### 3.5 `aoi_audit`

```sql
CREATE TABLE aoi_audit.audit_log (
  id BIGSERIAL PRIMARY KEY,
  actor_id INT, action VARCHAR(64), object_type VARCHAR(32), object_id VARCHAR(64),
  detail JSONB, request_id VARCHAR(64), created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 4. REST API 规格（`/api/*`）

> `/api/*` 下同时挂 LS 原生端点（登录/项目/任务/标注/上传/导出等，零改动）与 aoi 二开端点（下文）。二开端点统一信封（§2.3）。

### 4.0 通用

- 鉴权：Bearer JWT（§2.4）+ DRF 权限类；无凭据/凭据无效 → `40100`。
- 所有写操作建议带 `Idempotency-Key`。

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `POST /api/auth/login` | 匿名 | `{email, password}` → `{access, refresh, token_type, expires_in, user:{id,email}}`；凭据错误 `40100`（不区分账号/口令），字段缺失 `42200` |
| `POST /api/auth/logout` | 登录用户 | `{refresh}` 加入黑名单 → `{revoked: bool}`；幂等（无效/已吊销 → `revoked=false`），refresh 不属于当前用户 → `40300` |
| `GET /api/core/permissions` | 登录用户 | `{user_id, roles:[...], perms:[...]}`，供 A 前端控制按钮显隐（B 不调用，B 无 RBAC） |
| `CRUD /api/core/roles`、`POST /api/core/users/{id}/roles` | system.roles / system.users（super_admin） | 角色/权限点查看、用户角色分配（写审计） |

### 4.1 数据域 `/api/datasets`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `POST /import` | datasets.create | **包裹 LS 上传**：走 LS Upload/预签名入 MinIO → aoi 去重(md5)/坏图质检/元数据登记 → 登记入 LS project 任务。multipart `files[]` + form `source`/`station_code` → `{job_id}` |
| `GET /import/{job_id}` | datasets.view | `{status, total, ok, dup, bad, bad_items:[{filename, reason}]}` |
| `GET /images`、`GET /images/{id}/download` | datasets.view | 筛选/预签名下载 |
| `GET/POST/PUT /defects`、`POST /defects/publish` | datasets.* | 字典 CRUD；发布 → 渲染 label config（RectangleLabels，code=`object_fault_type_XX`）+ 版本快照 |
| `GET/POST /datasets`、`GET/PUT/DELETE /datasets/{id}`、`POST /datasets/{id}/versions` | datasets.* | 数据集/版本；发布触发划分 + **测试集红线**（违反 → 42200） |
| `GET /datasets/{id}/versions/{v}/export` | datasets.view | **复用 LS data_export（YOLO）** → zip 落 MinIO `datasets/exports/` |
| `GET /annotation-stats` | datasets.view | LS 标注/审核状态只读投影（不建表） |

### 4.2 训练域 `/api/train`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /base-models`、`GET /presets` | training.view | 基模/预置方案列表 + 可编辑字段 Schema |
| `POST /jobs` | training.create | `{dataset_version, framework:"yolo", preset:{...}}` → `{job_id}` |
| `GET /jobs/{id}` / `POST /jobs/{id}/cancel` | training.view/cancel | 状态/指标/取消 |
| `GET /jobs/{id}/progress` | training.view | **SSE**：`{phase, epoch, total, loss, metrics}`，`phase ∈ {training,evaluating,exporting,finished,failed}` |
| `GET /models?lifecycle=&task_type=` | training.view | 注册表：`[{id, version, framework, task_type, dataset_version, class_names, cover_classes, precision, weights_key, eval_metrics, gate_status, lifecycle}]` |
| `POST /models/{id}/approve` | training.approve | `{decision, note}` → `lifecycle=approved` |
| `POST /models/{id}/publish` | training.publish | **构建并推送模型镜像到 registry**（跨平台契约 §2.4）→ `{publish_id, status}` |
| `GET /models/{id}/publish` | training.view | 发布状态：`{image, tag, digest, status, attempts, error_message, published_at}` |

preset 结构：

```json
{"framework":"yolo","base_model":"yolov8s.pt",
 "class_subset":["object_fault_type_01","object_fault_type_02"],
 "params":{"tiling":{"size":1280,"overlap":0.2,"enabled":true},"imgsz":1280,
           "batch":8,"epochs":100,"lr0":0.01,"patience":20,
           "augment":{"flip":true,"mosaic":true,"mixup":0.1},
           "split":{"train":0.7,"val":0.2,"test":0.1}}}
```

### 4.3 预标域 `/api/prelabel`（LS 官方 ML backend 协议，A 自实现）

A 侧登记：LS 原生 ML 设置页 `MLBackend(url={A}/api/prelabel/{task_id})`，LS 调用 `{url}/{endpoint}`。

| 端点 | 请求/响应 |
|---|---|
| `GET /{task_id}/health` | → `{"status":"UP","model_version":"3-yolo@ds1"}` |
| `POST /{task_id}/setup` | → `{"model_version":"3-yolo@ds1","model_classes":{"object_fault_type_01":0,...}}`（与 label config 的 code 对齐） |
| `POST /{task_id}/predict` | 见下（**格式以仓库锁定的 LS tag 实测为准，B 提供 fixture**） |
| `POST /{task_id}/validate` | → `{"errors":[]}`（MVP 恒空） |
| `POST /{task_id}/webhook` | 预留 |

```json
// predict 请求
{"tasks":[{"id":101,"data":{"image":"http://ls-backend:8080/data/upload/1/abc.jpg"}}]}
// predict 响应（LS 1.x）
{"results":[{"id":101,"model_version":"3-yolo@ds1","result":[
  {"from_name":"defect","to_name":"image","type":"rectanglelabels",
   "score":0.72,"value":{"x":10.5,"y":12.3,"width":8.2,"height":5.6,"rotation":0,
   "rectanglelabels":["object_fault_type_01"]}}]}]}
```

- 取图：A 用 LS `/data/`（鉴权）或自建预签名拉取 `data.image`（D2 实测 `/data/...` 需鉴权；LS 默认不预签名）。
- 推理：`pipeline-core.run` + `OnnxRuntimeModel`（worker-gpu）；模型来自注册表 `lifecycle=approved`。
- 回写：走 LS 官方 predictions 回传；A 负责预标任务状态与三桶路由统计。
- **批量语义（D2 实测）**：LS 可能在一个 `predict` 请求中携带多个 `tasks`；A 必须**按请求顺序、按数量**返回同形 `results`，否则 LS 会降级为逐条重试或丢弃整批。
- 鉴权：见 §2.4；`aoi/prelabel` 默认放行 LS 调用，可选强制内部头。
- **预标范围（D2 确认）**：MVP 固定只对**未标注图片**推理（`scope=unlabeled_only`）；已有人工标注的图片不参与本轮预标。
- **三桶阈值优先级（D2 确认）**：`model.yaml` 的 `classes[].recommended` / `thresholds.default` → `prelabel_task.route_config` 覆盖（预设或人工微调）。
- 其余 A 业务接口见下表：预标任务 CRUD `/api/prelabel/tasks`（`prelabel.*`）。

### 4.4 复审域 `/api/review`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /workitems` / `POST /workitems/{id}/claim` / `POST /workitems/{id}/finalize` | review.* | 队列（支持 `source`/`dataset_version_id`/`bucket`/`status` 过滤）/认领/终裁；item 含 `bucket`（high/medium/low）+ 颜色 + `forced`；终裁 `{verdict, boxes?, final_reason, note, action, annotation?}`（原因必填；低桶/`forced` 必须带 `action ∈ {relabeled,no_defect,unlabelable}` 或 `annotation`） |
| `GET /suggestions` / `POST /suggestions/batch-confirm` | review.view/update | 建议清单/确认回流 |
| `GET /bad-images` / `POST /bad-images/{id}/handle` | review.* | 错误图片清单（人工重标签/重传入口） |

> 检测事实与坏图的**写入**来自 B，走 §4.7 的 `/api/ingest/findings`，本域只读查询 + 人工终裁。

### 4.5 系统域 `/api/system`

> A **没有工位与实例管理**：工位/相机/工位模板归平台 B；A 不主动连接 B，也不接收心跳。

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /audit` | system.audit（super_admin） | 审计查询（角色/授权、模型发布、训练、导出等关键操作） |

### 4.6 跨平台接收域 `/api/ingest`（内部头）

| 方法/路径 | 鉴权 | 说明 |
|---|---|---|
| `POST /findings` | `X-Internal-Token` | **B 回传错图**：`kind=suspicious` → `inspection_fact` + `review_workitem`；`kind=bad` → `bad_image`；均先落图片 → `{fact_id, workitem_id, image_id, bad_image_id, duplicated}`；幂等键 `(station_code, seq)`（按 kind 落不同表） |

> 完整字段、幂等与错误码见 `跨平台契约_A-B.md` §3。

---

## 5. 事件与异步任务

### 5.1 事件契约（Redis Streams，A 内部）

单流 `aoi.events`；信封：`{"event_id","produced_at","producer","type","payload"}`。

| type | 生产者 | 消费者 | payload |
|---|---|---|---|
| `dataset.published` | A | A(worker) | `{dataset_id, version}` |
| `training.completed` | A | A | `{train_job_id, model_ref, gate_status}` |
| `model.approved` | A | A（触发发布候选） | `{model_ref}` |
| `model.published` | A | A（审计） | `{model_ref, image, tag, digest}` |
| `review.finalized` | A | A（统计） | `{fact_id, workitem_id, verdict}` |
| `feedback.suggested` | A | A（统计） | `{rule_code, count}` |

> 平台 B **不接 Redis**，不消费/生产事件；跨平台交互只走镜像仓库（A→B）与错图回传（B→A）。

### 5.2 Celery 队列

| 队列 | 用途 | 资源 |
|---|---|---|
| `training` | YOLO 训练 / ONNX 导出 / 金标准回归 | GPU |
| `default` | 导入包裹 / 导出 / 统计 | CPU |
| `publish` | 模型发布（构建镜像 + docker push + 重试） | CPU + 网络 |

- LS 自带 `django_rq` 仅服务 LS 原生功能，保持不动；**aoi 二开任务统一 Celery**。
- 任务幂等：`Idempotency-Key` + 状态机 CAS；失败可重试，重试不产生重复副作用。

---

## 6. 存储契约（MinIO，A 侧）

| 桶/键 | 内容 | 写 | 读 |
|---|---|---|---|
| LS 原生存储（uploads/data，默认桶 `aoi-images`） | LS 上传/媒体 | LS | A 前端（预签名） |
| `images/{md5}.jpg` | aoi 原图登记（含 B 回传图片） | A | A |
| `datasets/exports/{dataset}_{version}.zip` | LS data_export 产物 | A | A |
| `models/{model_ref}/{precision}/model.onnx` + `.sha256` + `model.yaml` | 模型产物（发布源，含能力描述） | A | A（构建镜像时读取） |
| `goldens/goldens.json` + `g001~g003.jpg` | 金标准（A 侧回归用，**不跨机传输**） | A | A |
| `hv-data/` | 高价值数据桶（二期） | 二期 | 二期 |
| `tmp/` | 中转 | A | A |

> **D2 实测**：LS 原生上传落 MinIO 私有桶；`/data/...` 需鉴权访问，`AWS_QUERYSTRING_AUTH=False` 时 LS 默认不生成预签名 URL；LS 后端无缩略图端点。预签名 URL 与缩略图由 aoi 导入/下载包裹（D4）补足。
> 平台 B **不读 A 的 MinIO**：模型由 A 打成镜像推送到 registry，B 从 registry 拉取；图片由 B 回传后由 A 写入 MinIO。

---

## 7. 模型能力描述与镜像发布（A 产出；B 消费）

**A 不再拥有/下发方案模板**：检测模板由 B 在自己的 GUI 里配置（平台 B 契约 §3.3）。A 通过模型镜像里的 `model.yaml` 给出模型能力与**推荐阈值**。

- `model.yaml` 字段与校验规则：见 `跨平台契约_A-B.md` §2.3；
- 镜像布局、命名、tag 规范、digest 固定：见 `跨平台契约_A-B.md` §2.1、§2.2；
- 发布流程与状态机：见 `跨平台契约_A-B.md` §2.4；A 侧表 `aoi_training.model_publish`（§3.3）。

A 侧生成 `model.yaml` 的数据来源（字段级别见跨平台契约 §2.3）：

| 字段分组 | 来源 |
|---|---|
| 元信息（`model_ref`/`skillname`/`framework`/`framework_version`/`dataset_version`/`dict_version`/`base_model`/`precision`/`created_at`/`license`） | `aoi_training.model` + `aoi_training.base_model` + `aoi_datasets.defect_dict_version` |
| `source`（train_job_id/created_by/git_commit） | `aoi_training.train_job` + 发布时环境 |
| `onnx.*`（sha256/size/opset/ir/producer/张量名/形状/动态批） | ONNX 导出结果 + `onnxruntime` 探测 |
| `onnx.input.*`（dtype/layout/color_order/normalize/resize） | 训练/导出配置（Ultralytics 导出默认 RGB、letterbox） |
| `classes[].code`/`index`/`enabled` | `aoi_training.model.class_names`（索引序） |
| `classes[].name_cn`/`name_en`/`risk_level`/`color`/`aliases` | `aoi_datasets.defect_class` |
| `classes[].recommended` | 评估结果 + 字典风险档默认值（发布前可人工微调） |
| `postprocess`/`tiling`/`thresholds` | 训练 preset（`aoi_training.preset.params`）+ 导出默认值 |
| `metrics`/`gate_status` | `aoi_training.model.eval_metrics` / `gate_status` |
| `benchmark` | 发布前基准推理（可空） |
| `training`（超参/增强/划分） | `aoi_training.train_job.preset` |
| `requires`（skillname/pipeline_core/schema/onnxruntime） | 发布时公共包与运行时版本 |
| 二期预留（`signature`/`sbom_ref`/`golden_summary`/`calibration`/`quantization`/`extensions`） | MVP 一律 `null`/`{}`，字段位先占住 |

---

## 8. 模型产物与门禁（A 侧执行）

| 项 | 约定 |
|---|---|
| 导出参数 | opset=17、dynamic batch、`imgsz=训练同尺寸`、onnxsim |
| 命名 | `models/{model_ref}/fp32/model.onnx`、`.../fp16/model.fp16.onnx` + `.sha256` |
| 张量 | Ultralytics 导出为准（`images`→`output0`），导出日志附实际张量名与形状 |
| 注册表 | `aoi_training.model`：`class_names`/`cover_classes`/`eval_metrics`/`gate_status`/`lifecycle` |
| 门禁 | 任一对象召回 < 风险档下限（高 99% / 中 97% / 低 95%）→ `gate_failed` 一票否决；误报率超限（3/5/8%）仅告警 |
| 金标准 | A 侧加载模型跑 `goldens/`，召回 100% 才允许 `approved`；失败回退上一版本并告警 |
| FP16 | 召回跌幅 > 1pt 自动回退 FP32 |
| 发布前置 | `lifecycle=approved` + 人工审批 + 金标准通过 + `model.yaml` 生成 + sha256 计算完成 |

---

## 9. 训练数据导出契约（复用 LS data_export）

- MVP 用 **LS 原生 YOLO 导出**：D2 实测 LS 1.24 产物为 `images/`、`labels/`、`classes.txt`、`notes.json`；**没有 `data.yaml`**。`classes.txt` 的行顺序即 label config / 字典快照顺序（以 `classes.txt` 为 names 权威来源）。
- aoi 包裹职责：数据集版本 ↔ LS project 绑定；导出前执行**测试集红线**（test 子集含非 `manual_real` → 42200 拒绝）；导出后校验 `classes.txt` 的 names 与字典发布版本一致，zip 落 `datasets/exports/`。
- `data.yaml` 是 Ultralytics 训练配置，不是 LS 导出产物：由 aoi 训练包裹（D9）在训练时按需生成，**不作为导出 zip 的必备项**（D2 裁定，见变更记录）。
- `code ↔ 索引` 映射随字典快照同步，并写入模型 `model.yaml` 的 `classes[].index`（B 侧工位模板据此构建 `class_map`）。
- 自研 zip 导出仅作二期兜底。

---

## 10. 复审 / 重标签 / 回流契约

1. **复审自研（D2 裁定）**：LS OSS 无 Review 流，**不复用 LS Review**；复审由 `aoi/review` 自研接口承担（`workitems/claim/finalize`、`suggestions`、`bad-images`）。
2. **首轮训练 → 预标签 → 三桶复审（主流程，D2 确认）**：用户在少量已标注图片上做**首轮训练**（不是外部预训练）；训练出的模型对**剩余未标注图片**做预标签（`scope=unlabeled_only`），写入 LS predictions 并由 `pipeline-core` 输出 `verdict ∈ {auto_pass, recheck, manual}` → 三桶：
   - 高/`auto_pass`/绿：系统**自动转 annotation**，写 auto-finalized 复审记录（`final_fact.action=accepted_prediction`）；
   - 中/`recheck`/黄：生成 `review_workitem`（`route=manual`），建议人工确认/微调；
   - 低/`manual`/红：生成 `review_workitem`（`route=manual`, `forced=true`），**强制人工重标**后才能 finalize；
   - B 回传 suspicious 仍落 `review_workitem`，与预标三桶共用同一队列；
   - 全部 workitem finalized 后，**人工确认 + 系统校验**（低桶已重标、校验通过）→ `dataset_version.phase=published` 落版，供后续训练使用。
3. **B 回传复审**：B 回传 `/api/ingest/findings` → A 建 `inspection_fact` + `review_workitem`（`route=manual`）→ 同样走人工终裁；与预标三桶共用同一复审队列。
4. **回流**：R1~R4 规则 → `feedback_suggestion` → 人工确认 → 图片以 `source=reflux_review` 进数据集候选（红线：不进测试集）。
5. **坏图**：`bad_image` 清单人工重标签/重传后置 `handled=true`。
6. 状态枚举：`inspection_fact.status ∈ {initial, rechecking, finalized}`；`workitem.status ∈ {pending, processing, finalized, failed}`。

> **预标三桶复审的完整数据流向与待确认 schema**（`review_workitem` 扩展、`dataset_version` 过程状态、低/中/高桶动作语义）见 `docs/设计_预标三桶复审流程.md`；确认后回写 §3.4/§4.4 与本文。

---

## 11. 训练契约

- 状态机：`queued → running → succeeded/failed/canceled`；succeeded 附 `gate_status` 与 `model_ref`。
- 资源：A 训练与 B 推理在不同机器，天然互斥，无需分时调度。
- LLM 参数复审：预留 `LLMReviewer` + `StubLLMReviewer`（返回「需人工确认」），上线必经人工 approve。

---

## 12. 预留接口（二期实现，接口现在冻结）

```python
# A：label_studio/aoi/training/llm_reviewer.py
class LLMReviewer(ABC):
    def review(self, config_snapshot, metrics, gate, bad_cases) -> ReviewReport: ...
# MVP: StubLLMReviewer -> ReviewReport(verdict="需人工确认", rationale="LLM 复审未接入")

# 复审后端抽象（B 侧二期实现 VLM 时，A 只改注册配置）
class RecheckBackend(ABC):
    def recheck(self, image_ref, boxes) -> RecheckResult: ...
# MVP: ManualRecheckBackend —— route=vlm 工作项自动转人工队列
```

---

## 13. 契约测试与 LS 原生 smoke 清单

### 13.1 契约测试

- `tests/contracts/test_pipeline_core.py`（共享包，A/B 同跑）：切片/合并/三档判定/`load_config`/StubRuntimeModel。
- `tests/contracts/test_platform_a_api.py`：信封/鉴权/**权限锚点（每视图声明权限点；D2 恒放行，见下）**/导入幂等/训练状态机（approve/publish 门禁与 40401）/**模型发布（model.yaml 生成 + 镜像 tag 规范 + `(model_ref, tag)` 唯一）**/`/api/ingest/findings` 幂等（含半写补建）/复审状态机（claim/finalize 并发与低桶强制）。
  - **RBAC 覆盖延期（P1 标注）**：三角色矩阵、越权 `40300`、授权缓存失效属 **D4** 交付（`AoiPermission.has_permission` 目前仅要求登录）；D2 只测试"权限锚点已声明 + 匿名 40100"，避免文档声称了不存在的覆盖。
- fixtures：`detect_result_sample.json`、`findings_ingest_sample.json`、`model_yaml_sample.yaml`、`ml_backend_predict_sample.json`、`goldens.json`。
- stub 原则：aoi API 在 D3 前全量 stub + OpenAPI。

### 13.2 LS 原生 smoke 清单（D2 复用验证日逐项实测，以实测为准回写本文档）

1. 登录 + token API（HS256 JWT，claims 含 `user_id`）。
2. 新建项目 + label config 注入（RectangleLabels，code=`object_fault_type_XX`）。
3. 上传图片 + 缩略图 + 预签名下载。
4. 框标注编辑器交互（RectangleLabels）。
5. Review 流（标注→审核→通过/驳回）。
6. data_export YOLO 导出（`images/labels/data.yaml` 布局实测记录）。
7. ML 设置页登记 `MLBackend(url={A}/api/prelabel/{task_id})` → `/{task_id}/health` 连通。
8. Batch predictions 对 A 的预标端点发起（D12~13 预标用）。

---

## 变更记录

> 破坏性变更一律走四件套：**改文档 + 改 stub + 改 fixture + 双方契约测试过**。

| 日期 | 条目 | 变更 | 四件套证据 |
|---|---|---|---|
| 2026-09-09 | datasets CRUD 路径（T2.9） | §4.1 字面 `CRUD /datasets`（落库为 `/api/datasets/datasets`）**修正**为 `GET/POST /api/datasets` + `GET/PUT/DELETE /api/datasets/{id}`；旧路径 `/api/datasets/datasets*` 不再存在 | ① 本文档 §4.1 与本表；② stub 路由 `label_studio/aoi/datasets/urls.py`（`path('', …)` + `path('/<int:id>', …)`）；③ fixture `tests/contracts/fixtures/aoi_api_paths.json`（含 `/api/datasets/{id}`）；④ `tests/contracts/test_platform_a_api.py::test_datasets_path_contract`（`/api/datasets/{id}` 200、`/api/datasets/datasets` 404） |
| 2026-09-09 | 上传/存储表述修正（T2.7） | §1/§6 明确：D2 实测 LS 无服务端缩略图、`/data/` 需鉴权且默认不预签名；缩略图/预签名由 aoi 导入/下载包裹（D4）补足，LS 原生通道仍复用 | ① 本表 + §1/§6；② stub `ImageDownloadView`（URL 返回，D4 接预签名）；③ fixture `aoi_api_paths.json`；④ `TestAllStubs`/`test_ls_reuse_smoke.py::test_03` |
| 2026-09-09 | YOLO 导出布局修正（T2.7/T2.9） | §9 由 `data.yaml` 修正为 LS 原生 `images/ + labels/ + classes.txt + notes.json`；names 顺序以 `classes.txt` 为准；`data.yaml` 由训练包裹（D9）按需生成，不作导出必备项 | ① 本表 + §9；② stub `DatasetExportView`（`classes_source=classes.txt`、`data_yaml=null`）；③ fixture `yolo_export_layout_sample.json`；④ `TestExportContract::test_yolo_export_layout_contract` |
| 2026-09-09 | 复审流程明确（T2.7） | §1/§10 由「复用 LS Review」修正为「自研 aoi 复审」；主流程为预标三桶（`auto_pass/recheck/manual`）→ `recheck/manual` 进人工复审 → `final_fact`；B 回传 findings 共用同一队列 | ① 本表 + §1/§10；② stub `aoi/review/*`（workitems/claim/finalize）；③ fixture `aoi_api_paths.json`；④ `TestAllStubs` + `test_review_finalize_requires_reason` |
| 2026-09-09 | JWT/ML backend 鉴权说明（T2.7） | §2.4/§4.3 补充：`/api/token/` 为 refresh，业务接口用 access + Bearer；LS 调预标端点不携带内部头，默认放行、可选强制 40100；批量 predict 按序等量返回 | ① 本表 + §2.4/§4.3；② stub `aoi/prelabel/views.py`（可选内部头）；③ fixture `ml_backend_predict_sample.json`（`observed_request_headers`）；④ `TestPrelabelProtocol`（含 batch 顺序/数量） |
| 2026-09-09 | 预标三桶复审数据形状（D2） | 确认：MVP 先矩形；首轮训练→预标签（仅未标注图）→三桶（高 auto_pass/绿自动标注、中 recheck/黄建议人工、低 manual/红强制人工）→人工确认+系统校验后落版；`review_workitem` 采用方案 A 扩展；`dataset_version` 新增 `phase`；阈值 model.yaml recommended → prelabel_task.route_config | ① 本表 + §3.2/§3.4/§4.3/§4.4/§10；② `aoi_review` 0002/`aoi_datasets` 0002 迁移 + stub；③ fixture `review_flow_sample.json`；④ `TestReviewFlowContract` |
| 2026-09-10 | 排期同步（**非语义**，接口/字段/状态机不变） | §13.2 第 8 项预标日期 D15 → **D12~13**：预标开发提前到复审之前（先预标后复审），三桶人工复审 D13~15；见《MVP开发计划》§1/§5 | ① 本表 + §13.2；②③④ 无需变更（无契约语义改动） |

| 2026-09-10 | D2 review P0/P1 修复（**语义变更**） | ① `model_publish` 唯一性 `UNIQUE(model_ref)` → **`UNIQUE(model_ref, tag)`**（fp16 才能单独发布）；② `prelabel_task.status` 补默认 `queued` + 枚举，状态由服务端控制（`route_bucket` 只读）；`dataset_version` 创建时 `status/phase` 一律 draft；③ RBAC 判定入口由 `AoiPermission('x')`（实例，DRF 不可用）改为 **`aoi_permission('x')` 工厂 + 视图 `aoi_perm` 锚点**；④ 明确 RBAC 三角色矩阵/40300/缓存失效为 D4 交付（§13.1 标注） | ① 本表 + §3.1/§3.2/§3.3/§4.1/§4.3/§13.1；② stub 与迁移：`aoi_training/0003`、`aoi_datasets/0003`、`aoi_review/0003`；③ fixture 无字段变化（`aoi_api_paths.json` 已含相关路径）；④ `TestTrainingPublishGuards`/`TestStateMachineInjection`/`TestPermissionAnchors`/`TestReviewStateMachine` |
| 2026-09-10 | 认证链路标准化（D3，**语义变更**） | ① 新增 `POST /api/auth/login`（匿名，email+password → access/refresh）与 `POST /api/auth/logout`（refresh 进黑名单，幂等）；② Bearer 校验从 `jwt_auth.middleware.JWTAuthenticationMiddleware` 迁到 **DRF 认证类**（`aoi.common.authentication.AoiJWTAuthentication`），中间件已从 `MIDDLEWARE` 移除；③ 显式 `SIMPLE_JWT`（access 30 min / refresh 7 天 / 不轮换，理由见 §2.4）；④ 上游 `/api/token/*`、`/user/login/`（浏览器 session）与 `X-Internal-Token` **语义不变** | ① 本表 + §2.4/§4.0；② 实现 `label_studio/aoi/core/auth.py`、`aoi/common/authentication.py`、`core/settings/base.py`、`aoi/urls.py`；③ fixture `aoi_api_paths.json`（版本 `d3-20260910`，新增两条 auth 路径与 `auth: public`）；④ `TestAoiJwtAuth`（15 例：登录/刷新/登出黑名单/Bearer 打 aoi 与 LS 原生端点/浏览器 session 回归/中间件移除守卫） |

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方测试过。*
