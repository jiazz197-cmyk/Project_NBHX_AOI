# 平台 A 接口与数据契约（训练与标注平台，LS 二开）

> 归属：**B 主笔**（主数据源 / 业务接口 / 二开包裹）；消费：A 侧前端、Celery workers、平台 B（仅经跨平台契约）。
> 冻结基线：D2；变更窗口：D9 / D15。跨平台接口（模型/方案下发、错图回传、心跳）见 `跨平台契约_A-B.md`，不在此重复。
> 技术栈：Django + DRF（LS 1.x fork）、PostgreSQL 15、MinIO、Redis 7 + Celery 5。

---

## 0. 范围与原则

- 平台 A 是**唯一主数据源**：缺陷字典、数据集、标注、训练、模型注册、方案模板、工位。
- LS 原生能力**能用则用**（§1）；二开只做五个业务新域（datasets / prelabel / training / review / plans）+ 四个支撑 app（core / system / audit / reports）+ 薄包裹。
- 平台 B 不直连 A 的数据库/对象存储；A 也不直连 B 的数据库。所有跨平台交互走 `跨平台契约_A-B.md`。
- **sidecar 已取消**：原 sidecar 的 ML backend 协议与预标推理归 A 自身（Django + Celery GPU worker + `pipeline-core`）。

---

## 1. LS 原生复用对照表

| 平台功能 | LS 原生能力（直接复用） | aoi 二开薄包裹 | MVP 决策 |
|---|---|---|---|
| 登录/令牌 | token API（JWT HS256，claims 含 `user_id`） | 无 | **复用** |
| 用户/组织/角色 | LS users + 组织角色框架 | 三角色↔LS 角色映射 + 权限点表（`aoi/core`） | 复用+映射 |
| 标注项目/任务 | `projects/tasks/annotations` 原生 | label config 由缺陷字典渲染注入 | **复用** |
| 框标注交互 | 标注编辑器（RectangleLabels） | 零改动（红线） | **复用** |
| 数据浏览 | Data Manager | 零重构（红线） | **复用** |
| 标注审核 | LS Review 流（标注→审核） | aoi 只读投影统计；不满足再降级平台审核接口 | **复用** |
| 文件上传/存储 | LS 文件存储（MinIO）+ 预签名 URL + 缩略图 | aoi 导入包裹：去重/质检/元数据登记 | 复用+包裹 |
| 预标回写 | `ml/` MLBackend 连接器 + Batch predictions | **A 侧自实现 ML backend 协议**（`aoi/prelabel`） | 复用+自实现 |
| 数据集导出 | `data_export`（YOLO/COCO） | aoi 版本绑定 + 测试集红线 + `data.yaml` 校验 | **复用** |
| 前端框架 | web/apps 组件库/路由/auth store/i18n | Menubar 入口 + 二开页面 | 复用+加页 |
| 审计（部分） | LS activity log | `aoi/audit` 关键操作追加写 | 复用+补充 |

**结论**：账户、标注、上传、审核、预标通道、导出六块几乎零开发；B 的主战场是「字典 / 数据集版本 / 训练 / 复审 / 方案模板」五个新域 + 薄包裹 + 模型下发。

---

## 2. 通用工程约定

### 2.1 术语与枚举（权威定义在 `packages/skillname`）

| 术语 | 定义 |
|---|---|
| `skillname` | 任务类型：`ObjectDetection`（MVP 唯一）→ LS 控件 `RectangleLabels` |
| `object_fault_type_XX` | 缺陷对象 code，XX 两位数字（01~99），由缺陷字典配置 |
| `model_ref` | 模型注册版本号，格式 `{seq}-{framework}@ds{version}`，如 `3-yolo@ds1` |
| `plan_id` / `plan_version` | 检测方案模板标识与版本 |
| `station_code` | 工位 code，`ST01`~`ST08`（主数据在 A） |
| `verdict` | 初检判定：`auto_pass` / `recheck` / `manual`（语义在 `pipeline-core`） |
| `source` | 图片来源：`manual_real` / `camera` / `reflux_review` / `prelabel_model_{id}` |
| `kind` | 回传类型：`suspicious`（可疑图）/ `bad`（坏图） |

