# `tests/contracts/` — 双平台契约测试（B 归属部分）

> D2 冻结基线：平台 A 契约测试 + fixtures。消费方写用例、维护方 CI 跑；**红则阻断合并**（计划 T2.8）。

## 目录

| 文件 | 说明 |
|---|---|
| `conftest.py` | Django/DRF fixtures、`jpeg_bytes`、`auth_client`、测试账号常量（`TEST_USER_EMAIL`/`TEST_USER_PASSWORD`）、`aoi.core` 进程内状态重置（含 `_NEXT_ROLE_ID`）、**发布模式强制 fake + 关闭产物落盘**（`force_fake_publish_mode`，避免本地 `.env` 开 registry 时联网推仓库 / 测试写仓库工作区） |
| `test_skillname.py` | T1.2 `packages/skillname`：枚举/code 正则（ASCII 01~99）/`model_ref`（ASCII）/镜像 tag |
| `test_pipeline_core.py` | D1 `packages/pipeline-core`：切片/坐标转换/NMS 合并（按 object_code）/三档判定（宁错不漏）/`load_config` 校验/`run` 缺模型必错/`StubRuntimeModel`；与 C 侧 fixtures 互相锁定 |
| `test_platform_a_api.py` | T2.2–T2.5/T2.9 + P0/P1 回归 + D3 认证与发布：信封/鉴权/全量 stub 200/OpenAPI 基线/label config golden/model.yaml/预标协议/ingest 幂等与半写补建/发布与复审状态机/权限锚点；`TestAoiJwtAuth` 16 例覆盖真实 JWT 链路（登录→Bearer 打 aoi 与 LS 原生端点→刷新→登出黑名单→浏览器 session 回归→中间件移除守卫）；`TestPublishFakePipeline`/`TestRegistryPushClient`/`TestPublishRegistryMode` 覆盖发布服务 stub（产物 schema2 自洽与 digest 链、字节可复现、落盘与审计、失败重推、registry 客户端 mock 全链路）；`TestIngestFindingsFixtureContract` 用 C 侧 `findings_ingest_sample.json` 锁定 B→A 回传应答 |
| `test_ls_reuse_smoke.py` | T2.7 LS 原生复用 smoke（`@pytest.mark.reuse`；需 `LS_REUSE_*`；写入需 `LS_REUSE_ALLOW_MUTATION=1`，结束清理自建资源） |
| `samples.py` | fixture 唯一数据源（model.yaml/manifest/ML backend/API 路径基线） |
| `make_fixtures.py` | 维护用：重新生成 `fixtures/`（不参与 CI 断言） |
| `fixtures/` | B 归属 7 份：`label_config_expected.xml`、`model_yaml_sample.yaml`、`model_manifest_sample.json`、`ml_backend_predict_sample.json`、`aoi_api_paths.json`、`yolo_export_layout_sample.json`、`review_flow_sample.json`（三桶复审）；C 归属 2 份（D1 已交付）：`findings_ingest_sample.json`（错图回传 meta，suspicious+bad）、`inspect_config_sample.yaml`（`load_config` 样例，A 预标与 B 工位模板共用） |

> `aoi_api_paths.json` 的 `auth` 字段取值：`jwt`（登录用户）/ `public`（匿名，如 `/api/auth/login`）/
> `internal-token`（`X-Internal-Token`）/ `optional-internal-token`（LS ML backend 协议）。
> 该基线同时是 OpenAPI 的「不多不少」比对源（`test_route_and_openapi_baseline`）。

## 契约点名但尚未落地的测试/ fixture（归属与延期）

| 契约位置 | 名称 | 归属 | 状态 |
|---|---|---|---|
| 跨平台 §6 | `tests/contracts/test_cross_platform.py` | C（平台 B 侧拉取/回传） | 待平台 B 骨架落地（D3+） |
| 跨平台 §6 | `fixtures/findings_ingest_sample.json`、`inspect_config_sample.yaml` | C | **已交付（D1，随 feature/c-infer-platform 合入）** |
| 平台A §13.1 | `tests/contracts/test_pipeline_core.py` | C（`packages/pipeline-core`） | **已交付（D1，随 feature/c-infer-platform 合入）** |
| 平台A §13.1 | `fixtures/detect_result_sample.json`、`goldens.json` | B | 训练链（D9~D12）时补 |
| 平台A §13.1 | RBAC 三角色矩阵 / 越权 40300 / 授权缓存失效 | B | **D4** 交付（D2 只测权限锚点 + 匿名 40100，见契约 §13.1 标注） |
| 跨平台 §2.3 规则 10 | `requires` 版本兼容判定 | C（B 侧校验）+ B（A 侧 schema_version 已测） | B 侧随平台 B 落地；A 侧负例已加 |

