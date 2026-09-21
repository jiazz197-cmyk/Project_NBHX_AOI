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
| `<object>_<fault_type>_NN` | 缺陷对象 code：前缀是两段**可变英文词**（如 `panel_scratch`、`glass_dent`），后缀 `NN` 固定两位数字 01~99（`00` 非法），由缺陷字典配置。正则 `^[a-z][a-z0-9_]{0,27}_(0[1-9]|[1-9][0-9])$`（ASCII，前缀≤28 ⇒ 总长≤31 对齐 `VARCHAR(32)`）。历史写法 `object_fault_type_XX` 是其一个合法实例（超集放宽，D5 收尾第二轮）。**code 后缀是 code 自身编号，不是类别索引**——类别索引由字典顺序/显式 `index` 决定 |
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
| `/` | web（LS 前端静态 + 二开页面） | SPA 页面路由：LS 原生页面由各上游 app 自己注册（如 `/projects/` → 壳模板）；aoi 页面（`/datasets`、`/training`、`/review`、`/system`、`/organization-admin`）由 `aoi/urls.py` **点名路由**渲染壳模板（D5，非泛 catch-all——`aoi.urls` 无前缀 include 在 `core/urls.py` 中先于 30+ 条上游路由，泛 `^.*$` 会全部吞掉） |
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
- **全局 DRF 权限类红线（D4 改口）**：原口径为「不改全局 `REST_FRAMEWORK`（权限类是上游语义）」，D4 起修正为——**仅允许在 `REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES` 首位插入 aoi 闸门类 `aoi.common.native_gate.AoiNativeGatePermission`，其余项一律不得修改**（`DEFAULT_AUTHENTICATION_CLASSES`/`EXCEPTION_HANDLER` 等保持上游语义）。闸门为 deny-list、默认放行、fail-open，拦截表与错误语义见 §3.1.1。
- **B → A（错图回传）**：`X-Internal-Token: <INTERNAL_TOKEN>`；`instance_code` / `station_code` 由 B 在回传体中给出，供审计与溯源。
- **LS → A 预标端点（D2 实测）**：LS 调用 `aoi/prelabel/{task_id}/*` 时**不携带 `X-Internal-Token`/Authorization**，仅带 `User-Agent: heartex/...`；因此默认放行，请求若带内部头则必须正确。置 `AOI_PRELABEL_REQUIRE_INTERNAL_TOKEN=true` 可强制 40100（需配合网关注入头或 LS Basic Auth）；生产建议该端点仅在内网暴露。
- **A → 镜像仓库（模型发布）**：`MODEL_REGISTRY_USER` / `MODEL_REGISTRY_PASSWORD`，见跨平台契约 §1.2。**A 不直接连接 B**。
- 权限点（模块级）：`datasets.*`、`training.*`、`review.*`、`system.*`；动作 `view/create/update/cancel/approve/publish`，共 **38 码**（§3.1）；三角色 `operator`（操作员）/ `admin`（管理员）/ `super_admin`（超级管理员）——**仅用于平台 A**；默认权限矩阵见 §3.1。LS 原生端点由 `aoi.common.native_gate` 闸门按 §3.1.1 拦截，被拦时返回 LS 方言错误体。

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
CREATE SCHEMA IF NOT EXISTS aoi_core;        -- 随 aoi_core/0001 迁移创建（沿用其余 aoi app 模式）

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

