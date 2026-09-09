# P0 骨架设计：LS 二开 monorepo + sidecar（D1~D3 落实依据）

> 定位：平台 = **Label Studio 1.x 二开主应用**（单入口、Django+DRF 主数据源）。主题：**LS 深度复用**——账户/标注/上传/审核/预标通道/导出六块几乎零开发，二开只做「字典/数据集版本/训练/复审/方案模板」五个新域 + 薄包裹。
> 依据：`docs/contracts/公共接口与数据契约.md`、`docs/MVP开发计划_3人22天.md`、手册 §2.3。
> 只定义骨架（结构/职责/签名/stub 行为/验收口径），代码明天起落实。归属：🟦B · 🟧C · 🟪共担 · ⬜A。

---

## 1. 整体仓库骨架（LS fork monorepo，手册 §2.3 落地）

```
aoi-doorpanel/                        # 交付仓库 = LS 1.x fork monorepo
├── frontend/                         # 🟦 LS 1.x web/（React+TS，锁上游 tag）
│   └── src/apps/labelstudio/
│       ├── components/Menubar/       # 🟦 菜单：保留「标注」，新增 数据集/训练/检测/系统（先占位）
│       └── pages/
│           ├── Datasets/             # 数据集/字典/导入/预标路由（W1 填充）
│           ├── Training/             # 训练工作台（W2 填充）
│           ├── Inspect/              # 检测/复审/方案模板（W1 填充）
│           ├── Reports/              # 报告（最后做，占位）
│           └── System/               # 用户角色/工位/审计（W1 填充）
├── backend/                          # 🟦 LS 主应用（Django+DRF，主数据源）
│   ├── label_studio/                 # 🟦 LS 原生包：只读锁定上游 tag（红线）
│   └── aoi/                          # 🟦 二开顶层 app（复用关系见 §2.2）
│       ├── core/                     # 三角色映射、权限点循环注册、request_id、错误码
│       ├── datasets/                 # 字典/label config 生成、导入包裹、数据集版本/划分红线
│       ├── prelabel/                 # 预标任务表/三桶路由统计（D15 启用）
│       ├── training/                 # 基模注册/训练任务/预置方案/门禁/模型注册/LLM 复审预留
│       ├── review/                   # 检测事实/复审工作项/终裁/建议清单/坏图回传
│       ├── plans/                    # 检测方案模板（版本化/激活）
│       ├── reports/                  # 报告（占位）
│       └── audit/                    # 审计日志
├── sidecar/                          # 🟪 FastAPI 侧车：8990（B/C 共担，本阶段重点，§3）
├── workers/                          # 🟦 Celery（training=GPU / default=CPU）
├── packages/                         # 共享核心
│   ├── pipeline-core/                # 🟧 切片/NMS/合并/类别映射/三档判定（方案模板驱动）
│   ├── events/                       # 🟦 Redis Streams/幂等基类
│   ├── trainers/                     # 🟦 Trainer adapter（MVP 仅 yolo）
│   ├── exporters/                    # 🟦 onnx.py（FP32/FP16）
│   └── common/                       # 🟦 Job 状态机/配置/日志
├── deploy/                           # ⬜ A：compose（ls-backend/sidecar/workers/pg/minio/redis）、
│                                     #       assets、scripts、离线镜像包
└── docs/                             # contracts/ + 计划/骨架文档
```

---

## 2. LS 复用点与二开点（核心）

### 2.1 复用总表（契约 §0.5 落地到骨架）

| 平台功能 | 骨架动作 | 归属 |
|---|---|---|
| 登录/令牌 | 不动 LS token API；sidecar 同 SECRET 验签（契约 §1.4） | 🟦/🟧 |
| 用户/组织/角色 | 复用 LS users；aoi/core 三角色映射+权限点 | 🟦 |
| 标注项目/任务/编辑器/Data Manager | 零改动复用；label config 由字典渲染注入 | 🟦 |
| 标注审核 | 复用 LS Review 流；aoi 只读投影（不建表） | 🟦 |
| 上传/存储/缩略图 | 复用 LS 存储+预签名；aoi 导入包裹（去重/质检/元数据） | 🟦 |
| 预标通道 | 复用 LS ml/ 连接器+Batch predictions；sidecar 只实现官方协议 | 🟪 |
| 数据集导出 | 复用 LS data_export（YOLO）；aoi 版本绑定+红线 | 🟦 |
| 前端框架 | 复用 LS web 组件/路由/auth store；Menubar+4 页（🟦）；**素材更换：公司 logo/平台名称/描述、去除 LS 吉祥物（🟧C，D4~5）** | 🟦/🟧 |

### 2.2 aoi 各 app 的复用关系（写进每个 app 的 README）

