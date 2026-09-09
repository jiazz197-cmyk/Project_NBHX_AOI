# 平台 B 接口与数据契约（推理与检测平台，轻量）

> 归属：**C 主笔**；消费：B 独立前端、相机适配器、镜像仓库拉取模块。
> 冻结基线：D2；变更窗口：D9 / D15。跨平台接口（模型镜像发布/拉取、错图回传）见 `跨平台契约_A-B.md`，不在此重复。
> 技术栈：FastAPI + Uvicorn（单进程）、SQLite（WAL）、本地磁盘、APScheduler、ONNX Runtime、`pipeline-core` + `skillname`。

---

## 0. 范围与轻量化约束

### 0.1 范围

平台 B 只做五件事：**拉取模型 → 配置工位模板 → 按模板推理 → 统计与日报 → 错图回传**。
不做：用户体系/RBAC/登录认证、数据集与标注、训练、字典维护、模型训练、视频流、大屏。
**工位、相机、工位模板全部由 B 自管**（A 不持有、不下发）。

### 0.2 轻量化硬约束（评审红线）

1. 依赖只允许：`fastapi`、`uvicorn[standard]`、`python-multipart`、`pydantic`、`sqlalchemy`、`onnxruntime`（或 `onnxruntime-gpu`）、`numpy`、`pillow`、`jinja2`、`apscheduler`、`httpx`、`pyyaml`、`skillname`、`pipeline-core`。
2. **禁止**：Redis、Celery、RabbitMQ、Kafka、MinIO、Django、LS 前端组件、K8s、Docker daemon（可选，见 §3.2）。
3. 单进程：1 个 Uvicorn worker + 进程内线程池；定时任务用 APScheduler，不另起 worker。
4. 数据库默认 SQLite（WAL）；不强制外部 PostgreSQL。
5. 前端首屏静态资源 gzip 后 ≤ 2MB；仅 5 个页面。
6. 任何新增依赖需在评审中说明「不加会怎样」，并更新本节清单。

---

## 1. 通用约定

### 1.1 访问控制（无 RBAC、无用户认证）

> B **不做用户体系、不做登录、不做任何用户认证**；三角色 RBAC（操作员/管理员/超级管理员）只在平台 A 使用。
> B 的接口仅在内网/产线网段暴露，靠**网络隔离**而非账号控制。

| 调用方 | 认证 | 说明 |
|---|---|---|
| B 前端 / 现场运维（查询与写操作） | **无** | 打开即用；不校验用户身份，写操作只记本地操作日志 |
| 相机/模拟器 → `/inspect/image` | **无** | 内网调用；由本机相机适配器或 A 的节拍模拟器发起 |
| B → 镜像仓库（拉模型） | registry 只读凭据 | 公开仓库可留空；与用户体系无关 |
| B → A（回传） | 携带 A 的 `X-Internal-Token` | 由平台 A 校验；B 只透传 |

- 审计字段 `actor` 取调用来源（`local` / `camera` / `registry`），不关联用户。
- B 不因认证失败返回 401（除回传 A 时 A 侧返回）。

### 1.2 统一信封与错误码

成功：`{"code":0,"message":"ok","request_id":"req-...","data":{...}}`

| HTTP | code | 含义 |
|---|---|---|
| 400 | 40010 | 坏图/镜像层解包失败/sha256 不符/参数不可读 |
| 404 | 40401 / 40402 | 资源不存在 / 工位未注册未启用 |
| 409 | 40900 | 状态冲突（同 `model_ref` 不同 digest、模板版本冲突） |
| 422 | 42200 | 业务校验失败（`data.detail.fields`） |
| 429 | 42900 | 队列背压 / registry 限流（可重试） |
| 500 | 50000 | 内部错误 |
| 503 | 50300 | 未就绪（模型加载失败/磁盘不足/无可用 GPU） |

> registry 鉴权失败时透传 `40100`（见跨平台契约 §1.4），这是 B 唯一会返回 401 的场景。

### 1.3 公共请求约定

- 头：`X-Request-ID`、`Idempotency-Key`（回传类写操作）。
- 时间 ISO8601 UTC；分页 `?page=&page_size=`（默认 20，最大 200），响应 `{total, items}`。
- 大图读取走 `GET /api/v1/inspections/{id}/image`（流式），不内联 base64。

