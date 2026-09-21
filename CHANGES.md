# AOI 二开骨架清理记录

基于仓库同级项目文档 `docs/` 中的《MVP开发计划》《P0骨架设计》与《子文档 01》，
对上游 Label Studio 仓库做骨架化清理。保留后续二开需要使用的源码与构建/运行骨架，
移除与 AOI 门板检测平台无关的上游文档、演示素材、社区 CI、云端部署模板等。

## 清理范围

- 完整剥离外部云存储集成：移除 `io_storages/s3`、`gcs`、`azure_blob`、`redis` 数据源 provider
  及前端 StorageSettings/DataManager 对应 provider；同步清理云存储相关测试；
  仅保留本地文件/上传导入（部署侧保留 MinIO + PostgreSQL）
- 移除上游文档站：`docs/`
- 移除上游宣传/示例图片：`images/`
- 移除上游 GitHub 社区 CI/Issue 模板/PR 工作流：`.github/`
- 移除本地开发容器与编辑器辅助配置：`.devcontainer/`、`.cursor/`
- 移除上游运维/监控辅助目录：`prometheus/`、`scripts/`、`tools/`
- 移除云端/第三方部署模板：`app.json`、`azuredeploy.*`、`heroku.yml`、
  `Dockerfile.heroku`、`Dockerfile.cloudrun`、`Dockerfile.hgface`
- 移除 MySQL 部署编排变体：`docker-compose.mysql.yml`
- 移除本地开发覆盖编排：`docker-compose.override.example.yml`

## 保留

- `label_studio/`：LS Django/DRF 主应用源码
- `web/`：LS React/TS 前端源码
- `deploy/`、`Dockerfile`、`docker-compose.yml`、`docker-compose.minio.yml`：本地/交付构建与运行骨架（PostgreSQL + MinIO）
- `pyproject.toml`、`uv.lock`、`web/package.json`、`web/bun.lock`：依赖锁定
- `LICENSE`、`NOTICE`、`licenses/`：Apache-2.0 署名与第三方许可

---

## 上游基线锁定（D1）

| 项 | 值 |
|---|---|
| 上游版本 | `label-studio 1.24.0.dev0` |
| fork HEAD | `30a7f330d6fa7d9bfab641a57ef63ff5fbb6c029`（`git rev-parse HEAD`） |
| 锁定日期 | 2026-09-09 |
| 数据库基线 | 仅 PostgreSQL（`DJANGO_DB=default`）；SQLite 不作为 aoi 开发库 |

**上游只读目录清单**（红线：除下表注入点外不得写入业务代码）：

`label_studio/core/`、`label_studio/users/`、`label_studio/projects/`、`label_studio/tasks/`、
`label_studio/data_export/`、`label_studio/data_import/`、`label_studio/data_manager/`、
`label_studio/ml/`、`label_studio/ml_models/`、`label_studio/organizations/`、`label_studio/io_storages/`、
`label_studio/webhooks/`、`label_studio/labels_manager/`、`label_studio/jwt_auth/`、`label_studio/session_policy/`。

**注入点（4 处，与 `docs/P0骨架设计_双平台.md` §2.2 一一对应）**：

| # | 文件 | 改动 | 说明 |
|---|---|---|---|
| 1 | `label_studio/core/settings/base.py` | ① `INSTALLED_APPS += [8 个 aoi.* AppConfig]`；② `REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES` 增加 `aoi.common.authentication.AoiJWTAuthentication`（D3）；③ `MIDDLEWARE` 移除 `jwt_auth.middleware.JWTAuthenticationMiddleware`（D3）；④ 新增 `SIMPLE_JWT` 显式配置（D3） | 带注释「AOI 二开（注入点，见 CHANGES.md）」；D3 认证链路详见下方「认证链路标准化」 |
| 2 | `label_studio/core/urls.py` | `re_path(r'^', include('aoi.urls'))` | 放在 `organizations.urls` **之前**，保证 aoi `/api/*` 优先匹配 |
| 3 | `web/apps/labelstudio/src/components/Menubar/Menubar.jsx` | 新增 4 个菜单入口（Datasets/Training/Review/System） | 仅数据驱动，不改上游组件逻辑 |
| 4 | `web/apps/labelstudio/src/pages/index.js` | 注册 4 个二开页面路由 | 一行一页，页面空壳在 `pages/<Page>/` |

**授权例外（第 5 处上游改动，2026-09-09 授权；见下方「缺陷修复」）**：

| # | 文件 | 改动 | 说明 |
|---|---|---|---|
| 5 | `label_studio/data_manager/managers.py` | `annotate_storage_filename` 兼容 0/1 个 import link name | 清理云存储 provider 后的 `Concat` 500 修复；有回归测试 `TestTaskDetailConcatRegression` |

**自检命令**（应只出现上述 5 个文件；超出的都是违规改动）：

```bash
git diff --name-only 30a7f330d -- \
  label_studio/core label_studio/users label_studio/projects label_studio/tasks \
  label_studio/data_manager label_studio/data_export label_studio/data_import \
  label_studio/ml label_studio/ml_models label_studio/organizations label_studio/io_storages \
  label_studio/webhooks label_studio/labels_manager label_studio/jwt_auth label_studio/session_policy
# 期望输出：label_studio/core/settings/base.py、label_studio/core/urls.py、label_studio/data_manager/managers.py
```

### 枚举裁定（T1.2）

- MVP 唯一 `task_type = skillname.SkillName.OBJECT_DETECTION`（`ObjectDetection`）→ LS 控件 `RectangleLabels`；
- `aoi_training.*.task_type` 一律取 `skillname.SkillName.OBJECT_DETECTION`；
- **禁止** import 上游 `ml_models.SkillNames`（上游仅 `TextClassification`/`NER`，见 `label_studio/ml_models/models.py`）；
- `model_ref` 严格格式 `^([0-9]+)-([a-z0-9._-]+)@ds([0-9]+)$`（ASCII；`\d` 的 Unicode 语义禁止）；镜像 tag 由 `skillname.image_tag_from_model_ref` 生成；
- 缺陷 code `^object_fault_type_(0[1-9]|[1-9][0-9])$`（01~99，ASCII），8 色调色板由 `skillname.color_for_index` 提供。

---

## 缺陷修复（D2）

### 任务详情 `GET /api/tasks/{id}/` 500（`Concat`）

- **背景**：清理云存储 provider 后 `settings.IO_STORAGES_IMPORT_LINK_NAMES` 仅剩 1 项
  （`io_storages_localfilesimportstoragelink`）；上游 `data_manager/managers.py::annotate_storage_filename`
  使用 `Concat(*intersperse(...))`，在 0/1 个 link name 时位置表达式不足 2 个，抛
  `ValueError: Concat must take at least two expressions`。
  任务详情走 `all_fields=True`，必然命中；与 MinIO 自身存储无关（MinIO 走 `S3Boto3Storage`）。
- **修复**（`label_studio/data_manager/managers.py`，2026-09-09 授权）：
  - 0 个 link name → `Value(None, output_field=TextField())`；
  - 1 个 → `Coalesce(key, Value(None, output_field=TextField()))`；
  - ≥2 个 → 原 `Concat(*intersperse(...))` 不变。
- **验证**：`PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts/test_platform_a_api.py::TestTaskDetailConcatRegression -q` → **5 passed**
  （0/1/2 link name、`all_fields=True`、`GET /api/tasks/{id}/` 200）。
- **记录**：本节即为该问题的完整记录（背景/根因/修复/验证）；回归用例 `TestTaskDetailConcatRegression`，修复注释在 `data_manager/managers.py::annotate_storage_filename`。

---

## D2 review 修复（2026-09-10，P0/P1/P2）

对 `feat/d2-aoi-skeleton` 未提交改动的完整 review（5 个独立审查分区 + 复核）后落地的修复：

**P0（安全 / 数据一致性 / 共享词汇表）**

- `INTERNAL_TOKEN` **fail closed**：未配置时仅 `DEBUG=true` 才回落开发默认值，否则抛 `ImproperlyConfigured`，
  错图回传端点一律 40100；`.env.example` 与 `docker-compose.yml` 补齐 `INTERNAL_TOKEN` 等 AOI 变量
  （`aoi/common/settings.py`、`aoi/review/ingest.py`、`aoi/prelabel/views.py`）。
- ingest 每个分支 `transaction.atomic()` 写入；并发重复请求撞唯一约束时按幂等返回；
  fact 已存在但 workitem 缺失（半写/崩溃）时**补建**，不再返回 `workitem_id=null`。
- ingest 元数据全量校验（类型/枚举/长度/图片字段）→ 42200 + `detail.fields`；单图 >100MB → 40010（不读入内存）。
- `skillname` 词汇表：`object_fault_type_XX` 限定 ASCII 01~99（`00`、全角/阿拉伯数字一律非法）；
  `model_ref`/镜像 tag 只接受 ASCII 数字。

**P1（冻结面上的守卫与状态机）**

- 异常 → 错误码映射补齐：`Http404→40401`、限流 `429→42900`、503→50300、405/415→40010（`aoi/common/errors.py`、`views.py`）。
- RBAC 判定入口改为 `aoi.common.permissions.aoi_permission('training.publish')` 工厂（DRF 可实例化），
  每个 aoi 视图声明 `aoi_perm` / `aoi_perm_by_method`。
- `/api/train/models/{id}/publish`：未知模型 40401、未 approved → 40900、`model.version` 非 `model_ref` → 42200、
  GET 无记录 → 40401、响应标 `stub: true`；`model_publish` 唯一性改为 `(model_ref, tag)`（fp16 可单独发布）。
- `/api/train/models/{id}/approve`：decision 白名单、未知模型 40401、门禁未通过不得 approved。
- 复审：claim 条件更新（重复认领 40900）、finalize 状态机（重复终裁 40900、终裁单条唯一）、
  低桶（`bucket=low` 或 `forced`）必须带 action/annotation、`final_reason` 白名单，
  终裁落库 `annotation_id/class_id/boxes/note` 并推进 `inspection_fact.status`。
- `/api/core/roles*`：code 唯一（40900）、内置角色不可删（40900）、未知角色/用户拒绝（42200/40401）、角色变更写审计。
- 状态机收口：`dataset_version` 创建时 `status/phase` 服务端控制（客户端传其他值 42200）；
  `prelabel_task` 默认 `queued` + 迁移白名单 + `model_ref`/`route_config` 校验 + `route_bucket` 只读；
  字典 `risk_level` 必填、`aliases` 类型校验。
- 字典快照 index 改用**列表位置**（0..n-1 连续），与 `classes.txt` / `model.yaml.classes[].index` 对齐。

