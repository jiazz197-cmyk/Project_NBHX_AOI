"""按 OCI / Docker Registry HTTP API v2 拉取模型镜像。

默认 MODEL_PULL_MODE=oci（纯 httpx + tarfile，无 Docker daemon 依赖）。
对齐 docs/contracts/跨平台契约_A-B.md、docs/P0骨架设计_双平台.md §1。

TODO: 实现 Registry v2 拉取（含鉴权与重试）。
"""
