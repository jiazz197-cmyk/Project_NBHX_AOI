# AOI 双平台 MVP 开发计划（3 人 × 22 天）

> 形态：**平台 A（训练与标注平台，LS 1.x 二开）+ 平台 B（推理与检测平台，独立轻量前后端）**，跨机器部署。
> 公共部分只有 `packages/skillname` 与 `packages/pipeline-core`。
> 配套：`docs/双平台架构与拆分方案.md`（边界裁决）、`docs/P0骨架设计_双平台.md`（D1~D3 落地依据）、`docs/contracts/` 三份契约（D2 冻结）。

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 平台形态 | A = LS 1.x 二开（Django+DRF 主数据源，账户复用 LS、**RBAC 自研**）；B = FastAPI + SQLite + 独立 React 前端（无 RBAC、无 Redis/Celery/MinIO） |
| 复用策略 | A 侧「能用 LS 原生的绝不自己写」；B 侧「能不做的一律不做」，只保留推理/统计/日报/回传 |
| 工时 | 3×22 = 66 人日；五条主线保留；B 前端独立开发；A 侧报告最后做、可砍 |
| 里程碑 | M1(D8) 模型+方案下发→假图推理→错图回传→A 建复审项；M2(D14) 标注→训练→审批→下发→激活→推理→回传→复审→回流；M3(D19) 预标 + 真机 1 路 + 8 路仿真 + 日报 + 双机离线包；M4(D22) 验收 |
| 契约 | `contracts/跨平台契约_A-B.md`（D2 冻结，D9/D15 窗口）；A/B 各自契约同步维护 |
| 拆分红利 | A 侧预标不再需要独立服务；B 侧零基础设施依赖、可断网运行；产线可用性不再受中心平台影响 |

---

## 1. 分工与边界

### A（数据、B 平台前端与交付）
数据整理工具、假数据生成（OK 图 + 缺陷图）、节拍模拟器（打 B 的 `/api/v1/inspect/image`）、MinIO 桶初始化、CI、**双平台部署**（A 侧 compose + B 侧 compose/systemd + 跨机网络连通性）、**平台 B 的 5 个前端页面**（概览/检测记录/日报/工位相机/系统）、离线交付包、发版、部署/操作手册。

### B（平台 A：LS 二开与数据智能）
1. **D1~3：训练域数据基座前置**——`aoi_training` 四表迁移（`train_job`/`base_model`/`model`/`preset`）+ `skillname` 枚举裁定落地 + `/api/train/base-models|models|jobs` stub；`model` 表含 `task_type`/`cover_classes`。
2. D1~4：LS fork 仓库骨架（锁 tag、上游模块只读、`label_studio/aoi/` 二开 app、Menubar 占位）+ 契约/stub 先行（aoi API 全量 stub + OpenAPI、共享表迁移、label config 生成）+ D4~5 **前端素材更换**（公司 logo/名称/描述，去除 LS 吉祥物与登录页署名）。
3. D4~7：**自研 RBAC 三角色**（角色/权限点/授权表 + DRF 权限类；LS 原生角色框架不可用）+ 图片标注（配置 LS 项目/Review 流）+ 缺陷字典 + 导入包裹（复用 LS 上传）+ **错图接收端点 `/api/ingest/findings`**。
4. D9~12：训练链（数据集版本/划分/红线、LS data_export 包裹、训练执行流 + 门禁 + ONNX 导出、模型注册与审批）+ **模型下发服务**（推送到 B）。
5. D13~14：复审/回流后端（工作项/终裁/建议清单/坏图）。
6. D15~16：预标任务 + **A 侧自实现 LS ML backend 协议**（复用 `pipeline-core` 推理）。
7. D20~22：A 侧报告（最后，仅单页统计，可砍）、审计、验收脚本、文档。

### C（平台 B 后端、推理与相机、公共包）
1. **公共包先行**（D1~2）：`packages/skillname` + `packages/pipeline-core` 真逻辑与签名冻结（A/B 双方契约测试）。
2. **平台 B 骨架**（D1~3）：FastAPI + SQLite + APScheduler + 静态前端托管 + 全量端点 stub。
3. **相机链路推理**（D4~8）：ONNX Runtime 适配器 + `pipeline-core.run` + `/api/v1/inspect/image` + 检测记录落库。
4. **错图回传**（D6~8）：outbox + 重试 + 断点补传，打通 A 的 `/api/ingest/findings`。
5. **模型/方案接收**（D9~12）：分片上传 + sha256 + 落盘注册；方案校验 + 热加载 + 激活/回滚 + 加载自检。
6. **统计与日报**（D15~18）：错图统计、信息统计、日报生成与导出。
7. **真实相机 1 路 + 8 通道仿真**（D17~18）；B 侧运维（保留策略/磁盘水位/日志轮转/备份）。

