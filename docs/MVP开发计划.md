# AOI 双平台 MVP 开发计划（3 人 × 22 天）

> 形态：**平台 A（训练与标注平台，LS 1.x 二开）+ 平台 B（推理与检测平台，独立轻量前后端）**，跨机器部署。
> **模型经镜像仓库（Docker Hub / 内网 registry）分发：A 发布，B 拉取；A 不主动连接 B。**
> 公共部分只有 `packages/skillname` 与 `packages/pipeline-core`。
> 配套：`docs/双平台架构与拆分方案.md`（边界裁决）、`docs/P0骨架设计_双平台.md`（D1~D3 落地依据）、`docs/contracts/` 三份契约（D2 冻结）。

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 平台形态 | A = LS 1.x 二开（数据/标注/预标/训练/**模型发布（勾选模型上传 + 已上传管理/软删）**；账户复用 LS、**RBAC 自研**）；B = FastAPI + SQLite + 独立 React 前端（**一键拉取模型/工位模板/推理/统计/日报/回传**；无 RBAC、无用户认证、无 Redis/Celery/MinIO） |
| 模型分发 | A 把 `/model/{model.onnx, model.onnx.sha256, model.yaml}`（**权重 + 能力描述，同版本**）打成 `FROM scratch` 镜像 `docker push` 到 registry——**上传哪些模型由管理员在模型库中勾选决定**，已上传记录可下线/软删/恢复；B 用 Registry v2 API **列远端 tag + 一键拉取**并校验；**无 A→B 直连、无实例管理、无心跳** |
| 工位与模板 | **全部由 B 自管**（工位/相机/工位模板，GUI 编辑）；A 不持有工位主数据，只在 `model.yaml` 给推荐阈值 |
| 工时 | 3×22 = 66 人日；五条主线保留；两个前端各自独立开发（**平台 A 前端＝B，平台 B 前端＝A**）；A 侧报告最后做、可砍 |
| 里程碑 | M1(D8) 发布镜像→B 拉取→配模板→假图推理→错图回传→A 建复审项；M2(D14) 标注→首轮训练→审批→发布→拉取→模板→推理→回传→**预标→三桶→复审**→回流；M3(D19) **预标三桶闭环（含落版）** + 真机 1 路 + 8 路仿真 + 日报 + 双机离线包；M4(D22) 验收 |
| 契约 | `contracts/跨平台契约_A-B.md`（D2 冻结，D9/D15 窗口）；A/B 各自契约同步维护 |
| 拆分红利 | A 侧预标不再需要独立服务；B 侧零基础设施依赖、可断网运行；产线可用性不再受中心平台影响 |

---

## 1. 分工与边界

### A（数据、平台 B 前端与交付）
数据整理工具、假数据生成（OK 图 + 缺陷图）、节拍模拟器（打 B 的 `/api/v1/inspect/image`）、MinIO 桶初始化、CI、**镜像仓库准备**（registry 地址/命名/账号/离线导出脚本）、**双平台部署**（A 侧 compose + B 侧 compose/systemd + 跨机连通性）、**平台 B 的 5 个前端页面**（概览/检测记录/日报/工位相机/系统）、离线交付包、发版、部署/操作手册。

> **平台 A 的前端不归 A**：`web/` 二开页面（数据集/训练（含模型库与发布）/复审/系统 + 素材更换）由 **B** 实现（D2 确认，见 `docs/P0骨架设计_双平台.md` §2.2 归属）；A 只出平台 B 的前端。

### B（平台 A：后端二开、前端二开与数据智能）
1. **D1~3：训练域数据基座前置**——`aoi_training` 四表迁移（`train_job`/`base_model`/`model`/`preset`）+ `skillname` 枚举裁定落地 + `/api/train/base-models|models|jobs` stub；`model` 表含 `task_type`/`cover_classes`。
2. D1~4：LS fork 仓库骨架（锁 tag、上游模块只读、`label_studio/aoi/` 二开 app、Menubar 占位）+ 契约/stub 先行（aoi API 全量 stub + OpenAPI、共享表迁移、label config 生成）+ D4~5 **A 侧前端素材更换**（公司 logo/名称/描述，去除登录页上游署名；**Heidi 吉祥物保留组件、只替换文案**——D4 裁定）。**A 侧前端页面（数据集/训练（含模型库与发布）/复审/系统）归 B**：按页随对应后端同期交付（D4~D7 数据集/复审骨架、D9~D13 训练/模型库、D13~D15 复审三桶页）。
3. D4~7：**自研 RBAC 三角色**（角色/权限点/授权表 + DRF 权限类；LS 原生角色框架不可用）+ 图片标注（配置 LS 项目；**不做 LS Review 配置**，复审归 `aoi/review`）+ 缺陷字典 + 导入包裹（复用 LS 上传）+ **错图接收端点 `/api/ingest/findings`**。
4. D9~12：训练链（数据集版本/划分/红线、LS data_export 包裹、训练执行流 + 门禁 + 金标准 + ONNX 导出、模型注册与审批）+ **模型发布服务**（`/model/{model.onnx, model.onnx.sha256, model.yaml}` → `FROM scratch` 单层镜像 → `docker push`；契约 §2.1/§2.4）+ **已上传模型管理**（列表 / 下线 / 软删 / 恢复；仅管理员与超管，删除仅清 A 侧记录、仓库镜像保留）。
5. **D12~13（先）：预标**——D12 预标任务 + **A 侧自实现 LS ML backend 协议**（D2 fixture 先行，D12 ONNX 导出后接真模型）；D13 预标真推理（`pipeline-core` + ONNX Runtime，跑 worker-gpu）+ **三桶路由**（`verdict → bucket → review_workitem`，高桶自动转 annotation）。
6. **D13~15（后）：复审**——三桶人工复审（认领/终裁/低桶强制编辑）+ 错图终裁 + 建议清单（R1~R4）/坏图（D13~D14，M2 走通）；D15 批量复审完善 + 数据集落版校验（全部 workitem finalized、低桶已重标 → `phase=published`）。
7. D16：预标阈值调优 + 预标批量压测（真实规模）+ 与 C 对齐 `pipeline-core` 判定语义（边界用例）。
8. D20~22：A 侧报告（最后，仅单页统计，可砍）、审计、验收脚本、文档。

### C（平台 B 后端、推理与相机、公共包）
1. **公共包先行**（D1~2）：`packages/skillname` + `packages/pipeline-core` 真逻辑与签名冻结（A/B 双方契约测试）。
2. **平台 B 骨架**（D1~3）：FastAPI + SQLite + APScheduler + 静态前端托管 + 全量端点 stub。
3. **相机链路推理**（D4~8）：ONNX Runtime 适配器 + `pipeline-core.run` + `/api/v1/inspect/image` + 检测记录落库。
4. **错图回传**（D6~8）：outbox + 重试 + 断点补传，打通 A 的 `/api/ingest/findings`。
5. **模型拉取与工位模板**（D9~12）：Registry v2 拉取（manifest/层解包/sha256/`model.yaml` 校验）+ **远端可用 tag 列表**（`GET /tags/list`）与**一键拉取** + 工位模板校验/热加载/加载自检。
6. **统计与日报**（D15~18）：错图统计、信息统计、日报生成与导出。
7. **真实相机 1 路 + 8 通道仿真**（D17~18）；B 侧运维（保留策略/磁盘水位/日志轮转/备份）。

**跨人共担约定**：

| 事项 | 归属 |
|---|---|
| `skillname` 词汇表（任务类型/code/model_ref/镜像 tag 规范） | **B 主笔**，C 消费并校验 |
| `pipeline-core`（切片/NMS/合并/三档判定/`load_config`；**不绑定 ONNX**，推理后端由 `RuntimeModel` 注入） | **C 主笔**；A 消费（预标）、B 消费（在线推理 + 工位模板校验） |
| 跨平台契约（`model.yaml`/镜像规范/错图回传） | **B 定契约 + A 侧发布实现；C 实现 B 侧拉取与回传** |
| **平台 A 前端**二开页面（数据集/训练（含模型库与发布）/复审/系统 + 素材更换） | **B 主笔**（`web/apps/labelstudio/src/pages/`，复用 LS 组件库，D2 确认） |
| **平台 B 前端** 5 页（概览/检测记录/日报/工位相机/系统） | **A 主笔**（依赖 C 的 API stub） |
| 镜像仓库与双平台部署/离线包 | **A 主笔**，B/C 提供依赖清单 |
| 契约测试 | 消费方写用例、维护方 CI 跑 |

---

## 1.1 技术栈选型与中间件分工

### 1.1.1 技术栈

| 层 | 平台 A | 平台 B |
|---|---|---|
| 后端 | Django + DRF（LS 1.x fork） | FastAPI + Uvicorn（单进程） |
| 数据库 | PostgreSQL 15 | **SQLite（WAL）**，可切 PG |
| 对象存储 | MinIO | 本地磁盘 |
| 异步任务 | **Celery 5** + Redis 7（aoi 二开任务） | APScheduler（进程内），**无 Redis/Celery** |
| 推理 | ONNX Runtime（预标，Celery GPU worker；TensorRT 二期） | ONNX Runtime（CUDA EP / CPU） |
| **模型分发** | 构建镜像 + `docker push` 到 registry | **Registry v2 API 拉取**（httpx + tarfile，无 Docker daemon） |
| 前端 | LS 1.x web（React + TS） | Vite + React + TS + Ant Design 5 + ECharts（**独立**） |
| 报告 | Jinja2（A 侧可选） | Jinja2（日报 HTML + CSV） |
| 交付 | Docker Compose | Docker Compose 或 systemd |

> **Celery/RQ 说明**：LS 上游自带 `django_rq` 仅服务 LS 原生功能，保持不动；**aoi 二开的训练/导入/发布任务统一 Celery**，两者共存不冲突。平台 B 不使用任何消息队列。

### 1.1.2 中间件分工

| 工作项 | 归属 | 内容 |
|---|---|---|
| A 侧基础设施编排 | A | PG、MinIO、Redis、worker-gpu、worker-cpu、beat 的 compose/健康检查/离线依赖 |
| B 侧部署编排 | A | B 的 Dockerfile/compose/systemd、静态前端托管、磁盘规划、备份脚本 |
| 镜像仓库 | A | registry 地址与命名规范、推送/拉取账号（A 写、B 只读）、离线导出脚本 |
| 公共契约 | B | Celery app 骨架、队列命名、任务协议、事件定义、幂等基类 |
| A 业务任务接入 | B | datasets/training/review/**发布** 的 Celery task 与状态流转 |
| B 侧定时任务 | C | APScheduler：日报、统计滚动、保留清理、outbox 重试 |
| 跨机联调 | A/B/C | D3 打通发布/拉取与错图回传 stub；D6 回传真实联调；D7 镜像真实联调 |

---

## 2. 平台 A 的 LS 原生复用清单与二开增量

### 2.1 复用（零开发或仅配置，D2 复用验证日实测确认）

| 平台功能 | LS 原生能力 | MVP 动作 |
|---|---|---|
| 登录/令牌/账户 | LS users + token API（JWT HS256，含 `user_id`） | 零改动复用账户与登录 |
| 角色/权限（RBAC） | LS 原生角色/组织权限框架**不可用** | **自研**：`aoi_core` 五表（角色/权限点/授权表/用户角色 + 授权版本号）+ DRF 权限类 + **LS 原生闸门**（契约 §3.1/§3.1.1）（D4 已落地） |
| 标注项目/任务/框标注 | projects/tasks/annotations + RectangleLabels | 零改动；label config 由字典渲染 |
| 数据浏览 | Data Manager | 零重构 |
| 标注审核 | **LS OSS 1.24 无 Review 流**（D2 实测、D4 复验） | **自研**：`aoi/review` 三桶复审 + 终裁（契约 §10.1） |
| 上传/存储/缩略图 | 本地存储/MinIO + 预签名 + 缩略图 | aoi 导入包裹（去重/质检/元数据） |
| 预标通道 | ml/ MLBackend + Batch predictions + predictions 回传 | 零二开；A 侧实现官方协议 |
| 数据集导出 | data_export（YOLO/COCO） | aoi 版本绑定 + 红线 + 校验 |
| 前端框架 | web/apps 组件/路由/auth store | Menubar 入口 + 二开页面 |

### 2.2 二开增量（真正要写的代码）

- **`label_studio/aoi/` 七个二开 app（四个业务新域 + 三个支撑 app）**：业务新域 datasets（字典/版本/划分红线/导入包裹）、prelabel（预标 + ML backend 协议）、training（任务/门禁/注册/**发布 + 已上传管理（下线/软删/恢复）**）、review（工作项/终裁/建议/坏图 + 错图接收）；支撑 app core（**自研 RBAC**/公共）、audit（审计）、reports（可选）。
- **A 侧前端页面**（**B 主笔**，D2 确认，不归 A）：数据集、训练（含模型库与发布：**模型列表多选批量上传 + 已上传记录管理**）、复审、系统（用户/角色/审计）（复用 LS 组件库）+ 素材更换（公司 logo/名称/描述，去除上游署名与登录页营销文案；Heidi 组件保留、文案替换为平台自有）。
- **workers**：Celery 训练/导入/模型发布任务。
- **A 侧预标推理**：`pipeline-core` + ONNX Runtime，跑在 worker-gpu。