**P2（测试可信度与卫生）**

- prelabel 协议测试改为比对磁盘 fixture（并新增 fixture ↔ protocol 常量一致性测试）；
  model.yaml 测试钉死契约字面量并补 `schema_version`/`skillname` 负例；manifest 的 yaml sha256 由 fixture 字节计算。
- 契约 §13.1 标注 RBAC（三角色矩阵/40300/缓存失效）为 D4 交付；`tests/contracts/README.md` 增补测试模块/ fixture 归属与延期表。
- `TestAllStubs` 起真实 Model/WorkItem 种子，不再依赖伪造响应；workitem 列表空队列返回空列表。
- LS reuse smoke：写入需 `LS_REUSE_ALLOW_MUTATION=1`，模块结束清理自建 project/MLBackend，凭据被拒不再 skip 成绿灯。
- `tests/contracts/conftest.py` 重置 `_NEXT_ROLE_ID`；`reuse` marker 注册进 `pyproject.toml`。

**P3**：不阻塞提交的工程卫生项已外挂到 `docs/D3_工程卫生清单.md`（30 项，D3 处理）。

---

## 认证链路标准化（D3，2026-09-10）

**问题**：上游把 Bearer JWT 的校验放在 Django 中间件 `jwt_auth.middleware.JWTAuthenticationMiddleware`
里直接赋值 `request.user`，DRF 侧实际靠 `SessionAuthentication` 读 `request._request.user` 才拿到用户。
后果：① 认证不经过 DRF 认证链，`request.auth` 为空、OpenAPI 不认；② 鉴权失败只 log 不抛，
无法区分「令牌过期/签名错/组织开关关/旗标没开」，排查靠猜；③ 依赖 DRF 内部实现细节；
④ 没有「账号密码换 token」的登录端点（`/api/token/` 要求先有 session）；⑤ 鉴权路径上挂了
LaunchDarkly 旗标；⑥ 没有 `SIMPLE_JWT` 配置，access 生命周期/签名密钥全靠默认值。

**改动**（仅动注入点内文件 + `aoi/` 可写区，上游 `jwt_auth/` 一行未改）：

| 文件 | 改动 |
|---|---|
| `label_studio/core/settings/base.py` | ① `DEFAULT_AUTHENTICATION_CLASSES` 改为 `AoiJWTAuthentication` → `TokenAuthenticationPhaseout` → `SessionAuthentication`；② `MIDDLEWARE` 移除上游 JWT 中间件；③ 新增显式 `SIMPLE_JWT`（HS256、access 30 min、refresh 7 天、**不轮换**） |
| `label_studio/aoi/common/authentication.py`（新增） | `AoiJWTAuthentication`：延迟导入 simplejwt 的薄代理。**必要**——`core/settings/label_studio.py` 在 settings 导入期就 import `core.utils.common` → `rest_framework.views` → `rest_framework.schemas`，后者立即 import 认证类列表；simplejwt 认证类在模块级 import `django.contrib.auth.models`，此时 app registry 未 ready（`AppRegistryNotReady`） |
| `label_studio/aoi/core/auth.py`（新增） | `POST /api/auth/login`（匿名，email+password → access/refresh；凭据校验与浏览器登录同源：`USER_AUTH` 钩子 → Django 后端）、`POST /api/auth/logout`（refresh 进黑名单，幂等，非本人令牌 40300） |
| `label_studio/aoi/urls.py` | 挂载两条 auth 路由；`AOI_PREFIXES` 增加 `auth`（尾斜杠兜底） |

**为什么 refresh 不开启轮换**：`/api/token/` 签发的 PAT（`jwt_auth.models.LSAPIToken`，200 年 refresh）
是用户长期保存的凭据，一旦开启 `ROTATE_REFRESH_TOKENS`，用户手里那份会在首次刷新后立即进黑名单。

**不变的部分**：浏览器会话登录 `/user/login/`（sessionid）、上游 `/api/token/*`（PAT/刷新/吊销/轮换）、
`X-Api-Key` 头改写、`X-Internal-Token`（B→A 回传）、`admin/` 与密码重置链路。

**验证**：`tests/contracts/test_platform_a_api.py::TestAoiJwtAuth`（15 例，含真实 Bearer 打
aoi 端点与 LS 原生 `/api/current-user/whoami`、登出黑名单、浏览器 session 回归、中间件移除守卫）；
契约文档 §2.4/§4.0 与 fixture `aoi_api_paths.json`（`d3-20260910`）同步更新。
`tests/contracts/test_ls_reuse_smoke.py`（需真实 LS 实例）覆盖 `/data/upload` 的 Bearer 下载回归。

---

## 文档变更（D3）：A 侧「勾选模型上传 + 已上传管理」与 B 侧「一键拉取」（2026-09-11）

**背景**：模型经镜像仓库分发（构建镜像 / 推送 / 拉取）的机制**不变**；本次补齐两处能力约定：

1. **A 侧自主决定上传哪些模型**——由管理员在「训练 → 模型库」中**勾选**（支持多选批量）后上传，不是"审批通过即自动发布"；
2. **A 侧可管理已上传模型**——列表 / 下线（`lifecycle=retired`）/ **软删（仅 A 侧记录 + 审计，仓库镜像保留）** / 恢复；仅管理员与超级管理员，**删除前必须先下线**；
3. **B 侧一键拉取**——新增远端可用 tag 列表（Registry v2 `GET /tags/list`）→ 选中 → 一键拉取；拉取完成后模型立即可用于工位模板与模型选择。

**改动（仅文档）**：

| 文档 | 改动 |
|---|---|
| `docs/contracts/跨平台契约_A-B.md` | §2.4 触发方式改为"管理员勾选批量上传（逐条独立）"+ 新增「已上传模型的管理」表（下线/软删/恢复规则）；§2.5 新增"一键拉取"流程与"A 侧软删不影响 B 可用 tag"；§6 契约测试补 3 项 |
| `docs/contracts/平台A_接口与数据契约.md` | §3.3 `model_publish` 增 `deleted_at`/`deleted_by`；§4.2 新增 `POST /models/publish`（批量逐条独立）、`POST /models/{id}/retire`、`GET /publishes`、`POST /publishes/{id}/delete`、`POST /publishes/{id}/restore` 与**前后端约定表**；审计枚举补"下线/删除/恢复" |
| `docs/contracts/平台B_接口与数据契约.md` | §3.2 新增 `GET /models/remote`（远端可用 tag + `local` 标记）与**「一键拉取」前端约定**（列表/置灰/状态/重试/模板选择闭环）；注明 A 侧软删不影响本列表 |
| `docs/MVP开发计划.md` | 速览/分工/二开增量/裁剪（新增软删与拉取入口两项决策）/风险（误删与误操作）/D7、D9、D10 排期/变更记录 |
| `docs/P0骨架设计_双平台.md` | `model_publish` 加软删字段；A 侧 stub 表补 5 个端点；B 侧 stub 表补 `GET /models/remote`；前端页面与验收 ⑧ 同步 |
| `README.md`、`docs/docker-registry-setup.md` | 平台间链路说明；仓库文档补"A 侧删除为软删、镜像保留、B 仍可拉取" |

**接口新增（路径/字段命名待评审确认）**：`POST /api/train/models/publish`、`POST /api/train/models/{id}/retire`、
`GET /api/train/publishes`、`POST /api/train/publishes/{id}/delete`、`POST /api/train/publishes/{id}/restore`、
`GET /api/v1/models/remote`。删除/恢复复用 `training.publish` 权限点（管理员/超管）。

**待跟进（"破坏性变更四件套"的 stub/fixture/测试三件，D7 前）**：A 侧 `model_publish` 迁移补 `deleted_at`/`deleted_by`；
A 侧批量上传/下线/软删/恢复 stub 与契约测试；B 侧 `GET /models/remote` stub（真实实现调 Registry v2 `GET /tags/list`）与假 tag 列表 fixture。

---

## D3 发布服务 stub（假 build/push）与三项确认（2026-09-11）

**范围**：平台 A 线 D3 里程碑最后一项「发布服务 stub（假 build/push）」落地；同时确认前三项已就绪并补契约锁定测试。
经评审确认：本次**不含**「已上传管理」五端点与 `deleted_at`/`deleted_by`（仍为 D7 前待办，见上节）。

### 1. 三项确认（不改业务代码）

| 项 | 确认方式 | 结果 |
|---|---|---|
| JWT 登录链 | `TestAoiJwtAuth` 16 例 + 真实 `runserver` 冒烟 6 步 | 全绿：登录换 token → Bearer 打 aoi `/api/train/models`（200 信封）→ Bearer 打 LS 原生 `/api/current-user/whoami`（200）→ 无 token 40100 → logout `{revoked:true}` → 黑名单 refresh 再换 access 被拒（`Token is blacklisted`） |
| `/api/ingest/findings` | 既有 28 例 + **新增 `TestIngestFindingsFixtureContract`** | 全绿：C 侧 fixture `findings_ingest_sample.json`（suspicious + bad）此前**无任何测试消费**，现按真实 payload 打端点，断言应答形状、桶位（recheck→medium）与重复请求 `duplicated=true` |
| `model_publish` 表 | `manage.py showmigrations aoi_training` + 契约测试 | 全绿：`0002_model_publish` / `0003_p1_publish_unique_ref_tag` 已应用；`UNIQUE(model_ref, tag)` 与 `digest/attempts/error_message/published_at` 齐备，**无 schema 变更** |

### 2. 发布服务 stub（本次新代码）

**新增 `label_studio/aoi/training/publish.py`**（D7 Celery worker 的调用入口）：

| 能力 | 实现 |
|---|---|
| 假 build | 不依赖 docker：`build_fake_onnx`（按 model_ref 确定的占位权重 10752B）→ `build_model_files`（`build_model_yaml` + `validate_model_yaml` 校验 + 缺陷字典富化）→ `build_image_artifacts`（与 `FROM scratch + COPY model/ /model/` 等价的 docker schema2 单层产物：layer.tar.gz / config.json / manifest.json；tar `mtime=0`、`gzip(mtime=0)`、config 时间戳固定 → **同一份 `model.yaml` 输入**字节可复现） |
| push 双模式 | `AOI_PUBLISH_MODE=fake`（默认，离线，digest = 本地 manifest sha256）/ `registry`（`RegistryPushClient`：token → blob 单块上传 → manifest PUT，**digest 一律以仓库返回的 `Docker-Content-Digest` 回执为准**；不回执或回执不一致 → 失败，不拿本地值兜底）；`AOI_REGISTRY_PROXY` **只作用于该客户端会话** |
| 状态机 | `queued → building → pushing → published` 每步落库；失败 → `failed` + `error_message`（构建错 42200 / 推送错 50300），可人工重推（同 tag 复用记录、`attempts` 递增） |
| 成功副作用 | `digest`/`published_at` 落 `model_publish`；`model.lifecycle=published`；`model.config_snapshot.model_yaml` 快照；审计 `model.published`（含 mode） |
| 产物落盘 | `AOI_PUBLISH_ARTIFACTS_DIR`（默认 `tmp/publish/<tag>/`）：`model/` + `artifacts/`（含 `digest.txt`）+ `Dockerfile` + `push.sh`（curl 直推临时通道，含代理参数）；`tmp/` 已在 `.gitignore` |

