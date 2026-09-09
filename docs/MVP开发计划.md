# AOI 检测平台 MVP 开发计划（3 人 × 22 天）

> 平台形态：LS 1.x 二开主应用；**Label Studio 深度复用**——账户/标注/上传/审核/预标通道/导出六块几乎零开发（复用清单见 §2），二开只做「字典/数据集版本/训练/复审/方案模板」五个新域 + 薄包裹。
> 配套：`docs/P0骨架设计_LS二开仓库与sidecar.md`（D1~D3 落实依据）、`docs/contracts/公共接口与数据契约.md`（D2 冻结）、`AOI检测平台技术手册.html`（总体设计）。

---

## 0. 结论速览

| 项 | 结论 |
|---|---|
| 平台形态 | LS 1.x 二开主应用：单入口、Django+DRF 主数据源；sidecar 只做计算 |
| 复用策略 | **能用 LS 原生的绝不自己写**（§2 清单）；二开 = 5 个新域 + 薄包裹 |
| 工时 | 3×22=66 人日；核心五主线全保留；LLM/VLM 接口预留+人工接管；报告最后 |
| 里程碑 | M1(D8) 假图→推理→人工复审重标签；M2(D14) 标注→训练→注册→方案模板→推理→复审→回流；M3(D19) 预标+真机 1 路+8 路仿真+离线包；M4(D22) 验收 |
| 契约 | `docs/contracts/公共接口与数据契约.md`，D2 冻结，D2 下午复用验证日（LS 能力实测），D9/D15 变更窗口 |

---

## 1. 分工与边界

### A（数据与交付）
数据整理工具、假数据生成（OK 图+缺陷图）、节拍模拟器（HTTP 打 sidecar）、MinIO 桶初始化、CI、compose/Dockerfile/离线交付包、发版、部署/操作手册。

### B（平台与数据智能）——复用优先
1. **D1~3：训练域数据基座前置**——`aoi_training` 四表迁移（训练任务表 `train_job`、基础模型注册 `base_model`、训练后模型注册 `model`、预置方案 `preset`）+ task_type/skill 枚举（skillname）裁定落地 + `/api/train/base-models|models|jobs` 注册/列表 stub（`model` 表含 task_type/cover_classes；`GET /api/train/models` 返回 C 消费字段 framework/task_type/cover_classes/lifecycle/weights_key）。**前置原因：C 推理链路（sidecar 模型注册表代理、方案模板绑 model_ref、ML backend 登记）依赖这些表与字段存在，D4 起即可对真实 schema 联调，避免 stub 漂移。**
2. D1~4：LS fork 仓库骨架（锁 tag、backend/label_studio 只读、aoi apps、Menubar 占位）+ 契约/stub 先行（aoi API 全量 stub+OpenAPI、共享表迁移、label config 生成）。
3. D4~7：**RBAC 三角色（映射 LS 角色）+ 图片标注（配置 LS 项目/Review 流，非开发）**+ 缺陷字典 + 导入包裹（复用 LS 上传）。
4. D9~12：训练链（数据集版本/划分/红线、LS data_export 包裹、训练执行流+门禁+ONNX 导出；表/注册 API 已前置 D1~3）。
5. D13~14：复审/回流后端（工作项/终裁/建议清单/坏图）。
6. D15~16：预标任务 + LS ML 设置页登记（对接 C；训练产物自动登记 MLBackend 流程仍在此，依赖 D1~3 已就绪的注册表）。
7. D20~22：报告（最后，仅单页统计）、审计、验收脚本、文档。

### C（推理与相机）——主线顺序
1. **相机链路推理**（D4~8）：pipeline-core + `/inspect/image` + 检测事实落库。
2. **错误图片回传**（D6~8）：坏图登记 `bad-images`，与复审工作项打通。
3. **人工复审重标签**（D8~14，与 B 联调）：检测/复审页，终裁→建议清单→回流。
4. **检测方案模板编写与适配**（D9~12）：编辑页、激活校验、热加载、多模型分发、金标准自检。
5. **预标注部分推理**（D15~16，后置）：ML backend 协议端点（LS 官方协议）。
6. 真实相机 1 路 + 8 通道仿真（D17~18）。
7. **前端素材更换**（D4~5，基于 B 的 fork 就绪）：平台 logo、名称与描述替换为公司内部版本，**去除 LS 吉祥物**与登录页署名；只做素材级替换，全量品牌重塑/汉化仍按手册归 B、进二期。