### 2.3 平台 B 的复用与不造轮子

| 能力 | 做法 |
|---|---|
| 切片/合并/三档判定/配置解析 | **直接复用 `pipeline-core`**（`load_config`/`InspectConfig`），与 A 的预标判定同源 |
| 任务类型/缺陷 code/model_ref/镜像 tag 校验 | **直接复用 `skillname`** |
| 模型获取 | Registry v2 API（httpx + tarfile），不引入 Docker daemon；本机有 Docker 时可切 CLI |
| 工位模板编辑 | Ant Design Form + `POST /template/validate` 实时校验，不自研编辑器 |
| Web 框架 | FastAPI 自动 OpenAPI，前端按契约对接，不手写 SDK |
| 定时任务 | APScheduler 进程内，不引入 Celery/Redis |
| 日报 | Jinja2 HTML + CSV，不引入 WeasyPrint（PDF 二期） |
| 迁移 | 顺序 SQL 迁移 + `schema_version` 表，不引入 Alembic（可切） |

---

## 3. MVP 范围裁剪

| 变更点 | MVP 决策 |
|---|---|
| 平台拆分 | A 数据/标注/预标/训练/发布；B 拉模型/配工位模板/推理/统计/日报/回传；跨机器，不共享数据库/对象存储 |
| 模型分发 | **只走镜像仓库**；不做 A→B 直连、不做分片上传/断点续传、不做实例注册与心跳 |
| 已上传模型的删除 | **只软删 A 侧记录**（`deleted_at` + 审计，仓库镜像保留、B 仍可拉取）；**仓库镜像的物理清理不入 MVP**（人工执行）；删除前必须先下线（`lifecycle=retired`），仅管理员/超管可操作，支持恢复 |
| B 侧拉取入口 | **列远端 tag + 一键拉取**（只读凭据调 Registry v2 `GET /tags/list`）；不做镜像仓库的目录/搜索、不做断点续传、不做拉取进度百分比（只做 `pulling`/成功/失败三态） |
| 工位与工位模板 | **B 自管**（GUI 编辑）；A 不持有工位主数据，只在 `model.yaml` 给推荐阈值 |
| B 的 RBAC / 用户认证 | **都不做**；无用户体系、无登录、无用户认证；靠内网隔离 |
| B 的基础设施 | **不做** Redis/Celery/MinIO/Nginx（可选）/K8s/Docker daemon（可选）；SQLite + 本地磁盘 + 单进程 |
| GPU 调度（分时互斥） | 不做。A 训练与 B 推理本就在不同机器，天然互斥 |
| 预标注（ML backend） | **保留，D12~13 开发（先于复审）**：通道本身是 LS 原生，D2 就验连通；A 侧自实现协议 + 三桶路由；**三桶人工复审 D13~15（后）** |
| A 侧报告 | 最后（D20~22），仅单页统计；来不及就砍 |
| B 侧日报 | **核心能力，不砍**；D15 起做，D18 前可用 |
| LLM 参数复审 / VLM 复审 | 接口 + stub，线上人工接管 |
| 高价值数据桶 | 建桶 + 目录规范预留，落桶二期 |
| 去重/质检 | MD5 去重 + 格式/坏图质检；pHash/模糊检测二期 |
| 训练框架 | 仅 YOLO；HF/sklearn 二期 |
| 相机 | 1 路真实（D17）+ 8 路仿真；硬触发/`camera.captured` 流二期 |
| 视频流/大屏 | 不进 MVP；B 只做 1~2fps 快照与结果展示 |
| 两级审核 | **不复用 LS Review（LS OSS 无此能力，D4 复验见契约 §10.1）**；复审由 `aoi/review` 自研（三桶路由 + 人工终裁），平台不自建通用审核 UI |
| 私有 registry / OCI artifact | 用公开或内网 registry 的普通镜像；`oras`/签名/SBOM 二期 |
| B 自动升级 | 不做；离线包人工升级 |