`POST /api/train/models/{id}/publish` 同步执行上述流水线：应答新增 `digest`/`mode`，`status` 由 `queued` 变 `published`；
`stub` = `mode == 'fake'`（registry 模式已真推、B 可拉取，故为 `false`）。GET 端点语义不变。

### 3. 验证

- **契约测试全量**：`tests/contracts` → **196 passed, 8 skipped**（8 例为需真实 LS 的 reuse smoke）。新增 12 例：产物 schema2 自洽与 digest 链、字节可复现、落盘与审计、失败后重推、registry 客户端（token scope / blob / manifest / digest 不符 / 网络异常 / 缺凭据）、registry 模式端到端（HTTP mock）、ingest fixture 锁定、落盘目录解析与关闭开关。
- **真机 JWT 冒烟**：真实 `runserver` + PostgreSQL，6 步见上表。
- **真实推送验证（registry 模式，经 7897 代理）**：dev 库临时模型 `90-stub@ds9` → `POST /publish` → 5.7s 返回 `digest=sha256:bd95d5bf…223f`、`mode=registry`、`stub=false`；回读仓库校验：`GET /tags/list` 含 `90-stub-ds9`，manifest 回读 sha256 与记录 digest、`Docker-Content-Digest` 三者一致，config/layer blob digest 一致，层内 `model/` 三文件齐全且 `model.onnx.sha256` 与 `model.yaml.onnx.sha256` 互洽。验证后已删除临时模型/发布/审计行与冒烟用户；**镜像 tag 保留**（B 侧可直接拉取验证）。

### 4. 冒烟暴露并当场修复的两个真实缺陷

1. **产物目录错位**：`settings.BASE_DIR` 实为 `label_studio/core`（不是仓库根），`BASE_DIR.parent` 把产物写到了 `label_studio/tmp/publish`。改为以 `publish.py` 位置上溯定位仓库根（`REPO_ROOT`）。
2. **测试落盘未关闭**：`aoi.common.settings._get()` 对空串会回落到环境变量，使 conftest 的 `AOI_PUBLISH_ARTIFACTS_DIR=''` 失效、测试写入仓库工作区。`get_publish_artifacts_dir()` 改为**显式设置优先（空串 = 关闭）**，并补解析用例锁定；`label_studio/tmp` 已清理，测试不再产生脏文件。

### 5. 配置与不做项

- 新增配置：`.env.example` / `.env` / `docker-compose.yml` 透传 `AOI_PUBLISH_MODE`、`AOI_REGISTRY_PROXY`（示例 `http://127.0.0.1:<proxy-port>`）、`AOI_PUBLISH_ARTIFACTS_DIR`；本地 `.env` 开 `registry` 便于真推，契约测试由 conftest 强制 `fake` + 不落盘，二者解耦。
- **不做**（D7 前/计划外）：批量上传/下线/软删/恢复五端点与 `deleted_at`/`deleted_by`；Celery `publish` worker 与指数退避重试（`PUBLISH_RETRY` 保留未接线）；真实训练权重导出（当前为占位 ONNX）；B 侧任何代码。

### 6. 文档口径与 D2 证据文档恢复（2026-09-11）

**文档纪律（项目负责人 2026-09-11 裁定，后续遵守）**：`docs/MVP开发计划.md`、`docs/P0骨架设计_双平台.md`、
`docs/双平台架构与拆分方案.md`、`docs/docker-registry-setup.md`、`docs/contracts/**` 是**不随时间变动的计划/契约规格**——
**不写入进度、状态、日期注记或变更日志**；一切「做了什么、当前到哪、与计划有何差异」只记在本文件（`CHANGES.md`）。

按此口径，本次**未改动上述文档**（曾短暂写入的状态注记已全部撤回）。因此存在一处**已知的「规格 vs 实现」差异**，在此登记备查：

- `docs/P0骨架设计_双平台.md` §2.6 的 publish 行仍描述「写 `model_publish=queued` → Celery `docker push` → 返回 `{publish_id}`」，
  而 D3 实际实现为**同步**假 build + `fake`/`registry` 双模式 push，应答含 `digest`/`mode`/`stub`（见本文件 §2）；
- `docs/contracts/跨平台契约_A-B.md` §2.4 描述的是 **D7 目标机制**（docker build/push + 指数退避）；D3 的等价实现（Python 构造镜像产物 + Registry v2 直推）
  在**镜像内布局、tag 规范、`model_publish` 字段、digest 语义**上与契约一致，B 侧按契约实现不受影响；
- 新增配置键 `AOI_PUBLISH_MODE` / `AOI_REGISTRY_PROXY` / `AOI_PUBLISH_ARTIFACTS_DIR` 记录在 `.env.example`（带注释）与 `README.md` §3.1；
- 以上差异若需正式并入契约文本，走 **D9/D15 契约变更窗口**（含"四件套"），不在本分支临时改规格文档。

**处置两份 D2 证据文档**（卫生清单 H1/H2，最终走「② 丢弃」）：`docs/复用验证_D2.md`、`docs/已知问题_任务详情500.md` 已从 index 与工作区消失且从未提交，决定**不再恢复**；其内容分别由本文件「缺陷修复（D2）」一节与对应用例/注释承载（如需追溯原文，内容仍可自 git 悬空对象 blob `46bb8e1`（复用验证）/ `6614975`（Concat 500）取回，未被 GC 前有效）。**13 处悬空引用已逐处改写为「结论 + 证据落在代码/测试」**（未只删链接）：

| 位置 | 改写 |
|---|---|
| `docs/README.md` | 阅读顺序表删去第 7/9 行并重排（8 项） |
| `label_studio/aoi/common/settings.py` | docstring 内联 D2 实测结论 + 指向 `TestPrelabelProtocol::test_optional_internal_token` |
| `label_studio/data_manager/managers.py` | 注释内联根因（link name ≤1 时 `Concat` 表达式不足）+ 指向 `TestTaskDetailConcatRegression` |
| `tests/contracts/test_ls_reuse_smoke.py` | 5 处改为内联结论（thumbnail 缺失、UI 人工项、Review 流 skip 依据、LS 只带 User-Agent、批量协议） |
| `tests/contracts/test_platform_a_api.py` | 2 处改为内联根因/实测结论 |
| `tests/contracts/README.md` | UI 人工清单说明改为自包含表述 |
| `tests/contracts/samples.py` + `fixtures/{yolo_export_layout_sample,ml_backend_predict_sample}.json` | `source` 字段去掉文档路径，保留「实测来源」语义（samples 与 fixture 同步改） |
| `docs/D3_工程卫生清单.md` | H1/H2 两行标记「已处置（2026-09-11）」并记录处置方式 |




---

## D3 后修正：digest 必须取仓库回执 + 代理端口去硬编码（2026-09-11）

### 1. 背景：上一轮真推报告的**一处错误结论已更正**

上一轮真推（`90-stub@ds9` / `91-yolo@ds9`）报告中曾写「Docker Hub 对 manifest PUT 不回 `Docker-Content-Digest`，
客户端走的是 `registry_digest or local_digest` 兜底分支」。经复测与代码复核，**该结论是错的**，错因在**取证脚本的日志过滤器**：

- 现象：`tmp/real_publish_run.py` 的探针用固定大小写名单过滤响应头（`{k: v for k, v in response.headers.items() if k in interesting}`），
  而 Docker Hub 回的是**小写**头名 `docker-content-digest`（Python `requests` 头字典是大小写不敏感的，但**手写字典推导不是**），
  于是该头被探针丢掉，日志里只剩 `Content-Length`；
- 真相：`RegistryPushClient.push()` 读的是 `response.headers.get('Docker-Content-Digest')`（**大小写不敏感**），**一直拿到了仓库回执**，
  并没有走兜底分支；
- 复测证据：真实推送的响应头为 `docker-content-digest: sha256:…`，blob PUT 与 manifest PUT 都有；且 `push()` 返回值与仓库回执、落库 digest 三者一致。
- 已修：探针改为大小写不敏感过滤（`tmp/real_publish_run.py`，仅取证脚本，不在版本库）。

**教训**：取证工具的过滤器本身会造假证据；「没看到头」必须先验证是「仓库没发」还是「探针没记」。

### 2. 代码变更：digest 必须来自仓库回执（`label_studio/aoi/training/publish.py`）

| 项 | 变更前 | 变更后 |
|---|---|---|
| manifest 回执 | 有则核对，**没有则静默用本地 sha256**（`return registry_digest or artifacts.digest`） | **没有回执 = 失败**：抛 `RegistryPushError`（发布置 `failed` + 50300），绝不把本地自算值当仓库确认值落库 |
| blob 回执 | 完全不看 | blob PUT 也要求 `Docker-Content-Digest`；缺失或与上传 digest 不一致 → 失败（防篡改） |
| blob「已存在」分支 | `init` 无 `Location` 直接报错 | 允许 Registry v2 的 `201 + 无 Location`（blob 已存在）：**仅当回执 digest 与本地一致**才放行 |
| 退路（可选） | 无 | 新增 `missing_digest_policy`：`strict`（默认，不回执即失败）/ `readback`（PUT 后按 tag GET 回读 manifest、**逐字节比对**通过才认，多一次往返换可用性） |

新增常量 `DIGEST_POLICY_STRICT` / `DIGEST_POLICY_READBACK` / `DIGEST_POLICIES` 与内部助手 `_content_digest()`（大小写不敏感的统一点）。

### 3. 契约测试（`tests/contracts` → **205 passed, 8 skipped**；本轮 +9 例）

新增用例：blob 回执不一致 / blob 回执缺失 / manifest 回执缺失（默认 strict 拒绝）/ `readback` 策略成功 / `readback` 字节不一致拒绝 /
blob 已存在（无 Location）仅回执匹配才放行 / 未知 policy 拒绝 / **跨时刻重建 digest 必须不同（D7 待修事实锁定）** /
仓库不回执时发布落 `failed` 且 `digest` 为空（端到端）。既有 `TestPublishRegistryMode` 的假仓库已抽成 `_mock_registry()` 并按真实语义回回执。