| aoi app | 复用 LS 原生 | 二开内容 |
|---|---|---|
| core | users/组织/权限框架 | 三角色↔LS 角色映射、权限点循环注册、request_id、错误码 |
| datasets | 上传/存储/缩略图、data_export | 缺陷字典、label config 生成、导入包裹、版本/划分红线 |
| prelabel | ml/MLBackend、Batch predictions、predictions 回传 | 任务表、三桶路由统计 |
| training | —（Celery+sidecar 控制） | 基模注册/训练任务表/task_type 枚举/预置方案/门禁/模型注册（四表 D1 前置） |
| review | DataManager 看图组件、LS Review（标注审核） | 工作项/终裁/建议清单/坏图 |
| plans | — | 方案模板 CRUD/版本/激活 |
| reports / audit | activity log（部分） | 报告占位 / 审计表 |

### 2.3 二开硬底线（骨架里就锁死）

1. `backend/label_studio/` 只读锁定上游 tag，改动记 CHANGES.md，可 diff 上游。
2. 标注编辑器/Data Manager 零重构。
3. 不动 LS 原生表语义；aoi 独立建表（契约 §2）。
4. 前端新页面独立路由，不侵入原生组件树。

---

## 3. sidecar 骨架（本阶段重点，共担）

### 3.1 范围（P0 只做这些）

| 做 | 不做（二期/之后） |
|---|---|
| FastAPI 壳 + 路由聚合 + 统一信封/错误码 | 真实 ONNX 推理（StubRuntimeModel 假结果） |
| **LS JWT 验签中间件**（与 LS 同 SECRET）+ 内部头 | MinIO 直连（方案模板先读本地 `plans/`） |
| 全部端点 stub（契约 §4） | Redis 订阅（SSE 先走 stub 事件流） |
| pipeline-core 真逻辑（切片/合并/三档判定）+ stub 模型 | 训练进度真实来源（B 的 worker 后续接入） |
| ML backend 协议端点（LS 官方协议，B 契约+C 实现） | GPU/显存管理（health 占位） |
| 契约测试 + 5 fixture | 采集适配/真实相机 |

### 3.2 目录与归属

```
sidecar/
├── pyproject.toml            🟧  依赖（§3.5）
└── sidecar/
    ├── app.py                🟪  路由聚合+异常处理+中间件装配
    ├── config.py             🟧  环境变量契约（§3.4）
    ├── envelope.py           🟪  统一信封+错误码（契约 §1.3）
    ├── middleware.py         🟦  RequestID + LS JWT 验签/内部头（B 定鉴权契约）
    ├── state.py              🟧  运行时状态（已加载模型/激活方案/背压门）
    ├── django_client.py      🟧  内部调用：facts/bad-images/注册表/权限查证（容错降级）
    ├── dev_token.py          🟦  与 LS 同构的测试 JWT（供 A 模拟器/前端）
    ├── endpoints/
    │   ├── health.py         🟧  GET /health
    │   ├── inspect.py        🟧  POST /inspect/image、/inspect/batch
    │   ├── models.py         🟧  /models/{ref}/load|unload、/models/current
    │   ├── plans.py          🟧  /plans/current、/plans/reload
    │   ├── progress.py       🟦  GET /progress/{job_id}（SSE stub）
    │   └── ml_backend.py     🟪  /{job_id}/health|setup|predict|validate|webhook ← LS ml/ 对接
    ├── runtime/registry.py   🟧  模型注册表代理（调 GET /api/train/models，取 framework/task_type/cover_classes/weights_key/lifecycle，容错）
    └── vlm/__init__.py       ⬜  二期预留（VlmRecheckBackend 实现位）
```

### 3.3 pipeline-core（🟧，契约 §8）签名

```python
@dataclass
class DetectBox:   xyxy; class_id; object_code: str; score: float; model_ref: str = ""
@dataclass
class DetectResult: boxes; tiling_meta: dict; verdict: str; verdict_reasons: list[str]
@dataclass
class ObjectSpec:  code; model_ref; class_map: dict[int,str]; recheck_min; auto_min; risk_level
@dataclass
class PipelineConfig: objects: list[ObjectSpec]; tile_size=1280; overlap=0.2
class RuntimeModel(ABC): infer(tile) -> list[RawBox]

def slice_image(img, tile_size=1280, overlap=0.2) -> list[Tile]
def box_to_global(box, offset) -> DetectBox
def merge_across_tiles(boxes, iou_thr=0.5) -> list[DetectBox]
def decide_verdict(boxes, cfg) -> tuple[str, list[str]]      # 宁错不漏，逐对象阈值
def run(image, cfg, models) -> DetectResult
def load_plan(yaml_text) -> PlanConfig                        # 契约 §7 规则 1/4/5/6
class StubRuntimeModel(RuntimeModel)                          # 确定性假框
```

### 3.4 端点 stub 行为（契约 §4，D3 验收口径）