## 交 A 的 CI 输入

```yaml
# 伪代码；A 的 CI 按实际 runner 落地
services:
  postgres:
    image: postgres:16
    env: { POSTGRES_USER: postgres, POSTGRES_PASSWORD: postgres, POSTGRES_DB: postgres }
    ports: ['5432:5432']

steps:
  # 最小化测试依赖（已验证）；也可用 `uv sync --group test` 安装完整 test 组
  - run: ~/.local/bin/uv pip install --python .venv/bin/python pytest==9.0.3 pytest-django==4.12.0 pytest-env==1.6.0
  - run: ~/.local/bin/uv pip install --python .venv/bin/python -e packages/skillname -e packages/pipeline-core
  - run: |
      export DJANGO_DB=default \
             POSTGRE_HOST=localhost POSTGRE_PORT=5432 \
             POSTGRE_NAME=postgres POSTGRE_USER=postgres POSTGRE_PASSWORD=postgres
      PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts -q
```

要点：

1. **必须 PostgreSQL**：aoi 迁移创建 `aoi_datasets/aoi_training/aoi_review/aoi_audit` schema，SQLite 不支持（计划 §2 决策 3）；pytest-django 会建/销毁测试库，DB 用户需 `CREATEDB`。
2. `packages/skillname` 与 `packages/pipeline-core` 必须 editable 安装（共享包零三方依赖；`pipeline-core` 的 YAML 解析需 `pyyaml`，测试环境随 `test` 组提供）。
3. `PYTHONPATH=label_studio`（或 pytest `pythonpath = ["label_studio"]`），因为根 `pyproject.toml` 的 `DJANGO_SETTINGS_MODULE=core.settings.label_studio`。
4. 本仓库 `pyproject.toml` 的依赖组名是 `test`（不是 `dev`）；CI 用 `--group test` 或最小化安装 `pytest/pytest-django/pytest-env`。
5. `tests/contracts` 不需要前端构建；前端二开源码已用 bun 1.3.11 本地 `build:dev` + `biome check` 验证（bun 在 `~/.bun/bin`，非交互 shell 需加 PATH）。

## 本地运行

```bash
cd /data/jiazhenyu/huaxiang
export DJANGO_DB=default POSTGRE_HOST=localhost POSTGRE_PORT=5432 \
       POSTGRE_NAME=postgres POSTGRE_USER=admin POSTGRE_PASSWORD='<local-pg-password>'
~/.local/bin/uv pip install --python .venv/bin/python -e packages/skillname -e packages/pipeline-core
~/.local/bin/uv pip install --python .venv/bin/python pytest==9.0.3 pytest-django==4.12.0 pytest-env==1.6.0
PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts -q
```

LS 复用 smoke（可选，需已运行的 LS；**凭据从环境变量读取，不要写进仓库**）：

```bash
export LS_REUSE_BASE_URL=http://127.0.0.1:8080
export LS_REUSE_EMAIL='<测试账号邮箱>'
export LS_REUSE_PASSWORD='<测试账号密码>'
# 写操作（新建 project/标注/MLBackend）需显式开关；模块结束会自动删除自建资源
export LS_REUSE_ALLOW_MUTATION=1
PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts/test_ls_reuse_smoke.py -q
```

> 设置了 `LS_REUSE_BASE_URL` 但凭据缺失/被拒会 **fail 而不是 skip**（避免"零覆盖但绿灯"）。

UI 项（框标注交互、Review 流）为人工清单：需在浏览器人工核对，自动化侧只断言 API 基线；LS 1.24.0.dev0 OSS 无 Review 流，已在用例内 skip 并注明静态证据。
