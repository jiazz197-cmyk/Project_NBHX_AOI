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