---

## 2. 数据模型（SQLite，`b_` 前缀）

```sql
CREATE TABLE b_model (
  model_ref TEXT PRIMARY KEY,
  skillname TEXT NOT NULL,                   -- ObjectDetection
  framework TEXT NOT NULL,                   -- yolo
  dataset_version TEXT,
  class_names TEXT NOT NULL,                 -- JSON 数组，索引序
  cover_classes TEXT NOT NULL,               -- JSON 数组
  precision TEXT NOT NULL DEFAULT 'fp32',    -- fp32/fp16
  config_json TEXT NOT NULL,                 -- model.yaml 原文（含推荐阈值/展示名/张量信息）
  source_image TEXT,                         -- 拉取来源镜像，如 docker.io/<org>/aoi-model:3-yolo-ds1
  image_digest TEXT,                         -- sha256:...
  sha256 TEXT NOT NULL,                      -- model.onnx 的 sha256
  size_bytes INTEGER NOT NULL,
  opset INTEGER, input_name TEXT, output_name TEXT, input_shape TEXT,
  stored_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',      -- pulling/ready/active/failed
  received_at TEXT NOT NULL, activated_at TEXT
);
CREATE UNIQUE INDEX idx_b_model_sha ON b_model(sha256);

CREATE TABLE b_station (
  code TEXT PRIMARY KEY,                     -- ST01~ST08（B 自管）
  name TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  channel_id TEXT,
  camera_config TEXT,                        -- JSON：adapter/source/trigger/fps_limit/config
  template_json TEXT,                        -- JSON：工位模板（§3.3），未配置为 NULL
  template_version INTEGER DEFAULT 0,
  status TEXT DEFAULT 'offline',             -- online/offline/error
  last_capture_at TEXT, last_error TEXT
);

CREATE TABLE b_defect_class (                -- 展示用字典（从模型 config 派生，非主数据）
  code TEXT PRIMARY KEY,                     -- object_fault_type_XX
  name_cn TEXT NOT NULL,
  risk_level INTEGER, color TEXT,
  source_model_ref TEXT, updated_at TEXT NOT NULL
);

CREATE TABLE b_inspection (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_code TEXT NOT NULL, seq INTEGER NOT NULL,
  captured_at TEXT NOT NULL, received_at TEXT NOT NULL,
  template_version INTEGER,
  model_refs TEXT,                           -- JSON 数组
  verdict TEXT NOT NULL,                     -- auto_pass/recheck/manual
  verdict_reasons TEXT,                      -- JSON 数组
  boxes TEXT,                                -- JSON 数组（DetectBox）
  tiling_meta TEXT,                          -- JSON
  latency_ms INTEGER,
  image_path TEXT, thumb_path TEXT, image_md5 TEXT,
  pushed_status TEXT DEFAULT 'n/a',          -- n/a/pending/pushing/pushed/dead
  pushed_at TEXT, created_at TEXT NOT NULL,
  UNIQUE(station_code, seq)
);
CREATE INDEX idx_b_inspection_time ON b_inspection(captured_at);
CREATE INDEX idx_b_inspection_verdict ON b_inspection(verdict);

CREATE TABLE b_bad_image (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_code TEXT NOT NULL, seq INTEGER NOT NULL,
  captured_at TEXT, error_code TEXT NOT NULL,
  image_path TEXT, image_md5 TEXT, note TEXT,
  pushed_status TEXT DEFAULT 'pending',      -- pending/pushing/pushed/dead
  pushed_at TEXT, created_at TEXT NOT NULL,
  UNIQUE(station_code, seq)
);

CREATE TABLE b_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                        -- suspicious/bad
  ref_id INTEGER NOT NULL,                   -- b_inspection.id / b_bad_image.id
  idempotency_key TEXT NOT NULL UNIQUE,      -- {station}-{seq}-{kind}
  payload TEXT NOT NULL,                     -- JSON meta（跨平台契约 §3.2）
  attempts INTEGER DEFAULT 0,
  next_retry_at TEXT,
  status TEXT DEFAULT 'pending',             -- pending/pushing/pushed/dead
  last_error TEXT, created_at TEXT NOT NULL, pushed_at TEXT
);

CREATE TABLE b_stats_daily (
  day TEXT NOT NULL,                         -- YYYY-MM-DD（captured_at 本地日）
  station_code TEXT NOT NULL,
  total INTEGER DEFAULT 0, auto_pass INTEGER DEFAULT 0,
  recheck INTEGER DEFAULT 0, manual INTEGER DEFAULT 0,
  bad_count INTEGER DEFAULT 0,
  defect_counts TEXT,                        -- JSON {object_code: count}
  error_counts TEXT,                         -- JSON {error_code: count}
  avg_latency_ms INTEGER, p95_latency_ms INTEGER,
  PRIMARY KEY (day, station_code)
);

CREATE TABLE b_report (
  day TEXT PRIMARY KEY,
  html_path TEXT, csv_path TEXT,
  stats_json TEXT, generated_at TEXT
);

CREATE TABLE b_setting (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);

CREATE TABLE b_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT, action TEXT, object_type TEXT, object_id TEXT,
  detail TEXT, request_id TEXT, created_at TEXT NOT NULL
);
```