> 枚举值**不得**在 A 侧硬编码副本；统一 `from skillname import ...`。

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
| 404 | 40401 / 40402 | 资源不存在 / 工位未注册未启用 |
| 409 | 40900 | 状态冲突（重复激活/重复批次/幂等冲突） |
| 422 | 42200 | 业务校验失败（`detail.fields`） |
| 429 | 42900 | 限流 |
| 500 | 50000 | 内部错误 |
| 503 | 50300 | 依赖不可用（B 不可达/存储异常） |

### 2.4 鉴权

- **前端 → A**：LS 原生 token API 签发的 JWT（HS256，`JWT_SECRET` = LS `SECRET_KEY`，claims 含 `user_id`）；权限点由 DRF 权限类判断。
- **B → A（回传/心跳）**：`X-Internal-Token: <INTERNAL_TOKEN>`；`X-Instance-Code` 标识 B 实例，供审计。
- **A → B（下发）**：`X-Platform-Token`，见跨平台契约 §1.2。
- 权限点（模块级）：`datasets.*`、`training.*`、`review.*`、`plans.*`、`system.*`；动作 `view/create/update/cancel/approve/rollback/dispatch`。

### 2.5 公共请求约定

- 请求头：`X-Request-ID`（nginx 生成并贯穿日志）；`Idempotency-Key`（导入/训练/激活/下发等写操作必带）。
- 时间 ISO8601 UTC；编码 UTF-8；分页 `?page=&page_size=`，响应 `{total, items}`。
- 文件上传 multipart：字段 `file`/`files`，单图 ≤100MB；MVP 不做分片断点。

---

## 3. 数据模型（PostgreSQL 主数据源）

> LS 原生表（projects/tasks/annotations/ml/users）**只读复用、不修改语义**（红线）；aoi 业务表独立 schema。平台 B 不直连本库。

### 3.1 `aoi_datasets`

```sql
CREATE TABLE aoi_datasets.image (
  id SERIAL PRIMARY KEY,
  object_key VARCHAR(128) UNIQUE NOT NULL,   -- images/{md5}.jpg
  md5 CHAR(32) NOT NULL,
  source VARCHAR(24) NOT NULL,               -- manual_real/camera/reflux_review/prelabel_model_{id}
  station_id INT, station_code VARCHAR(32), seq BIGINT, captured_at TIMESTAMPTZ,
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
  model_ref VARCHAR(64), route_config JSONB, -- 三桶阈值（默认与方案模板同源）
  status VARCHAR(16), route_bucket JSONB, created_by INT
);
```

### 3.2 `aoi_training`

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
  lifecycle VARCHAR(16) DEFAULT 'candidate', -- candidate/approved/online/retired
  config_snapshot JSONB
);

CREATE TABLE aoi_training.model_dispatch (   -- 模型下发状态（A→B）
  id SERIAL PRIMARY KEY,
  model_ref VARCHAR(64) NOT NULL,
  target_code VARCHAR(32) DEFAULT 'B01',     -- B 实例（MVP 单实例）
  status VARCHAR(16) DEFAULT 'queued',       -- queued/uploading/verifying/ready/failed
  upload_id VARCHAR(128), bytes_sent BIGINT, sha256 CHAR(64),
  attempts INT DEFAULT 0, error_message TEXT,
  requested_by INT, created_at TIMESTAMPTZ DEFAULT now(), acked_at TIMESTAMPTZ,
  UNIQUE(model_ref, target_code)
);
```

### 3.3 `aoi_review`

```sql
CREATE TABLE aoi_review.inspection_fact (
  id BIGSERIAL PRIMARY KEY,
  image_id INT,
  station_id INT, station_code VARCHAR(32), seq BIGINT, channel_id INT,
  plan_id VARCHAR(64) NOT NULL, plan_version INT NOT NULL,
  result_json JSONB NOT NULL,                -- {boxes, verdict, verdict_reasons, tiling_meta}
  verdict VARCHAR(16),                       -- 冗余便于查询
  source_platform VARCHAR(32),               -- B 实例 code，如 B01
  latency_ms INT,
  status VARCHAR(16) DEFAULT 'initial',      -- initial/rechecking/finalized
  captured_at TIMESTAMPTZ, received_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(station_code, seq)                  -- 可疑图回传幂等（坏图走 bad_image）
);