CREATE TABLE aoi_core.authz_state (          -- 授权版本号（单行），跨进程失效依据
  id INT PRIMARY KEY,                        -- 固定 1
  version BIGINT NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ DEFAULT now()
);
```

**权限点注册（D4）**
- 码表由 `aoi/core/permissions.py` 常量定义：`MODULES(4) × ACTIONS(6) = 24` + `EXTRA_PERMISSIONS(14)` = **38 码**。`ACTIONS` 不扩（否则生成 `training.delete`/`review.config` 等 13 个永无视图使用的空码），新增码一律进 `EXTRA_PERMISSIONS`。
- 播种触发点＝**`post_migrate` signal**（`aoi/core/apps.py` 只注册 receiver，不在 `ready()` 里写库——`ready()` 会在 `check`/`shell`/`collectstatic` 时触发，只读库环境直接失败），幂等命令 `aoi_seed_rbac` 兜底。语义：
  1. `permission` 按码表**全量 upsert**，不删多余行；
  2. 三角色按 `code` upsert；**角色已存在则不动其 `role_permission`**（人工调整不被重启回滚）；
  3. 角色**首次创建**时按默认矩阵写 `role_permission`；
  4. `super_admin` **每次播种补授缺失码（只加不减）**——显式撤销它的某个码会在下次播种被补回，这是有意的：它天然是全权限角色。
- 超管引导（D5 更新）：`post_migrate`/`aoi_seed_rbac` 幂等播种**固定超管** `superadmin@nbhx.com`——不存在则按 LS 注册链路接线创建（`username` 取邮箱前缀、挂 `OrganizationMember`、设 `active_organization`，无组织则创建），并补授 `super_admin`（只加不减）；已存在**不重置密码**（改密走 LS 原生账户页）。`aoi_grant_role <email> <role_code>` 仍可用于授予其他用户（全量覆盖，带 `--list`，写审计）。
- **最后超管守卫（D5）**：`POST /api/core/users/{id}/roles` 与 `POST /api/core/users/{id}/deactivate` 若导致**活跃超管**（`is_active=True` 且持 `super_admin`）数量归零 → `40900`（防止永久锁死授权入口）。
- **停用语义（D5）**：「删除用户」一律为**停用组合拳**：`is_active=False`（已签发 JWT 立即失效）+ 清空 aoi 角色 + 全部 `OrganizationMember` 置 `deleted_at`（`active_organization` 镜像上游成员软删行为）；硬删（`htx_user` 35 个 FK 全 `NO ACTION`，ORM 级联会连带删项目/标注）不在平台语义内。

**判定与缓存（D4）**
- 判定入口（P1 errata）：DRF 权限类由 `aoi.common.permissions.aoi_permission('training.publish')` 生成（返回**类**，可放进 `permission_classes`；不要放实例——DRF 会无参实例化每一项）；每个 aoi 视图通过 `aoi_perm` / `aoi_perm_by_method` 声明权限点。
- 判定链 `user_role → role_permission → permission.code`；结果按 `(user_id, version)` 缓存 **5 分钟**。
- **失效口径**：`authz_state.version` 与角色/授权变更在**同一事务**内 +1；判定侧**每请求读一次版本号**（单行 PK 查询）。`CACHES` 未配置（Django 默认 `LocMemCache`，多 worker 进程间不共享），因此「删 key 式失效」不可用，版本号是唯一可靠手段，且**零延迟生效**。
- `has_object_permission` 与 `has_permission` **同判定**；对象级规则（复审认领归属等）留在视图层业务校验。
- 无角色用户 `perms = []`；除 `GET /api/core/permissions`（豁免，仅需登录）外一律 `40300`。`user_role` 不建外键，**读时校验 LS 用户存在**，不存在视为无角色（不挂 signal 清理）。
- 视图声明了不在码表内的权限点 → 抛 `AssertionError`（配置期错误，不静默放行）。
- **三角色定义**：`operator`（操作员）负责日常标注与复审；`admin`（管理员）负责数据集/训练/模型发布/复审等业务全量操作；`super_admin`（超级管理员）在管理员之上增加角色与用户授权、审计。**三角色只在平台 A 使用**，平台 B 无 RBAC、无用户认证。
- **默认权限矩阵（38 码全表；`✅` 允许，`—` 拒绝）**。`DEFAULT_ROLE_MATRIX` 的码集必须与 `PERMISSION_CODES` 完全一致（契约测试断言，遗漏即红）：

| 权限点 | `operator`（操作员） | `admin`（管理员） | `super_admin` | 占用方 |
|---|---|---|---|---|
| `datasets.view` | ✅ | ✅ | ✅ | aoi 视图 |
| `datasets.create` | ✅ | ✅ | ✅ | aoi 视图 + 闸门 |
| `datasets.update` | ✅ | ✅ | ✅ | aoi 视图 |
| `datasets.publish`（发布缺陷字典 → 渲染 label config + 快照） | — | ✅ | ✅ | aoi 视图 |
| `datasets.export` | — | ✅ | ✅ | aoi 视图 + 闸门 |
| `datasets.delete` | — | ✅ | ✅ | 闸门（项目删除） |
| `datasets.config`（LS 项目配置/label config 改写） | — | ✅ | ✅ | 闸门 |
| `datasets.cancel` / `datasets.approve` | — | — | ✅ | 保留码 |
| `prelabel.view` / `prelabel.create` / `prelabel.update` | — | ✅ | ✅ | aoi 视图 |
| `training.view` | ✅ | ✅ | ✅ | aoi 视图 |
| `training.create` / `training.cancel` / `training.approve` / `training.publish` | — | ✅ | ✅ | aoi 视图 |
| `training.update` | — | — | ✅ | 保留码 |
| `review.view` | ✅ | ✅ | ✅ | aoi 视图 |
| `review.update`（工作项认领/处理） | ✅ | ✅ | ✅ | aoi 视图 |
| `review.finalize`（终裁） | ✅ | ✅ | ✅ | aoi 视图 |
| `review.create` / `review.cancel` / `review.approve` / `review.publish` | — | — | ✅ | 保留码 |
| `system.roles` / `system.users` | — | — | ✅ | aoi 视图 + 闸门 |
| `system.audit` | — | — | ✅ | aoi 视图 |
| `system.storage` / `system.ml` / `system.webhook` / `system.labels` | — | — | ✅ | 闸门 |
| `system.view` / `system.create` / `system.update` / `system.cancel` / `system.approve` / `system.publish` | — | — | ✅ | 保留码 |

> 统计：视图使用 19 码 + 闸门专用 6 码 + 保留码 13 码 = 38。**保留码**仅入库、不授给 `operator`/`admin`，供二期直接启用，避免新增码时再改播种逻辑。

- **语义澄清**：`datasets.update` 指「aoi 数据集/导入/标注操作」，**不含** LS 项目配置与 label config 改写（后者归 `datasets.config`）；`review.update` 指工作项认领/处理，`review.finalize` 指终裁。

- **接口**：`GET /api/core/permissions` 返回当前用户 `{user_id, roles:[...], perms:[...]}`（形状不变，供前端按钮/菜单显隐）；`super_admin` 可 `CRUD /api/core/roles`、`GET /api/core/users`、`POST /api/core/users/{id}/roles|deactivate|activate`。端点语义详见 §4.0。
- **不共享**：RBAC 属 A 侧业务权限，**不进 `packages/`**；平台 B 无用户体系。
- **审计**：角色/授权变更写 `aoi_audit.audit_log`（`role.create`/`role.update`/`role.delete`/`user.roles.assign`/`user.deactivate`/`user.activate`）。

#### 3.1.1 LS 原生闸门（D4）

> **背景**：LS 原生 `has_permission` 在 LSO 下等价于「未被移出组织」（`projects/mixins.py`，单组织部署），任何已登录用户都能改项目配置、导出数据、改存储/ML/Webhook 配置。RBAC 只覆盖 aoi 视图，因此需要一道闸门堵住原生绕过路径。

- **实现**：`aoi.common.native_gate.AoiNativeGatePermission` 注入 `REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES` **首位**（见 §2.4 红线口径）。之所以不用 Django 中间件：D3 已移除 JWT 中间件，`MIDDLEWARE` 中 `request.user` 只有 session 身份，Bearer/`X-Api-Key` 调用者不可见；DRF 层认证已完成，三种身份都正确。
- **语义**：**deny-list，默认放行**——不在拦截表内的一律放行；`SAFE_METHODS`（GET/HEAD/OPTIONS）默认放行，**除**导出产物读取。用 allow-list 会让标注主流程直接不可用。
- **拦截表**（4 类高危 + 1 条权限锚点）：

| 类别 | 方法 + 路径 | 权限点 |
|---|---|---|
| ① 项目删除/配置改写 | `DELETE /api/projects/{pk}/` | `datasets.delete` |
| | `PATCH` / `PUT /api/projects/{pk}/` | `datasets.config` |
| | `POST /api/projects/{pk}/summary/reset/` | `datasets.config` |
| ② 导出 | `POST /api/projects/{pk}/export`、`POST /api/projects/{pk}/exports/`、`DELETE /api/projects/{pk}/exports/{id}`、`POST /api/projects/{pk}/exports/{id}/convert` | `datasets.export` |
| | `GET /api/projects/{pk}/export/files`、`GET /api/auth/export/` | `datasets.export` |
| ③ 基础设施配置 | 写方法 `/api/storages/**` | `system.storage` |
| | 写方法 `/api/ml/**` | `system.ml` |
| | 写方法 `/api/webhooks/**` | `system.webhook` |
| | 写方法 `/api/labels/**` | `system.labels` |
| ④ 组织与用户 | 写方法 `/api/organizations/**`、`/api/invite`、`/api/invite/reset-token`、`/api/users/**` | `system.users` |
| ⑤ 权限锚点（非高危） | `POST /api/projects/` | `datasets.create`（operator 放行） |

- **前缀陷阱**：`/api/auth/login`、`/api/auth/logout` 是 **aoi 端点**必须放行，而 `/api/auth/export/` 是上游导出链路**必须拦截** —— 不得用 `/api/auth/**` 通配放行（契约测试有专项断言）。
- **豁免**（显式声明，回归断言对象）：`/api/token/**`、`/api/auth/login|logout`、`/api/current-user/**`、`/api/tasks/**`、`/api/annotations/**`、`/api/drafts/**`、`/api/predictions/**`、`/api/dm/**`、`/api/projects/{pk}/next/`、`/api/projects/{pk}/tasks/`、`/api/prelabel/**`、`/api/ingest/**`、`/heidi-tips/`、`/admin/**`、`/django-rq/**`、`/health`、`/user/login/`、`/user/signup/`，以及所有 `GET /api/projects/**`（`export/files` 除外）。
- **错误语义**：命中拦截且缺码 → DRF `PermissionDenied` → 上游 `core.utils.common.custom_exception_handler` 返回 **LS 方言 `{"detail": ...}`**，**不是** aoi 信封（§2.3）。前端需能处理两种错误体；契约测试分两组断言。
- **fail-open**：闸门自身异常一律放行并 `logger.warning`——闸门是加固手段，不得因自身缺陷锁死平台。
- **不做**：LS 原生全量写端点矩阵（只做上述 4 类）；A→B 无实例管理/心跳，与本闸门无关。

### 3.2 `aoi_datasets`

```sql
CREATE TABLE aoi_datasets.image (
  id SERIAL PRIMARY KEY,
  object_key VARCHAR(128) UNIQUE NOT NULL,   -- 两态：B 回传=images/{md5}.jpg；A 导入=LS 上传路径 upload/{project}/{uuid8}-{filename}
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
  code VARCHAR(32) UNIQUE NOT NULL,          -- <object>_<fault_type>_NN（前缀≤28，总长≤31）
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

CREATE TABLE aoi_datasets.import_job (       -- D5：导入包裹任务（Celery 异步，契约 §4.1/§5.2）
  id SERIAL PRIMARY KEY,
  job_id VARCHAR(16) UNIQUE NOT NULL,        -- uuid12，对外标识（URL 中的 {job_id}）
  status VARCHAR(16) DEFAULT 'queued',       -- queued/running/succeeded/failed
  total INT DEFAULT 0, ok INT DEFAULT 0, dup INT DEFAULT 0, bad INT DEFAULT 0,
  bad_items JSONB DEFAULT '[]',              -- [{filename, reason}]；reason ∈ unsupported_extension/too_large/decode_failed
  file_upload_ids JSONB DEFAULT '[]',        -- 复用 LS 上传生成的 FileUpload 主键（任务侧消费）
  source VARCHAR(24), station_code VARCHAR(32), dataset_id INT,
  created_by INT, created_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
  error_message TEXT
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
  deleted_at TIMESTAMPTZ,                    -- 软删标记（仅 A 侧记录；**仓库镜像保留**，B 仍可拉取）
  deleted_by INT,                            -- 删除人（仅管理员/超管，见 §4.2）
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
| `GET /api/core/permissions` | 登录用户（豁免权限点） | `{user_id, roles:[code...], perms:[code...]}`，供 A 前端控制按钮/菜单显隐（B 不调用，B 无 RBAC）。无角色 → `perms=[]`；匿名 → `40100` |
| `GET /api/core/roles` | system.roles（super_admin） | 分页角色列表，每项含 `permissions:[code...]` |
| `POST /api/core/roles` | system.roles | `{code ≤32, name_cn ≤64, description?, permissions?}`；code 冲突 → `40900`；字段非法 → `42200`；写审计 `role.create` + 版本号 +1 |
| `GET /api/core/roles/{id}` | system.roles | 角色详情（含 `permissions`）；不存在 → `40401` |
| `PUT /api/core/roles/{id}` | system.roles | 改 `name_cn`/`description`；带 `permissions:[code]` 时**全量覆盖** `role_permission`；内置角色**禁改 `code`、禁删**；审计 `role.update`（记 perms 差集）+ 版本号 +1 |
| `DELETE /api/core/roles/{id}` | system.roles | 内置角色 → `40900`；删除后 `user_role` 级联清理 + 审计 `role.delete` + 版本号 +1 |
| `POST /api/core/users/{id}/roles` | system.users | `{roles:[code...]}` **全量覆盖**（传 `[]` 即清空）；未知 role code → `42200`；用户不存在 → `40401`；审计 `user.roles.assign` + 版本号 +1。`roles` 支持字符串或数组 |

### 4.1 数据域 `/api/datasets`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `POST /import` | datasets.create | **包裹 LS 上传（D5 真实化，Celery 异步）**：multipart `files[]` + form `dataset_id`（必填）/`source`（可选，默认 `manual_real`，其它值 → `42200`）/`station_code`（可选 ≤32）→ `{job_id}`。校验：dataset 不存在 → `40401`；dataset 无 `ls_project_id` 或 LS 项目不存在 → `42200`（提示先创建数据集）；`files` 全空 → `42200`。逐文件预检：扩展名 ∉ {`.jpg`,`.jpeg`,`.png`,`.bmp`} → `bad_items` 记 `unsupported_extension`（不上传）；>100MB → 记 `too_large`（不上传）；**部分成功语义**（单坏文件不卡整批）。合法文件复用 LS `data_import.uploader.create_file_upload` 入 LS 存储（生产=MinIO），再由 Celery `default` 队列任务（§5.2）登记 `aoi_datasets.image`（`object_key`=LS 上传路径）并建 LS 任务（镜像上游 `async_import_background`：`ProjectSummary` 行锁 + `ImportApiSerializer` 批量建任务 + `update_tasks_counters_and_task_states` + `update_data_columns`；不 emit webhook）；任务内逐文件结局：md5 **全局**去重命中 → `dup`（不建任务、不重复登记，其 FileUpload 字节保留为已知行为）；PIL 解码失败 → `bad_items` 记 `decode_failed` 并登记 `Image(qc_status='rejected')`；成功 → `Image(qc_status='ok')` + LS 任务。broker 不可用 → `50300`（job 留 queued，已上传 FileUpload 为已知孤儿字节） |
| `GET /import/{job_id}` | datasets.view | `{status, total, ok, dup, bad, bad_items:[{filename, reason}]}`；未知 `job_id` → `40401`（D5 起查真实任务表，不再有 stub） |
| `GET /images`、`GET /images/{id}/download`、`GET /images/{id}`、`DELETE /images/{id}` | `GET`=datasets.view；`DELETE`=datasets.update | 筛选/预签名下载；详情（D5 收尾新增）。`DELETE`（D5 收尾新增）：删除图片登记 + 其 LS 任务（镜像上游删任务路径，删后重算计数）+ 存储字节（`FileUpload`）+ 版本明细（`dataset_item`）；未知 id → `40401`。任务按 `data.image` 精确（裸对象键）或后缀（`/data/upload/...` 同源 URL）匹配，兼容存量数据 |
| `GET/POST/PUT /defects`、`POST /defects/publish`、`GET /defects/versions` | `GET`=datasets.view（含 `/defects/versions`）；`POST`=**datasets.create**；`PUT`=datasets.update；发布=**datasets.publish**（admin+super） | 字典 CRUD；发布 → 渲染 label config（RectangleLabels，`value`=code、`html`=中文展示名）+ 版本快照，并**回写已建 AOI 标注项目的 label config**（响应带 `projects_synced`；D5 收尾 #2）。（D5 权限澄清：写拆分为 POST=create / PUT=update，三角色对两码同持，行为无回退；**D5 收尾：`PUT` 为部分更新语义**——只校验/更新携带字段，启停开关只带 `{code, active}` 即可，`code` 仅用于定位不可改）。**`GET /defects/versions`（D5 收尾 #1 新增）**：发布历史（最新在前），条目 `{id, version, published_by, published_by_name, published_at, defect_count, labels:[{code,index,color,name_cn,risk_level}], is_latest}`；旧快照缺 `name_cn` 时回退查当前字典补展示名 |
| `GET/POST /datasets`、`GET/PUT/DELETE /datasets/{id}`、`POST /datasets/{id}/versions` | `GET`=datasets.view；`POST`=datasets.create；`PUT`/`DELETE`=datasets.update | 数据集/版本。**D5 起 `ls_project_id` 由服务端生成**（标注项目创建自 D6 提前）：`POST` 必填 `name`，服务端取最新已发布缺陷字典版本并按 `aoi/datasets/ls_project.py` 模板创建真实 LS 项目；**无任何已发布版本时回退当前启用缺陷（`active=True`）以 `draft` 语义建项目（D5 收尾：支持未发布字典先建数据集）**，连启用缺陷都没有 → `42200`；客户端携带 `ls_project_id`（`POST`/`PUT`）→ `42200`。发布触发划分 + **测试集红线**（违反 → 42200）。`GET /datasets` 投影含 `versions:[{id,version,status,phase}]`（D5 收尾）。`DELETE /datasets/{id}`（D5 收尾改为级联清理）：删 LS 项目（含任务/标注，镜像上游 `perform_destroy` 断信号）、项目内导入的图片登记/任务/存储字节、版本与 `dataset_item`；视图锚点仍是 `datasets.update`（D4 不动视图锚点）；`datasets.delete` 专供 §3.1.1 闸门拦截 LS 原生项目删除 |
| `GET /datasets/{id}/versions/{v}/export` | datasets.view | **复用 LS data_export（YOLO）** → zip 落 MinIO `datasets/exports/` |
| `GET /annotation-stats` | datasets.view | LS 标注/审核状态只读投影（不建表） |

**AOI 标注项目模板（D4，`aoi/datasets/ls_project.py`）**

- 形态：**代码级常量模板 + 纯函数**（`AOI_PROJECT_DEFAULTS` / `build_project_kwargs(...)`），无表、无端点、无 IO。
- **D5 起 `POST /api/datasets` 由服务端创建真实 LS 项目**（标注项目创建自 D6 提前，`ls_project_id` 改为服务端生成，见上表）；快照还原规则：取最新 `defect_dict_version.snapshot` 的 `{labels:{code:{index,color}}}` 按 `index` 排序还原 defects 后渲染 label config。
- 模板钉住的 LS Project 字段（显式钉死，不依赖上游默认值漂移）：`label_config`（由缺陷字典渲染）、`title`=`{dataset_name}`、`description`（含 dataset/version/dict_version）、`color`=`#FFFFFF`（**不使用品牌色**，裁定 2026-09-14）、`maximum_annotations=1`、`show_overlap_first=False`、`sampling=SEQUENCE`、`skip_queue=REQUEUE_FOR_OTHERS`、`show_skip_button=True`、`expert_instruction`（标注规范文案）、`show_instruction=True`、`show_collab_predictions=True`、`evaluate_predictions_automatically=False`、`reveal_preannotations_interactively=True`、**`enable_empty_annotation=True`（OK 图必须能提交空标注，用于 YOLO 负样本）**、`show_annotation_history=False`、`show_ground_truth_first=False`、`min_annotations_to_start_training=0`。
- **不含任何 review 设置**：LS OSS 无 Review 流（§10.1、§1 实测）。

### 4.2 训练域 `/api/train`

| 方法/路径 | 权限 | 说明 |
|---|---|---|
| `GET /base-models`、`GET /presets` | training.view | 基模/预置方案列表 + 可编辑字段 Schema |
| `POST /jobs` | training.create | `{dataset_version, framework:"yolo", preset:{...}}` → `{job_id}` |
| `GET /jobs/{id}` / `POST /jobs/{id}/cancel` | training.view/cancel | 状态/指标/取消 |
| `GET /jobs/{id}/progress` | training.view | **SSE**：`{phase, epoch, total, loss, metrics}`，`phase ∈ {training,evaluating,exporting,finished,failed}` |
| `GET /models?lifecycle=&task_type=` | training.view | 注册表：`[{id, version, framework, task_type, dataset_version, class_names, cover_classes, precision, weights_key, eval_metrics, gate_status, lifecycle}]`；**同时是前端「选择要上传的模型」的数据源** |
| `POST /models/{id}/approve` | training.approve | `{decision, note}` → `lifecycle=approved` |
| `POST /models/{id}/retire` | training.publish | 下线：`lifecycle=retired`（**删除已上传记录的前置条件**，见下） → `{id, lifecycle}` |
| `POST /models/{id}/publish` | training.publish | **对单个模型**构建并推送镜像到 registry（跨平台契约 §2.4）→ `{publish_id, status}` |
| `POST /models/publish` | training.publish | **批量上传**：`{model_ids:[...], precision?:"fp32"}` → **逐条独立执行**，返回 `{results:[{model_id, publish_id?, status, error?}]}`；某条失败（未审批/门禁未过/同 tag 已发布）不影响其余条目 |
| `GET /models/{id}/publish` | training.view | 发布状态：`{image, tag, digest, status, attempts, error_message, published_at}` |
| `GET /publishes?include_deleted=&model_ref=&status=` | training.view | **已上传模型列表**（跨模型）：`[{publish_id, model_id, model_ref, image, tag, digest, status, deleted_at, published_at, published_by}]`；默认隐藏已删除项 |
| `POST /publishes/{id}/delete` | training.publish | **软删已上传记录**（仅管理员/超管）：要求该模型 `lifecycle=retired`，否则 `40900`；**只删 A 侧记录，仓库镜像保留**（B 仍可拉取/回滚） |
| `POST /publishes/{id}/restore` | training.publish | **恢复/重新上线**：清空 `deleted_at` 并将 `lifecycle` 置回 `published`（仓库镜像仍在，恢复零成本） |

**「选择上传」与「已上传模型管理」的前后端约定**（跨平台契约 §2.4；项目负责人 2026-09-11 裁定）：

| 侧 | 要求 |
|---|---|
| 后端 | ① 上传由**人工选择**驱动，支持多选批量（`POST /models/publish`），**逐条独立**处理并返回每条结果，不做整批回滚；② 删除为**软删**（`deleted_at`/`deleted_by`，保留审计），**绝不动仓库镜像**；③ 删除前置校验 `lifecycle=retired`，未下线一律 `40900` 并提示先下线；④ 删除/恢复**仅管理员与超级管理员**（复用 `training.publish` 权限点）；⑤ 恢复后 `lifecycle` 回 `published` |
| 前端（A 侧「训练 → 模型库与发布」页，归 B 交付） | ① 模型列表（`GET /models`）支持**多选 + 「批量上传」**，逐条展示上传结果与失败原因，失败项可单独重推；② 独立「已上传」区展示 `image/tag/digest/status/published_at` 与删除态筛选；③ 每行提供「下线」「删除」「恢复」，删除需二次确认；模型未 `retired` 时删除按钮禁用并提示「请先下线」；④ 删除确认文案明确「仅移除 A 侧记录，仓库镜像保留、B 仍可拉取」；⑤ 全部操作受 `training.publish` 权限控制 |

> **不做「该模型是否已被产线使用」的展示**：A 从不主动连接 B、不做心跳/回执，A 侧只呈现自己的上传状态（`image/tag/digest/status`）。

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
| `GET /audit` | system.audit（super_admin） | 审计查询（角色/授权、模型发布/下线/删除/恢复、训练、导出等关键操作） |

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
| `default` | 导入包裹（D5 已落地）/ 导出 / 统计 | CPU |
| `publish` | 模型发布（构建镜像 + docker push + 重试） | CPU + 网络 |

**Celery 落地口径（D5）**：

- broker = 环境变量 `CELERY_BROKER_URL`，默认 `redis://localhost:6379/1`——与 LS 自带 `django_rq` 的 Redis DB 0 **隔离**，LS 原生 RQ 保持不动。
- app 定义在 `label_studio/aoi/celery.py`（`Celery('aoi')` + `config_from_object('django.conf:settings', namespace='CELERY')` + `autodiscover_tasks()`）；`aoi/__init__.py` 导入 `celery_app` 使 `@shared_task`/`.delay()` 绑定 aoi app。
- `CELERY_TASK_ROUTES = {'aoi.*': {'queue': 'default'}}`：**仅 `default` 队列有真实任务**（导入包裹 `aoi.datasets.tasks.process_import_job`）；`training`/`publish` 队列暂无任务，路由待各自任务落地时再加（不配占位路由）。
- 测试口径：契约测试 autouse fixture 强制 `CELERY_TASK_ALWAYS_EAGER=True` + `CELERY_TASK_EAGER_PROPAGATES=True`（eager 同步执行，任务异常直接外抛）。
- worker 启动：`celery -A aoi worker --queues=default --loglevel=info`（docker-compose `worker` 服务 / 宿主机 `make run-celery`）。

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

1. **复审自研（D2 裁定，D4 复验）**：LS OSS 无 Review 流，**不复用 LS Review**；复审由 `aoi/review` 自研接口承担（`workitems/claim/finalize`、`suggestions`、`bad-images`）。
   **D4 复验依据**（`label-studio 1.24.0.dev0 @30a7f330d`）：`core/utils/common.py::is_community()` 判定为社区版（企业能力在未安装的 `label_studio_enterprise`）；全仓 `class AnnotationReview\|class Review` 零命中；`Project` 无任何 review 设置字段；所有 `urls.py` 无 review 路由；`web/` 无 review 页面；`users/firewall.py` 在 LSO 下是显式 no-op（docstring「LSE swaps in an enterprise implementation」）。
   `feature_flags.json` 中的 `review_routing_rules`、`annotator_reviewer_firewall` 等是**两版共用的云端下发 flag 文件**，不构成 OSS 能力，不得作为依据。故《MVP开发计划》D5/D6/§2.1 的「Review 流配置验证 / 复用 LS Review」为陈旧表述，已回写。
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
- `tests/contracts/test_platform_a_api.py`：信封/鉴权/**权限锚点（每视图声明权限点）**/导入幂等/训练状态机（approve/publish 门禁与 40401）/**模型发布（model.yaml 生成 + 镜像 tag 规范 + `(model_ref, tag)` 唯一 + 批量上传逐条独立 + 未 `retired` 删除 → 40900 + 软删不删仓库镜像 + 恢复回 published）**/`/api/ingest/findings` 幂等（含半写补建）/复审状态机（claim/finalize 并发与低桶强制）。
  - **RBAC 与闸门（D4 已交付，取代原「RBAC 覆盖延期」标注）**：新增 9 组用例——
    | 类 | 断言 |
    |---|---|
    | `TestPermissionCodeRegistry` | 每个视图 `aoi_perm`/`aoi_perm_by_method` ∈ `PERMISSION_CODES`；码表 38 且无重复；`DEFAULT_ROLE_MATRIX` 码集 == `PERMISSION_CODES` |
    | `TestRbacMatrix` | 三角色 × 38 码逐码断言（期望值**硬编码在测试**，不读实现常量） |
    | `TestRbacForbidden40300` | operator 越权（`datasets.export`/`datasets.publish`/`training.create`/`system.roles`）→ `40300`；无角色 → `40300`；匿名 → `40100` |
    | `TestPermCacheInvalidation` | 授予/撤销后**同进程立即**生效；`authz_state.version` 递增 |
    | `TestRoleAdminApi` | `PUT` 带 `permissions` 全量覆盖（含清空）；内置角色禁删 `40900`；未知码 `42200`；`user_role` 级联 |
    | `TestGrantRoleCommand` | `aoi_grant_role` 全量覆盖 + `--list`；未知角色退出码非 0；审计落 `user.roles.assign` |
    | `TestNativeGate` | 四类高危按角色拦截；**前缀陷阱**：`/api/auth/export/` 拦、`/api/auth/login\|logout` 放行；`GET /api/projects/{pk}/imports\|reimports/{id}/` 放行 |
    | `TestNativeGateAnnotationFlow` | 标注主流程 10 条豁免路径**全部不被拦**（最高优先级回归） |
    | `TestSeedRbac` | 播种幂等；内置角色矩阵不被二次覆盖；super_admin 补授只加不减 |
  - **组织管理（D5 已交付）**：新增 4 组用例——
    | 类 | 断言 |
    |---|---|
    | `TestUserAdminApi` | 非超管 `GET /api/core/users`/停用/启用 → `40300`；列表项含 aoi 角色；任命 admin/operator 后**同进程立即生效**、卸任立即失效；停用组合拳三件套（`is_active=False` + 角色清空 + `OrganizationMember.deleted_at`）且**已签发 JWT 立即被拒**；启用恢复访问且角色为空；审计 `user.deactivate`/`user.activate` 落库 |
    | `TestLastSuperAdminGuard` | 停用/清角色两路导致活跃超管归零 → `40900`；存在第二个活跃超管时放行 |
    | `TestBootstrapSuperAdmin` | 固定超管播种幂等（重跑不重置密码）、组织成员与 `active_organization` 接线、`super_admin` 只加不减 |
    | `TestAoiSpaPages` | `/datasets`、`/training`、`/review`、`/system`、`/organization-admin`（含尾斜杠）登录后 200；未登录 → 登录页重定向（H22） |