**SQLite 约定**：`journal_mode=WAL`、`synchronous=NORMAL`、`busy_timeout=5000`；写操作经单写锁串行化；统计聚合按分钟批量写入。
**没有 `b_plan` 表**：方案模板概念已被「工位模板」取代，直接存 `b_station.template_json`（含 `template_version`）。

---

## 3. REST API（`/api/v1`）

### 3.1 健康与系统

| 方法/路径 | 说明 |
|---|---|
| `GET /health` | 服务/GPU/磁盘/模型/工位/outbox 总览 |
| `GET /system/info` | 版本（platform/skillname/pipeline_core/schema）、配置摘要、路径、依赖版本 |
| `GET /system/outbox` | 回传队列：`{pending, pushing, dead, items[]}` |
| `POST /system/outbox/{id}/retry`、`POST /system/outbox/retry-all` | 手动重推 |
| `GET /system/audit` | 本地操作日志 |

```json
GET /api/v1/health
{"code":0,"message":"ok","request_id":"req-...","data":{
  "status":"UP",
  "gpu":{"device":0,"mem_used_gb":3.2,"mem_total_gb":23.7},
  "disk":{"free_gb":120.4,"used_pct":62},
  "models":[{"model_ref":"3-yolo@ds1","precision":"fp32","loaded":true,"vram_gb":3.8}],
  "stations":{"total":8,"enabled":8,"online":7,"with_template":8},
  "inspect":{"queue":0,"concurrency":2},
  "outbox":{"pending":3,"dead":0}}}
```

### 3.2 模型库（从镜像仓库拉取）

| 方法/路径 | 说明 |
|---|---|
| `GET /models` | 本地模型列表：`{model_ref, skillname, precision, sha256, source_image, image_digest, status, classes, received_at}` |
| `GET /models/{model_ref}` | 详情（含 `config_json`：类别/推荐阈值/张量名与形状） |
| `POST /models/pull` | **从镜像仓库拉取**：`{image: "<registry>/<org>/aoi-model:3-yolo-ds1", digest?: "sha256:..."}` → 拉 manifest/层 → 解包 → 校验 → 注册；返回 `{model_ref, digest, status, classes}` |
| `POST /models/import` | **离线导入**：multipart 上传 `docker save` 或层 tar → 同样校验/注册 |
| `POST /models/{model_ref}/preload` | 预加载 ONNX 会话 |
| `POST /models/{model_ref}/unload` | 卸载（被启用工位模板引用时 → `40900`） |
| `DELETE /models/{model_ref}` | 删除本地文件与记录（被引用时 → `40900`） |

- 拉取模式：`MODEL_PULL_MODE=oci`（默认，httpx 直连 Registry v2，无需 Docker）或 `docker`（本机 `docker pull` + `docker create` + `docker cp`）。
- 校验规则与失败语义见跨平台契约 §2.3、§2.5。
- 模型只是「能力供给」；**启用与否由工位模板决定**（§3.3）。

### 3.3 工位、相机与工位模板（B 自管，GUI 编辑）