**跨人共担约定**：

| 事项 | 归属 |
|---|---|
| `skillname` 词汇表（任务类型/code/model_ref 规范） | **B 主笔**，C 消费并校验 |
| `pipeline-core`（切片/NMS/合并/三档判定/load_plan） | **C 主笔**，B 消费（预标） |
| 跨平台契约（模型/方案下发、错图回传、心跳） | **B 定契约 + A 侧实现；C 实现 B 侧** |
| B 平台前端 5 页 | **A 主笔**（依赖 C 的 API stub） |
| 双平台部署与离线包 | **A 主笔**，B/C 提供依赖清单 |
| 契约测试 | 消费方写用例、维护方 CI 跑 |

---

### 1.1 技术栈选型与中间件分工

#### 1.1.1 技术栈

| 层 | 平台 A | 平台 B |
|---|---|---|
| 后端 | Django + DRF（LS 1.x fork） | FastAPI + Uvicorn（单进程） |
| 数据库 | PostgreSQL 15 | **SQLite（WAL）**，可切 PG |
| 对象存储 | MinIO | 本地磁盘 |
| 异步任务 | **Celery 5** + Redis 7（aoi 二开任务） | APScheduler（进程内），**无 Redis/Celery** |
| 推理 | ONNX Runtime（预标，Celery GPU worker） | ONNX Runtime（CUDA EP / CPU） |
| 前端 | LS 1.x web（React + TS） | Vite + React + TS + Ant Design 5 + ECharts（**独立**） |
| 报告 | Jinja2（A 侧可选） | Jinja2（日报 HTML + CSV） |
| 交付 | Docker Compose | Docker Compose 或 systemd |

> **Celery/RQ 说明**：LS 上游自带 `django_rq` 仅服务 LS 原生功能，保持不动；**aoi 二开的训练/导入/下发任务统一 Celery**，两者共存不冲突。平台 B 不使用任何消息队列。

#### 1.1.2 中间件分工

| 工作项 | 归属 | 内容 |
|---|---|---|
| A 侧基础设施编排 | A | PG、MinIO、Redis、worker-gpu、worker-cpu、beat 的 compose/健康检查/离线依赖 |
| B 侧部署编排 | A | B 的 Dockerfile/compose/systemd、静态前端托管、磁盘规划、备份脚本 |
| 公共契约 | B | Celery app 骨架、队列命名、任务协议、事件定义、幂等基类 |
| A 业务任务接入 | B | datasets/training/review/下发 的 Celery task 与状态流转 |
| B 侧定时任务 | C | APScheduler：日报、统计滚动、保留清理、心跳、outbox 重试 |
| 跨机网络与联调 | A/B/C | D3 打通模型下发与错图回传 stub；D6 真实联调 |

---

## 2. 平台 A 的 LS 原生复用清单与二开增量

### 2.1 复用（零开发或仅配置，D2 复用验证日实测确认）

| 平台功能 | LS 原生能力 | MVP 动作 |
|---|---|---|
| 登录/令牌/账户 | LS users + token API（JWT HS256，含 `user_id`） | 零改动复用账户与登录 |
| 角色/权限（RBAC） | LS 原生角色/组织权限框架**不可用** | **自研**：`aoi_core` 三角色 + 权限点 + 授权表 + DRF 权限类 |
| 标注项目/任务/框标注 | projects/tasks/annotations + RectangleLabels | 零改动；label config 由字典渲染 |
| 数据浏览 | Data Manager | 零重构 |
| 标注审核 | Review 流 | 配置启用；aoi 只读投影 |
| 上传/存储/缩略图 | 本地存储/MinIO + 预签名 + 缩略图 | aoi 导入包裹（去重/质检/元数据） |
| 预标通道 | ml/ MLBackend + Batch predictions + predictions 回传 | 零二开；A 侧实现官方协议 |
| 数据集导出 | data_export（YOLO/COCO） | aoi 版本绑定 + 红线 + 校验 |
| 前端框架 | web/apps 组件/路由/auth store | Menubar 入口 + 二开页面 |

### 2.2 二开增量（真正要写的代码）