**sidecar 共担约定（骨架按端点域分工）**：
| sidecar 端点/组件 | 归属 |
|---|---|
| 路由聚合/鉴权中间件（LS JWT 验签，契约 §1.4） | **B、C 共担**（B 定鉴权契约，D1~3 一起起） |
| `/progress/{job_id}` SSE | **B 主笔**，C 提供服务壳 |
| ML backend 协议骨架（LS 官方协议） | **B 契约+fixture，C 实现推理侧** |
| `/inspect/*`、`/models/*`、`/plans/reload`、pipeline-core | C |
| 运行/部署/显存管理 | C |

### 1.1 技术栈选型与 Redis/Celery 公共中间件分工（MVP 明确）

#### 1.1.1 技术栈选型

| 层 | MVP 选型 | 说明 |
|---|---|---|
| 主前端 | LS 1.x web（React + TS） | 内嵌工作台，不建独立前端 |
| 主后端 | Django + DRF（LS 1.x） | 用户/项目/标注/二开 API 主数据源 |
| 数据库 | PostgreSQL 15 | 本地开发与交付统一使用，不用 SQLite |
| 对象存储 | MinIO | 数据集图片/上传文件/导出/权重/模板等对象资产 |
| 异步任务 | **Celery 5** | 明确不使用 RQ / django_rq；worker-gpu / worker-cpu / beat |
| Broker / 事件 / 缓存 | Redis 7 | Celery broker + Redis Streams + pub/sub |
| 推理计算 | FastAPI + Uvicorn | sidecar，承担推理/SSE/采集/ML backend |
| 推理引擎 | ONNX Runtime（CUDA EP） | FP32/FP16 |
| 训练框架 | YOLO（MVP 仅此） | Trainer adapter 预留 HF/sklearn |
| 报告渲染 | Jinja2 + WeasyPrint | Celery beat 触发轻量 DAG |
| 交付 | Docker Compose + 离线镜像包 | 单机离线交付 |

> 技术栈冲突以本表为准：**异步任务只用 Celery，不用 RQ**。

#### 1.1.2 Redis + Celery：跨模块公共中间件分工

Redis 和 Celery 是跨模块公共中间件，不是某一人的私有模块。MVP 阶段先定契约和分工，不提前落地具体中间件服务；相关实现按以下边界推进：

| 工作项 | 归属 | 内容 |
|---|---|---|
| 基础设施编排 | A | Redis、worker-gpu、worker-cpu、beat 的 compose/容器/健康检查/离线依赖；MinIO bucket 初始化 |
| 公共契约 | B | Celery app 骨架、队列命名、任务协议、事件定义（Redis Streams 幂等三元组）、消费幂等基类 |
| 业务任务接入 | B | datasets/training/report 等业务任务的 Celery task 定义与状态流转 |
| 计算侧消费/生产 | C | sidecar 侧 SSE、事件订阅/发布、训练进度对接、pipeline-core 计算任务 |
| 联调验收 | A/B/C | D2 冻结事件/任务契约；跨模块任务必须走 Celery/Redis 协议，不直连他人数据表 |

> 当前 MVP 前期不要求立即在代码中启用 Redis/Celery；先完成契约、分工和 stub，后续按 D 计划在需要的模块落地。

---

## 2. LS 原生复用清单与二开增量（MVP 核心）

### 2.1 复用（零开发或仅配置，D2 复用验证日实测确认）

| 平台功能 | LS 原生能力 | MVP 动作 |
|---|---|---|
| 登录/令牌 | token API（JWT HS256，含 user_id） | 零改动；sidecar 同 SECRET 验签 |
| 用户/组织/角色 | users + 角色框架 | aoi/core 三角色映射 |
| 标注项目/任务/框标注 | projects/tasks/annotations + RectangleLabels 编辑器 | 零改动；label config 由字典渲染 |
| 数据浏览 | Data Manager | 零重构 |
| 标注审核 | Review 流（标注→审核） | 配置启用；aoi 只读投影（不满足再降级） |
| 上传/存储/缩略图 | 本地存储 + 预签名 + 缩略图 | aoi 导入包裹（去重/质检/元数据） |
| 预标通道 | ml/ MLBackend + Batch predictions + predictions 回传 | 零二开；sidecar 实现官方协议 |
| 数据集导出 | data_export（YOLO/COCO） | aoi 版本绑定 + 红线 + 校验 |
| 前端框架 | web/apps 组件/路由/auth store | Menubar 入口 + 4 新页面 |