| 方法/路径 | 说明 |
|---|---|
| `CRUD /stations` | 工位主数据：`{code, name, enabled, channel_id}`（B 自建，如 ST01~ST08） |
| `PUT /stations/{code}/camera` | 相机配置：`{adapter, source, trigger, fps_limit, config}` |
| `POST /stations/{code}/enable` / `disable` | 启停 |
| `POST /stations/{code}/capture` | 软触发一次采集+推理 |
| `GET /stations/{code}/snapshot` | 最近一帧快照 |
| `GET /stations/{code}/template` | 读取工位模板（未配置时返回 `null` + `suggest` 建议值） |
| `PUT /stations/{code}/template` | **保存工位模板**（GUI 编辑结果）→ 校验 → 热加载 |
| `POST /stations/{code}/template/validate` | 只校验不保存（GUI 实时校验用） |

工位模板（存 `b_station.template_json`）：

```json
{
  "template_version": 3,
  "model_ref": "3-yolo@ds1",
  "skillname": "ObjectDetection",
  "tile_size": 1280,
  "overlap": 0.2,
  "objects": [
    {"code": "object_fault_type_01", "class_map": {"0": "object_fault_type_01"},
     "thresholds": {"recheck_min": 0.60, "auto_min": 0.90}, "risk_level": 3},
    {"code": "object_fault_type_02", "class_map": {"1": "object_fault_type_02"},
     "thresholds": {"recheck_min": 0.55, "auto_min": 0.88}, "risk_level": 2}
  ]
}
```

校验（保存与热加载前均执行，实现在 `pipeline-core.load_config` + `skillname`）：

1. `model_ref` ∈ 本地 `b_model` 且 `status=ready`；
2. `objects` 非空、`code` 唯一且通过 `skillname.is_valid_fault_code`；
3. `code` ∈ 该模型 `class_names`；`class_map` 的 value 全等于 `code` 且 key ∈ 模型类别索引；
4. `0 < recheck_min < auto_min < 1`；
5. `tile_size > 0`、`0 ≤ overlap < 1`；
6. 保存时 `template_version` 自增；校验失败 → `42200` + `detail.fields`。

> GUI 新建模板时，默认值取自模型 `config_json.classes[].recommended`（A 给的推荐阈值）；操作员可覆盖。A 不下发模板。

### 3.4 推理

```http
POST /api/v1/inspect/image
Content-Type: multipart/form-data

-- file=@img.jpg, station_code=ST01, captured_at=2026-09-08T08:30:00Z, seq=42
```

响应：

```json
{"code":0,"data":{
  "inspection_id":98765,"station_code":"ST01","seq":42,
  "template_version":3,
  "verdict":"recheck","verdict_reasons":["mid_score"],
  "boxes":[{"object_code":"object_fault_type_01","score":0.72,"model_ref":"3-yolo@ds1","xyxy":[100,200,180,260]}],
  "tiling_meta":{"tile_size":1280,"overlap":0.2,"tiles":12,"ms":1400},
  "latency_ms":1400,"pushed":true}}
```

错误：`40402` 工位未注册/未启用；`42200` 工位未配置模板；`40010` 坏图（同时登记 `b_bad_image`）；`42900` 队列满；`50300` 模型未就绪。

`POST /api/v1/inspect/batch`：`{"object_keys":["images/ab..cd.jpg"],"station_code":"ST01"}` → `{job_id, total, ok, failed}`（本地目录/对象键批量补跑）。

### 3.5 检测记录

| 方法/路径 | 说明 |
|---|---|
| `GET /inspections` | 筛选：`station_code`、`verdict`、`kind`（suspicious/bad）、`from`、`to`、`pushed_status`、分页 |
| `GET /inspections/{id}` | 详情（含 boxes/tiling_meta/template_version/model_refs） |
| `GET /inspections/{id}/image` | 原图（流式，`?download=1` 下载） |
| `GET /inspections/{id}/thumb` | 缩略图 |
| `GET /bad-images` | 坏图清单（按 `error_code`/工位/时间筛选） |

### 3.6 统计

| 方法/路径 | 说明 |
|---|---|
| `GET /stats/summary?range=today\|7d\|30d&station_code=` | 信息统计卡片（§6.1） |
| `GET /stats/trend?from=&to=&station_code=&bucket=hour\|day` | 检测量/三档/时延趋势 |
| `GET /stats/errors?from=&to=&station_code=` | 错图统计（§6.2） |

### 3.7 日报

| 方法/路径 | 说明 |
|---|---|
| `GET /reports/daily?from=&to=` | 日报列表 |
| `GET /reports/daily/{day}` | 日报详情（HTML 片段 + stats_json） |
| `POST /reports/daily/{day}/generate` | 手动重生成（补跑历史日） |
| `GET /reports/daily/{day}/export?format=html\|csv` | 导出 |

