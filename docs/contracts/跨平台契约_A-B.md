# 跨平台契约：平台 A ↔ 平台 B

> 归属：**B 定义契约与 A 侧实现；C 实现 B 侧**；冻结：D2；变更窗口：D9 / D15。
> 覆盖：模型下发、方案下发、错图回传、心跳与版本上报、认证、幂等/重试/断点。
> 不覆盖：平台各自内部接口（见 `平台A_接口与数据契约.md`、`平台B_接口与数据契约.md`）、`packages/` 内部签名（见 `P0骨架设计_双平台.md` §4）。

---

## 0. 范围与方向

| 链路 | 方向 | 发起方 | 接收方 | 频度 | 载荷量级 |
|---|---|---|---|---|---|
| 模型下发 | A→B | A（训练平台） | B | 每次模型审批通过 | 10~500MB（分片） |
| 方案下发 | A→B | A | B | 每次方案激活 | < 100KB |
| 错图回传 | B→A | B | A | 每张可疑/坏图 | 0.1~10MB/条 |
| 心跳与版本 | B→A | B | A | 60s | < 10KB |

- 两个平台**跨机器部署**，不共享数据库、对象存储、Redis；所有交互为显式 HTTP(S)。
- A 为主数据源与发起方；B 为消费方与回传方。B 不回写 A 的模型/方案/工位主数据。
- B 断网时继续推理，回传积压在本地 outbox（§6.3），恢复后补传。

---

## 1. 通用约定

### 1.1 传输与网络

| 项 | 约定 |
|---|---|
| 协议 | HTTP/1.1（或 HTTPS，推荐内网 CA/自签 + 指纹校验；公网禁止） |
| 编码 | UTF-8；时间 ISO8601 UTC（`2026-09-08T08:30:00Z`） |
| 请求头 | `X-Request-ID`（发起方生成，贯穿双方日志）、`Content-Type`、`Idempotency-Key`（写操作） |
| 超时 | 建连 5s；元数据/心跳 30s；分片 PUT 120s；错图回传 60s |
| 时钟 | 双方强制 NTP；偏差 > 2s 告警；跨平台数据同时携带 `captured_at`（B 采集时钟）与 `received_at`（接收方时钟） |
| 大小限制 | 模型单文件 ≤ 2GB；回传单条图片 ≤ 100MB |

### 1.2 认证（平台间共享密钥，非用户身份）

| 方向 | 头 | 校验方 | 配置 |
|---|---|---|---|
| A→B | `X-Platform-Token: <token>` | B | B 的 `PLATFORM_TOKEN` = A 的 `INFER_PLATFORM_TOKEN` |
| B→A | `X-Internal-Token: <token>` | A | A 的 `INTERNAL_TOKEN` = B 的 `INTERNAL_TOKEN` |

- 密钥至少 32 字节随机串；轮换采用双密钥并存窗口（旧密钥保留 7 天）。
- 失败一律返回 `40100`，不区分「无令牌/令牌错误」。
- B 无用户体系、无用户认证：其前端与全部业务接口在内网直接可用；只有平台间下发接口用机器密钥（见平台 B 契约 §1.1）。

### 1.3 统一信封

成功：`{"code":0,"message":"ok","request_id":"req-...","data":{...}}`
失败：HTTP 状态码 + 同信封，`data.detail` 给字段级错误：

```json
{"code":42200,"message":"plan validation failed","request_id":"req-9f2",
 "data":{"detail":{"fields":{"objects[1].model_ref":"model not ready on platform B"}}}}
```

### 1.4 错误码（跨平台子集）

| HTTP | code | 含义 | 产生方 |
|---|---|---|---|
| 400 | 40010 | 载荷不可读/分片不连续/sha256 校验失败/图片解码失败 | B、A |
| 401 | 40100 | 平台令牌缺失或错误 | B、A |
| 404 | 40401 | `upload_id` / `model_ref` / `plan_id` 不存在 | B |
| 409 | 40900 | 幂等冲突（同 `model_ref` 不同 sha256；同 `(station,seq,kind)` 内容不一致） | B、A |
| 422 | 42200 | 元数据/方案校验失败（`detail.fields`） | B、A |
| 429 | 42900 | B 侧队列背压（可重试） | B |
| 500 | 50000 | 内部错误 | B、A |
| 503 | 50300 | B 未就绪（磁盘满、模型加载失败、无可用 GPU） | B |

---

## 2. 模型下发（A→B）

