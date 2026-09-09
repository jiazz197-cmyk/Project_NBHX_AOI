# 跨平台契约：平台 A ↔ 平台 B

> 归属：**B 定义契约与 A 侧实现；C 实现 B 侧**；冻结：D2；变更窗口：D9 / D15。
> 覆盖：模型发布与拉取（经镜像仓库）、模型能力描述 `model.yaml`、错图回传、版本兼容、认证、幂等/重试。
> 不覆盖：平台各自内部接口（见 `平台A_接口与数据契约.md`、`平台B_接口与数据契约.md`）、`packages/` 内部签名（见 `P0骨架设计_双平台.md` §4）。

---

## 0. 范围与方向

| 链路 | 方向 | 机制 | 频度 | 载荷量级 |
|---|---|---|---|---|
| 模型发布 | A → 镜像仓库 | `docker build` + `docker push` | 每次模型审批通过 | 10~500MB |
| 模型拉取 | 镜像仓库 → B | OCI/Docker Registry HTTP API v2（或 `docker pull`） | 按需（新模型/回滚） | 同 |
| 错图回传 | B → A | HTTP multipart | 每张可疑/坏图 | 0.1~10MB/条 |

**关键约束**：

- **A 从不主动连接 B**：没有实例注册、没有心跳、没有方案下发、没有分片上传。
- 模型是 A→B 唯一的**信息载体**：镜像里除 ONNX 权重外，还带 `model.yaml`（模型能力描述，含 skillname、类别、推荐阈值）。
- **B 拥有工位与工位模板**：模板由 B 在自己的 GUI 里配置，A 不感知；A 只在 `model.yaml` 里给推荐阈值作为默认值。
- B→A 只有 `POST /api/ingest/findings` 一个端点（错图回传）；B 无用户认证。

---

## 1. 通用约定

### 1.1 传输与网络

| 项 | 约定 |
|---|---|
| 协议 | 镜像仓库 HTTPS；回传 HTTP/1.1（推荐 HTTPS，内网 CA/自签 + 指纹校验） |
| 编码 | UTF-8；时间 ISO8601 UTC（`2026-09-08T08:30:00Z`） |
| 请求头 | `X-Request-ID`（发起方生成，贯穿双方日志）、`Content-Type`、`Idempotency-Key`（回传写操作） |
| 超时 | 建连 5s；回传 60s；镜像层下载 600s（大文件流式） |
| 时钟 | 双方强制 NTP；跨平台数据同时携带 `captured_at`（B 采集时钟）与 `received_at`（A 接收时钟） |
| 大小限制 | 单模型镜像 ≤ 2GB；回传单条图片 ≤ 100MB |

### 1.2 认证

| 链路 | 凭据 | 说明 |
|---|---|---|
| A → 镜像仓库（推送） | `MODEL_REGISTRY_USER` / `MODEL_REGISTRY_PASSWORD` | 只授予发布任务的写权限 |
| B ← 镜像仓库（拉取） | `MODEL_REGISTRY_USER` / `MODEL_REGISTRY_TOKEN` | **只读**；公开仓库可留空（注意 Docker Hub 匿名限流） |
| B → A（回传） | `X-Internal-Token: <INTERNAL_TOKEN>` | 由 A 校验；B 只透传 |
| B 的前端与业务接口 | **无认证** | B 无用户体系、无登录；靠内网隔离（见平台 B 契约 §1.1） |

- 密钥至少 32 字节随机串；轮换采用双密钥并存窗口（旧密钥保留 7 天）。
- 回传认证失败返回 `40100`，不区分「无令牌/令牌错误」。

### 1.3 统一信封

成功：`{"code":0,"message":"ok","request_id":"req-...","data":{...}}`
失败：HTTP 状态码 + 同信封，`data.detail` 给字段级错误：

```json
{"code":42200,"message":"model config invalid","request_id":"req-9f2",
 "data":{"detail":{"fields":{"classes[1].code":"unknown fault code"}}}}
```

### 1.4 错误码（跨平台子集）

