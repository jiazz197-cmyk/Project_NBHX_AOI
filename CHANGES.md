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