### 2.1 流程

```
① POST  {B}/api/v1/ingest/model                 元数据 → {upload_id, exists, received_bytes}
② HEAD  {B}/api/v1/ingest/model/{upload_id}/blob   → {received_bytes, size_bytes}   # 断点续传
③ PUT   {B}/api/v1/ingest/model/{upload_id}/blob   分片写入（Content-Range）
④ POST  {B}/api/v1/ingest/model/{upload_id}/commit sha256 校验 → 原子落盘 → 注册 ready
   GET   {B}/api/v1/ingest/tasks/{upload_id}        查询状态（A 轮询/对账）
```

### 2.2 ① 创建下发任务

```http
POST {B}/api/v1/ingest/model
X-Platform-Token: ***
X-Request-ID: req-...
Content-Type: application/json

{
  "model_ref": "3-yolo@ds1",
  "skillname": "ObjectDetection",
  "framework": "yolo",
  "dataset_version": "1.0.0",
  "cover_classes": ["object_fault_type_01", "object_fault_type_02"],
  "class_names": ["object_fault_type_01", "object_fault_type_02"],
  "precision": "fp32",
  "filename": "model.onnx",
  "size_bytes": 41234567,
  "sha256": "9f2c...e1",
  "opset": 17,
  "input":  {"name": "images",  "shape": [1, 3, 1280, 1280]},
  "output": {"name": "output0", "shape": [1, 6, 8400]},
  "created_at": "2026-09-08T08:30:00Z",
  "source_platform": "aoi-train"
}
```

响应：

```json
{"code":0,"message":"ok","request_id":"req-...","data":{
  "upload_id":"up-20260908-3yolo-ds1-fp32","model_ref":"3-yolo@ds1",
  "exists":false,"received_bytes":0}}
```

幂等规则：

| 场景 | 行为 |
|---|---|
| `model_ref` 已存在且 sha256 相同 | `exists=true`，跳过 ②③④，直接可用 |
| `model_ref` 已存在但 sha256 不同 | `40900`（模型版本不可覆盖；A 需以新 `model_ref` 重新注册） |
| 同 `model_ref` 存在未完成 upload | 复用该 `upload_id`，返回当前 `received_bytes` 供续传 |

### 2.3 ② / ③ 分片上传与断点续传

- 分片大小默认 4MB（A 侧 `DISPATCH_CHUNK_SIZE`），末片可小；单文件 ≤ 2GB。
- 每片请求：

```http
PUT {B}/api/v1/ingest/model/{upload_id}/blob
X-Platform-Token: ***
Content-Range: bytes 0-4194303/41234567
Content-Type: application/octet-stream
<binary>
```

- B 校验 `Content-Range` 起点等于当前 `received_bytes`，否则 `40010`；返回：

```json
{"code":0,"data":{"received_bytes":4194304,"size_bytes":41234567}}
```

- 续传：`HEAD .../blob` 返回已收字节数；A 从该偏移继续。
- 未完成分片保留 24h（`INGEST_TMP_TTL_HOURS`），超时清理；A 侧重试可直接重新走 ①。

### 2.4 ④ 提交与校验

```http
POST {B}/api/v1/ingest/model/{upload_id}/commit
X-Platform-Token: ***
```

B 行为：流式 sha256 校验 → 与元数据比对 → 原子移动到 `models/{model_ref}/{precision}/model.onnx`，写 `model.onnx.sha256` → 注册 `b_model`（`status=ready`）。

```json
{"code":0,"data":{"model_ref":"3-yolo@ds1","status":"ready",
  "sha256":"9f2c...e1","size_bytes":41234567,
  "stored_path":"models/3-yolo@ds1/fp32/model.onnx"}}
```

失败：sha256 不一致 → `40010` 并删除临时文件；磁盘不足 → `50300`。

### 2.5 A 侧状态机（`aoi_training.model_dispatch`）

```
queued → uploading → verifying → ready
                    ↘ failed（可人工重推，最多 3 次自动重试：30s / 2m / 10m）
```

- 每次状态变更写审计；`ready` 需 B 返回的 `sha256` 与 A 记录一致。
- A 侧 `POST /api/train/models/{id}/dispatch` 触发；B 不可达时保持 `queued` 并告警。

---

## 3. 方案下发（A→B）

### 3.1 请求

