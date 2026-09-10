# 前端运行说明

## 环境要求

- Node.js ≥ 18
- npm ≥ 9

## 启动

```bash
cd infer-platform/frontend
npm install        # 首次运行，安装依赖（之后跳过）
npx vite --host 0.0.0.0 --port 5173
```

浏览器打开 `http://服务器IP:5173`。

## 数据模式

`.env.development` 中切换：

```
VITE_DATA_MODE=mock   # 使用内置假数据（默认，后端未就绪时用）
VITE_DATA_MODE=api    # 调用真实后端（VITE_API_TARGET 指向后端地址）
```

## 构建

```bash
npx vite build
```

产物在 `dist/` 目录。

---

## 文件结构

```
infer-platform/frontend/
│
├── index.html                  # Vite 入口 HTML，挂载点 <div id="root">
├── package.json                # 依赖声明（React 18、Ant Design 5、ECharts 等）
├── tsconfig.json               # TypeScript 编译配置
├── vite.config.ts              # Vite 构建配置（开发代理到后端）
├── .env.development            # 开发环境变量（数据模式、API 地址）
├── README.md                   # 本文件
│
├── api-docs/
│   ├── openapi.json            # OpenAPI 3.0 接口规范（27 个端点），可导入 Apifox
│   └── README.md               # 接口规范说明、统一信封格式、接口清单
│
├── public/                     # 静态资源（暂空，可放 favicon 等）
│
├── dist/                       # 构建产物（npm run build 生成，不入库）
│
└── src/                        # 源代码
    ├── main.tsx                # 应用入口：挂载 React、全局配置（中文、主题色）
    ├── App.tsx                 # 路由定义：4 个页面路径映射
    ├── vite-env.d.ts           # Vite 环境类型声明
    │
    ├── api/                    # 接口层
    │   ├── client.ts           # HTTP 客户端：封装 fetch，统一信封处理
    │   ├── mock.ts             # 假数据：所有接口的 mock 实现
    │   └── types.ts            # TypeScript 类型定义（数据模型，对齐契约）
    │
    ├── components/             # 公共组件
    │   └── AppLayout.tsx       # 页面布局：侧边栏菜单 + 顶栏 + 内容区
    │
    ├── pages/                  # 页面
    │   ├── LiveDetection/      # 实时检测：8 路监控墙、模板选择、异常告警
    │   │   └── index.tsx
    │   ├── Dashboard/          # 工作台：良率、工位状态、最近异常、日报摘要
    │   │   └── index.tsx
    │   ├── Inspections/        # 检测记录：卡片流、筛选
    │   │   └── index.tsx
    │   └── System/             # 系统：健康状态、模型库、outbox 队列、版本
    │       └── index.tsx
    │
    └── styles/
        └── global.css          # 全局样式 + 告警动画
```

## 依赖项

| 包 | 用途 |
|---|---|
| react / react-dom | 页面框架 |
| react-router-dom | 页面路由 |
| antd | UI 组件库（表格、表单、卡片等） |
| @ant-design/icons | 图标 |
| echarts | 图表（暂未使用，预留） |
| dayjs | 时间处理（暂未使用，预留） |