### 4. 真推复验（strict 代码路径，经本机代理）

`93-yolo@ds9` → `POST /publish` → **全 201**，逐跳响应头（`tmp/real_publish_strict.log`）：

```
PUT  …/blobs/uploads/<uuid>?digest=sha256:28e2e54f…  → 201  docker-content-digest: sha256:28e2e54f…  location: …/blobs/sha256:28e2e54f…
PUT  …/blobs/uploads/<uuid>?digest=sha256:78d8f8cf…  → 201  docker-content-digest: sha256:78d8f8cf…  location: …/blobs/sha256:78d8f8cf…
PUT  …/manifests/93-yolo-ds9                          → 201  docker-content-digest: sha256:f73cef98…  oci-tag: 93-yolo-ds9
```

接口应答 `digest=sha256:f73cef98…`（= 仓库回执，不再可能是本地兜底值）、`mode=registry`、`stub=false`；
独立回读校验（`tmp/verify_pushed_image.py`）全项 PASS；DB 现场：`Model` 新增 `92-yolo@ds9`/`93-yolo@ds9`（复核用），
`model_publish` 与临时用户已清理。

### 5. 代理端口去硬编码（项目负责人要求：端口不进业务代码）

| 文件 | 变更 |
|---|---|
| `label_studio/aoi/common/settings.py` | `get_registry_proxy()` docstring 删掉硬编码 `127.0.0.1:7897`，明确「只从 `AOI_REGISTRY_PROXY` 读，端口等地基信息不写进代码」 |
| `label_studio/aoi/training/publish.py` | `push.sh` 模板示例改 `http://127.0.0.1:<proxy-port>` |
| `tests/contracts/test_platform_a_api.py` | 新增 `REGISTRY_PROXY_FOR_TESTS = os.environ.get('TEST_REGISTRY_PROXY', 'http://proxy.invalid:3128')`（`.invalid` 为 RFC 2606 保留域名，绝不误连），3 处引用替换 |
| `.env.example` | 改**假占位** `AOI_REGISTRY_PROXY=http://127.0.0.1:10809`，注明「仅格式占位，并非真实端口」 |
| `.env`（gitignored） | 同步改占位值；实跑时由环境变量 `AOI_REGISTRY_PROXY=http://<host>:<port>` 注入（已验证占位值 10809 连接被拒） |

`git grep 7897` 在 `label_studio/ docs/ tests/ deploy/ *.example` 范围内已为**空**；`docker-compose.yml` 透传沿用 `${AOI_REGISTRY_PROXY:-}`。

### 6. D7 计划项（已写入 `docs/MVP开发计划.md` §5 D7「验收附加项」）

1. **digest 取仓库回执**（本文件 §2 已实现，D7 只做验收）；
2. **digest 可复现**：同 `model_ref` + 同产物内容，任意时刻重建必须同 digest —— 根因是 `model.yaml` 的
   `created_at`（`model_yaml._utcnow()`，秒级）与 `published_at` 参与了 manifest 字节；修法（时间戳移出镜像内 `model.yaml` 或固定为构建批次时间）
   与验收用例（把当前"必须不等"的锁定用例翻转为"必须相等"）均记在该节；
3. 三处口径同步：`publish.py` 模块头措辞、跨平台契约 §2.4 步骤、B 侧 digest 校验。

> **文档纪律例外（备案）**：按本文件 §6 的文档纪律，`docs/MVP开发计划.md` 属"计划规格、不写变更日志"；
> 本次系**项目负责人明确要求**把 D7 待修项写入计划，故以「D7 验收附加项」区块落规格口径（写"必须做到什么"，不写"当前做到哪"）。

### 7. 运维遗留（需人工处置）

- **`rekal1018/aoi-model` 上多出 3 个探测 tag**：`lab-bad-digest-check` / `lab-digest-hdr-check` / `lab-probe-client`
  （本轮为验证 Docker Hub 回执行为所推）。**脚本删不掉**：registry v2 `DELETE /manifests/<tag>` 需要 `delete` scope，
  而当前 PAT（读写）换 `delete` scope 时被拒（`access token has insufficient scopes`），Docker Hub 管理 API 同样返回
  `403 insufficient scope`。请在 Docker Hub 网页端删除，或换一个有删除权限的 token 后执行：
  `DELETE https://registry-1.docker.io/v2/rekal1018/aoi-model/manifests/<tag>`。
- 另有真推留下的 `90-stub-ds9` / `91-yolo-ds9` / `92-yolo-ds9` / `93-yolo-ds9` 四个 tag：按契约"镜像不可变、A 侧软删不动仓库"的口径**保留**，
  供 B 侧拉取联调；如需清理同样需上述删除权限。

---

## 依赖去 git 源 + A 侧 CI 落地（2026-09-11）

### 1. 背景

落 A 侧 CI（`tests/contracts` 挂 GitLab）时发现：根 `pyproject.toml` 的 `label-studio-sdk`
钉在 `git+https://github.com/HumanSignal/label-studio-sdk.git@effb2988`（上游 LS 自带，
随 fork 骨架继承；上游用它未发版的提交，故钉 rev 而非 PyPI 版本）。后果：任何
`uv sync --frozen` 都必须能出网 GitHub——本机直连实测不通（仅 127.0.0.1:7897 代理可用），
内网 runner 能否出网未知，CI 落地的硬阻塞。

另：该包为 LS 运行时依赖（`data_import`/`data_export`/`projects`/`tasks` 等 17 处模块级
import，含 `converter` 导出引擎），不可移除，只能换源。

### 2. 变更

| 文件 | 变更 |
|---|---|
| `pyproject.toml` | `label-studio-sdk` 改版本约束 `>=2.1.1,<3.0.0`；删除 `[tool.uv.sources]` 的 git pin |
| `uv.lock` | 重锁，仅该包变化：`v2.1.3 (effb2988) → v2.1.1`（PyPI registry）；git 源清零 |
| `.gitlab-ci.yml` | **新增**。job `a-contract-tests`：python:3.12-slim + postgres:16 service，`uv sync --frozen --group test` → editable 装两个共享包 → `PYTHONPATH=label_studio` 跑 `tests/contracts`；uv 缓存按 uv.lock 键控；MR 与默认分支触发 |

版本选择说明：钉的 rev 自报 2.1.3（未发版），PyPI 最新 2.1.1（2026-08-10 发布），退两个 patch。

### 3. 验证（换源不改行为）

1. **契约套件（CI 目标）三形态全绿 205 passed / 8 skipped**：常规环境、`MINIO_SKIP=true`、
   `env -i` 白名单环境（只给 PG + `MINIO_SKIP` + `PYTHONPATH`，即 CI job 的精确环境形态）。
2. **SDK 相关面上游子集 A/B**（data_export/data_import/projects/tasks/prediction_validation/tests/sdk）：
   2.1.1 下 230 passed / 10 failed；将 2.1.3（本地 uv git 缓存）装回重跑**同样 10 个失败**——
   证明失败为存量问题（骨架清理剥离 S3/nginx 相关所致），与换版本无关。
3. **源码 diff**：`label_interface/interface.py` 仅 26 行差异且全在报错文案；`control_tags.py`
   差异为新增标签类型（Bitmask/MagicWand/Vector/Timeline，AOI 不使用）。
4. `find_tags('control')`（`cache_labels.py` 的调用形态）在两版本实现逐字相同（单数非合法类别、
   均落"返回全部 tags"兜底）——上游自身用法，行为零变化。

### 4. CI 配方中被实测钉死的细节

- **共享包必须单独 editable 安装**（`aoi_training.models` import `skillname`；不装则上游套件收集即挂）；
- **`MINIO_SKIP=true` 必须显式设置**：`base.py:951` 的 endpoint 缺省 `localhost:9000` 且默认不 skip，
  本地跑绿隐含依赖了常驻 minio 容器，CI 不带 MinIO；
- `psycopg[binary]` 免编译，slim 镜像无需构建链；`tests/contracts` 无需 MinIO/Redis 服务。

### 5. 顺带发现（存量，本次未处理）

- 上游 `make test` 自 9 月 8 日骨架化起不可运行：`label_studio/fsm/tests/conftest.py:27` 引用
  已被清理的 `label_studio.tests.conftest.aws_credentials`，收集即错（绕开 fsm 后另有 10 例存量失败，见 §3.2）；
- 本机默认 uv 缓存 `~/.cache/uv/sdists-v9/.git`（0 字节异常文件）导致 uv 无法初始化缓存，
  本机需 `UV_CACHE_DIR` 指仓库内 `.uv-cache`。

## D4：自研 RBAC 真实化 + LS 原生闸门 + LS 项目模板 + 前端素材更换（2026-09-14）

> 依据 `docs/contracts/平台A_接口与数据契约.md` §2.4/§3.1/§3.1.1/§4.0/§4.1/§10.1/§13.1（本次同步修改）
> 与 `.dsh/D4-D5_B线施工计划_RBAC-LS项目模板-素材更换.md`。**契约先行**：文档先于代码改完。

### 1. RBAC：进程内 stub → `aoi_core` 五表 + 真判定

