# skillname

AOI 双平台共享词汇表（纯 Python，**零三方依赖**）。权威定义来源：`docs/P0骨架设计_双平台.md` §4.1、
`docs/contracts/跨平台契约_A-B.md` §2.2/§2.3。

```python
from skillname import SkillName, ls_control_for, image_tag_from_model_ref

ls_control_for(SkillName.OBJECT_DETECTION)          # "RectangleLabels"
image_tag_from_model_ref("3-yolo@ds1")              # "3-yolo-ds1"
image_tag_from_model_ref("3-yolo@ds1", "fp16")      # "3-yolo-ds1-fp16"
```

- `SkillName`：MVP 唯一 `ObjectDetection`（→ LS 控件 `RectangleLabels`）；其余枚举预留。
- `<object>_<fault_type>_NN`：缺陷对象 code，前缀为两段可变英文词（如 `panel_scratch_01`），后缀 `01~99`（`00` 非法）。历史写法 `object_fault_type_XX` 仍合法（超集）。
- `model_ref`：`{seq}-{framework}@ds{dataset_version}`，如 `3-yolo@ds1`。
- 枚举值不得在平台侧硬编码副本；A/B/C 统一 `from skillname import ...`。