---

## 4. 公共接口协调

> 详细定义在 `docs/contracts/`：**跨平台契约 A-B**（`model.yaml`/镜像规范/错图回传）、**平台 A 契约**、**平台 B 契约**。

**协调机制**：D2 冻结契约；**D2 下午复用验证日**（LS 能力逐项实测，实测为准回写契约）；先 stub 后实现；契约测试消费方写、维护方 CI 跑；D9/D15 变更窗口，破坏性变更四件套。

**跨平台关键接口 TOP9（按联调时间排）**：

| # | 接口/规范 | 方向 | 时间 |
|---|---|---|---|
| 1 | `model.yaml` Schema + 镜像布局（`/model/*`） | 规范 | D2 冻结 |
| 2 | `packages/pipeline-core` 签名（`InspectConfig`/`load_config`） | 共享 | D2 |
| 3 | `packages/skillname`（含 `image_tag_from_model_ref`） | 共享 | D2 |
| 4 | `POST {B}/api/v1/models/pull`（假 manifest 走通） | registry→B | D3 stub / D7 真实 ★ |
| 5 | `POST {A}/api/train/models/{id}/publish` | A→registry | D3 stub / D7 真实 ★ |
| 6 | `POST {A}/api/ingest/findings`（错图回传） | B→A | D3 stub / D6 真实 ★ |
| 7 | `POST {B}/api/v1/inspect/image`（相机/模拟器） | 外部→B | D5 |
| 8 | `PUT {B}/api/v1/stations/{code}/template`（工位模板） | B 本地 | D9 |
| 9 | `POST /api/prelabel/{task_id}/{health,setup,predict,validate}`（LS 官方协议） | LS→A | D12~13 ★ |