| 文件 | 说明 |
|---|---|
| `label_studio/aoi/core/models.py` | 4 张 RBAC 表（`role`/`permission`/`role_permission`/`user_role`，复合主键用 Django 5.2 `CompositePrimaryKey`）+ **`authz_state`**（单行授权版本号） |
| `label_studio/aoi/core/migrations/0001_initial.py` | 首条 `CREATE SCHEMA IF NOT EXISTS aoi_core`（沿用其余 aoi app 模式）+ 末条插入 `authz_state(id=1, version=0)` |
| `label_studio/aoi/core/permissions.py` | 权限码表 **38 码**（`ACTIONS` 不扩，新增 6 码进 `EXTRA_PERMISSIONS`：`datasets.delete`/`datasets.config`/`system.storage`/`system.ml`/`system.webhook`/`system.labels`）+ 中文名表 + `DEFAULT_ROLE_MATRIX` + `seed_rbac()` |
| `label_studio/aoi/core/apps.py` | `post_migrate` 播种（**不在 `ready()` 写库**：`ready()` 会在 `check`/`shell`/`collectstatic` 时触发）；失败只告警不阻断 migrate |
| `label_studio/aoi/core/authz.py`（新增） | `current_version`（每请求一次 PK 查询）/ `bump_version` / `resolve_user_perms`（按 `(user_id, version)` 缓存 300s）/ `role_codes_for_user` |
| `label_studio/aoi/common/permissions.py` | `AoiPermission.has_permission` 接真判定；`aoi_permission()` 工厂**未知码导入即失败**（配置期错误）+ 工厂产物缓存（每请求 `get_permissions()` 不再重复 `type()`） |
| `label_studio/aoi/core/views.py` | `/api/core/*` 四端点真实化：`PUT /roles/{id}` 支持 `permissions` **全量覆盖**、`POST /users/{id}/roles` **全量覆盖**、`GET /roles` 带 `permissions`；写操作**同事务 bump 版本号** + 审计 |
| `label_studio/aoi/core/management/commands/aoi_seed_rbac.py`、`aoi_grant_role.py`（新增） | 幂等播种兜底；首个超管引导（全量覆盖 + `--list` + `--clear` + 写审计） |
| `label_studio/aoi/common/audit.py` | H10 最小部分：失败日志 `debug → warning`，`request_id` 截断到列宽 64（超长头会把审计整条吞掉） |
| `tests/contracts/conftest.py` | 删 `reset_aoi_stub_state`（stub 数据已不存在）；新增 `reset_authz_cache`（LocMemCache 跨用例共享，而用例回滚会让版本号与缓存错配）；`test_user` 默认授 `super_admin` |

**播种语义**（契约 §3.1）：权限点全量 upsert；内置三角色矩阵**仅首次创建时**写入（人工调整不被重启回滚）；`super_admin` 每次**只加不减补授**；授权变更**零延迟生效**（版本号每请求读一次，故 `CACHES` 未配置、LocMemCache 多 worker 不共享也正确）。

实测（本机 PG16）：`migrate aoi_core` → 自动播种 `permissions_created=38, roles_created=3, grants_created=63`；`aoi_seed_rbac` 连跑两次均 `+0`；库内 `operator=7 / admin=18 / super_admin=38`。

### 2. LS 原生闸门（契约 §3.1.1，**红线改口**）

- `label_studio/aoi/common/native_gate.py`（新增）：`AoiNativeGatePermission`，**deny-list、默认放行、fail-open**（异常放行 + `warning`），拦 4 类高危写操作 + 1 条权限锚点；命中缺码抛 DRF `PermissionDenied` → 上游 handler 返回 **LS 方言 `{"detail": …}`**（非 aoi 信封）。
- `label_studio/core/settings/base.py`（**注入点 1**）：`DEFAULT_PERMISSION_CLASSES` 首位插入闸门。**红线改口**：原「不改全局 `REST_FRAMEWORK`（权限类是上游语义）」修正为「仅允许在 `DEFAULT_PERMISSION_CLASSES` 首位插入 aoi 闸门类，其余项不得改」。
- 不用 Django 中间件的原因：D3 已移除 `jwt_auth.middleware.JWTAuthenticationMiddleware`，中间件里 `request.user` 只有 session 身份，Bearer/`X-Api-Key` 调用者不可见。

### 3. 施工中发现并修复的既有缺陷：`slash_fallback` 吞掉上游 `/api/auth/export/`

- 现象：`GET /api/auth/export/` 返回 **HTML 404**，上游 `ProjectExportFilesAuthCheck` 自 D3 起**不可达**。
- 根因：`label_studio/aoi/urls.py` 的兜底正则把 `auth` 并进 aoi 前缀通配，`/api/auth/export/` 先命中兜底 → `resolve('/api/auth/export')` 不存在 → `Resolver404`。`resolve()` 命中即终止，上游路由再无机会。
- 修法：兜底前缀**去掉 `auth`**，aoi 的两个 auth 端点（`login`/`logout`）逐个点名。契约测试已加专项断言（`/api/auth/export/` 被闸门拦=`403`，`/api/auth/login|logout` 放行）。

### 4. LS 项目模板（D4 只交模块，真实创建留 D6）

`label_studio/aoi/datasets/ls_project.py`（新增）：`AOI_PROJECT_DEFAULTS` + `project_title/project_description/build_project_kwargs`，字段**全部显式钉死**（`maximum_annotations=1`、`sampling=Project.SEQUENCE`、`skip_queue=Project.SkipQueue.REQUEUE_FOR_OTHERS`、**`enable_empty_annotation=True`**（OK 图负样本）、`color='#FFFFFF'`（不使用品牌色）），取值直接引用上游 `Project` 常量而非硬编码副本；**不含任何 review 设置**。

### 5. 前端素材更换

| 文件 | 类型 | 说明 |
|---|---|---|
| `label_studio/templates/users/new-ui/user_base.html` | **新增覆盖文件** | 位于 `TEMPLATES['DIRS']`（`label_studio/templates/`），DIRS 先于 APP_DIRS → 遮蔽上游同名模板，**上游模板一行未改**。改动 5 处：平台标题、去掉 GA 与外站追踪 iframe、NBHX logo、平台描述、公司署名；登录页营销 tips 改为静态平台提示 |
| `label_studio/aoi/common/static/aoi/NBHX.png` | 新增 | 品牌字标（须落在**已安装 app** 的 `static/` 下，`AppDirectoriesFinder` 才扫得到）；生产由 Dockerfile 的 `collectstatic` 收集 |
| `web/.../src/assets/images/logo.svg` | **新注入点** | LS+HumanSignal 组合 logo → NBHX 字标（位图内嵌，保持 `ReactComponent` 导出与 Menubar 调用点不变） |
| `web/.../src/index.html` | **新注入点** | `<title>Labelstudio</title>` → `AOI 数智检测` |
| `web/.../components/HeidiTips/content.ts` | **新注入点** | 三集合文案中文化（去 Enterprise/Starter Cloud/humansignal 链接） |
| `label_studio/aoi/core/heidi_tips.py`（新增）+ `aoi/urls.py` | aoi 自有文件 | 注册 `heidi-tips/` **遮蔽**上游 GitHub 代理路由，返回平台自有集合 |

**遮蔽路由的三条硬约束**（实测于 `web/.../HeidiTips/utils.ts`）：必须 **200 + 完整集合**（返回 `{}` → `getRandomTip` 返回 `null` → tips 全消失；返回 404 → 前端不更新缓存、**永久沿用旧缓存**）；`link.url` **必须是绝对地址**（`createURL` 内部 `new URL(base)`，相对路径抛错）；集合键名须与 `TipCollectionKey` 一致。

### 6. 验证

- **契约测试**：`tests/contracts/test_platform_a_api.py` **191 passed**（新增 12 组：`TestPermissionCodeRegistry`/`TestRbacMatrix`/`TestRbacForbidden40300`/`TestPermCacheInvalidation`/`TestRoleAdminApi`/`TestGrantRoleCommand`/`TestSeedRbac`/`TestNativeGate`/`TestNativeGateAnnotationFlow`/`TestHeidiTipsRoute`/`TestLoginPageBranding`/`TestLsProjectTemplate`）。
- **A 侧子集**（`tests/contracts` 排除 B 侧模块）：**263 passed / 8 skipped**；余下 4 个失败在 `test_cross_platform.py`，报 `ModuleNotFoundError: No module named 'fastapi'`——A 侧 venv 未装 fastapi（实测确认），该文件需按自身文档用 `infer-platform/backend` 的 venv 跑，**与本次改动无关**。
- **三角色矩阵硬编码断言**：38 码全表 + `operator=7`/`admin=18`/`super_admin=38` 逐码比对（期望值写在测试里，不读实现常量）。
- **前端构建**：`cd web && bun run build` ✅ 23s；产物 `dist/apps/labelstudio/index.html` 标题为 `AOI 数智检测`，bundle 内已含 NBHX 位图与中文 Heidi 文案，且**不再含** `Did you know?`/`Starter Cloud`/`A full-fledged open source`。
- **biome**：改动的 3 个前端文件 check 通过；**ruff**：改动文件 check/format 全绿（`test_pipeline_core.py`/`test_platform_b_api.py` 有 3 处**存量** lint 漂移，非本次引入，未顺手改）。
- **迁移**：`migrate aoi_core` 在干净库建出 5 表；`sqlmigrate` 含 `CREATE SCHEMA`；`aoi_seed_rbac` 幂等。

### 7. 残留项与未做项（需人工决策）

| # | 项 | 说明 |
|---|---|---|
| R1 | favicon 未替换 | `NBHX.png` 是 161×32 横版字标，直接当 32×32 favicon 会严重变形；等 32×32/64×64 图标 |
| R2 | 登录页右下角装饰图形 | `core/static/images/login-bg.svg` 仍是上游品牌色（抽象几何，无 logo/文字）。如需中性化：在 `label_studio/static/images/` 放同路径覆盖文件（`FileSystemFinder` 优先） |
| R3 | 注册页残留文案 | `users/new-ui/user_signup.html:47` 有 `How did you hear about Label Studio?`；本轮只覆盖登录页，未 fork 注册页模板 |
| R4 | 暗色主题下 logo 对比度 | NBHX 为红黑字标 + 透明底，Menubar 暗色主题下深色笔画可能不可见，需目视确认 |
| R5 | `web/libs/editor/public/images/{logo,ls_logo}.*` | 三个未被代码引用的静态文件（`Choices.jsx:61` 仅注释示例），未清理 |
| R6 | H9（`Idempotency-Key` CAS 表） | 卫生清单标 D4 但**非本轮三件事**，未做，建议单独排期 |
| R7 | H23（Menubar 按 `perms` 显隐） | 本轮未做（计划里为第一个可砍项），仍属 D4~D7 |
| R8 | 构建副作用 | `bun run build` 会覆写 `label_studio/core/static/js/sw.js` 并生成 `sw.js.map`（红线目录内的文件）；已 `git checkout` 回退并删除产物，**后续构建后需复查** |

## D5：组织管理页（仅超管）+ 屏蔽 LS 原生组织页 + SPA 深链修复（2026-09-15）

> 依据 `docs/contracts/平台A_接口与数据契约.md` §2.2/§3.1/§4.0/§13.1/§14（本次同步修改）与
> `.dsh/新需求_组织管理页面_交接.md`。裁定：删除=**停用组合拳**；新用户走登录页自助注册
> （`DISABLE_SIGNUP_WITHOUT_LINK=False`，不做邀请）；独立菜单项；超管唯一且固定账号；
> 原生组织页**彻底摘除**；H22/H23 一并结项。

### 1. 后端（`aoi/core` + `aoi/pages`，权限点沿用 `system.users`，未扩码表）