```http
POST {B}/api/v1/ingest/plan
X-Platform-Token: ***
X-Request-ID: req-...
Content-Type: application/json

{
  "plan_id": "PLAN-DOORPANEL-STD",
  "version": 3,
  "checksum": "sha256(content_yaml)",
  "content_yaml": "plan_id: PLAN-DOORPANEL-STD\nversion: 3\nobjects:\n  - code: object_fault_type_01\n...",
  "stations": [
    {"code": "ST01", "name": "1号线-左门板", "enabled": true, "channel_id": "ch01"},
    {"code": "ST02", "name": "1号线-右门板", "enabled": true, "channel_id": "ch02"}
  ],
  "dictionary": {
    "object_fault_type_01": {"name_cn": "划伤", "risk_level": 3, "color": "#FF4D4F"},
    "object_fault_type_02": {"name_cn": "凹坑", "risk_level": 2, "color": "#FAAD14"}
  },
  "activated_at": "2026-09-08T09:00:00Z"
}
```

> `dictionary` 为方案涉及缺陷 code 的展示信息（中文名/风险档/颜色），B 落本地用于统计与日报展示；B 不维护字典主数据，A 每次下发方案时全量覆盖。`dictionary` 必须覆盖方案中所有 `code`，否则 `42200`。

### 3.2 B 侧校验与激活（顺序执行，全部通过才切换）

| # | 校验 | 失败 |
|---|---|---|
| 1 | `plan_id` 规范（`skillname.is_valid_plan_id`）；`version` 为正整数 | 42200 |
| 2 | `checksum` 与 `content_yaml` 的 SHA256 一致 | 42200 |
| 3 | `pipeline-core.load_plan` 结构校验（objects 非空且 code 唯一；`class_map` 非空且 value 等于 code；`0 < recheck_min < auto_min < 1`） | 42200 |
| 4 | 每个 `model_ref` 在本机 `b_model` 且 `status=ready`；`class_map` 的 value 属于该模型 `class_names` | 42200 |
| 5 | 每个 `code` 通过 `skillname.is_valid_fault_code`；与模型 `cover_classes` 一致 | 42200 |
| 6 | `stations` code 规范（`ST\d{2}`）且无重复；`dictionary` 覆盖方案全部 `code` | 42200 |
| 7 | ONNX 会话可加载（张量名/形状与模型元数据一致）+ 空跑自检（1 张空白图） | 50300 |
| 8 | 版本号 `>=` 当前 active 版本（防回退误操作；回滚需 A 侧显式指定 `allow_rollback=true`） | 42200 |

> 金标准回归在 **A 侧模型门禁阶段**执行；B 侧只做加载自检（规则 7），避免跨机传输金标准数据与重复计算。

### 3.3 响应

```json
{"code":0,"data":{
  "ok":true,"plan_id":"PLAN-DOORPANEL-STD","version":3,
  "loaded_models":[{"model_ref":"3-yolo@ds1","precision":"fp32","vram_gb":3.8}],
  "checks":[
    {"name":"schema","passed":true,"detail":""},
    {"name":"models_ready","passed":true,"detail":""},
    {"name":"onnx_load","passed":true,"detail":""},
    {"name":"smoke_infer","passed":true,"detail":"1 tile / 12ms"}
  ],
  "activated_at":"2026-09-08T09:00:03Z"}}
```

- 失败返回 `42200`/`50300` + `checks[]`；**B 保持上一个 active 方案继续运行**，不进入半激活状态。
- 成功后 B 原子切换 active 方案并热替换模型会话；旧模型会话在无在途请求后卸载。
- 回滚：A 推送历史版本并带 `"allow_rollback": true`。

---

## 4. 错图回传（B→A）

### 4.1 触发条件

| `kind` | 触发 | 是否带图 |
|---|---|---|
| `suspicious` | `verdict ∈ {recheck, manual}` | 必须带原图 |
| `bad` | 采集失败 / 解码失败 / 超时 / 模型异常 / 磁盘错误 | 有则带，无则纯元数据 |

`auto_pass` **不回传**（留在 B 本地，减少跨机带宽）。

### 4.2 请求