---

## 4. 推理链路

### 4.1 执行顺序

```
接收图片 → 解码（坏图 → 40010 + 登记 bad_image）
  → 取工位模板（无模板 → 42200；模型未 ready → 50300）
  → pipeline-core.load_config(template_json) → InspectConfig
  → pipeline-core.run(image, cfg, models)
       ① 按 model_ref 分组对象
       ② slice_image(tile_size, overlap)
       ③ OnnxRuntimeModel.infer(tiles)（批推理，FP32/FP16）
       ④ box_to_global + merge_across_tiles(NMS)
       ⑤ decide_verdict（逐对象阈值，宁错不漏）
  → 落 b_inspection（含 image/thumb）
  → verdict != auto_pass → 写 b_outbox（suspicious）→ 异步回传 A
  → 返回响应
```

- 并发：`INSPECT_CONCURRENCY=2` 线程池；队列 `INSPECT_QUEUE_MAX=32`，满则 `42900`。
- 多模型：按 `model_ref` 分组分发；MVP ≤ 2 个检测模型；逐框带 `model_ref`。
- 超时：单图推理超时 `INFER_TIMEOUT_MS`（默认 10000）→ `manual` + `model_error` 登记。

### 4.2 判定语义（`pipeline-core.decide_verdict`，宁错不漏）

- `auto_pass`：无框，或全框 `score ≥ auto_min` 且风险等级低/中。
- `recheck`：存在 `recheck_min ≤ score < auto_min`，或存在高风险框。
- `manual`：存在 `score < recheck_min`，或模型异常/超时。
- 不确定一律不自动放行。

### 4.3 结果结构（`b_inspection` 存储与回传同构）

```json
{"boxes":[{"object_code":"object_fault_type_01","score":0.72,"model_ref":"3-yolo@ds1","xyxy":[100,200,180,260]}],
 "verdict":"recheck","verdict_reasons":["mid_score"],
 "tiling_meta":{"tile_size":1280,"overlap":0.2,"tiles":12,"ms":1400}}
```

### 4.4 模型加载自检（拉取后 / 模板启用时）

1. ONNX 会话可创建；
2. 输入/输出张量名与形状与 `model.yaml` 一致；
3. 1 张空白图空跑成功且耗时 < 5s；
4. 任一失败 → 模型 `status=failed` / 模板启用失败 `50300`，不影响已有模型与工位。

> 金标准回归在 A 侧模型门禁阶段完成，B 不重复执行（跨平台契约 §2.4）。

---

## 5. 相机接入与坏图处理

### 5.1 适配器

| 适配器 | 用途 | MVP |
|---|---|---|
| `DirectorySource` | 目录轮询仿真（8 通道仿真用） | ✅ |
| `GigEAdapter` | 真实 GigE 相机（软触发） | ✅ 1 路（D17） |
| `RtspAdapter` | RTSP 拉流抽帧 | 二期 |
| `HttpPushAdapter` | 外部系统推图（等价 `/inspect/image`） | ✅ 天然支持 |

`camera_config` 示例：`{"adapter":"gige","source":"192.168.1.10","trigger":"soft","fps_limit":2,"config":{"exposure_us":8000}}`。

### 5.2 采集原则（不可检测原则）

- 采集失败/超时/解码失败 → 登记 `b_bad_image`（`error_code` 明确）→ 回传 A；**绝不伪造合格**。
- 工位未启用/未配置模板 → 不采集（`40402`/`42200`）。
- 每工位 `seq` 单调递增（重启后从 `b_inspection` 最大值 +1 继续）。
- 时间戳以采集时刻为准（`captured_at`），回传时附 `received_at`。

---

## 6. 统计口径

### 6.1 信息统计（`/stats/summary`、`/stats/trend`）