| 端点 | stub 行为 | 关键错误 |
|---|---|---|
| `GET /health` | 契约 §4.1 结构；gpu 占位；`vlm/llm="stub"` | 开放 |
| `POST /inspect/image` | multipart → PIL 解码（坏图→40010+登记 bad-images）→ 无激活方案→50300 → `run(StubRuntimeModel)` → 写 facts（容错）→ §4.2 响应 | 40100/40402/40010/42900/50300 |
| `POST /inspect/batch` | `{object_keys, station_id}` → 逐个 stub → 汇总 | 同上 |
| `/models/*` | state 增删/列表（P0 注册 StubRuntimeModel） | 40401 |
| `GET /plans/current`、`POST /plans/reload` | 读 `PLANS_DIR/{plan_id}/v{version}.yaml` → 校验 → 激活 → `{ok, loaded_models, checks[]}` | 42200/40401/50300 |
| `GET /progress/{job_id}` | SSE stub：training×2~3 + finished（契约 §4.4） | — |
| `/{job_id}/health|setup|predict|validate|webhook` | LS 官方协议 stub；predict 用 fixture 同构假框 | 无内部头→40100 |

### 3.5 依赖与配置

- 依赖：fastapi / uvicorn[standard] / python-multipart / pydantic≥2 / pyjwt / pyyaml / httpx / pillow / numpy / pytest；pipeline-core 以 path 依赖先行 `pip install -e`。
- 配置键（.env，= 契约 §3.14 键清单）：`PORT` `JWT_SECRET`（**= LS SECRET_KEY**）`INTERNAL_TOKEN` `DJANGO_BASE_URL` `LS_BACKEND_BASE_URL` `REDIS_URL`（预留）`LOCAL_MODEL_ROOT` `PLANS_DIR` `FACT_WRITE_ENABLED` `INSPECT_QUEUE_MAX=32` `INSPECT_CONCURRENCY=2`。

---

## 4. D1~D3 落实步骤（三条线 + 复用验证日）

**仓库线（🟦 B 主笔）**
- D1：fork LS 1.x 锁 tag → monorepo + CHANGES.md → `backend/label_studio/` 只读就位 + `manage.py sys.path` 注入 → `aoi/` apps 骨架（**training 优先**）+ 共享表迁移（契约 §2，**含 aoi_training 四表：train_job/base_model/model/preset；model 含 task_type/cover_classes**）→ **task_type/skill 枚举裁定落地：aoi training 自建（ObjectDetection→RectangleLabels 口径），不依赖 ml_models.SkillNames**（ml_models 二期剥离 + label_studio 只读红线，避免二次迁移）→ `frontend` Menubar 占位 + 4 页面占位路由
- D2 上午：缺陷字典 + label config 生成 stub（RectangleLabels 渲染）→ 全量 aoi API stub+OpenAPI（契约 §3；**/api/train/base-models|models|jobs 注册/列表 stub 优先，C registry 代理 D3 联调依赖**）
- D2 下午：**复用验证日**（三人一起过 §2.1 清单，逐项实测 LS 原生能力，输出复用结论表；不可复用项当场定降级方案并回写契约）
- D3：JWT 登录链确认（sidecar 同 SECRET）+ 内部头 → 与 sidecar 联调（facts/bad-images 打桩应答）

**sidecar 线（🟪 B/C 共担，§3）**
- D1：两个 pyproject + envelope/错误码 + middleware 签名 + pipeline-core types/tiling 真逻辑 + stub 模型 → `/health` 返回信封
- D2：端点全量 stub + 方案模板加载校验 + fixtures 落盘（B 3 份、C 2 份）→ 契约测试跑绿
- D3：LS JWT 验签联调（B 定义、C 接入）+ `dev_token.py` → 空跑验收

**部署线（⬜ A）**
- D2：compose 骨架（ls-backend+sidecar+pg+minio+redis）+ nginx 路由（`/api/*`→ls-backend、`/sidecar/*`→sidecar、`/data/*`→ls-backend）
- D3：契约测试挂 CI

**D3 空跑链路验收口径（8 项，前 5 项 = LS 原生 smoke，后 3 项 = 二开）**：
1. LS 登录/令牌可用（JWT 可被 sidecar 验签）；
2. 新建项目可注入 label config（object_fault_type_XX）；
3. 上传图片 + 缩略图 + 预签名下载正常；
4. 框标注 + Review 流走通；
5. data_export YOLO 导出 smoke 通过（布局实测记录）；
6. sidecar `/health` 信封正确、全部端点 stub 200、样例图出假 DetectResult（verdict/boxes/tiling_meta 齐全）；
7. 无令牌 40100、内部头放行；
8. **接缝自检**：LS 登记 `MLBackend(http://sidecar:8990/stub-0)` → `/{job_id}/health` 返回 UP；契约测试两条 job 全绿。
9. **训练域 schema 就绪**：`/api/train/base-models`、`/api/train/models`、`/api/train/jobs` 返回真实表结构（空数据），sidecar registry 代理调通——D4 起 C 推理联调依赖。

**并行依赖输入**：B——LS 1.x tag 锁定与离线构建清单（给 A）、3 份 fixture 初版、JWT 定义确认、**aoi_training 四表迁移与 /api/train 注册 stub（给 C，D3 联调）**；A——离线 yarn/pip 源与 CI 挂载；C——pipeline-core 签名评审（B 确认二期评估器可用）。

---

*本文为 P0 骨架设计；D2 契约冻结前，签名以本文 + 接口契约为准；复用验证日的实测结论高于纸面推断。*