| HTTP | code | 含义 | 产生方 |
|---|---|---|---|
| 400 | 40010 | 载荷不可读/镜像层解包失败/sha256 校验失败/图片解码失败 | B、A |
| 401 | 40100 | registry 鉴权失败；回传令牌缺失或错误 | B、A |
| 404 | 40401 | 镜像/标签/清单不存在；回传中的资源不存在 | B、A |
| 409 | 40900 | 幂等冲突（同 `model_ref` 不同 digest；同 `(station,seq,kind)` 内容不一致） | B、A |
| 422 | 42200 | `model.yaml`/回传元数据校验失败（`detail.fields`） | B、A |
| 429 | 42900 | registry 限流（可重试） | 仓库 |
| 500 | 50000 | 内部错误 | B、A |
| 503 | 50300 | B 未就绪（磁盘满、模型加载失败、无可用 GPU） | B |

---

## 2. 模型产物与镜像规范

### 2.1 镜像内布局（固定）

```
/model/
├── model.onnx               # 推理权重（FP32；FP16 另发一个 tag）
├── model.onnx.sha256        # 权重 sha256（十六进制，无文件名后缀）
├── model.yaml               # 模型能力描述（§2.3，A/B 双方的唯一元数据来源）
└── NOTICE                   # 许可与来源信息（可选）
```

- 镜像以 `FROM scratch` 构建（仅文件，无 shell），层数固定为 1，便于 B 用 registry API 直接解包。
- 权重与 `model.yaml` **必须同版本发布**，不得分开发布。

### 2.2 镜像命名与标签

| 项 | 约定 |
|---|---|
| 镜像名 | `<registry>/<org>/aoi-model`，如 `docker.io/<org>/aoi-model`、`registry.corp:5000/aoi/aoi-model` |
| 标签 | `skillname.image_tag_from_model_ref(model_ref)`，如 `3-yolo@ds1` → `3-yolo-ds1` |
| 精度 | 同 `model_ref` 的不同精度用后缀：`3-yolo-ds1-fp16` |
| 不可变 | **B 按 digest 记录**；生产使用建议按 `image@sha256:...` 固定，`latest` 仅作便利别名 |
| 冲突 | 同一 tag 已存在且 digest 不同 → A 侧发布前必须换 `model_ref`（版本号递增），不得覆盖 |

### 2.3 `model.yaml`（模型能力描述，**随 skillname 给出**）

