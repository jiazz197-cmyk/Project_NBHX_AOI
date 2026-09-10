# `tests/contracts/` — 双平台契约测试（B 归属部分）

> D2 冻结基线：平台 A 契约测试 + fixtures。消费方写用例、维护方 CI 跑；**红则阻断合并**（计划 T2.8）。

## 目录

| 文件 | 说明 |
|---|---|
| `conftest.py` | Django/DRF fixtures、`jpeg_bytes`、`auth_client`、`aoi.core` 进程内状态重置（含 `_NEXT_ROLE_ID`） |
| `test_skillname.py` | T1.2 `packages/skillname`：枚举/code 正则（ASCII 01~99）/`model_ref`（ASCII）/镜像 tag |
| `test_platform_a_api.py` | T2.2–T2.5/T2.9 + P0/P1 回归：信封/鉴权/全量 stub 200/OpenAPI 基线/label config golden/model.yaml/预标协议/ingest 幂等与半写补建/发布与复审状态机/权限锚点 |
| `test_ls_reuse_smoke.py` | T2.7 LS 原生复用 smoke（`@pytest.mark.reuse`；需 `LS_REUSE_*`；写入需 `LS_REUSE_ALLOW_MUTATION=1`，结束清理自建资源） |
| `samples.py` | fixture 唯一数据源（model.yaml/manifest/ML backend/API 路径基线） |
| `make_fixtures.py` | 维护用：重新生成 `fixtures/`（不参与 CI 断言） |
| `fixtures/` | B 归属 7 份：`label_config_expected.xml`、`model_yaml_sample.yaml`、`model_manifest_sample.json`、`ml_backend_predict_sample.json`、`aoi_api_paths.json`、`yolo_export_layout_sample.json`、`review_flow_sample.json`（三桶复审） |

## 契约点名但尚未落地的测试/ fixture（归属与延期）

| 契约位置 | 名称 | 归属 | 状态 |
|---|---|---|---|
| 跨平台 §6 | `tests/contracts/test_cross_platform.py` | C（平台 B 侧拉取/回传） | 待平台 B 骨架落地（D3+） |
| 跨平台 §6 | `fixtures/findings_ingest_sample.json`、`inspect_config_sample.yaml` | C | 待 C 出具（A 侧不代写） |
| 平台A §13.1 | `tests/contracts/test_pipeline_core.py` | C（`packages/pipeline-core`） | 包尚未落地（D1~D2 交付物） |
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
  - run: ~/.local/bin/uv pip install --python .venv/bin/python -e packages/skillname
  - run: |
      export DJANGO_DB=default \
             POSTGRE_HOST=localhost POSTGRE_PORT=5432 \
             POSTGRE_NAME=postgres POSTGRE_USER=postgres POSTGRE_PASSWORD=postgres
      PYTHONPATH=label_studio .venv/bin/python -m pytest tests/contracts -q
```

要点：

1. **必须 PostgreSQL**：aoi 迁移创建 `aoi_datasets/aoi_training/aoi_review/aoi_audit` schema，SQLite 不支持（计划 §2 决策 3）；pytest-django 会建/销毁测试库，DB 用户需 `CREATEDB`。
2. `packages/skillname` 必须 editable 安装（`import skillname` 零三方依赖）。
3. `PYTHONPATH=label_studio`（或 pytest `pythonpath = ["label_studio"]`），因为根 `pyproject.toml` 的 `DJANGO_SETTINGS_MODULE=core.settings.label_studio`。
4. 本仓库 `pyproject.toml` 的依赖组名是 `test`（不是 `dev`）；CI 用 `--group test` 或最小化安装 `pytest/pytest-django/pytest-env`。
5. `tests/contracts` 不需要前端构建；前端二开源码已用 bun 1.3.11 本地 `build:dev` + `biome check` 验证（bun 在 `~/.bun/bin`，非交互 shell 需加 PATH）。

## 本地运行

```bash
cd /data/jiazhenyu/huaxiang
export DJANGO_DB=default POSTGRE_HOST=localhost POSTGRE_PORT=5432 \
       POSTGRE_NAME=postgres POSTGRE_USER=admin POSTGRE_PASSWORD='<local-pg-password>'
~/.local/bin/uv pip install --python .venv/bin/python -e packages/skillname
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

UI 项（框标注交互、Review 流）为人工清单，见 `docs/复用验证_D2.md` §4/§5。