CREATE TABLE aoi_review.review_workitem (
  id BIGSERIAL PRIMARY KEY,
  fact_id BIGINT NOT NULL,
  route VARCHAR(16) NOT NULL,                -- vlm/manual；MVP 中 vlm 由 stub 转 manual
  recheck_result JSONB,                      -- 预留：VLM 复审输出
  hv_key TEXT,                               -- 预留：高价值数据桶对象键
  status VARCHAR(16) DEFAULT 'pending',      -- pending/processing/finalized/failed
  assignee_id INT, final_verdict VARCHAR(32),
  final_reason VARCHAR(16),                  -- 误检/漏检/新缺陷/标注问题/光照异常
  finalized_at TIMESTAMPTZ
);

CREATE TABLE aoi_review.final_fact (
  id BIGSERIAL PRIMARY KEY,
  fact_id BIGINT, verdict VARCHAR(32),       -- defect_confirmed/false_alarm/uncertain
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
  station_id INT, station_code VARCHAR(32), seq BIGINT, captured_at TIMESTAMPTZ,
  error_code VARCHAR(16),                    -- capture_failed/decode_failed/timeout/model_error/disk_error
  image_key TEXT, source_platform VARCHAR(32),
  handled BOOLEAN DEFAULT FALSE, handled_by INT, note TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(station_code, seq)                  -- 回传幂等
);
```

### 3.4 `aoi_plans` / `aoi_system` / `aoi_audit`

```sql
CREATE TABLE aoi_plans.plan (
  id SERIAL PRIMARY KEY,
  plan_id VARCHAR(64) UNIQUE NOT NULL,       -- PLAN-{A-Z0-9-}
  name VARCHAR(128), created_by INT
);

CREATE TABLE aoi_plans.plan_version (
  id SERIAL PRIMARY KEY,
  plan_id VARCHAR(64) NOT NULL,
  version INT NOT NULL,
  content_yaml TEXT NOT NULL,
  checksum CHAR(64) NOT NULL,                -- yaml 的 SHA256
  status VARCHAR(16) DEFAULT 'draft',        -- draft/active/archived
  dispatch_status VARCHAR(16),               -- 推送 B 的结果：pending/ok/failed
  dispatch_detail JSONB,                     -- B 返回的 checks[]
  activated_by INT, activated_at TIMESTAMPTZ,
  created_by INT, UNIQUE(plan_id, version)
);

CREATE TABLE aoi_system.station (
  id SERIAL PRIMARY KEY,
  code VARCHAR(32) UNIQUE NOT NULL,          -- ST01~ST08
  name VARCHAR(64), enabled BOOLEAN DEFAULT FALSE,
  channel_id VARCHAR(32), config JSONB,
  door_model VARCHAR(64),
  plan_id VARCHAR(64), plan_version INT      -- 工位绑定检测方案模板
);

CREATE TABLE aoi_system.infer_instance (     -- B 实例注册与心跳
  id SERIAL PRIMARY KEY,
  code VARCHAR(32) UNIQUE NOT NULL,          -- B01
  name VARCHAR(64), base_url VARCHAR(256),
  enabled BOOLEAN DEFAULT TRUE,
  last_heartbeat_at TIMESTAMPTZ,
  version_json JSONB, status_json JSONB
);

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

