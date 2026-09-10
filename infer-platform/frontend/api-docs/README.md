# OpenAPI 接口规范说明

## 这是什么

`openapi.json` 是平台 B 全部 27 个 HTTP 接口的规格文档，遵循 OpenAPI 3.0 标准。

相当于前后端之间的"合同"：约定好每个接口的路径、参数、返回格式，
前端按这个写调用代码，后端按这个实现逻辑，两边独立开发，最后联调时对得上。

## 用途

### 1. Apifox 导入（接口文档 + Mock 服务）

1. 打开 Apifox → 导入 → OpenAPI/Swagger
2. 选择本文件
3. 导入后可在 Apifox 中查看接口文档、生成 Mock 服务

### 2. 后端开发参考

角色 C 根据本文档实现 FastAPI 路由，确保与前端约定一致。

### 3. 前端开发参考

角色 A 根据本文档写 API 调用代码（`src/api/client.ts`），请求路径与参数与本文档对齐。

## 统一信封

所有接口返回格式：

```json
{
  "code": 0,
  "message": "ok",
  "request_id": "req-xxxxx",
  "data": { ... }
}
```

- `code=0` 表示成功，非 0 表示错误（具体错误码见文档内各接口）
- `request_id` 用于追踪请求链路
- 实际业务数据在 `data` 字段中

## 接口概览

| 分组 | 接口 | 用途 |
|---|---|---|
| 健康 | `GET /health` | 服务/GPU/磁盘/工位/outbox 状态 |
| 模型 | `GET /models`、`POST /models/pull`、`DELETE /models/{ref}` | 模型拉取与管理 |
| 工位 | `GET /stations`、`POST/PUT/DELETE /stations/{code}` | 工位增删改查 |
| 模板 | `PUT /stations/{code}/template` | 工位检测模板配置 |
| 检测 | `POST /inspect/image`、`GET /inspections` | 图片推理与记录查询 |
| 统计 | `GET /stats/summary`、`/trend`、`/errors` | 良率与趋势 |
| 日报 | `GET /reports/daily`、`/export` | 日报查看导出 |
| 系统 | `GET /system/outbox`、`/version` | 回传队列与版本 |