- **`label_studio/aoi/` 九个二开 app（五个业务新域 + 四个支撑 app）**：业务新域 datasets（字典/版本/划分红线/导入包裹）、prelabel（预标 + ML backend 协议）、training（任务/门禁/注册/下发）、review（工作项/终裁/建议/坏图 + 错图接收）、plans（方案模板）；支撑 app core（**自研 RBAC**/公共）、system（工位/实例）、audit（审计）、reports（可选）。
- **A 侧前端页面**：数据集、训练、复审、方案模板、系统（复用 LS 组件库）+ 素材更换（公司 logo/名称/描述，去除 LS 吉祥物）。
- **workers**：Celery 训练/导入/模型下发任务。
- **A 侧预标推理**：`pipeline-core` + ONNX Runtime，跑在 worker-gpu。

### 2.3 平台 B 的复用与不造轮子

| 能力 | 做法 |
|---|---|
| 切片/合并/三档判定/方案解析 | **直接复用 `pipeline-core`**，与 A 的预标判定同源 |
| 任务类型/缺陷 code/model_ref 校验 | **直接复用 `skillname`** |
| Web 框架 | FastAPI 自动 OpenAPI，前端按契约对接，不手写 SDK |
| 图表/表格/表单 | Ant Design 5 + ECharts，不自定义组件库 |
| 定时任务 | APScheduler 进程内，不引入 Celery/Redis |
| 日报 | Jinja2 HTML + CSV，不引入 WeasyPrint（PDF 二期） |
| 迁移 | 顺序 SQL 迁移 + `schema_version` 表，不引入 Alembic（可切） |

---

## 3. MVP 范围裁剪

| 变更点 | MVP 决策 |
|---|---|
| 平台拆分 | A 训练/标注/预标/复审；B 推理/相机/统计/日报/回传；跨机器 HTTP，不共享数据库/对象存储 |
| B 的 RBAC / 用户认证 | **都不做**；无用户体系、无登录、无用户认证；仅 `/api/v1/ingest/*` 用机器密钥（非用户认证） |
| B 的基础设施 | **不做** Redis/Celery/MinIO/Nginx（可选）/K8s；SQLite + 本地磁盘 + 单进程 |
| GPU 调度（分时互斥） | 不做。A 训练与 B 推理本就在不同机器，天然互斥 |
| 预标注（ML backend） | 保留但后置 D15；通道本身是 LS 原生，D2 就验连通；A 侧自实现协议 |
| A 侧报告 | 最后（D20~22），仅单页统计；来不及就砍 |
| B 侧日报 | **核心能力，不砍**；D15 起做，D18 前可用 |
| LLM 参数复审 / VLM 复审 | 接口 + stub，线上人工接管 |
| 高价值数据桶 | 建桶 + 目录规范预留，落桶二期 |
| 去重/质检 | MD5 去重 + 格式/坏图质检；pHash/模糊检测二期 |
| 训练框架 | 仅 YOLO；HF/sklearn 二期 |
| 相机 | 1 路真实（D17）+ 8 路仿真；硬触发/`camera.captured` 流二期 |
| 视频流/大屏 | 不进 MVP；B 只做 1~2fps 快照与结果展示 |
| 两级审核 | 复用 LS Review 流；平台不再自建审核 UI |
| B 多实例 | 表结构预留 `target_code`；MVP 单实例 |
| B 自动升级 | 不做；离线包人工升级 |

---

## 4. 公共接口协调

> 详细定义在 `docs/contracts/`：**跨平台契约 A-B**（模型/方案下发、错图回传、心跳）、**平台 A 契约**、**平台 B 契约**。

**协调机制**：D2 冻结契约；**D2 下午复用验证日**（LS 能力逐项实测，实测为准回写契约）；先 stub 后实现；契约测试消费方写、维护方 CI 跑；D9/D15 变更窗口，破坏性变更四件套。

**跨平台关键接口 TOP8（按联调时间排）**：

| # | 接口 | 方向 | 时间 |
|---|---|---|---|
| 1 | `POST {B}/api/v1/ingest/model` + 分片 blob 上传 | A→B | D3 stub / D7 真实 |
| 2 | `POST {B}/api/v1/ingest/plan`（校验 + 热加载） | A→B | D3 stub / D7 真实 |
| 3 | `POST {A}/api/ingest/findings`（错图回传） | B→A | D3 stub / D6 真实 ★ |
| 4 | `POST {B}/api/v1/inspect/image`（相机/模拟器） | 外部→B | D5 |
| 5 | `packages/pipeline-core` 签名与语义冻结 | 共享 | D2 |
| 6 | `packages/skillname` 枚举与规范冻结 | 共享 | D2 |
| 7 | `POST {A}/api/ingest/heartbeat`（心跳/版本） | B→A | D3 |
| 8 | `POST /api/prelabel/{task_id}/{health,setup,predict,validate}`（LS 官方协议） | LS→A | D15 ★ |