### 2.2 二开增量（真正要写的代码）

- **aoi 五个新域**：core（RBAC）、datasets（字典/版本/划分红线/导入包裹）、training（任务/门禁/注册）、review（工作项/终裁/建议/坏图）、plans（方案模板）。
- **sidecar + pipeline-core**（§1 C 的边界）。
- **workers**：Celery 训练/导入任务。
- **前端 4 页**：数据集、训练、检测/复审、系统（复用 LS 组件库）。
- **新前端页面在 LS 中的位置（MVP 落地口径）**：
  - 相机/推理前端放在 **Menubar「检测」** 下，不新增独立前端。
  - 检测工作台主路由：`/inspect`；新增“相机/工位”子页建议放在 `/inspect/cameras`，承载快照预览、软触发、推理状态和结果展示。
  - 工位/相机参数与启停管理放在 **Menubar「系统」** 下，建议路由 `/system/stations`。
- **前端素材更换**（C）：公司 logo/平台名称/描述替换、去除 LS 吉祥物与登录页署名。
- **预标任务表/三桶统计**（D15 启用）。

### 2.3 由此带来的排期红利

B 的「标注闭环」从开发任务变成**配置+验证任务**（D4~7 减负约 3~4 人日），转作：P2 训练链提前启动、M1/M2 联调缓冲、复审页降级预案储备。22 天总盘子不变，但 M2 达成的确定性显著提高。

---

## 3. MVP 范围裁剪

| 变更点 | MVP 决策 |
|---|---|
| LS 二开深度 | **深度复用、最小二开**：功能面全复用原生；**素材级品牌更换进 MVP**（logo/平台名称/描述替换、去除 LS 吉祥物，C 负责）；全量品牌重塑/汉化/剥离/组织管理隐藏进二期 |
| GPU 调度（分时互斥） | 不做。compose profiles（infer/train）人工互斥；自动调度二期 |
| Redis / Celery | 不用 RQ/django_rq；统一 **Celery 5 + Redis 7**。MVP 前期不落地具体中间件实现，先定公共契约、分工与 stub，相关模块需要时按 §1.1.2 分工接入 |
| 预标注（ML backend） | 保留但后置 D15（通道本身是 LS 原生，D2 就验连通） |
| 报告 | 最后（D20~22），仅单页统计；来不及就砍 |
| LLM 参数复审 / VLM 复审 | 接口+stub（契约 §14），线上人工接管 |
| 高价值数据桶 | 建桶+目录规范预留，落桶二期 |
| 去重/质检 | MD5 去重 + 格式/坏图质检；pHash/模糊检测二期 |
| 训练框架 | 仅 YOLO；HF/sklearn 二期 |
| 相机 | 1 路真实（D17）+ 8 路仿真；硬触发/camera.captured 流二期 |
| 相机/推理前端 | **不建独立前端**；在 LS“检测/系统”工作台内实现工位预览/触发/状态/结果页，采用 1~2fps 快照轮询；MJPEG/RTSP/WebRTC 与独立大屏不进入 MVP，仅作长期扩展预留 |
| 两级审核 | 复用 LS Review 流（标注→审核）；平台不再自建审核 UI |

> **MVP 说明**：相机推流/推理前端放在 LS 内实现，是 22 天 MVP 的落地方案，不代表长期架构回退。总体目标仍以《AOI 检测平台技术手册》为准：LS 单入口工作台 + sidecar 计算；未来如需视频级预览或独立车间大屏，可在不改变主架构的前提下扩展独立大屏/媒体服务。

---

## 4. 公共接口协调（工程级见接口契约文档）

> 详细定义（复用对照表、DDL、请求/响应示例、错误码、事件、MinIO、方案模板 Schema、ML backend 协议、金标准、LS smoke 清单）在 **`docs/contracts/公共接口与数据契约.md`**。

**协调机制**：D2 冻结契约；**D2 下午复用验证日**（LS 能力逐项实测，实测为准回写契约）；先 stub 后实现；契约测试消费方写、维护方 CI 跑；D9/D15 变更窗口，破坏性变更四件套。

