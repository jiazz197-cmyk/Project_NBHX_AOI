# 模型制品仓库配置（Docker Hub）

> Docker Hub 账号: `rekal1018`
> 仓库路径: `rekal1018/aoi-model`

## 这个仓库存什么

**存的是模型制品（文件），不是 Docker 镜像**：

```
docker.io/rekal1018/aoi-model:<tag>   # OCI 制品（Registry HTTP API v2）
├── model.onnx            # A 训练产出的推理权重
├── model.onnx.sha256     # 权重校验和
└── model.yaml            # 模型能力描述（skillname/类别/推荐阈值/张量契约）
```

- A 平台在「训练 → 模型库」中**选定一个已训练、已审批的模型**后上传该制品（不执行 `docker build` / `docker push` 镜像）。
- B 平台从本仓库**下载**制品并校验后注册到本地模型库。
- 命名、tag、digest、媒体类型与校验规则见 `docs/contracts/跨平台契约_A-B.md` §2.1/§2.1.1/§2.2。

## Token 分配

| 平台 | 权限 | Token | 用途 |
|---|---|---|---|
| B（推理端） | 只读 | 见 `infer-platform/.env.example` | 产线工控机下载模型 |
| A（训练端） | 读写 | `<dockerhub-access-token>` | 中心机房上传模型制品 |

## A 平台配置

已写入仓库根 `.env`（`MODEL_*`，D7 真实上传起用；`.env` 不入库）：

```
MODEL_REGISTRY=docker.io
MODEL_REGISTRY_USER=rekal1018
MODEL_REGISTRY_PASSWORD=<dockerhub-access-token>
MODEL_IMAGE_REPO=rekal1018/aoi-model   # 变量名沿用，"制品仓库路径"
PUBLISH_RETRY=3
```

> 代码读取入口：`label_studio/aoi/common/settings.py`（`get_model_registry` / `get_model_image_repo` / `get_model_registry_user` / `get_model_registry_password` / `get_publish_retry`）；`docker-compose.yml` 已透传同名变量，宿主机裸跑与容器部署共用一套配置。

## B 平台配置

已写入 `infer-platform/.env.example`（`MODEL_REGISTRY` / `MODEL_REGISTRY_USER` / `MODEL_REGISTRY_TOKEN` 只读），无需额外操作。