**A 侧业务接口（B 平台内部）**：`/api/datasets/*`、`/api/train/*`、`/api/review/*`、`/api/inspect/plans/*`、`/api/system/*`，见平台 A 契约。

---

## 5. 22 天排期（细化到天）

### P0 契约与地基（D1–D3）——目标：双平台空跑 + 跨机链路 stub 打通 + LS 复用结论

| 天 | A | B | C |
|---|---|---|---|
| D1 | monorepo 目录与 uv workspace + `packages/` 骨架；CI 骨架；双平台部署骨架（端口/网络/环境变量） | 契约评审会（全员）；LS fork 骨架确认（上游只读、`label_studio/aoi/` app 骨架、Menubar 占位）；**aoi_training 四表迁移 + skillname 枚举裁定落地**；`/api/ingest/*` stub | 平台 B 骨架（FastAPI + SQLite + APScheduler + 前端壳 5 页路由）；**`skillname` + `pipeline-core` 真逻辑**（切片/合并/三档判定/load_plan）；B 全量端点 stub |
| D2 | 双平台 compose/systemd + 跨机网络连通性验证；离线依赖清单；B 前端脚手架（Vite + AntD + ECharts） | 上午：共享表迁移收尾 + label config 生成 stub + aoi API 全量 stub（含 `/api/train/*`）；**下午：复用验证日（LS 8 项实测）**；预标 ML backend fixture | B 端点 stub 收尾 + fixture；模型接收/方案接收 stub；契约测试跑绿；前端 mock 数据 |
| D3 | 契约测试挂 CI；B 前端登录壳/布局/路由 | JWT 登录链确认 + **`/api/ingest/findings` 打桩应答** + `model_dispatch` 表；模型下发服务 stub | B 的 `X-Platform-Token` 校验 + 分片上传 stub + 回传 outbox 骨架；与 A 打桩联调 |
| **验收** | **10 项**：① LS 登录/令牌 ② label config 注入 ③ 上传+缩略图 ④ 框标注+Review 流 ⑤ YOLO 导出 smoke ⑥ A 的 `/health` 与 OpenAPI ⑦ B 的 `/health` 与 OpenAPI ⑧ **A→B 模型/方案下发 stub 全绿（分片+sha256+幂等）** ⑨ **B→A 错图回传 stub 全绿（幂等+重复请求返回 duplicated）** ⑩ `pipeline-core`/`skillname` 双端契约测试绿 | | |

### P1 相机链路先行（D4–D8）→ M1(D8)

| 天 | A | B | C |
|---|---|---|---|
| D4 | 数据整理工具；B 前端「概览」页骨架 | **自研 RBAC 三角色**（角色/权限点/授权表 + DRF 权限类；LS 角色框架不可用）；LS 项目模板配置；**前端素材更换起步** | `pipeline-core` 切片/NMS 真逻辑；ONNX Runtime 适配器；B 检测记录落库 |
| D5 | 假数据生成（OK + 缺陷图）；B 前端「检测记录」页 | 缺陷字典 + label config 生成 + 导入包裹（复用 LS 上传）；**前端素材更换完成** | `/api/v1/inspect/image` 完整链路；单图推理 + 三档判定；B 记录查询接口 |
| D6 | 节拍模拟器（打 B 的 `/api/v1/inspect/image`） | 标注项目创建 + Review 流配置验证；**`/api/ingest/findings` 完整实现（图片落 MinIO + fact + workitem/bad_image）** | 相机适配器壳（DirectorySource）+ 坏图登记 + outbox 回传真实打通 |
| D7 | 双机联调 + 离线包初版；B 前端「工位与相机」页 | **模型下发 + 方案下发真实推送**（分片/续传/重试/`model_dispatch` 状态） | B 模型接收校验落盘 + 方案接收/校验/热加载；B 前端联调 |
| D8 | **M1 联调** + B 前端「系统」页 | **M1 联调**（复审工作项可见） | **M1 联调**（端到端稳定） |
| **M1** | 假图按节拍 → B 推理 → 三档判定 → 错图回传 → A 建复审工作项；B 概览页可见统计；界面为公司 logo/平台描述、无 LS 吉祥物 | | |

### P2 训练与闭环（D9–D14）→ M2(D14)