| 指标 | 口径 |
|---|---|
| 检测总量 | `b_inspection` 条数（按 `captured_at` 归档） |
| 三档分布 | `verdict` 计数与占比 |
| 合格率 | `auto_pass / total` |
| 缺陷 TopN | 按 `object_code` 统计框数 + 涉及图片数（一个图多框去重计图）；返回 `name_cn`（取自 `b_defect_class`，缺失回退 code） |
| 节拍 | 每工位每分钟检测量（`bucket=hour` 时按小时） |
| 时延 | `latency_ms` 的 avg 与 P95 |
| 工位在线 | `b_station.status=online` 占比（相机适配器在线，或最近采集时间 < 3 个节拍） |
| 运行状态 | 已加载模型、工位模板版本、outbox pending、磁盘水位 |

### 6.2 错图统计（`/stats/errors`）

| 指标 | 口径 |
|---|---|
| 坏图数 | `b_bad_image` 计数，按 `error_code` 分组 |
| 可疑图数 | `b_inspection.verdict != auto_pass` 计数，按 `object_code` / `verdict` 分组 |
| 错图率 | (坏图 + 可疑图) / (检测总量 + 坏图) |
| Top 工位 | 按工位数聚合坏图与可疑图 |
| 回传状态 | `pushed/pending/dead` 计数（与 outbox 一致） |

### 6.3 聚合与保留

- `b_stats_daily` 由 APScheduler 每 5 分钟滚动更新当日行；每日 00:05 定稿前一日。
- 统计查询优先读 `b_stats_daily`；当日与自定义区间可实时聚合 `b_inspection`（限制单次查询 ≤ 31 天）。

---

## 7. 日报

- 生成：每日 `00:10`（`REPORT_CRON` 可配）生成前一日日报；支持 `POST /reports/daily/{day}/generate` 补跑。
- 日界按 B 本地时区 `TZ`（默认 `Asia/Shanghai`）切分；库内时间戳仍存 UTC（`captured_at`）。
- 渲染：Jinja2 → `report/templates/daily.html.j2`；落 `/data/reports/{day}.html` + `{day}.csv`。
- 内容：
  1. 概览：检测总数、三档分布、合格率、可疑率、错图率；
  2. 分工位：检测量、三档、坏图数、节拍、时延（avg/P95）；
  3. 缺陷 TopN：`object_code`（含 `name_cn`）框数与图片数；
  4. 坏图汇总：`error_code` 分布；
  5. 异常事件：模型拉取/切换、工位模板变更、相机离线、outbox 积压、磁盘水位告警；
  6. 附录：模型版本、工位模板版本、平台/公共包版本、生成时间。
- 保留 90 天（`REPORT_RETENTION_DAYS`）；导出格式 HTML / CSV（PDF 二期）。

---

## 8. 存储与保留策略

```
/data/
├── infer.db                          # SQLite（WAL：infer.db-wal/-shm）
├── models/{model_ref}/{precision}/model.onnx (+ .sha256, model.yaml)
├── images/{yyyy}/{mm}/{dd}/{station_code}/{seq}_{md5}.jpg
├── thumbs/{yyyy}/{mm}/{dd}/{station_code}/{seq}.jpg
├── reports/{yyyy-mm-dd}.html / .csv
├── logs/
└── tmp/pull/{digest}/                # 拉取临时目录，成功后原子 rename，失败清理
```

| 数据 | 默认保留 | 说明 |
|---|---|---|
| `auto_pass` 原图 | **不落盘**（`AUTO_PASS_KEEP_IMAGE=false`） | 仅缩略图，保留 7 天 |
| `auto_pass` 缩略图 | 7 天 | `AUTO_PASS_KEEP_THUMB=true` |
| 可疑图/坏图原图 | 30 天 | **未 `pushed` 的不清理** |
| 检测记录（元数据） | 365 天 | 清理原图不删记录 |
| 模型 | 最近 3 个版本 | 被启用工位模板引用的不清理 |
| 日报 | 90 天 | — |
| 拉取临时目录 | 24h | — |

磁盘水位：`> 80%` 告警；`> 90%` 停止落原图（只留元数据 + 缩略图）并置 `disk_error` 告警，恢复后自动解除。

---

## 9. 前端（独立，5 页）