**跨人关键接口 TOP8（按联调时间排）**：
1. `POST /api/datasets/import`（LS 上传包裹）+ 图像元数据（A ↔ B）——D4
2. `POST /sidecar/inspect/image`（A 模拟器 ↔ C）+ 工位表 ST01~ST08（B 先行建）——D6
3. `POST /api/review/facts` + `result_json`（C 写 ↔ B 读）——D6 ★
4. `POST /api/review/bad-images` 错误图片回传（C ↔ B）——D7 ★
5. 复审流 `/api/review/workitems`+finalize+suggestions（C 页面 ↔ B 后端）——D8 ★
6. 方案模板 `/api/inspect/plans/*` + `/sidecar/plans/reload` + YAML Schema（B ↔ C）——D9 ★
7. 模型注册表 `/api/train/models` + ONNX 产物/金标准（B 产 ↔ C 载）——schema/接口 D3 前置，ONNX 产物 D11
8. ML backend 协议（B 的 LS 原生 ml/ ↔ C，setup/predict）——D15 ★

**公共 Model/方法**：`pipeline-core`（C）：run/slice_image/box_to_global/merge_across_tiles/decide_verdict、DetectBox/DetectResult/PipelineConfig；`trainers/exporters`（B）：BaseTrainer/TrainSpec/TrainResult、export_onnx；`events/common`（B）：stream_xadd/ConsumerBase、Job 状态机；sidecar 共享壳（共担）；预留：LLMReviewer/ReviewReport、RecheckBackend/RecheckResult、fuse/suggest（B 定接口）。

---

## 5. 22 天排期（细化到天）

### P0 契约与地基（D1–D3）——目标：空跑链路 + LS 复用结论
| 天 | A | B | C |
|---|---|---|---|
| D1 | 仓库脚手架、CI 骨架 | 契约评审会（全员）；**LS fork 仓库骨架**（锁 tag、backend/label_studio 只读、aoi apps 迁移初版、Menubar 占位）；**aoi_training 四表迁移（train_job/base_model/model/preset）+ task_type/skill 枚举**（供 C 联调）；sidecar 共担：路由聚合+鉴权中间件+SSE 端点 | sidecar 共担：inspect 挂载+pipeline-core 骨架+模型加载壳 |
| D2 | 契约冻结；compose 骨架+nginx 路由+`.env.template` | 上午：共享表迁移+aoi_training 四表/task_type 枚举收尾+label config 生成 stub+aoi API stub（**含 /api/train/base-models、/api/train/models、/api/train/jobs**）；**下午：复用验证日（全员，LS 能力 8 项实测）**；ML backend 协议 fixture | 端点全量 stub+方案模板校验+fixtures（C 2 份）→ 契约测试绿 |
| D3 | 契约测试挂 CI | JWT 登录链确认（sidecar 同 SECRET）+ 内部头 + 打桩应答 facts/bad-images；**/api/train/models、/api/train/base-models 真实 schema 联调（C registry 代理对接）** | LS JWT 验签接入 + dev_token.py + 空跑验收 |
| **验收** | **8 项**：①LS 登录/令牌 ②label config 注入 ③上传+缩略图 ④框标注+Review 流 ⑤YOLO 导出 smoke ⑥sidecar 健康/stub/假 DetectResult ⑦401/内部头 ⑧MLBackend health 连通+契约测试绿 | | |

### P1 相机链路先行（D4–D8）→ M1(D8)
| 天 | A | B | C |
|---|---|---|---|
| D4 | 数据整理工具 | **RBAC 三角色（映射 LS 角色）**；LS 项目模板配置 | 切片器/合并（pipeline-core 真逻辑）；**前端素材更换起步（依赖 B 的 fork）** |
| D5 | 假数据生成（OK+缺陷图） | 缺陷字典+label config 生成+导入包裹（复用 LS 上传） | NMS+三档判定；单图 stub 推理；**前端素材更换完成（公司 logo/平台名称/描述替换、去除 LS 吉祥物与登录页署名）** |
| D6 | 节拍模拟器（打 `/inspect/image`） | 标注项目创建+Review 流配置验证 | `/inspect/image` 完整+落库 facts（联调 B） |
| D7 | 模拟器联调 C + 离线包初版 | 数据集创建（version 骨架） | 坏图回传 bad-images（联调 B）+检测页初版 |
| D8 | **M1 联调** | **M1 联调**（复审工作项创建） | **M1 联调**（复审页初版） |
| **M1** | 假图按节拍 → 推理 → 落库 → 人工复审/重标签跑通；界面为公司 logo/平台描述、无 LS 吉祥物 | | |

