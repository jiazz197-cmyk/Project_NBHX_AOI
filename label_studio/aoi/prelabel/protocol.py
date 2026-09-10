"""LS 1.x ML backend 协议样例（契约 §4.3；T2.5 fixture 的唯一数据源）。

``tests/contracts/fixtures/ml_backend_predict_sample.json`` 由本模块常量生成/比对，
保证 fixture 与 stub 响应同形。
"""

from __future__ import annotations

from typing import Any

__all__ = [
    'MODEL_VERSION',
    'MODEL_CLASSES',
    'HEALTH_RESPONSE',
    'SETUP_RESPONSE',
    'VALIDATE_RESPONSE',
    'PREDICT_REQUEST_SAMPLE',
    'PREDICT_RESULT_TEMPLATE',
    'build_predict_response',
]

MODEL_VERSION = '3-yolo@ds1'

#: 与 label config 的 code 对齐（index 为模型类别维索引）
MODEL_CLASSES = {'object_fault_type_01': 0, 'object_fault_type_02': 1}

HEALTH_RESPONSE = {'status': 'UP', 'model_version': MODEL_VERSION}

SETUP_RESPONSE = {'model_version': MODEL_VERSION, 'model_classes': MODEL_CLASSES}

VALIDATE_RESPONSE = {'errors': []}

PREDICT_REQUEST_SAMPLE = {
    'tasks': [
        {
            'id': 101,
            'data': {'image': 'http://ls-backend:8080/data/upload/1/abc.jpg'},
        }
    ]
}

#: 单框结果模板（LS 1.x rectanglelabels；from_name/to_name 与 label config 对齐）
PREDICT_RESULT_TEMPLATE: dict[str, Any] = {
    'from_name': 'defect',
    'to_name': 'image',
    'type': 'rectanglelabels',
    'score': 0.72,
    'value': {
        'x': 10.5,
        'y': 12.3,
        'width': 8.2,
        'height': 5.6,
        'rotation': 0,
        'rectanglelabels': ['object_fault_type_01'],
    },
}


def build_predict_response(tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """按 LS 请求 tasks 逐个返回同形 stub 结果（无 tasks 时返回空 results）。"""
    results = []
    for task in tasks or []:
        results.append(
            {
                'id': task.get('id'),
                'model_version': MODEL_VERSION,
                'result': [dict(PREDICT_RESULT_TEMPLATE, value=dict(PREDICT_RESULT_TEMPLATE['value']))],
            }
        )
    return {'results': results}