**A 侧业务接口**：`/api/datasets/*`、`/api/train/*`、`/api/review/*`、`/api/core/*`、`/api/ingest/*`，见平台 A 契约。

---

## 5. 22 天排期（细化到天）

### P0 契约与地基（D1–D3）——目标：双平台空跑 + 镜像/回传链路 stub 打通 + LS 复用结论

| 天 | A | B | C |
|---|---|---|---|
| D1 | monorepo 目录与 `packages/` 骨架；CI 骨架；双平台部署骨架；**registry 地址/命名/账号准备** | 契约评审会（全员）；LS fork 骨架确认；**aoi_training 四表迁移 + skillname 枚举裁定落地**；`/api/ingest/*` stub | 平台 B 骨架（FastAPI + SQLite + APScheduler + 前端壳 5 页路由）；**`skillname` + `pipeline-core` 真逻辑**（切片/合并/三档判定/`load_config`）；B 全量端点 stub |
| D2 | 双平台 compose/systemd + registry 连通性验证；离线依赖清单；B 前端脚手架（Vite + AntD + ECharts） | 上午：共享表迁移收尾 + label config 生成 stub + aoi API 全量 stub（含 `/api/train/*`）+ **`model.yaml` 生成 stub**；**下午：复用验证日（LS 8 项实测）**；预标 ML backend fixture | B 端点 stub 收尾 + fixture；**假 manifest 拉取链路** + 工位模板 stub；契约测试跑绿；前端 mock 数据 |
| D3 | 契约测试挂 CI；B 前端布局/路由 | JWT 登录链确认 + **`/api/ingest/findings` 打桩应答** + `model_publish` 表 + 发布服务 stub（假 build/push） | 工位模板校验链路 + 与 A 打桩联调（错图回传）+ B 前端对接 mock |
| **验收** | **10 项**：① LS 登录/令牌 ② label config 注入 ③ 上传+缩略图 ④ 框标注（**Review 流不复用**：LS OSS 无此能力，D4 复验） ⑤ YOLO 导出 smoke ⑥ A 的 `/health` 与 OpenAPI ⑦ B 的 `/health` 与 OpenAPI ⑧ **发布/拉取 stub 全绿（`model.yaml` 生成 + 假 manifest + digest/sha256 校验 + 幂等）** ⑨ **错图回传 stub 全绿（幂等 + `duplicated=true` + 坏图无图分支）** ⑩ `pipeline-core`/`skillname` 双端契约测试绿 | | |

