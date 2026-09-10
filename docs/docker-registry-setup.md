# Docker Hub 镜像仓库配置

> Docker Hub 账号: `rekal1018`
> 镜像命名: `rekal1018/aoi-model`

## Token 分配

| 平台 | 权限 | Token | 用途 |
|---|---|---|---|
| B（推理端） | 只读 | 见 `infra/.env.example` | 产线工控机拉取模型 |
| A（训练端） | 读写 | `<dockerhub-access-token>` | 中心机房发布模型 |

## A 平台配置

角色B在 A 平台的环境变量或 CI 配置中填入：

```
MODEL_REGISTRY=docker.io
MODEL_REGISTRY_USER=rekal1018
MODEL_REGISTRY_PASSWORD=<dockerhub-access-token>
MODEL_IMAGE_REPO=rekal1018/aoi-model
```

## B 平台配置

已写入 `infra/.env.example`，无需额外操作。