- 鉴权：LS JWT（§2.4）+ DRF 权限类。
- 所有写操作建议带 `Idempotency-Key`。

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /api/core/permissions` | 登录用户 | `{user_id, role, perms:[...]}`，供 A 前端控制按钮显隐（B 不调用，B 无 RBAC） |

### 4.1 数据域 `/api/datasets`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `POST /import` | datasets.create | **包裹 LS 上传**：走 LS Upload/预签名入 MinIO → aoi 去重(md5)/坏图质检/元数据登记 → 登记入 LS project 任务。multipart `files[]` + form `source`/`station_code` → `{job_id}` |
| `GET /import/{job_id}` | datasets.view | `{status, total, ok, dup, bad, bad_items:[{filename, reason}]}` |
| `GET /images`、`GET /images/{id}/download` | datasets.view | 筛选/预签名下载 |
| `GET/POST/PUT /defects`、`POST /defects/publish` | datasets.* | 字典 CRUD；发布 → 渲染 label config（RectangleLabels，code=`object_fault_type_XX`）+ 版本快照 |
| `CRUD /datasets`、`POST /datasets/{id}/versions` | datasets.* | 数据集/版本；发布触发划分 + **测试集红线**（违反 → 42200） |
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
| `POST /models/{id}/dispatch` | training.dispatch | **推送到 B**（跨平台契约 §2）→ `{dispatch_id, status}` |
| `GET /models/{id}/dispatch` | training.view | 下发状态：`{status, target_code, attempts, bytes_sent, error_message, acked_at}` |

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
  {"from_name":"defect","to_name":"doorpanel","type":"rectanglelabels",
   "score":0.72,"value":{"x":10.5,"y":12.3,"width":8.2,"height":5.6,"rotation":0,
   "rectanglelabels":["object_fault_type_01"]}}]}]}
```

- 取图：A 用 LS 存储/预签名拉取 `data.image`。
- 推理：`pipeline-core.run` + `OnnxRuntimeModel`（worker-gpu）；模型来自注册表 `lifecycle=approved`。
- 回写：走 LS 官方 predictions 回传；A 负责预标任务状态与三桶路由统计。
- 其余 A 业务接口见下表：预标任务 CRUD `/api/prelabel/tasks`（`prelabel.*`）。

### 4.4 复审域 `/api/review`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /workitems` / `POST /workitems/{id}/claim` / `POST /workitems/{id}/finalize` | review.* | 队列/认领/终裁 `{verdict, boxes?, final_reason, note}`（原因必填） |
| `GET /suggestions` / `POST /suggestions/batch-confirm` | review.view/update | 建议清单/确认回流 |
| `GET /bad-images` / `POST /bad-images/{id}/handle` | review.* | 错误图片清单（人工重标签/重传入口） |

> 检测事实与坏图的**写入**来自 B，走 §4.7 的 `/api/ingest/findings`，本域只读查询 + 人工终裁。

### 4.5 方案模板域 `/api/inspect/plans`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET/POST /plans` | plans.view/create | `{plan_id, name, content_yaml}` → 自动 version=1 |
| `GET /plans/{plan_id}/versions`、`.../versions/{v}` | plans.view | 版本列表 / yaml+checksum |
| `POST /plans/{plan_id}/versions/{v}/activate` | plans.update | **同步整链**：A 校验 → 写 MinIO → **推送 B** → B 校验/热加载/自检 → 回写 active。失败 42200/50300 不落 active |

激活时序：

```
前端 --activate--> A（校验 schema/字典/模型注册表/工位）--写桶--> MinIO plans/
A --POST {B}/api/v1/ingest/plan {plan_id,version,checksum,content_yaml,stations}--> B
B: 校验 code/model_ref/阈值 → 加载模型 → 加载自检 → 原子切换
B --{ok,loaded_models,checks}--> A --plan_version.active--> 前端
```

### 4.6 系统域 `/api/system`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `CRUD /stations` | system.* | `{code, name, enabled, channel_id, config, plan_id, plan_version}` |
| `POST /stations/{id}/bind-plan` | system.update | `{plan_id, plan_version}` |
| `GET /instances` | system.view | B 实例列表：`{code, base_url, last_heartbeat_at, version_json, status_json, online}` |
| `GET /audit` | system.view（仅管理员） | 审计查询 |

### 4.7 跨平台接收域 `/api/ingest`（内部头）