```yaml
# ================= 元信息 =================
schema_version: 1                 # 必填；B 据此选择解析器（未知版本拒绝）
model_ref: 3-yolo@ds1             # 必填
skillname: ObjectDetection        # 必填
framework: yolo                   # 必填
framework_version: 8.4.1          # 可选
dataset_version: 1.0.0            # 必填
dict_version: 20260901-1          # 可选：缺陷字典版本
base_model: yolov8s.pt            # 可选
precision: fp32                   # 必填：fp32/fp16/int8
created_at: 2026-09-08T08:30:00Z  # 必填
published_at: 2026-09-08T09:00:00Z  # 可选
description: 门板表面缺陷检测 v3     # 可选
tags: [doorpanel, surface]        # 可选
license: Apache-2.0               # 可选
gate_status: passed               # 必填：pending/passed/failed
lifecycle: published              # 可选
source:                           # 可选：训练溯源
  platform: aoi-train
  train_job_id: 128
  created_by: 7
  git_commit: 59ec528

# ================= ONNX 张量契约 =================
onnx:
  file: model.onnx                # 必填
  sha256: 9f2c...e1               # 必填
  size_bytes: 41234567            # 必填
  opset: 17                       # 必填
  ir_version: 8                   # 可选
  producer: ultralytics 8.4.1     # 可选
  dynamic_batch: true             # 可选
  max_batch_size: 8               # 预留
  input:
    name: images                  # 必填
    shape: [1, 3, 1280, 1280]     # 必填
    dtype: float32                # 必填
    layout: NCHW                  # 必填
    color_order: RGB              # 可选：RGB/BGR
    normalize: {scale: 0.00392156862745098, mean: [0, 0, 0], std: [1, 1, 1]}   # 可选
    resize: {mode: letterbox, interpolation: bilinear, pad_value: 114}         # 预留
  output:
    name: output0                 # 必填
    shape: [1, 6, 8400]           # 必填
    format: yolo_v8_xywh_conf_cls # 必填
    num_classes: 2                # 可选
    num_anchors: 8400             # 可选
  runtime:                        # 预留：运行时建议
    providers: [cuda, cpu]
    fp16: true
    threads: 4

# ================= 类别（索引序） =================
classes:
  - index: 0                      # 必填
    code: object_fault_type_01    # 必填
    name_cn: 划伤                  # 必填（展示）
    name_en: scratch              # 预留
    risk_level: 3                 # 必填：3=高 2=中 1=低
    color: "#FF4D4F"              # 预留（展示）
    aliases: [刮伤]                # 预留
    enabled: true                 # 预留（工位模板默认是否启用）
    min_box_size: 4               # 预留（最小框边长 px）
    max_boxes_per_image: 50       # 预留
    recommended: {recheck_min: 0.60, auto_min: 0.90}   # 必填：工位模板默认值
  - index: 1
    code: object_fault_type_02
    name_cn: 凹坑
    risk_level: 2
    recommended: {recheck_min: 0.55, auto_min: 0.88}

# ================= 后处理（预留；B 缺省按下列值执行） =================
postprocess:
  conf_threshold: 0.25
  iou_threshold: 0.50
  max_detections: 300
  agnostic_nms: false
  multi_label: false
  box_format: xyxy
  class_agnostic: false

# ================= 切片（推荐值 + 预留） =================
tiling:
  enabled: true
  recommended_tile_size: 1280     # 必填（推荐值）
  overlap: 0.2                    # 必填（推荐值）
  min_tile_size: 640              # 预留
  edge_handling: pad              # 预留：pad/crop/skip
  batch_tiles: 4                  # 预留
  max_tiles: 64                   # 预留（防超大图打爆显存）

# ================= 判定策略（预留：全局默认，工位模板可覆盖） =================
thresholds:
  default: {recheck_min: 0.50, auto_min: 0.90}
  high_risk_force_recheck: true
  low_score_force_manual: 0.10

# ================= 指标 =================
metrics:
  map50: 0.93
  map50_95: 0.71
  precision: 0.94
  recall: 0.96
  per_class_recall: {object_fault_type_01: 0.99, object_fault_type_02: 0.97}
  per_class_precision: {object_fault_type_01: 0.95, object_fault_type_02: 0.93}
  eval_dataset: 1.0.0-test
  evaluated_at: 2026-09-08T08:00:00Z
  confusion_matrix_ref: null      # 预留

# ================= 性能基准（预留） =================
benchmark:
  device: RTX 4060
  provider: cuda
  precision: fp32
  tile_size: 1280
  batch: 4
  latency_ms_p50: 380
  latency_ms_p95: 520
  throughput_fps: 9.6
  vram_gb: 3.8

# ================= 训练超参（预留，溯源用） =================
training:
  epochs: 100
  imgsz: 1280
  batch: 8
  lr0: 0.01
  patience: 20
  seed: 42
  augment: {flip: true, mosaic: true, mixup: 0.1}
  split: {train: 0.7, val: 0.2, test: 0.1}

# ================= 兼容性（预留：不满足时告警/拒绝） =================
requires:
  skillname: ">=0.1.0"
  pipeline_core: ">=0.1.0"
  schema_version: ">=1"
  onnxruntime: ">=1.18"
  cuda: null
  vram_gb: 4

# ================= 二期预留 =================
signature: null                   # cosign 签名
sbom_ref: null                    # SBOM 对象键
golden_summary: null              # A 侧金标准摘要（不跨机传原图）
calibration: null                 # 置信度校准参数
quantization: null                # int8 / 动态量化信息
extensions: {}                    # 任意扩展字段；B 原样保存、不解析
```

**字段级别约定**：