> **D3 工程卫生**：D2 code review 判为 P3 的 30 项（提交/文档引用、stub 语义、索引与分页、前端与部署、工具链噪音）外挂在 `docs/D3_工程卫生清单.md`，D3 按该表顺序处理；不阻塞 M1。

### P1 相机链路先行（D4–D8）→ M1(D8)

| 天 | A | B | C |
|---|---|---|---|
| D4 | 数据整理工具；B 前端「概览」页骨架 | **自研 RBAC 三角色（✅ 已完成）**：`aoi_core` 五表 + 38 码 + 判定/缓存 + `/api/core/*` 真实化 + `aoi_grant_role` 引导；**LS 原生闸门（✅ 已完成）**；LS 项目模板 `aoi/datasets/ls_project.py`（✅ 已完成）；**前端素材更换（✅ 已完成）** | `pipeline-core` 切片/NMS 真逻辑；ONNX Runtime 适配器；B 检测记录落库 |
| D5 | 假数据生成（OK + 缺陷图）；B 前端「检测记录」页 | 缺陷字典 + label config 生成（✅ 已完成）；**导入包裹（✅ 已完成：Celery `default` 队列异步 + 复用 LS 上传 + md5 全局去重）**；**标注项目创建（✅ 自 D6 提前完成：`POST /api/datasets` 服务端按 `ls_project.py` 模板创建 LS 项目）**；前端素材更换完成；**A 侧前端「数据集」页（✅ 已完成：字典/图片/数据集三块）** | `/api/v1/inspect/image` 完整链路；单图推理 + 三档判定；B 记录查询接口 |
| D6 | 节拍模拟器（打 B 的 `/api/v1/inspect/image`） | 标注项目创建（**✅ 已提前至 D5 完成**，应用 `aoi/datasets/ls_project.py` 模板）；**不做 LS Review 配置**；**`/api/ingest/findings` 完整实现（图片落 MinIO + fact + workitem/bad_image）**；A 侧前端「复审」页骨架 | 相机适配器壳（DirectorySource）+ 坏图登记 + outbox 回传真实打通 |
| D7 | 双机联调 + 离线包初版；B 前端「工位与相机」页 | **模型发布服务真实推送**（在模型库中**勾选模型**（支持多选批量，逐条独立）→ `/model/{model.onnx, model.onnx.sha256, model.yaml}` → `FROM scratch` 单层镜像 → `docker push` → 写 `model_publish{image,tag,digest,status}`；权重先用基模导出的占位 ONNX，D12 真模型复用同一条流水线，**不得只发 `model.yaml`**）；**已上传记录的下线/软删/恢复后端**（软删只清 A 侧记录，仓库镜像保留）；A 侧前端「训练」页骨架 | **B 模型拉取真实打通**（Registry v2 manifest/层解包/校验/注册）+ **远端可用 tag 列表与一键拉取**；B 前端联调 |
| D8 | **M1 联调** + B 前端「系统」页 | **M1 联调**（复审工作项可见） | **M1 联调**（端到端稳定） |
| **M1** | A 发布镜像 → B 拉取 → 配一个工位模板 → 假图按节拍推理 → 三档判定 → 错图回传 → A 建复审工作项；B 概览页可见统计；界面为公司 logo/平台描述、无上游署名与 LS 营销文案 | | |