### P2 训练与闭环（D9–D14）→ M2(D14)
| 天 | A | B | C |
|---|---|---|---|
| D9 | 缺陷样本补充 | 数据集版本/划分/测试集红线 | 方案模板 Schema 校验+reload 热加载（联调 B） |
| D10 | 万级导入压测 | LS data_export 包裹（YOLO 导出+红线校验） | 模板编辑页 |
| D11 | 交付包完善（权重/字体/初始方案模板） | YOLO adapter + 训练执行流 + SSE（任务表/注册 API 已前置 P0） | 多模型按对象分发+模型加载（联调 B 注册表） |
| D12 | 自检脚本 | 门禁+ONNX 导出+模型 lifecycle 流转/回退（注册表已前置 P0） | 金标准自检+模板激活/回滚页 |
| D13 | 备份脚本 | 复审/建议清单/回流后端完整 | 复审页完善（确认/驳回/改标） |
| D14 | **M2 联调** | **M2 联调**（LLM stub 接入人工确认流） | **M2 联调** |
| **M2** | 标注→训练→注册→方案模板→推理→复审→回流 全闭环（小数据集） | | |

### P3 预标+相机+生产化（D15–D19）→ M3(D19)
| 天 | A | B | C |
|---|---|---|---|
| D15 | 真实数据导入演练 | 预标任务+LS ML 设置页登记 | ML backend 协议端点（setup/predict，联调 B） |
| D16 | 新机离线导入自检演练 | 预标三桶路由（联调 C） | 预标回写（LS predictions，联调 B） |
| D17 | 7×24 冒烟 | 审计完善+验收脚本 | 真实 GigE 相机 1 路+触发采集 |
| D18 | 压测（8 路仿真） | 操作文档 | 8 通道仿真并发+背压+时延验证 |
| D19 | **M3 联调** | **M3 联调** | **M3 联调** |
| **M3** | 预标闭环 + 真机 1 路 ≤3s + 8 路仿真不丢 + 离线包新机导入全绿 | | |

### P4 收尾（D20–D22）→ M4(D22)
| 天 | A | B | C |
|---|---|---|---|
| D20 | 交付包终版 | 报告统计页（最后做；来不及则砍） | FP16 回归+性能优化 |
| D21 | 交叉验收+缺陷修复（全员） | 同左 | 同左 |
| D22 | 发版 tag + 交付包 + 部署/操作手册 | 验收记录 | 验收记录 |
| **M4** | MVP 验收通过（五主线+性能+离线） | | |

---

## 6. 风险与应对

| 风险 | 应对 |
|---|---|
| B 仍是单点（契约+训练+复审） | LS 复用使 B 减负（§2.3）；P0 只做契约与 stub；复审页可降级为「检测页内人工确认」 |
| LS 复用点实测与预期不符（Review/导出等） | **D2 复用验证日**逐项实测；不符项当天定降级方案回写契约（如 Review 降级为平台轻量审核接口、data_export 降级为自研 zip） |
| 66 人日压缩率高，M2 闭环超时 | 复用红利转联调缓冲（§2.3）；回流环节允许「人工导图+改 source」降级 |
| 预标后置导致 D15 联调紧张 | ML backend fixture 在 D2 复用验证日就由 B 出具（LS 实测样例）；C 提前按 fixture 开发 |
| 真实相机型号/驱动未定 | C 用 DirectorySource+HTTP 双通道开发；相机延期不影响 M1/M2 |
| 训练/推理人工互斥忘切换 OOM | compose profiles + 启动脚本显式拦截 |
| 契约漂移 | 契约测试 CI 强制；D2 冻结+D9/D15 窗口；破坏性变更四件套 |
| 假数据与真实分布偏差 | A 按真实分辨率/光照/缺陷形态生成；金标准回归兜底 |

---

*随开发维护：D2/D9/D15 评审；契约变更同步 `docs/contracts/公共接口与数据契约.md` 与骨架设计。*