| 级别 | 含义 | B 侧行为 |
|---|---|---|
| **必填** | 缺失或非法 → 拒绝注册 | 解析并校验 |
| **可选** | 缺失 → 用缺省值 | 解析；缺失不报错 |
| **预留** | 本期不消费，但字段位先占住 | **原样存 `b_model.config_json`，不解析**；B 升级后可直接启用，无需 A 重新发布模型 |
| **未知** | A 未来新增的字段 | 忽略 + 原样保存（向前兼容） |

**B 侧校验规则**（拉取后立即执行，任一失败则拒绝注册）：

| # | 校验 | 失败 |
|---|---|---|
| 1 | 必填字段齐全（`schema_version`/`model_ref`/`skillname`/`framework`/`precision`/`gate_status`/`onnx.{file,sha256,size_bytes,opset,input,output}`/`classes[]`） | 42200 |
| 2 | `schema_version` 已知且 B 支持 | 42200 |
| 3 | `skillname` ∈ `skillname.SkillName` | 42200 |
| 4 | `model_ref` 能被 `skillname.parse_model_ref` 解析 | 42200 |
| 5 | `onnx.sha256` 与解包出的 `model.onnx` 实际 sha256 一致 | 40010 |
| 6 | `classes[].code` 通过 `skillname.is_valid_fault_code` 且不重复 | 42200 |
| 7 | `classes[].index` 唯一、连续、与 `onnx.output.shape` 的类别维一致 | 42200 |
| 8 | `0 < recommended.recheck_min < recommended.auto_min < 1` | 42200 |
| 9 | 可选/预留/未知字段 | 用缺省值 / 原样保存，不报错 |
| 10 | `requires.*` 版本约束 | 主版本不兼容 → 42200；其余仅告警 |

> `recommended` 只是**推荐值**：B 的工位模板可覆盖；A 不再下发方案模板。
> **预留字段的价值**：模型发布一次后长期留在 registry，B 可能分期升级；预留字段让「B 升级即启用新能力」，不必回头重发模型。

### 2.4 发布（A → 镜像仓库）

```
1. 模型 lifecycle=approved 且金标准回归通过
2. POST /api/train/models/{id}/publish  → Celery publish 任务
3. 生成 model.yaml（含 onnx.sha256）→ 构建镜像（FROM scratch + COPY /model/*）
4. docker build -t <registry>/<org>/aoi-model:<tag> .
5. docker push
6. 取 digest：docker inspect --format '{{index .RepoDigests 0}}'
7. 写 aoi_training.model_publish{image, tag, digest, status=published}
8. model.lifecycle → published
```

- 发布失败（网络/鉴权/磁盘）：`model_publish.status=failed` + `error_message`，指数退避重试 3 次（30s / 2m / 10m），可人工重推。
- A 侧记录 digest；B 拉取后回报的 digest 若不一致，视为仓库被篡改并告警。

### 2.5 拉取（镜像仓库 → B）

```
1. 运维在 B 的「系统 → 模型库」输入镜像地址（或从 tag 列表选择）
2. POST {B}/api/v1/models/pull {"image": "<registry>/<org>/aoi-model:3-yolo-ds1", "digest": "sha256:..."}
3. B 取 registry token（若需要）→ GET manifest → 校验 digest（若给定）
4. GET 层 blob → gunzip + untar → 提取 /model/*
5. 校验 model.onnx sha256（§2.3 规则 4）→ 解析 model.yaml → 执行 §2.3 全部校验
6. 落盘 /data/models/{model_ref}/{precision}/ → 注册 b_model + 刷新 b_defect_class
7. → {"code":0,"data":{"model_ref":"3-yolo@ds1","digest":"sha256:...","status":"ready","classes":2}}
```

- **幂等**：同 `model_ref` + 同 digest → 直接返回 `ready`（不重复下载）；同 `model_ref` 不同 digest → `40900`（需先删除旧版本）。
- **失败**：不写半成品（临时目录 + 原子 rename）；已有模型不受影响；错误与重试次数记录在模型库页。
- **无 Docker 依赖**：默认 `MODEL_PULL_MODE=oci`，用 httpx 直接走 Registry v2 API；本机有 Docker 时可切 `docker` 模式（`docker pull` + `docker create` + `docker cp`）。
- **离线导入**：A 侧 `docker save` 或层 tar → B 的 `POST /api/v1/models/import`（multipart 上传 tar）→ 走同样的校验/注册流程。