> **D7 A 侧「发布服务真实推送」的验收附加项（digest 语义，项目负责人 2026-09-11 裁定）**：
>
> | # | 要求 | 验收方式 |
> |---|---|---|
> | 1 | **digest 必须来自仓库回执**：每次推送以仓库返回的 `Docker-Content-Digest`（manifest 与每个 blob）为准并核对；**仓库不回回执一律视为失败**（不拿本地 manifest sha256 兜底），错误如实落 `model_publish.error_message` | 契约测试：仓库不回执 → 发布失败、状态 `failed`、`digest` 为空；回执与本地不一致 → 同样失败 |
> | 2 | **digest 可复现**：同一 `model_ref` + 同一产物内容，任意时刻重建推送必须得到**同一个 digest**（跨平台契约 §2.2「同 tag 不同 digest → 禁止覆盖」与 §2.4「B 按 digest 记录」都依赖它） | 契约测试：同一模型跨"不同时刻"连续发布两次，digest 必须相等（该用例当前以"必须不等"锁定待修事实，D7 修复后翻转为相等断言） |
> | 3 | 修法方向（实现自选，但须**同时**满足 1、2） | 时间戳（`model.yaml.created_at`/`published_at`）不参与 digest：① 落盘/推送前把时间戳从镜像内 `model.yaml` 中剔除，或固定为构建批次时间；② 或改由 `model_publish`/`config_snapshot` 承载时间信息，镜像内保持可复现字节 |
> | 4 | 三处口径同步 | `publish.py` 模块头「字节可复现」的措辞、跨平台契约 §2.4 的发布步骤、B 侧 digest 校验口径 |

### P2 训练 + 预标闭环（D9–D14）→ M2(D14)