| 方法/路径 | 鉴权 | 说明 |
|---|---|---|
| `POST /findings` | `X-Internal-Token` | **B 回传错图**：`kind=suspicious` → `inspection_fact` + `review_workitem`；`kind=bad` → `bad_image`；均先落图片 → `{fact_id, workitem_id, image_id, bad_image_id, duplicated}`；幂等键 `(station_code, seq)`（按 kind 落不同表） |
| `POST /heartbeat` | `X-Internal-Token` | B 心跳：upsert `infer_instance`，版本比对告警 |

> 完整字段、幂等与错误码见 `跨平台契约_A-B.md` §4、§5。

---

## 5. 事件与异步任务

### 5.1 事件契约（Redis Streams，A 内部）

单流 `aoi.events`；信封：`{"event_id","produced_at","producer","type","payload"}`。

| type | 生产者 | 消费者 | payload |
|---|---|---|---|
| `dataset.published` | A | A(worker) | `{dataset_id, version}` |
| `training.completed` | A | A | `{train_job_id, model_ref, gate_status}` |
| `model.approved` | A | A（触发下发候选） | `{model_ref}` |
| `dispatch.ready` | A | A | `{model_ref, target_code}` |
| `plan.activated` | A | A（审计） | `{plan_id, version}` |
| `review.finalized` | A | A（统计） | `{fact_id, workitem_id, verdict}` |
| `feedback.suggested` | A | A（统计） | `{rule_code, count}` |

> 平台 B **不接 Redis**，不消费/生产事件；跨平台交互一律走 HTTP 契约。

### 5.2 Celery 队列

| 队列 | 用途 | 资源 |
|---|---|---|
| `training` | YOLO 训练 / ONNX 导出 / 金标准回归 | GPU |
| `default` | 导入包裹 / 导出 / 统计 | CPU |
| `dispatch` | 模型下发（分片上传 + 重试） | CPU + 网络 |

- LS 自带 `django_rq` 仅服务 LS 原生功能，保持不动；**aoi 二开任务统一 Celery**。
- 任务幂等：`Idempotency-Key` + 状态机 CAS；失败可重试，重试不产生重复副作用。

---

## 6. 存储契约（MinIO，A 侧）

| 桶/键 | 内容 | 写 | 读 |
|---|---|---|---|
| LS 原生存储（uploads/data，默认桶 `aoi-images`） | LS 上传/媒体 | LS | A 前端（预签名） |
| `images/{md5}.jpg` | aoi 原图登记（含 B 回传图片） | A | A |
| `datasets/exports/{dataset}_{version}.zip` | LS data_export 产物 | A | A |
| `models/{model_ref}/{precision}/model.onnx` + `.sha256` | 模型产物（下发源） | A | A（推送时读取） |
| `plans/{plan_id}/v{version}.yaml` | 方案模板版本 | A | A |
| `goldens/goldens.json` + `g001~g003.jpg` | 金标准（A 侧回归用，**不跨机传输**） | A | A |
| `hv-data/` | 高价值数据桶（二期） | 二期 | 二期 |
| `tmp/` | 中转 | A | A |

> 平台 B **不读 A 的 MinIO**：模型由 A 读取后经 HTTP 分片推送到 B；图片由 B 回传后由 A 写入 MinIO。

---

## 7. 检测方案模板 Schema（A 拥有；B 消费）

```yaml
# plans/PLAN-DOORPANEL-STD/v3.yaml
plan_id: PLAN-DOORPANEL-STD
version: 3
objects:
  - code: object_fault_type_01
    model_ref: 3-yolo@ds1
    class_map: {0: object_fault_type_01}
    thresholds: {recheck_min: 0.60, auto_min: 0.90}
    risk_level: 3
  - code: object_fault_type_02
    model_ref: 3-yolo@ds1
    class_map: {1: object_fault_type_02}
    thresholds: {recheck_min: 0.55, auto_min: 0.88}
    risk_level: 2
stations:
  ST01: {plan: PLAN-DOORPANEL-STD, enabled: true}
  ST02: {plan: PLAN-DOORPANEL-STD, enabled: true}
```