| 文件 | 说明 |
|---|---|
| `label_studio/aoi/core/views.py` | 新增 3 视图：`GET /api/core/users`（分页列表，每项 `{id, email, is_active, roles}`）、`POST .../deactivate`（停用组合拳）、`POST .../activate`（恢复账号与成员关系，角色不回补）；`UserRolesView` 增加最后超管守卫 |
| `label_studio/aoi/core/urls.py` | +3 路由 |
| `label_studio/aoi/core/bootstrap.py`（新增） | 固定超管 `superadmin@nbhx.com` 幂等播种：按 LS 注册链路接线（`username` 取邮箱前缀 + `OrganizationMember` + `active_organization`，无组织则创建）+ 补授 `super_admin`；已存在不重置密码 |
| `label_studio/aoi/core/apps.py`、`aoi_seed_rbac.py` | `post_migrate` 与兜底命令在 `seed_rbac()` 后追加 `ensure_bootstrap_super_admin()` |
| `label_studio/aoi/pages.py`（新增）+ `aoi/urls.py` | 点名注册 5 个 SPA 页面路由（`datasets\|training\|review\|system\|organization-admin`，带可选尾斜杠）→ `@login_required` 壳模板视图（H22） |
| `label_studio/templates/aoi/page.html`（新增） | 壳模板（`extends base.html`，形态同 `projects/list.html`）；落在 `TEMPLATES['DIRS']`，上游零改动 |

**停用语义**（契约 §3.1）：`is_active=False`（已签发 JWT 立即失效）+ 清空 aoi 角色（同事务 `bump_version`）+ 全部 `OrganizationMember.deleted_at` 置当前时间（`active_organization` 镜像上游成员软删行为）。**硬删不做**：`htx_user` 35 个 FK 全 `NO ACTION`，ORM 级联会连带删项目/标注。

**最后超管守卫**：`deactivate` 与 `POST users/{id}/roles` 两路都拦——任何变更导致活跃超管（`is_active=True` 且持 `super_admin`）归零 → `40900`。

**SPA 路由不用泛 catch-all**：`aoi.urls` 在 `core/urls.py` 第 60 行**无前缀** include，其后还有 30+ 条上游路由（`admin/`、`docs/`、`heidi-tips/` 等），泛 `^.*$` 会全部吞掉；故逐个点名。`/organization/` 上游遗留路由（旧 Vue 模板）不动——上游只读。

### 2. 前端（`web/apps/labelstudio/src`）

| 文件 | 类型 | 说明 |
|---|---|---|
| `aoi/usePerms.ts`（新增） | aoi 自有 | **前端首条 aoi API 调用**：react-query 缓存 `GET /api/core/permissions`，`usePerms()` → `{perms, has}`；失败视为无权限（fail-closed）；后续页面复用此模式 |
| `pages/OrganizationAdmin/OrganizationAdminPage.jsx`（新增） | aoi 自有 | 用户表（邮箱/状态/角色）+ 设为/取消 `admin`、设为/取消 `operator`（全量覆盖语义，前端读现有角色增删后提交）+ 禁用/启用（`confirm` 二次确认）；`super_admin` 持有者行不提供任免按钮（守卫后端兜底） |
| `components/Menubar/Menubar.jsx` | **注入点 3** | 删除原生「Organization」入口；5 个 aoi 入口按 `perms` 显隐：`datasets.view`/`training.view`/`review.view`/`system.view`/`system.users`（H23 结项） |
| `pages/index.js` | **注入点 4** | 摘除 `OrganizationPage` 注册（`/organization` SPA 路由消失，超管也不可达）；新增 `OrganizationAdminPage`；`ModelsPage` 及 `Organization/` 目录文件保留（`HomePage` 仍引用其 `InviteLink`、`ModelsPage` 独立注册） |

SPA 调用鉴权：session cookie（DRF `SessionAuthentication`）；CSRF 由上游 `core.middleware.DisableCSRF` 对 API 请求豁免（`?enforce_csrf_checks` 可强制）。

### 3. 测试与夹具

- `tests/contracts/fixtures/aoi_api_paths.json`：+3 路径（`GET /api/core/users`、`POST /api/core/users/{id}/deactivate|activate`），版本 `d5-20260915`。
- `tests/contracts/test_platform_a_api.py`：新增 `TestUserAdminApi` / `TestLastSuperAdminGuard` / `TestBootstrapSuperAdmin` / `TestAoiSpaPages`（见契约 §13.1）。

### 4. 卫生清单结项

- **H22**（SPA 深链 404）：点名路由落地，契约 §2.2 已回写。
- **H23**（Menubar 无权限门控）：`usePerms` + 5 入口显隐落地。

## 开发环境：前端构建组合目标（2026-09-14）

故障现象：改前端后重新 build，登录后页面 JS/CSS 全部 400（请求 `/react-app/main-sCLm4fB-.js` 等旧 hash）。根因：Django 运行时只读 `STATIC_ROOT/js/manifest.json`（`label_studio/core/static_build/`，由 collectstatic 生成），不读 `web/dist` 里的 manifest；只 build 不 collectstatic → 服务端继续引用上一次构建的 hash，而旧 hash 文件已被新构建覆盖清除。缺失文件本应 404，但 `static_serve.py` 剥 `/react-app` 前缀后残留前导 `/`，`safe_join` 抛 `SuspiciousFileOperation` → 400（上游 bug，暂不改）。

处理：Makefile 新增 `frontend-build-collect`（= `frontend-build` + `collectstatic --noinput`），宿主机开发侧一条命令出齐两份产物；Dockerfile 构建链本就 build→collectstatic 顺序执行，无需改。注意 manifest 在进程启动时一次性加载（`manifest_assets.py` 模块级 `_MANIFEST`），collectstatic 后仍需重启后端。

## D5 收尾：导入包裹（Celery 异步 + 复用 LS 上传）+ 标注项目创建提前 + A 侧「数据集」页（2026-09-20）

> 依据 `docs/contracts/平台A_接口与数据契约.md` §3.2/§4.1/§5.2（本次同步修改）与
> `.dsh/D5_B线施工计划_缺陷字典收尾-导入包裹-数据集页.md`。三项裁定：① 导入走 Celery+Redis 异步；
> ② 完整复用 LS 上传（导入必须带 `dataset_id` 且已有 LS 项目），标注项目创建自 D6 提前；
> ③「数据集」页三块全做（字典/图片/数据集）。

### 1. 后端（`aoi/datasets` + Celery 基建）

| 文件 | 说明 |
|---|---|
| `label_studio/aoi/celery.py`（新增）、`aoi/__init__.py` | `Celery('aoi')` + `config_from_object(django.conf:settings, namespace='CELERY')` + `autodiscover_tasks()`；包导入期绑定 `celery_app`（`@shared_task`/`.delay()` 解析到 aoi app）；celery.py 不在导入期触碰 ORM |
| `label_studio/core/settings/base.py` | AOI 注入点：`CELERY_BROKER_URL`（默认 `redis://localhost:6379/1`，与 LS django_rq 的 DB 0 隔离）、`CELERY_TASK_ALWAYS_EAGER`（env，默认 False）、`CELERY_TASK_EAGER_PROPAGATES=True`、`CELERY_TASK_ROUTES={'aoi.*': {'queue': 'default'}}`、`broker_connection_retry_on_startup` |
| `label_studio/aoi/datasets/models.py` + `migrations/0004_import_job.py` | 新表 `aoi_datasets.import_job`（`job_id` uuid12 UNIQUE、`status` queued/running/succeeded/failed、`total/ok/dup/bad`、`bad_items` JSONB、`file_upload_ids` JSONB、`source/station_code/dataset_id/created_by`、`created_at/finished_at/error_message`） |
| `label_studio/aoi/datasets/views.py` | ① `POST /api/datasets` 重写：`name` 必填；携带 `ls_project_id` → `42200`；无已发布字典版本 → `42200`；服务端按最新快照还原 defects → `build_project_kwargs` → `Project.objects.create(organization, created_by)` → `Dataset` 落库 + 审计 `datasets.create`；② `DatasetDetailView.put`：`ls_project_id` 移出 `_EDITABLE`，客户端传入 → `42200`；③ `ImportCreateView.post` 重写：multipart `files[]`（兼容 `files`/`file`）+ `dataset_id`（数字/字符串皆收，multipart 表单是字符串）/`source`（白名单 `manual_real`，其它 → `42200`）/`station_code`；校验 dataset 40401、无 LS 项目 42200、空文件 42200；逐文件预检（扩展名 ∉ {.jpg,.jpeg,.png,.bmp} → `unsupported_extension`；>100MB → `too_large`，坏文件不上传，部分成功语义）；合法文件 `data_import.uploader.create_file_upload` 复用 LS 上传 → 建 `ImportJob(queued)` → `process_import_job.delay`；broker 异常 → `50300`；④ `ImportDetailView.get`：查真实任务表，未知 `job_id` → `40401`（`_IMPORT_JOBS` stub 删除）；⑤ 字典权限澄清：`POST /defects` = `datasets.create` |
| `label_studio/aoi/datasets/tasks.py`（新增） | `@shared_task process_import_job`：job → running；逐 FileUpload 读字节 → md5 全局去重（命中 → `dup`，不建任务、FileUpload 字节保留）→ PIL 解码（失败 → 登记 `Image(qc_status='rejected', qc_reason='decode_failed')` + `bad`）→ 成功登记 `Image(object_key=LS 上传路径, qc ok)` + 收集任务数据；批量建 LS 任务**镜像上游 `async_import_background`**（事务内 `ProjectSummary.select_for_update` + `ImportApiSerializer.save(project_id)` + `update_tasks_counters_and_task_states` + `update_data_columns`；不 emit webhook）；终态 `succeeded`（counts+bad_items）/`failed`（error_message），任务异常不外抛；审计 `datasets.import` |
| `label_studio/aoi/datasets/serializers.py` | + `serialize_import_job`（`{job_id, status, total, ok, dup, bad, bad_items, ...}`） |
| `pyproject.toml` + `uv.lock` | + `celery[redis]>=5.4`（celery 5.6.3；redis-py 5.2.1 满足 extra，无需新装） |

**导入语义**（契约 §4.1）：`object_key` 两态——B 回传=`images/{md5}.jpg`，A 导入=LS 上传路径 `upload/{project}/{uuid8}-{filename}`；md5 **全局**去重（同图不进第二个数据集/项目）；dup/bad 文件的 FileUpload 字节保留不清理（已知残留行为）；bad_items 还原用户原始文件名（剥掉上游 `{uuid8}-` 前缀）。

### 2. 前端（`web/apps/labelstudio/src`，aoi 自有文件，上游零改动）