| 天 | A | B | C |
|---|---|---|---|
| D9 | 缺陷样本补充；B 前端「日报」页骨架 | 数据集版本/划分/测试集红线；发布流程完善（重试/失败重推、批量逐条结果展示） | **工位模板 GUI 校验与热加载**（`load_config` 边界用例） |
| D10 | 万级导入压测；B 前端图表联调 | LS data_export 包裹（YOLO 导出 + 红线校验）；A 侧前端「模型库」页（**多选批量上传 + 已上传管理：下线/删除/恢复**） | B 多模型按对象分发 + 模型库页（**远端列表 + 一键拉取**/导入/删除） |
| D11 | 交付包完善（权重/字体/双平台镜像/离线模型镜像） | YOLO adapter + 训练执行流 + 训练进度 SSE + 发布前置（金标准/审批） | B 加载自检（张量匹配 + 空跑）+ 预加载/卸载 |
| D12 | 自检脚本；B 前端「模型库」区 | 门禁 + 金标准回归 + ONNX 导出 + 模型 lifecycle + 审批流；**预标任务 + A 侧 ML backend 协议端点**（fixture 先行，导出后接真模型） | B 磁盘保留策略 + 清理任务 + 磁盘水位告警 |
| D13 | 备份脚本 | **预标真推理（`pipeline-core` + ONNX Runtime，worker-gpu）+ 三桶路由**（高桶自动转 annotation + auto-finalized 记录；中/低桶生成 `review_workitem`，低桶 `forced=true`）；**三桶人工复审队列**（认领/终裁/低桶强制编辑）；A 侧前端「复审」三桶页（红/黄/绿） | B 检测记录/错图统计接口完善 |
| D14 | **M2 联调** | **复审/建议清单（R1~R4）/坏图后端完整** + **M2 联调** | **M2 联调** |
| **M2** | 标注 → 首轮训练 → 审批 → **发布镜像** → B 拉取 → 工位模板 → 推理 → 回传 → **预标 → 三桶 → 复审** → 回流 全闭环（小数据集） | | |

### P3 三桶复审落版 + 相机 + 生产化（D15–D19）→ M3(D19)

| 天 | A | B | C |
|---|---|---|---|
| D15 | 真实数据导入演练；B 前端「日报」详情/导出 | 三桶复审完善（批量/筛选/进度）+ **数据集落版校验**（全部 workitem finalized、低桶已重标 → `phase=published`）；A 侧前端复审页批量/落版入口 | B 日报生成（APScheduler + Jinja2 HTML + CSV）+ 统计聚合 |
| D16 | 双机离线导入演练 | 预标阈值调优 + 预标批量压测（真实规模）+ 与 C 对齐 `pipeline-core` 判定语义（边界用例） | 8 通道仿真并发 + 背压 + 时延验证 |
| D17 | 7×24 冒烟 | 审计完善 + 验收脚本 | 真实 GigE 相机 1 路 + 触发采集 |
| D18 | 压测（8 路仿真） | 操作文档（双平台） | 日报/统计验收 + FP16 回归 + 保留策略演练 |
| D19 | **M3 联调** | **M3 联调** | **M3 联调** |
| **M3** | **预标三桶闭环（预标→三桶→人工复审→落版）** + 真机 1 路 ≤3s + 8 路仿真不丢 + 双机离线包新机导入全绿 + 日报可出 | | |

### P4 收尾（D20–D22）→ M4(D22)

| 天 | A | B | C |
|---|---|---|---|
| D20 | 交付包终版；B 前端体验收尾 | A 侧报告统计页（最后做；来不及则砍） | B 性能优化 + 断网恢复演练 |
| D21 | 交叉验收 + 缺陷修复（全员） | 同左 | 同左 |
| D22 | 发版 tag + 双平台离线包 + 部署/操作手册 | 验收记录 | 验收记录 |
| **M4** | MVP 验收通过（五主线 + 性能 + 跨机 + 离线） | | |

---

## 6. 风险与应对