- fixtures：`detect_result_sample.json`、`findings_ingest_sample.json`、`model_yaml_sample.yaml`、`ml_backend_predict_sample.json`、`goldens.json`。
- stub 原则：aoi API 在 D3 前全量 stub + OpenAPI。**D4 起 `/api/core/*` 已由 `aoi_core` 真表承载**，不再是进程内 stub。

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
| 2026-09-14 | RBAC 真实化 + LS 原生闸门（D4，**语义变更**） | ① `aoi_core` 由进程内 stub 改为**五表**（原四表 + `authz_state` 版本号表），随 `aoi_core/0001` 迁移创建 schema；② 权限码 **38 个**（`ACTIONS` 不扩，新增 6 码进 `EXTRA_PERMISSIONS`：`datasets.delete`/`datasets.config`/`system.storage`/`system.ml`/`system.webhook`/`system.labels`），矩阵补齐 `datasets.publish`/`review.update`；③ 播种改为 **`post_migrate`**（非「启动时」）+ 幂等命令 `aoi_seed_rbac`，内置角色**仅首次写入**、`super_admin` **只加不减补授**；④ 判定缓存改为 **`(user_id, version)` + 每请求读版本号**（`CACHES` 未配置，LocMemCache 跨进程不共享），授权变更**零延迟生效**；⑤ 首个超管由 `aoi_grant_role` 命令产生；⑥ **全局 DRF 权限类红线改口**：允许在 `DEFAULT_PERMISSION_CLASSES` 首位插入 `aoi.common.native_gate.AoiNativeGatePermission`（§2.4/§3.1.1）；⑦ 闸门为 **deny-list 4 类高危 + 默认放行 + fail-open**，被拦返回 **LS 方言 `{"detail": …}`**；⑧ `datasets.update` 语义澄清（不含 LS 项目配置改写）；⑨ `PUT /api/core/roles/{id}` 支持 `permissions` 全量覆盖、`POST /api/core/users/{id}/roles` 为全量覆盖 | ① 本表 + §1/§2.4/§3.1/§3.1.1/§4.0/§4.1/§10.1/§13.1；② 实现 `aoi/core/{models,migrations/0001_initial,permissions,authz,views,serializers,apps}.py`、`aoi/core/management/commands/{aoi_seed_rbac,aoi_grant_role}.py`、`aoi/common/{permissions,native_gate,audit}.py`、`core/settings/base.py`（注入点 1）；③ fixture 无字段变化（`aoi_api_paths.json` 路径不变），`tests/contracts/conftest.py` 移除 `reset_aoi_stub_state`；④ `TestPermissionCodeRegistry`/`TestRbacMatrix`/`TestRbacForbidden40300`/`TestPermCacheInvalidation`/`TestRoleAdminApi`/`TestGrantRoleCommand`/`TestNativeGate`/`TestNativeGateAnnotationFlow`/`TestSeedRbac` |
| 2026-09-15 | 组织管理页 + 固定超管 + SPA 深链（D5，**语义变更**） | ① 新增 `GET /api/core/users`、`POST /api/core/users/{id}/deactivate\|activate`（均 `system.users`）；「删除用户」裁定为**停用组合拳**（`is_active=False` + 清角色 + 软移除组织成员）；② **最后超管守卫**：任何授权变更导致活跃超管归零 → `40900`（roles 与 deactivate 两路）；③ 固定超管 `superadmin@nbhx.com` 随 `post_migrate`/`aoi_seed_rbac` 幂等播种（已存在不重置密码）；④ `aoi/urls.py` 点名注册 5 个 aoi SPA 页面路由渲染壳模板（H22 结项）；⑤ 前端摘除原生 `/organization` 注册并删 Menubar 入口，Menubar 按 `perms` 显隐（H23 结项），新增 `/organization-admin` 页（仅 `system.users`） | ① 本表 + §2.2/§3.1/§4.0/§13.1；② 实现 `aoi/core/{views,urls,bootstrap,apps}.py`、`aoi/pages.py`、`label_studio/templates/aoi/page.html`、`web/.../src/aoi/usePerms.ts`、`web/.../src/pages/OrganizationAdmin/`、Menubar.jsx（**注入点 3**）、pages/index.js（**注入点 4**）；③ fixture `aoi_api_paths.json` +3 路径；④ `TestUserAdminApi`/`TestLastSuperAdminGuard`/`TestBootstrapSuperAdmin`/`TestAoiSpaPages` |

*本契约于 D2 冻结；D9、D15 评审窗口。破坏性变更四件套：改文档 + 改 stub + 改 fixture + 双方测试过。*