| 文件 | 说明 |
|---|---|
| `aoi/api.ts` | `body instanceof FormData` 时不设 `Content-Type`（浏览器自动带 multipart boundary） |
| `pages/Datasets/DatasetsPage.jsx` | 占位页 → 三 tab 骨架（缺陷字典/图片/数据集），入口门控 `datasets.view`；路由/菜单沿用既有注册（`pages/index.js`、Menubar 不动） |
| `pages/Datasets/DefectsPanel.jsx`（新增） | 字典列表（code/中文名/风险档/别称/启停）+ 新增/编辑（code 编辑只读）+ 停用/启用（`datasets.update` 显隐）+「发布字典」（`datasets.publish` 显隐）→ 展示 `version` + label config XML `<pre>` 预览 |
| `pages/Datasets/ImagesPanel.jsx`（新增） | 导入表单（数据集下拉 + `InputFile` multiple `accept=image/*` + source 固定 `manual_real` + 工位可选）→ `POST /api/datasets/import`(FormData) → `refetchInterval` 轮询 `GET /import/{job_id}` 至终态（react-query v4 回调签名 `refetchInterval(data)`）→ 展示 ok/dup/bad 与 bad_items 明细；图片列表（来源/工位筛选 + 前端分页）+ 下载（`GET /images/{id}/download` → 打开 `url`） |
| `pages/Datasets/DatasetsPanel.jsx`（新增） | 数据集列表（name/cur_version/ls_project_id 外链 `/projects/{id}/data`）+ 新建（`POST {name}`，`datasets.create`）+「新建草稿版本」（`POST /{id}/versions`，confirm 二次确认） |
| `aoi/uiTokens.jsx`（新增）+ 四文件样式重构 | UI 与 LS 原生对齐：页面壳（`--header-height` 同高 + `bg-neutral-background`）、分段式 tab、卡片化表格（inset 表头 + 行 hover）、语义徽章（风险档 低/中/高 → positive/primary/negative，质检/版本/来源同法）、发布预览 `<pre>` 换 token 底色。**全部 Tailwind 语义 token（`@humansignal/ui` tokens.js → tailwind colors），零写死色值——`html[data-color-scheme="dark"]` 翻转 token 即自动暗色兼容**；加载态用原生 `Spinner`，错误态走 negative token；构建产物已验证 token 类全部生成，collectstatic 已刷新 |

### 3. 部署与环境

| 文件 | 说明 |
|---|---|
| `docker-compose.yml` | + `redis`（redis:7-alpine）与 `worker` 服务（`celery -A aoi worker --queues=default --loglevel=info`，depends_on db/redis，`restart: unless-stopped`）；app/worker 均 + `CELERY_BROKER_URL`（compose 内默认 `redis://redis:6379/1`） |
| `.env.example` / `.env`、`Makefile`、`README.md` | + `CELERY_BROKER_URL`（宿主机默认 `redis://localhost:6379/1`）；README 启动段补「图片导入需要 Redis + worker」说明 |

**worker 启动收口（三条路径都无需手动单独起 worker）**：

- **宿主机裸跑开发（首选）**：`uv run python label_studio/manage.py runserver` **默认自动带起** aoi Celery worker——实现于 `aoi/core/dev_worker.py`，挂点为 `AoiCoreConfig.ready()` 的 `RUN_MAIN` 守卫（仅 runserver 的 autoreload 子进程有该变量，migrate/check/shell/测试/uwsgi 均零影响，与 D6「不在 ready() 做无守卫副作用」约束相容）；Ctrl+C（同进程组 SIGINT）与文件热重载（SIGTERM→sys.exit→atexit）都会一并退出/重建 worker。两个开关：`AOI_AUTOSTART_CELERY=false` 关闭（想单独看 worker 日志）、`CELERY_TASK_ALWAYS_EAGER=true` 时自动跳过。两个关键坑已修复并留注释：PYTHONPATH 必须用 `Path(__file__)` 自定位 label_studio/（`settings.BASE_DIR` 是 label_studio/core，不含 aoi 包）；celery 子进程 env 必须 pop 掉 `RUN_MAIN`，否则 worker 自身 django.setup() 会递归拉起 worker（fork 风暴，冒烟实测 15 秒繁殖到 5 个）。第三个坑：autoreload 模式下 runserver 在线程里起服务，**启动失败**（端口占用等）时 Django 用 `os._exit(1)` 退出——`os._exit` 跳过 atexit，仅靠父进程 atexit 会孤儿化 worker（冒烟复现）——修复为 worker 子进程挂 `PR_SET_PDEATHSIG`（`preexec_fn` + libc.prctl，内核保证随父进程死亡递送 SIGTERM，含 fork/prctl 竞态窗口的自检），与 atexit 双保险；实测端口占用路径 worker 零残留，热重载路径 worker 正常重建；
- **docker-compose（部署口径）**：`worker` 服务随 `docker-compose up` 自动启动（`restart: unless-stopped`），与 app/db/redis 同栈；
- **备选**：`make run-dev` = `make -j2 run-django run-celery` 并发拉起（`run-django`/`run-celery` 为仅 Django/仅 worker 的单进程调试入口，后者 `--pool=solo`）；临时无 Redis/worker 的调试可 `CELERY_TASK_ALWAYS_EAGER=true` 同步执行任务（与契约测试同一开关；生产禁用）。

### 4. 测试与文档

- `tests/contracts/conftest.py`：+ autouse `force_celery_eager`（`CELERY_TASK_ALWAYS_EAGER/EAGER_PROPAGATES=True`，对齐 `force_fake_publish_mode` 写法；导入任务在请求内同步完成）。
- `tests/contracts/test_platform_a_api.py`：+ `TestDatasetProjectCreation`（POST 建 LS 项目逐字段断言：label_config=快照渲染、`maximum_annotations=1`、`enable_empty_annotation=True`、`color=#FFFFFF`、title=name、description 含 dict_version、组织归属、审计；未发布字典/携带 `ls_project_id`/PUT 改 `ls_project_id` → `42200`）、`TestImportPackage`（eager 导入成功→Image 登记 object_key=upload 路径+LS 任务数=ok；同文件重传→`dup` 且不建新任务；坏字节→`decode_failed`+rejected 登记；`.txt`→`unsupported_extension`；未知 job→`40401`；缺 dataset_id/无项目/未知 source/空文件→`42200`；无角色→`40300`）、`TestDefectPermMapping`（锚点 + 方法解析 + operator 行为）、`TestCeleryWiring`（app 可导入、任务名 `aoi.*` 命中 `default` 队列路由、broker 与 RQ DB 0 隔离）；`test_all_aoi_endpoints_return_200` + `_seed_import_surface` 种子（字典版本+数据集+LS 项目）与 import multipart / 未知 job 40401 分支；`test_idempotency_key_accepted` 补字典种子。
- 契约文档：§3.2（+`import_job` 表、`image.object_key` 两态注释）、§4.1（import/datasets/defects 行重写、模板说明更新）、§5.2（Celery 落地口径）；`docs/MVP开发计划.md` D5 行勾选 + D6 行标注「标注项目创建已提前至 D5 完成」。`tests/contracts/fixtures/aoi_api_paths.json` **不变**（无新增端点）。

### 5. 已知残留（登记）

- dup/bad 文件已上传的 FileUpload 字节保留不清理（P3 卫生项）。
- 缩略图与 B 回传图（`images/{md5}.jpg`）预签名下载不在本轮（随 D6 ingest-MinIO 评估）。
- `annotation-stats` 仍为 stub；`training`/`publish` Celery 队列仅留在契约，不配路由占位。
- md5 为**全局**去重语义：同图不进第二个数据集/LS 项目（计 `dup`）。

## D5 收尾实测修复：停用缺陷 / 未发布字典先建数据集 / 标注页图片 ERR_LOADING_HTTP / 草稿版本反馈 / 图片与数据集删除（2026-09-20）

> A 侧实测反馈 4 个缺陷，全部定位为 D5 收尾引入或暴露的问题；每项附根因与修复，契约 §4.1 已同步。

### 1. 新增缺陷无法停用（PUT 全量校验误伤启停开关）

- **根因**：前端「停用/启用」发 `PUT /defects {code, active}`，而后端 `put` 走 POST 的全量校验 `_validate_defect_payload`（`name_cn`/`risk_level` 必填）→ 恒 `42200`。
- **修复**（`aoi/datasets/views.py`）：新增 `_validate_defect_patch`，`PUT` 改为**部分更新语义**——只校验/更新携带字段，未携带字段保持原值；`code` 仅用于定位不可改。POST 仍全量必填（门禁不变）；全量 PUT 兼容（契约测试 `test_put_full_payload_still_works`）。

### 2. 无法测试「未发布字典先建数据集」

- **根因**：`POST /api/datasets` 硬性要求已存在 `defect_dict_version`，无 → `42200`，D5 把标注项目创建提前后该前置卡死了引导流程。
- **修复**（`aoi/datasets/views.py`）：无任何已发布版本时**回退当前启用缺陷（`active=True`，按 code 排序）以 `draft` 语义渲染 label config 建项目**（项目描述/审计 `dict_version=draft` 可追溯）；连启用缺陷都没有仍 `42200`（原有用例口径不变）。已发布版本存在时行为不变（优先快照，测试锚定）。

### 3. 标注页 4 张图全部 ERR_LOADING_HTTP（并非跨域）

- **根因**：`tasks.py::_image_value` 云存储分支沿用上游口径落**裸存储对象键**（`upload/<project>/<uuid8>-<file>`）进任务 `data.image`；LSF 把它按**相对路径**解析 → 404 → 四张图全挂（文件本身在 MinIO 里完好）。另发现本部署 `HOSTNAME` 未配时 `AWS_S3_CUSTOM_DOMAIN='/data'`、`file.url` 形如 `https:////data/...` 也不可用。
- **修复**：① `tasks.py`：云存储分支改为拼 `MEDIA_URL`（`/data/`）前缀的**同源 URL**——本部署 MinIO 走 LS `/data/` 鉴权代理（`AWS_QUERYSTRING_AUTH=False`），与本地模式同一条 `UploadedFileResponse` 路由，session cookie 同源加载，天然无跨域；② 新增数据迁移 `0005_fix_ls_task_image_url`：把「值与 `FileUpload.file` 精确匹配且非绝对 URL」的存量任务改写为同源 URL（迁移期依赖 `tasks`/`data_import` 节点注册历史模型）；③ 任务删除路径按「精确 + 后缀」两种形态匹配 `data.image`，兼容存量。
- **第二轮补刀（用户复测仍报 `https:///data/...`）**：上面只修了「任务 data 落库值」，但标注页读任务时 `resolve_uri` 默认开启，`Task.resolve_uris`（tasks/models.py）会剥掉 `/data/` 前缀匹配 `FileUpload` 后用 **`file_upload.url` 重写任务 data**——而 `S3Boto3Storage.url` 拼 `{protocol}//{custom_domain}/{key}`，本部署 `HOSTNAME` 为空 → `custom_domain='/data'` → 拼出空主机绝对地址 `https:///data/upload/...`，读期重写又把坏 URL 塞回任务。修复：新增 `aoi/common/storage.py::SameOriginS3Boto3Storage`（仅接管 `upload/` 对象键的 `url()` → `{MEDIA_URL}{key}` 相对路径，其余媒体名回退上游），注入点 `core/settings/base.py` MinIO 块把默认后端切到它；实测 `GET /api/tasks/{id}` 与 `/data/upload/...` 取图均恢复正常，契约测试补「`file_upload.url` 必须是同源相对路径」断言。

