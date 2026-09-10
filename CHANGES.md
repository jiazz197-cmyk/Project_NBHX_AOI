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
- **记录**：`docs/已知问题_任务详情500.md`、`docs/复用验证_D2.md` §2.9。

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
