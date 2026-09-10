# 旧平台数据包

> 来源：上一版 AOI 平台（SHLG_Matrix/Orin）导出的 Camera Model Bundle
> 用途：仅供开发参考，不入库（.gitignore 已忽略）

---

## 这是什么

旧平台将训练好的检测模型、金标准测试用例、相机点位配置打包成"相机模型包（Camera Model Bundle）"，部署到产线 Jetson Orin 工控机上运行。这里是 3 个版本的完整包。

**不是训练数据集，不包含训练图片或标注。**

---

## 包清单

| 包 ID | 版本 | 内容 |
|---|---|---|
| `aaa5d5d9-...-1.0.1-orin-0.3.128` | 1.0.1 | 3 个检测器（2 个分类 ONNX + 1 个模板匹配），金标准测试，3 个相机点位 |
| `b278d134-...` | 无版本号 | 1 个光度检测器，金标准测试，1 个相机点位 |
| `9ca499a8-...-1.0.10-orin-0.3.134` | 1.0.10 | 光度检测器新版，含 JSON Schema 校验文件 |

---

## 每个包的目录结构

```
bundle/
├── manifest.json              # 包清单（创建者、包含的检测器列表、文件校验）
├── evaluation-report.json     # 评估报告（精度、局限、审批状态）
├── runtime-requirements.json  # 运行要求（推理后端、显存、平台）
├── SHA256SUMS                 # 防篡改校验和
├── detectors/                 # 检测器
│   └── det-xxxx/
│       ├── contract.json      #   检测器契约（输入规格、阈值、类别定义）
│       ├── model.onnx         #   ONNX 模型权重（仅分类检测器）
│       └── algorithm-parameters.json  # 算法参数（模板匹配/光度检测器）
├── golden-tests/              # 金标准测试
│   └── det-xxxx/
│       ├── manifest.json      #   测试清单
│       ├── xxx.input.png      #   输入图片
│       └── xxx.expected.json  #   期望输出（旧平台已验证）
└── points/                    # 相机点位配置
    └── CAMxx-Pxx.json         #   ROI 区域坐标与偏移策略
```

---

## 已提取到项目的部分

有效内容已提取到 `tests/contracts/fixtures/`，可直接用于新平台开发：

| 提取位置 | 内容 |
|---|---|
| `fixtures/models/classification/` | 2 个 ONNX 模型 + 分类器契约 |
| `fixtures/models/golden-images/` | 代表性金标准测试图片 |
| `fixtures/legacy_*.json` | 旧平台契约、点位配置、期望输出样例 |
| `fixtures/models/README.md` | 模型使用说明 |

---

## 与新平台的对应

| 旧平台概念 | 新平台对应 |
|---|---|
| 检测器（detector） | 模型（model）+ 工位模板（station template） |
| `contract.json` | `model.yaml` |
| `implementationType` | `SkillName` 枚举 |
| `criticalNgClassIds` | `ObjectSpec.critical` |
| `acceptanceThreshold` | `auto_min` |
| 相机点位（point） | 工位模板中的 ROI 配置 |
| ZIP 包导入 | Docker 镜像仓库拉取 |

---

## 注意事项

- 这些 ONNX 模型是旧平台产物，仅供测试参考。生产模型由平台 A 训练并通过镜像仓库发布。
- 旧平台使用 TensorRT 作为推理后端（Jetson Orin），新平台默认 ONNX Runtime，预处理参数可能需调整。
- 旧平台类别命名（class-0/class-1）与新平台规范（object_fault_type_XX）不同，迁移时需映射。