### 4. 新建草稿版本「无反应」

- **根因**：创建实际成功（DB 有 1.0.0~1.0.3），但前端成功后只静默 invalidate——无 toast，列表也不显示版本，用户感知即「无反应」。
- **修复**：后端 `serialize_dataset` 增加 `versions:[{id,version,status,phase}]` 投影（`dataset_id` 非 FK 无法 prefetch，列表量级小逐行一查）；前端 `DatasetsPanel` 成功 toast（`草稿版本 x.y.z 已创建`）+ 新增「版本」列即时可见。

### 5. 图片、图集没有删除功能

- **后端**：① 新增 `GET/DELETE /api/datasets/images/{id}`（`DELETE`=`datasets.update`；未知 id → `40401`）：删图片登记 + LS 任务（镜像上游 Data Manager `delete_tasks` 路径：`async_project_summary_recalculation` + `update_tasks_states`）+ 存储字节（`FileUpload.file.delete`，异常仅告警）+ `dataset_item`；② `DELETE /api/datasets/{id}` 由「只删登记行」改为**级联清理**：LS 项目（含任务/标注，镜像上游 `perform_destroy` 断信号）、项目内导入图片（`upload/{project_id}/` 前缀）、dup/bad 残留 FileUpload 字节、版本与 `dataset_item`；B 线回传图（`images/{md5}.jpg`）登记行保留。均写审计（`datasets.image.delete` / `datasets.delete`）。
- **前端**：`ImagesPanel` 行级「删除」（confirm 二次确认，`datasets.update` 显隐）；`DatasetsPanel` 行级「删除」（confirm 文案明确不可恢复，成功 toast）。
- **fixture/契约**：`aoi_api_paths.json` 增 `GET/DELETE /api/datasets/images/{id}`（version `d5-20260920-2`）；§4.1 三行同步；新增契约测试 `TestDefectPatchUpdate`（4）、`TestDatasetDraftDictionaryFallback`（3）、`TestImageDelete`（3）、`TestDatasetDeleteCascade`（2），导入用例补「任务 image 必须是 `/data/` 同源 URL」断言。`tests/contracts/test_platform_a_api.py` 全量 248 通过。

### 6. 回归过程中发现并顺带修复：导入结果计数虚增（真实 API 实测暴露）

- **现象**：混合批次（1 好图 + 1 个 `.txt` 预检拒绝）导入成功后 `ok=1, dup=2`，而图片因 md5 全局去重并未登记——ok/dup 被预检 bad 数虚增。
- **根因**：`tasks.py::process_import_job` 的 `ok = dup = bad = job.bad` 链式赋值把预检拒绝数同时灌进 `ok`/`dup` 初值。
- **修复**：拆开初值——`ok=0; dup=0; bad=job.bad`（预检拒绝只进 bad）。

## D5 收尾第二轮：缺陷字典发布历史 / 标注页中文名 / 缺陷 code 方案评估（2026-09-21）

### 1. 缺陷字典发布历史不可见

- **根因**：`DefectDictVersion` 每次发布都在写（dev 库已有 4 版），但**没有任何读接口**，前端发布后只拿到当次 `{version, label_config}`，刷新即失——无法回答「当前项目用的哪一版、谁在什么时候改了什么」。
- **后端**：新增 `GET /api/datasets/defects/versions`（`datasets.view`，契约 §4.1）：最新在前，条目 `{id, version, published_by, published_by_name, published_at, defect_count, labels:[{code,index,color,name_cn,risk_level}], is_latest}`；`serialize_defect_version` 落 `aoi/datasets/serializers.py`；发布人在 `views._publisher_names` 批量解析（邮箱优先）。
- **前端**：`DefectsPanel` 新增「发布历史」区：版本/发布时间/发布人/缺陷数 + 「查看快照」行内展开（索引、code、中文名、色块），最新版打标；发布成功后自动刷新历史 + toast。

### 2. 打标签时显示编号而非中文名

- **根因**：`render_label_config` 只渲染 `<Label value="{code}"/>`，标注页只能显示 code；且发布快照只存 `{index,color}`，中文名在建项目/重同步链路上丢失。
- **修复（value/展示名分离）**：
  - label config 改为 `<Label value="{code}" html="{name_cn}" background="…"/>`——`value` 仍是 code（标注结果、导出、`classes.txt`、`model.yaml`、B 侧契约完全不变），`html` 只影响按钮/区域文本（LSF 原生 `Label.html`）。
  - **明确不用 `alias`**：LSF `SelectedModel.selectedValues()` 是 `alias ? alias : value`，设 alias 会把标注结果值写成中文名，直接破坏 code 契约（已实测确认）。
  - 快照补 `name_cn`/`risk_level`；`label_config.defects_from_snapshot` 对旧快照（无 name_cn）回退查当前字典补展示名——存量 4 个版本无需重建。
  - 发布时把新 label config **回写到已建 AOI 标注项目**（`views._sync_dataset_projects`，`value` 不变故已有标注仍合法），响应带 `projects_synced`；老数据集点一次「发布字典」即生效。
  - **注入点 #5**（新增，登记于本文件顶部注入点清单）：`web/libs/editor/src/mixins/SelectedModel.js` 加 `getSelectedDisplayString()`（展示名优先 `html`）、`mixins/AreaMixin.js::getLabelText` 与 `components/SidePanels/OutlinerPanel/RegionLabel.tsx` 改用它——否则标签按钮显示中文、而画布框标签和右侧区域列表仍显示 code。三处都只改**展示**，结果值仍走 `selectedValues()`。
- **前端**：发布结果卡片文案改为「已同步 N 个标注项目」，label config 预览提示 `value=code / html=中文名`。
- **测试**：golden fixture `label_config_expected.xml` 重新生成（含 `html`），新增 `test_html_display_name_is_separate_from_result_value`、`test_defects_from_snapshot_falls_back_to_dictionary`、`TestDefectPublishHistory`（4）。

### 3. fixture 生成器与文件不同步（本轮暴露并修掉）

- **现象**：跑 `tests/contracts/make_fixtures.py` 会把 `aoi_api_paths.json` 覆盖回 `d2-20260909` 基线，丢掉 D5 的 7 条路径（`/api/auth/login|logout`、`/api/core/users*`、`GET|DELETE /api/datasets/images/{id}`），且把 1 空格缩进重排成 2 空格。
- **根因**：`samples.py::aoi_api_paths()` 才是生成源，但历史上只手工改了 fixture，生成器停在 d2。
- **修复**：把 7 条缺失路径 + 本轮新增的 `GET /api/datasets/defects/versions` 补进 `samples.py`，版本升 `d5-20260921-1`；`make_fixtures.py` 对该文件改用 `indent=1`（与仓库既有风格一致，消除全文件重排）。复跑生成后 fixture 与 OpenAPI aoi 路径集合**完全一致**（47 == 47，方法集合无差异）。

### 4. 缺陷 code 方案（`object_fault_type_XX`）影响面评估

- **结论**：**契约级、非局部改动**——见下方「缺陷 code 放宽方案」小节（待产品确认目标格式后实施）。当前未改动任何 code 相关逻辑。

### 5. 缺陷 code 放宽为 `<object>_<fault_type>_NN`（产品确认方案 A：超集，存量零迁移）

- **背景**：原正则把模板占位符当字面量写死：`^object_fault_type_(0[1-9]|[1-9][0-9])$`，实际语义应是 `<object>_<fault_type>` **两段可变英文词** + 两位编号。
- **改动**：`packages/skillname/skillname/codes.py`
  - 正则 → `^[a-z][a-z0-9_]{0,27}_(?:0[1-9]|[1-9][0-9])$`（ASCII；`00` 仍非法；前缀≤28 ⇒ 总长≤31，落在 `defect_class.code VARCHAR(32)` 内）；新增 `FAULT_CODE_PREFIX_MAX_LENGTH` / `FAULT_CODE_MAX_LENGTH` / `FAULT_CODE_DEFAULT_PREFIX` 并导出。
  - `format_fault_code(index, prefix='object_fault_type')` 支持前缀（缺省保持历史输出，向后兼容）；`fault_code_index()` 文档澄清它取的是 **code 自身编号，不是类别索引**。
  - 超集性质：`object_fault_type_11` 等历史 code 仍合法 ⇒ 字典、已发布快照、LS label config、已有标注、`model.yaml`、B 侧 `b_defect_class` **全部无需迁移**。
- **排序假设修正**：`views.py` 三处 `DefectClass.objects...order_by('code')` 改为 `order_by('id')`——前缀可变后字典序不再等于「字典构建顺序」，而发布时默认 `index`（=列表位置）与调色板分配依赖这个顺序；id 序与 `training/publish.py` 的取数顺序一致，且新增条目追加在末尾、不扰动既有 index/颜色。
- **前端**：`DefectsPanel` 表单提示改为 `code（<对象>_<缺陷类型>_NN，如 panel_scratch_01）`，placeholder 同步。
- **文档/测试**：契约 §2.1 词表 + §4.1 DDL 注释、B 契约 DDL 注释、`docs/双平台架构与拆分方案.md` 伪代码、`docs/P0骨架设计_双平台.md`、`docs/设计_预标三桶复审流程.md`、`docs/README.md`、`packages/skillname/README.md`、`tests/contracts/README.md` 全量同步；`test_skillname.py` 增可变前缀正/负例与 `format_fault_code(prefix=…)`，`test_platform_a_api.py` 增 `test_defect_accepts_variable_prefix_code`（含发布 XML `value=panel_scratch_07 html=面板划伤`）与 `test_defect_rejects_malformed_variable_prefix`。
