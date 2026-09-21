"""重新生成 B 归属 fixtures（维护用，不参与 CI 断言）。

用法：
    PYTHONPATH=label_studio .venv/bin/python tests/contracts/make_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from aoi.datasets.label_config import render_label_config
from samples import (
    aoi_api_paths,
    build_model_yaml_sample,
    label_config_sample_defects,
    ml_backend_sample,
    model_manifest_sample,
    review_flow_sample,
    yolo_export_layout_sample,
)

FIXTURES = Path(__file__).parent / 'fixtures'


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / 'model_yaml_sample.yaml').write_text(
        yaml.safe_dump(build_model_yaml_sample(), sort_keys=False, allow_unicode=True), encoding='utf-8'
    )
    (FIXTURES / 'model_manifest_sample.json').write_text(
        json.dumps(model_manifest_sample(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    (FIXTURES / 'ml_backend_predict_sample.json').write_text(
        json.dumps(ml_backend_sample(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    (FIXTURES / 'label_config_expected.xml').write_text(
        render_label_config(label_config_sample_defects()), encoding='utf-8'
    )
    (FIXTURES / 'review_flow_sample.json').write_text(
        json.dumps(review_flow_sample(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    (FIXTURES / 'yolo_export_layout_sample.json').write_text(
        json.dumps(yolo_export_layout_sample(), indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    (FIXTURES / 'aoi_api_paths.json').write_text(
        # indent=1：该 fixture 自 T2.9 起就是 1 空格缩进，保持一致，避免每次生成都全文件重排
        json.dumps(aoi_api_paths(), indent=1, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    print('fixtures written to', FIXTURES)


if __name__ == '__main__':
    main()