校验（A 保存、B 接收均执行，规则一致，实现在 `pipeline-core.load_plan` + `skillname`）：

1. `plan_id` 匹配 `^[A-Z0-9-]{4,64}$`；`objects` 非空、`code` 唯一。
2. `code` ∈ 缺陷字典 active 项，且符合 `object_fault_type_XX`。
3. `model_ref` ∈ 注册表且 `gate_status=passed`、`lifecycle=approved`；`cover_classes` 含该 code；`task_type=ObjectDetection`。
4. `class_map` 非空、value 全等于该 code，且 value ∈ 模型 `class_names`。
5. `0 < recheck_min < auto_min < 1`。
6. `stations` 的 code 存在于工位表；`enabled=true` 必须有绑定。

变更 = 新版本 + checksum；激活 = A 推送 B 成功 → 标 `active`（旧版归档）；回滚 = 推送历史版本（带 `allow_rollback`）。

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
| 下发前置 | `lifecycle=approved` + 人工审批 + 金标准通过 + sha256 计算完成 |

---

## 9. 训练数据导出契约（复用 LS data_export）

- MVP 用 **LS 原生 YOLO 导出**：标注批次（project）导出 YOLO zip（`images/`、`labels/`、`data.yaml`，classes 按 label config 顺序）。
- aoi 包裹职责：数据集版本 ↔ LS project 绑定；导出前执行**测试集红线**（test 子集含非 `manual_real` → 42200 拒绝）；导出后校验 `data.yaml` 的 names 与字典发布版本一致，zip 落 `datasets/exports/`。
- `code ↔ 索引` 映射随字典快照同步（方案模板 `class_map` 与模型 `class_names` 参考）。
- 自研 zip 导出仅作二期兜底。

---

## 10. 复审 / 重标签 / 回流契约

1. **标注与审核**：复用 LS 原生 Review 流（标注→审核）；aoi 只读投影统计，不建表。
2. **推理结果复审**：B 回传 `/api/ingest/findings` → A 建 `inspection_fact` + `review_workitem`（MVP `route=vlm` 由 stub 转 manual）→ 工程师终裁（确认/驳回/改标/补框 + 必填原因）→ 落 `final_fact`。
3. **回流**：R1~R4 规则 → `feedback_suggestion` → 人工确认 → 图片以 `source=reflux_review` 进数据集候选（红线：不进测试集）。
4. **坏图**：`bad_image` 清单人工重标签/重传后置 `handled=true`。
5. 状态枚举：`inspection_fact.status ∈ {initial, rechecking, finalized}`；`workitem.status ∈ {pending, processing, finalized, failed}`。

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

- `tests/contracts/test_pipeline_core.py`（共享包，A/B 同跑）：切片/合并/三档判定/方案校验/StubRuntimeModel。
- `tests/contracts/test_platform_a_api.py`：信封/鉴权/权限点/导入幂等/训练状态机/方案激活/`/api/ingest/findings` 幂等。
- fixtures：`detect_result_sample.json`、`inspection_finding_sample.json`、`plan_template_sample.yaml`、`ml_backend_predict_sample.json`、`goldens.json`。
- stub 原则：aoi API 在 D3 前全量 stub + OpenAPI。

### 13.2 LS 原生 smoke 清单（D2 复用验证日逐项实测，以实测为准回写本文档）

1. 登录 + token API（HS256 JWT，claims 含 `user_id`）。
2. 新建项目 + label config 注入（RectangleLabels，code=`object_fault_type_XX`）。
3. 上传图片 + 缩略图 + 预签名下载。
4. 框标注编辑器交互（RectangleLabels）。
5. Review 流（标注→审核→通过/驳回）。
6. data_export YOLO 导出（`images/labels/data.yaml` 布局实测记录）。
7. ML 设置页登记 `MLBackend(url={A}/api/prelabel/{task_id})` → `/{task_id}/health` 连通。
8. Batch predictions 对 A 的预标端点发起（D15 预标用）。

---

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方测试过。*