```http
POST {A}/api/ingest/findings
X-Internal-Token: ***
X-Request-ID: req-...
Idempotency-Key: ST01-1042-suspicious
Content-Type: multipart/form-data

-- meta: (application/json)
{
  "kind": "suspicious",
  "station_code": "ST01",
  "seq": 1042,
  "captured_at": "2026-09-08T08:31:00Z",
  "received_at": "2026-09-08T08:31:02Z",
  "plan_id": "PLAN-DOORPANEL-STD",
  "plan_version": 3,
  "model_refs": ["3-yolo@ds1"],
  "verdict": "recheck",
  "verdict_reasons": ["mid_score"],
  "boxes": [{"object_code":"object_fault_type_01","score":0.72,"model_ref":"3-yolo@ds1","xyxy":[100,200,180,260]}],
  "tiling_meta": {"tile_size":1280,"overlap":0.2,"tiles":12,"ms":1400},
  "latency_ms": 1400,
  "image": {"md5":"ab12...cd","ext":"jpg","width":2448,"height":2048,"size_bytes":834211},
  "error_code": null
}
-- file: @ST01_1042.jpg        # kind=bad 且无图时可省略
```

`error_code` 取值：`capture_failed` / `decode_failed` / `timeout` / `model_error` / `disk_error`。

### 4.3 响应

```json
{"code":0,"data":{"fact_id":1234,"workitem_id":567,"image_id":100,
  "bad_image_id":null,"duplicated":false}}
```

### 4.4 A 侧处理

1. 幂等检查：`kind=suspicious` 查 `inspection_fact`、`kind=bad` 查 `bad_image`，命中则返回既有 id 且 `duplicated=true`；同键内容不一致 → `40900`。
2. `station_code` 未注册/未启用 → `40402`（B 侧记入 outbox 但不重试，转人工处理，避免死循环）。
3. 图片：解码 → MD5 去重 → 落 MinIO `images/{md5}.jpg` → 写 `aoi_datasets.image`（`source=camera`，含 `station_id`/`captured_at`）。
4. `kind=suspicious` → 写 `aoi_review.inspection_fact`（`result_json` = `{boxes, verdict, verdict_reasons, tiling_meta}` + 跨平台字段）+ 建 `review_workitem`（`route=manual`，`status=pending`）。
5. `kind=bad` → 写 `aoi_review.bad_image`（`error_code`，`handled=false`），不建 fact/workitem。
6. 图片解码失败时：`kind=bad` 仍登记 `bad_image` 并返回成功；`kind=suspicious` 返回 `40010`（B 侧转人工导出）。

### 4.5 B 侧 outbox 状态机

```
pending → pushing → pushed
                  ↘ retrying（1m/5m/15m/1h/6h，最长 24h）→ dead（人工重推/导出）
```

- 未 `pushed` 的图片**不参与保留清理**（防止回传丢失）。
- `dead` 记录在 B 的「系统」页可见，支持手动重推与本地导出。

---

## 5. 心跳与版本上报（B→A）

```http
POST {A}/api/ingest/heartbeat
X-Internal-Token: ***
Content-Type: application/json

{
  "instance_code": "B01",
  "base_url": "https://10.0.10.9:8990",
  "versions": {"platform":"0.1.0","skillname":"0.1.0","pipeline_core":"0.1.0","schema":"1"},
  "status": {
    "uptime_s": 86400,
    "gpu": {"device": 0, "mem_used_gb": 3.2, "mem_total_gb": 23.7},
    "disk_free_gb": 120.4,
    "active_plan": {"plan_id":"PLAN-DOORPANEL-STD","version":3},
    "models_ready": 2,
    "stations_enabled": 8,
    "stations_online": 7,
    "inspect": {"queue": 0, "concurrency": 2, "avg_latency_ms": 1420, "p95_latency_ms": 2310},
    "outbox_pending": 3,
    "clock_skew_ms": -120,
    "last_error": null
  }
}
```

响应：`{"code":0,"data":{"ok":true,"server_time":"2026-09-08T08:32:00Z"}}`

A 侧行为：upsert `aoi_system.infer_instance`；`last_heartbeat_at` 超过 5 分钟标 `offline` 并告警；版本不匹配在 A 的「系统」页告警。

**版本协商规则**：

| 差异 | 行为 |
|---|---|
| `skillname` 主版本不同 | 阻断方案下发（`42200`，语义可能不兼容），人工升级 B |
| `pipeline_core` 主版本不同 | 允许下发但告警（判定语义可能漂移），D15 前必须对齐 |
| `platform`/`schema` 不同 | 仅告警 |

---

## 6. 幂等、重试、超时、断点

### 6.1 幂等键