### 2.6 版本兼容

| 差异 | 行为 |
|---|---|
| `schema_version` 未知 | 拒绝（42200） |
| `skillname` 主版本不兼容 | 拒绝（42200），提示升级 B |
| `pipeline_core` 主版本不兼容 | 告警并拒绝（判定语义可能漂移） |
| 次版本差异 | 仅告警，允许使用 |

> 因为 A 不接收心跳，版本兼容性**只在 B 拉取模型时检查**；B 的版本信息随错图回传的 `meta.versions` 可选上报，供 A 侧统计参考（不作为管控依据）。

---

## 3. 错图回传（B → A）

### 3.1 触发条件

| `kind` | 触发 | 是否带图 |
|---|---|---|
| `suspicious` | `verdict ∈ {recheck, manual}` | 必须带原图 |
| `bad` | 采集失败 / 解码失败 / 超时 / 模型异常 / 磁盘错误 | 有则带，无则纯元数据 |

`auto_pass` **不回传**（留在 B 本地，减少跨机带宽）。

### 3.2 请求

```http
POST {A}/api/ingest/findings
X-Internal-Token: ***
X-Request-ID: req-...
Idempotency-Key: ST01-1042-suspicious
Content-Type: multipart/form-data

-- meta: (application/json)
{
  "kind": "suspicious",
  "instance_code": "B01",
  "station_code": "ST01",
  "station_name": "1号线-左门板",          // B 侧工位名，仅用于 A 侧展示
  "seq": 1042,
  "captured_at": "2026-09-08T08:31:00Z",
  "received_at": "2026-09-08T08:31:02Z",
  "template_version": 3,                   // B 的工位模板版本
  "model_refs": ["3-yolo@ds1"],
  "verdict": "recheck",
  "verdict_reasons": ["mid_score"],
  "boxes": [{"object_code":"object_fault_type_01","score":0.72,"model_ref":"3-yolo@ds1","xyxy":[100,200,180,260]}],
  "tiling_meta": {"tile_size":1280,"overlap":0.2,"tiles":12,"ms":1400},
  "latency_ms": 1400,
  "image": {"md5":"ab12...cd","ext":"jpg","width":2448,"height":2048,"size_bytes":834211},
  "error_code": null,
  "versions": {"platform":"0.1.0","skillname":"0.1.0","pipeline_core":"0.1.0"}   // 可选
}
-- file: @ST01_1042.jpg        # kind=bad 且无图时可省略
```

`error_code` 取值：`capture_failed` / `decode_failed` / `timeout` / `model_error` / `disk_error`。

### 3.3 响应

```json
{"code":0,"data":{"fact_id":1234,"workitem_id":567,"image_id":100,
  "bad_image_id":null,"duplicated":false}}
```

### 3.4 A 侧处理

1. 幂等检查：`kind=suspicious` 查 `inspection_fact`、`kind=bad` 查 `bad_image`（键 `(station_code, seq)`），命中则返回既有 id 且 `duplicated=true`；同键内容不一致 → `40900`。
2. `station_code` 只是 B 侧的不透明字符串（A **没有**工位主数据）：长度 ≤32、非空即可；`station_name` 仅展示用。
3. 图片：解码 → MD5 去重 → 落 MinIO `images/{md5}.jpg` → 写 `aoi_datasets.image`（`source=camera`，含 `station_code`/`captured_at`）。
4. `kind=suspicious` → 写 `aoi_review.inspection_fact`（`result_json` = `{boxes, verdict, verdict_reasons, tiling_meta}` + 跨平台字段）+ 建 `review_workitem`（`route=manual`，`status=pending`）。
5. `kind=bad` → 写 `aoi_review.bad_image`（`error_code`，`handled=false`），不建 fact/workitem。
6. 图片解码失败时：`kind=bad` 仍登记 `bad_image` 并返回成功；`kind=suspicious` 返回 `40010`（B 侧转人工导出）。

### 3.5 B 侧 outbox 状态机