| 天 | A | B | C |
|---|---|---|---|
| D9 | 缺陷样本补充；B 前端「日报」页骨架 | 数据集版本/划分/测试集红线；方案版本/激活/回滚完善 | B 方案回滚 + 加载自检增强 + `pipeline-core.load_plan` 边界用例 |
| D10 | 万级导入压测；B 前端图表联调 | LS data_export 包裹（YOLO 导出 + 红线校验） | B 多模型按对象分发 + 模型/方案管理接口 |
| D11 | 交付包完善（权重/字体/初始方案模板/双平台镜像） | YOLO adapter + 训练执行流 + 训练进度 SSE | B 加载自检（张量匹配 + 空跑）+ 模型预加载/卸载 |
| D12 | 自检脚本；B 前端「模型与方案」区 | 门禁 + **金标准回归** + ONNX 导出 + 模型 lifecycle + 审批流 | B 磁盘保留策略 + 清理任务 + 磁盘水位告警 |
| D13 | 备份脚本 | 复审/建议清单/回流后端完整 | B 检测记录/错图统计接口完善 |
| D14 | **M2 联调** | **M2 联调** | **M2 联调** |
| **M2** | 标注 → 训练 → 注册 → 审批 → **下发 B** → 方案激活 → B 推理 → 回传 → A 复审 → 回流 全闭环（小数据集） | | |

### P3 预标 + 相机 + 生产化（D15–D19）→ M3(D19)

| 天 | A | B | C |
|---|---|---|---|
| D15 | 真实数据导入演练；B 前端「日报」详情/导出 | 预标任务 + **A 侧 ML backend 协议端点**（复用 `pipeline-core`） | B 日报生成（APScheduler + Jinja2 HTML + CSV）+ 统计聚合 |
| D16 | 双机离线导入演练 | 预标三桶路由（联调 C 的预标推理） | 8 通道仿真并发 + 背压 + 时延验证 |
| D17 | 7×24 冒烟 | 审计完善 + 验收脚本 | 真实 GigE 相机 1 路 + 触发采集 |
| D18 | 压测（8 路仿真） | 操作文档（双平台） | 日报/统计验收 + FP16 回归 + 保留策略演练 |
| D19 | **M3 联调** | **M3 联调** | **M3 联调** |
| **M3** | 预标闭环 + 真机 1 路 ≤3s + 8 路仿真不丢 + 双机离线包新机导入全绿 + 日报可出 | | |

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
| 跨机器网络不稳定/带宽受限 | 模型分片上传 + 断点续传 + sha256；回传只发可疑/坏图，auto_pass 不回传；outbox 退避重试；D3 就做网络连通性验证 |
| 两平台契约漂移（尤其 `skillname`/`pipeline-core`） | 公共包语义化版本 + 双端契约测试挂 CI；D2 冻结、D9/D15 窗口；版本不匹配由心跳告警 |
| B 侧被做重（引入 Redis/Celery/MinIO） | §3.5 轻量化硬约束进评审红线；B 的依赖清单由 C 维护、A 在交付包中校验 |
| B 无用户认证带来的安全风险 | 内网/产线网段隔离（唯一安全边界）+ 不暴露 DB 与文件目录；跨机走 HTTPS/VPN；仅模型/方案下发保留机器密钥 |
| A 的模型下发阻塞 B 上线 | B 侧支持「本地已有模型 + 方案」离线运行；下发失败不影响 B 继续用旧版本 |
| 可疑图回传积压导致 B 磁盘涨 | 保留策略 + 未回传图片不清理 + 磁盘水位告警 + 人工导出兜底 |
| B 仍是单人（C 同时做后端+推理+相机） | 公共包先行、B 端点 stub 先行、前端由 A 承担；B 的功能面按 §3 严格裁剪 |
| 自研 RBAC 工作量与越权风险 | 权限点集中注册 + DRF 权限类统一入口；三角色矩阵与 40300 进契约测试；D4~5 完成 RBAC，D6 起页面按权限显隐 |
| LS 复用点实测与预期不符（Review/导出等） | **D2 复用验证日**逐项实测；不符项当天定降级方案回写契约 |
| 66 人日压缩率高，M2 闭环超时 | 复用红利转联调缓冲；回流环节允许「人工导图 + 改 source」降级；A 侧报告可砍 |
| 预标后置导致 D15 联调紧张 | ML backend fixture 在 D2 就由 B 出具（LS 实测样例）；C 提前按 fixture 开发 |
| 真实相机型号/驱动未定 | C 用 DirectorySource + HTTP 双通道开发；相机延期不影响 M1/M2 |
| 跨机时钟漂移影响日报 | NTP 强制；双时间戳（`captured_at`/`received_at`）；偏差 > 2s 告警 |
| 假数据与真实分布偏差 | A 按真实分辨率/光照/缺陷形态生成；A 侧金标准回归兜底 |

---

*随开发维护：D2/D9/D15 评审；契约变更同步 `docs/contracts/` 与 `docs/P0骨架设计_双平台.md`。*