| 操作 | 幂等键 |
|---|---|
| 模型下发 | `model_ref` + `sha256`（B 侧全局唯一） |
| 方案下发 | `plan_id` + `version` + `checksum` |
| 错图回传 | `(station_code, seq)`（按 `kind` 落不同表）；HTTP 头 `Idempotency-Key: {station}-{seq}-{kind}` |
| 心跳 | 天然幂等（按 `instance_code` upsert） |

### 6.2 重试策略

| 链路 | 重试 | 退避 | 终止 |
|---|---|---|---|
| A→B 元数据/提交 | 3 次 | 30s / 2m / 10m | `failed`，人工重推 |
| A→B 分片 | 每片 3 次 | 5s / 15s / 60s | 暂停，保留断点，恢复后续传 |
| B→A 回传 | 无限（受时限） | 1m / 5m / 15m / 1h / 6h | 24h 后 `dead`，人工处理 |
| 心跳 | 忽略失败 | — | 下个周期重试 |

仅对 `42900` / `5xx` / 网络错误重试；`4xx` 业务错误不重试（`40010` 除外：分片不连续可重取偏移后续传）。

### 6.3 断连行为

| 场景 | A 侧 | B 侧 |
|---|---|---|
| 模型下发中断 | `model_dispatch=failed/uploading`，保留断点信息 | 临时分片保留 24h |
| 方案下发失败 | 保持旧版本 active，记录 `checks[]` | 保持旧版本 active |
| 回传中断 | 无（A 是被动接收） | outbox 积压，UI 显示 pending，图片不清理 |
| 长时间断网 | 心跳告警 | 用最近方案继续推理，统计/日报照常 |

---

## 7. 时序图

### 7.1 模型下发

```
A(训练平台)                                   B(推理平台)
    │ 门禁通过 + 人工审批(approved)                │
    │──POST /ingest/model (元数据+sha256)────────▶│ 校验元数据/幂等
    │◀─{upload_id, exists:false}─────────────────│
    │──PUT /ingest/model/{upload_id}/blob (0-4M)───────▶│ 追加写
    │◀─{received_bytes}──────────────────────────│
    │        ... 分片重复 ...                     │
    │──POST /ingest/model/{upload_id}/commit───────────▶│ sha256 校验 → 原子落盘
    │◀─{status:ready, sha256}────────────────────│
    │ model_dispatch=ready                       │ b_model=ready
```

### 7.2 方案激活

```
A                                             B
    │ 校验 schema/字典/注册表/工位                 │
    │──POST /ingest/plan (yaml+checksum)────────▶│ load_plan 校验
    │                                             │ 模型 ready 检查
    │                                             │ ONNX 加载 + 空跑自检
    │                                             │ 原子切换 active
    │◀─{ok, loaded_models, checks[]}─────────────│
    │ 全部通过 → plan_version=active              │
```

### 7.3 推理与错图回传

```
相机/模拟器         B                                  A
    │──POST /api/v1/inspect/image──▶│                    │
    │                               │ pipeline-core.run  │
    │                               │ 落 inspection      │
    │                               │ verdict!=auto_pass │
    │                               │──POST /api/ingest/findings──▶│
    │                               │                    │ 图片→MinIO→image
    │                               │                    │ fact + workitem/bad_image
    │                               │◀─{fact_id,...}─────│
    │                               │ outbox=pushed      │
```

---

## 8. 联调 fixtures 与契约测试

| fixture | 归属 | 用途 |
|---|---|---|
| `model_ingest_request.json` | B | 模型下发元数据样例 |
| `plan_template_sample.yaml` | B | 方案模板样例（含 stations） |
| `findings_ingest_sample.json` | C | 错图回传 meta 样例（suspicious + bad 两条） |
| `heartbeat_sample.json` | C | 心跳样例 |

契约测试（`tests/contracts/test_cross_platform.py`）：

1. 模型下发：幂等（同 sha256 → `exists`）、冲突（同 ref 不同 sha256 → `40900`）、分片乱序 → `40010`、sha256 不符 → `40010`、断点续传字节数正确。
2. 方案下发：schema 非法 → `42200`；模型未 ready → `42200`；回退版本 → `42200`；成功时 `checks` 四项齐备。
3. 错图回传：重复请求 → `duplicated=true` 且 id 一致；坏图无图 → 成功；工位未注册 → `40402`；suspicious 图不可解码 → `40010`。
4. 心跳：upsert 幂等；版本差异按 §5 规则判定。
5. 认证：缺 `X-Platform-Token` / `X-Internal-Token` → `40100`。

---

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方契约测试过。*