| 页面 | 路由 | 内容 |
|---|---|---|
| 概览 | `/` | 今日检测量、三档分布、合格率/错图率、缺陷 TopN、节拍、时延 P95、工位在线、模型/模板版本、outbox 状态 |
| 检测记录 | `/inspections` | 列表 + 筛选（工位/判定/时间/回传状态）+ 图片与框预览；错图统计视图（坏图按 `error_code`、可疑图按 `object_code`） |
| 日报 | `/reports` | 日报列表、详情、HTML/CSV 导出 |
| 工位与相机 | `/stations` | 工位增删改、相机配置、启停、软触发、快照；**工位模板编辑**（选模型 → 勾类别 → 调阈值，带实时校验） |
| 系统 | `/system` | 健康、**模型库（拉取/离线导入/删除/预加载）**、outbox 队列与重推、保留策略、版本信息 |

技术：Vite + React + TS + Ant Design 5 + ECharts；构建产物由 FastAPI `StaticFiles` 托管，SPA fallback 到 `index.html`。
开发：Vite dev server 代理 `/api` 到 `http://localhost:8990`。
无登录页、无用户菜单、无口令弹窗；所有页面打开即用（靠内网/产线网段隔离，见 §1.1）。

---

## 10. 部署与运维

### 10.1 交付形态

- **Docker Compose（推荐）**：单服务（backend + 静态前端）+ `./data` 卷。
- **systemd**：无 Docker 环境时用 venv + 静态目录 + `uvicorn` 单元文件（`MODEL_PULL_MODE=oci` 无需 Docker）。

```yaml
# infer-platform/deploy/docker-compose.yml
services:
  infer:
    build: {context: ../.., dockerfile: infer-platform/deploy/Dockerfile}
    image: aoi-infer:0.1.0
    restart: unless-stopped
    ports: ["8990:8990"]
    environment:
      - DB_PATH=/data/infer.db
      - DATA_DIR=/data
      - MODEL_REGISTRY=docker.io
      - MODEL_PULL_MODE=oci
      - ONNX_PROVIDER=cuda
    volumes:
      - ./data:/data
    deploy:
      resources:
        reservations:
          devices: [{capabilities: [gpu], count: 1}]   # CPU 部署时删除
```

### 10.2 升级与备份

- 升级：停服 → 备份 `/data` → 替换镜像/包 → 启动（自动执行顺序 SQL 迁移）→ `/health` 自检 → 用当前启用模板空跑 1 张图。
- 备份：`sqlite3 infer.db ".backup '/backup/infer-$(date +%F).db'"` + `rsync /data/models /data/reports`；保留 7 天。
- 离线包：镜像 tar + `data/models` 预置权重（或 `docker save` 的模型镜像）+ `.env` 模板 + 安装脚本。
- 日志：`logs/infer.log` 按天轮转，保留 30 天；不引入 ELK。

### 10.3 验收口径（M3）

- 真实相机 1 路：单图端到端 ≤ 3s（采集→推理→落库→响应）。
- 8 通道仿真：连续 2 小时不丢图、队列不溢出、P95 时延 ≤ 3s。
- 模型拉取：从镜像仓库拉取新模型 → 校验 → 在工位模板里切换 → 生效，全程 ≤ 5min（不含大镜像下载）。
- 断网演练：断开 A 后继续推理 ≥ 30min，回传积压进 outbox，恢复后 5min 内补传完成。
- 日报：连续 7 天自动生成且数据与 `b_stats_daily` 一致。

---

## 11. 契约测试与 fixtures

- `tests/contracts/test_pipeline_core.py`（共享）：切片/合并/三档判定/`load_config`/`StubRuntimeModel`。
- `tests/contracts/test_platform_b_api.py`：信封/坏图 40010/工位 40402/无模板 42200/背压 42900/模型拉取幂等与 digest 校验/工位模板校验与热加载/outbox 幂等。
- fixtures：`detect_result_sample.json`、`model_yaml_sample.yaml`、`model_manifest_sample.json`、`findings_ingest_sample.json`、`inspect_config_sample.yaml`。
- stub 原则：D3 前全量端点 stub（未实现返回 `50300`），前端可独立开发。

---

## 12. 二期预留（本期不做）

1. 视频级预览：MJPEG/WebRTC 独立媒体服务。
2. VLM 复审：`RecheckBackend` 在 B 侧实现，先出建议再由 A 终裁。
3. PDF 日报、Excel 多 sheet 导出。
4. 自动升级：离线升级包 + 签名校验。
5. 切换 PostgreSQL：ORM 层不变，配置切换。
6. 多 B 实例统计汇总：由运维侧统一看板消费各 B 的 `/stats/summary`（A 不参与）。

---

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方契约测试过。*