```
pending → pushing → pushed
                  ↘ retrying（1m/5m/15m/1h/6h，最长 24h）→ dead（人工重推/导出）
```

- 未 `pushed` 的图片**不参与保留清理**（防止回传丢失）。
- `dead` 记录在 B 的「系统」页可见，支持手动重推与本地导出。

---

## 4. 幂等、重试、超时

### 4.1 幂等键

| 操作 | 幂等键 |
|---|---|
| 模型发布 | `model_ref` + tag（同 tag 不同内容禁止覆盖） |
| 模型拉取 | `model_ref` + `digest` |
| 错图回传 | `(station_code, seq)`（按 `kind` 落不同表）；HTTP 头 `Idempotency-Key: {station}-{seq}-{kind}` |

### 4.2 重试策略

| 链路 | 重试 | 退避 | 终止 |
|---|---|---|---|
| A 发布镜像 | 3 次 | 30s / 2m / 10m | `failed`，人工重推 |
| B 拉取镜像 | 3 次 | 30s / 2m / 10m | 模型库页显示失败，人工重试 |
| B→A 回传 | 无限（受时限） | 1m / 5m / 15m / 1h / 6h | 24h 后 `dead`，人工处理 |

仅对 `42900` / `5xx` / 网络错误重试；`4xx` 业务错误不重试。

### 4.3 断连行为

| 场景 | A 侧 | B 侧 |
|---|---|---|
| 镜像仓库不可用 | 发布任务失败并可重推 | 用本地已有模型继续推理，模型库页提示 |
| A 不可用 | — | 推理/统计/日报照常；回传积压进 outbox |
| B 不可用 | 无感知（A 不依赖 B） | — |

---

## 5. 时序图

### 5.1 模型发布 → 拉取

```
A（训练平台）                镜像仓库                    B（推理平台）
   │ 审批通过                      │                          │
   │──build + docker push────────▶│                          │
   │◀─digest───────────────────────│                          │
   │ model_publish=published       │                          │
   │                               │◀──GET manifest/layers────│  模型库页点「拉取」
   │                               │───layer tar.gz──────────▶│
   │                               │                          │ 解包 /model/* → sha256
   │                               │                          │ 解析 model.yaml → 校验
   │                               │                          │ b_model=ready
```

### 5.2 推理与错图回传

```
相机/模拟器         B                                  A
    │──POST /api/v1/inspect/image──▶│                    │
    │                               │ 工位模板 + pipeline-core.run
    │                               │ 落 inspection      │
    │                               │ verdict!=auto_pass │
    │                               │──POST /api/ingest/findings──▶│
    │                               │                    │ 图片→MinIO→image
    │                               │                    │ fact + workitem/bad_image
    │                               │◀─{fact_id,...}─────│
    │                               │ outbox=pushed      │
```

---

## 6. 联调 fixtures 与契约测试

| fixture | 归属 | 用途 |
|---|---|---|
| `model_yaml_sample.yaml` | B | `model.yaml` 样例（含 classes/推荐阈值） |
| `model_manifest_sample.json` | B | Registry manifest 样例（供 B 的拉取解析测试） |
| `findings_ingest_sample.json` | C | 错图回传 meta 样例（suspicious + bad 两条） |
| `inspect_config_sample.yaml` | C | 检测配置样例（`pipeline-core.load_config` 用，A 预标与 B 工位模板共用） |

契约测试（`tests/contracts/test_cross_platform.py`）：

1. 模型发布：同 tag 不同 digest 禁止覆盖；`model.yaml` 与权重 sha256 一致。
2. 模型拉取：digest 校验、幂等（同 digest 直接 ready）、坏层 → `40010`、非法 `model.yaml` → `42200`。
3. 错图回传：重复请求 → `duplicated=true` 且 id 一致；坏图无图 → 成功；未知工位（A 侧无工位主数据）→ 正常接收；suspicious 图不可解码 → `40010`。
4. 认证：registry 凭据错误 → `40100`；回传缺 `X-Internal-Token` → `40100`。
5. 版本兼容：`schema_version` 未知 / `skillname` 主版本不兼容 → 拒绝。

---

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方契约测试过。*