| 风险 | 应对 |
|---|---|
| 镜像仓库不可达/限流/凭据失效 | B 用本地已有模型继续推理；A 侧发布失败可重推；离线包（`docker save`/层 tar）人工导入；必要时切内网 registry |
| 镜像 digest 不可复现或拿不到仓库回执（同 tag 不同 digest → 违反"不覆盖"；B 无法按 digest 固定版本） | **按 §5 D7「验收附加项」在 D7 修死**：digest 一律取仓库回执、不回执即失败；时间戳移出参与 digest 的内容，保证同输入同 digest |
| 模型上传/删除误操作 | 上传由管理员勾选触发（非自动），失败可重推；删除为**软删 + 审计 + 可恢复**且要求先下线；仓库镜像不删，误删不影响 B 拉取 |
| 私有仓库拉取凭据泄漏 | B 只配只读 token；token 存环境变量不落库；定期轮换 |
| 两平台契约漂移（`skillname`/`pipeline-core`/`model.yaml`） | 公共包语义化版本 + `model.yaml.schema_version`；双端契约测试挂 CI；D2 冻结、D9/D15 窗口 |
| B 侧被做重（引入 Redis/Celery/MinIO/Docker daemon） | 轻量化硬约束进评审红线；B 的依赖清单由 C 维护、A 在交付包中校验 |
| B 无用户认证带来的安全风险 | 内网/产线网段隔离（唯一安全边界）+ 不暴露 DB 与文件目录；跨机走 HTTPS/VPN |
| A 发布镜像阻塞 B 上线 | B 支持离线导入模型镜像；发布失败不影响 B 用旧模型运行 |
| 工位模板配错导致误判 | 保存/启用前强制 `load_config` 校验 + 前端实时校验 + 操作日志；模板版本可回退 |
| 可疑图回传积压导致 B 磁盘涨 | 保留策略 + 未回传图片不清理 + 磁盘水位告警 + 人工导出兜底 |
| 平台 B 仍是单人（C 同时做后端+推理+相机） | 公共包先行、B 端点 stub 先行、**平台 B 前端由 A 承担**；B 的功能面按 §3 严格裁剪 |
| 平台 A 前端（数据集/训练/模型库/复审/系统）与预标、复审都压在 B 一人身上 | 复用 LS 组件库 + aoi API stub（D2 起可用）；页面以表格+表单为主，不做复杂交互；M2 前只做训练/复审两页，其余进 P3 |
| LS 复用点实测与预期不符（Review/导出等） | **D2 复用验证日**逐项实测；不符项当天定降级方案回写契约 |
| 66 人日压缩率高，M2 闭环超时 | 复用红利转联调缓冲；回流环节允许「人工导图 + 改 source」降级；A 侧报告可砍 |
| 预标依赖首轮模型产物（D12 ONNX 导出），训练链一延，预标三桶与复审就顺延 | ML backend fixture 在 D2 就由 B 出具（LS 实测样例），预标任务/协议/三桶路由先用 fixture 自测；D15~16 预留阈值调优与批量压测缓冲 |
| 真实相机型号/驱动未定 | C 用 DirectorySource + HTTP 双通道开发；相机延期不影响 M1/M2 |
| 跨机时钟漂移影响日报 | NTP 强制；双时间戳（`captured_at`/`received_at`）；偏差 > 2s 告警 |
| 假数据与真实分布偏差 | A 按真实分辨率/光照/缺陷形态生成；A 侧金标准回归兜底 |

---

*随开发维护：D2/D9/D15 评审；契约变更同步 `docs/contracts/` 与 `docs/P0骨架设计_双平台.md`。*

*2026-09-10 调整：① 预标提前到 D12~13（**先于复审**），三桶人工复审 D13~15；② 平台 A 前端归属 **B**（与 `docs/P0骨架设计_双平台.md` §2.2、`docs/设计_预标三桶复审流程.md` §7 一致）；③ 模型发布镜像内容按跨平台契约 §2.1 明确为 `/model/{model.onnx, model.onnx.sha256, model.yaml}`（不是只放 `model.yaml`）。*

*2026-09-11 补充（项目负责人裁定，镜像分发机制不变）：① **A 侧上传由管理员在模型库中勾选决定**（支持多选批量，`POST /api/train/models/publish`，**逐条独立**返回结果，非"审批即自动发布"）；② **A 侧可管理已上传模型**——列表 / 下线（`lifecycle=retired`）/ **软删（只清 A 侧记录 + 审计，仓库镜像保留）** / 恢复，仅管理员与超管，删除前必须先下线；③ **B 侧一键拉取**——新增远端可用 tag 列表（Registry v2 `GET /tags/list`）→ 选中 → 一键拉取，拉取完成后模型立即可用于工位模板与模型选择；④ 不引入 A→B 心跳/回执，A 侧不展示"模型是否已被产线使用"。详见 `docs/contracts/跨平台契约_A-B.md` §2.4/§2.5、`平台A_接口与数据契约.md` §3.3/§4.2、`平台B_接口与数据契约.md` §3.2。*
