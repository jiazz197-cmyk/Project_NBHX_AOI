# Docker Hub 镜像仓库配置

> Docker Hub 账号: `<dockerhub-username>`（部署方自行指定）
> 镜像命名: `<dockerhub-username>/aoi-model`

> ⚠️ **本仓库为脱敏开源版本，任何真实 Token 一律不入库。**
> 请自行在 Docker Hub → Account Settings → Personal access tokens 创建 Token，
> 并通过环境变量 / CI 变量 / Secret 注入，**不要提交到 Git**。

## Token 分配

| 平台 | 权限 | Token | 用途 |
|---|---|---|---|
| B（推理端） | 只读 | 见 `infer-platform/.env.example` | 产线工控机拉取模型（含 `GET /tags/list` 列 tag） |
| A（训练端） | 读写 | 部署方自行创建并注入 | 中心机房发布模型 |

## A 平台配置

在 A 平台的环境变量或 CI 配置中填入（**值由部署方自行生成**）：

```
MODEL_REGISTRY=docker.io
MODEL_REGISTRY_USER=<dockerhub-username>
MODEL_REGISTRY_PASSWORD=<dockerhub-access-token>
MODEL_IMAGE_REPO=<dockerhub-username>/aoi-model
```

## B 平台配置

已写入 `infer-platform/.env.example`（`MODEL_REGISTRY` / `MODEL_REGISTRY_USER` / `MODEL_REGISTRY_TOKEN` 只读），无需额外操作。
B 侧「系统 → 模型库」页可**列出本仓库可用 tag（Registry v2 `GET /tags/list`）并一键拉取**（跨平台契约 §2.5）。

## 注意：A 侧「删除」不影响本仓库

A 平台对已上传模型的「删除」是**软删**——只清 A 侧管理记录（`model_publish.deleted_at`）并写审计，
**本仓库中的镜像与 tag 一律保留**，B 仍可正常列出与拉取（跨平台契约 §2.4）。
仓库镜像的物理清理不在 MVP 范围内；如需腾空间请人工执行，并先确认没有 B 仍可能回滚到该版本。
