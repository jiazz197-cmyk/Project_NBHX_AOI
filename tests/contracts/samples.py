"""契约 fixture 的唯一数据源（D2；B 归属）。

- ``model_yaml_sample_inputs``：T2.4 ``model.yaml`` / ``model_manifest.json`` 样例输入；
- ``aoi_api_paths``：T2.9 ``aoi_api_paths.json`` 端点基线（含裁定路径 ``/api/datasets/{id}``）；
- ``ml_backend_sample``：T2.5 LS ML backend 协议样例（直接引用 ``aoi.prelabel.protocol``）。
"""

from __future__ import annotations

import copy
from typing import Any

#: 固定 64 位十六进制样例哈希（避免 fixture 每次生成漂移）
ONNX_SHA256 = '9f2c' + '0' * 58 + 'e1'
MODEL_YAML_SHA256 = 'ec0a47efd21f23e52653e00c4c5f59f947079677ed70309824ad251987835820'
MANIFEST_CONFIG_DIGEST = 'sha256:' + 'b' * 64
MANIFEST_LAYER_DIGEST = 'sha256:' + 'c' * 64

MODEL_YAML_CREATED_AT = '2026-09-08T08:30:00Z'
MODEL_YAML_PUBLISHED_AT = '2026-09-08T09:00:00Z'


def model_yaml_sample_inputs() -> dict[str, Any]:
    """``build_model_yaml`` 的确定性输入（fixture 与测试共用）。"""
    model = {
        'id': 3,
        'version': '3-yolo@ds1',
        'framework': 'yolo',
        'dataset_version': '1.0.0',
        'task_type': 'ObjectDetection',
        'base_model': 'yolov8s.pt',
        'weights_key': 'models/3-yolo@ds1/fp32/model.onnx',
        'class_names': ['object_fault_type_01', 'object_fault_type_02'],
        'cover_classes': ['object_fault_type_01', 'object_fault_type_02'],
        'precision': 'fp32',
        'input_shape': [1, 3, 1280, 1280],
        'tensor_names': {'input': 'images', 'output': 'output0'},
        'eval_metrics': {
            'map50': 0.93,
            'map50_95': 0.71,
            'precision': 0.94,
            'recall': 0.96,
            'per_class_recall': {'object_fault_type_01': 0.99, 'object_fault_type_02': 0.97},
            'per_class_precision': {'object_fault_type_01': 0.95, 'object_fault_type_02': 0.93},
            'eval_dataset': '1.0.0-test',
            'evaluated_at': '2026-09-08T08:00:00Z',
            'confusion_matrix_ref': None,
        },
        'gate_status': 'passed',
        'lifecycle': 'published',
        'config_snapshot': {'dict_version': '20260901-1'},
    }
    defect_classes = [
        {
            'code': 'object_fault_type_01',
            'name_cn': '划伤',
            'name_en': 'scratch',
            'risk_level': 3,
            'color': '#FF4D4F',
            'aliases': ['刮伤'],
            'enabled': True,
            'min_box_size': 4,
            'max_boxes_per_image': 50,
            'recommended': {'recheck_min': 0.60, 'auto_min': 0.90},
        },
        {
            'code': 'object_fault_type_02',
            'name_cn': '凹坑',
            'risk_level': 2,
            'recommended': {'recheck_min': 0.55, 'auto_min': 0.88},
        },
    ]
    base_model = {'name': 'yolov8s.pt', 'framework': 'yolo', 'framework_version': '8.4.1'}
    train_job = {
        'id': 128,
        'created_by': 7,
        'preset': {
            'params': {
                'tiling': {'size': 1280, 'overlap': 0.2, 'enabled': True},
                'imgsz': 1280,
                'batch': 8,
                'epochs': 100,
                'lr0': 0.01,
                'patience': 20,
                'seed': 42,
                'augment': {'flip': True, 'mosaic': True, 'mixup': 0.1},
                'split': {'train': 0.7, 'val': 0.2, 'test': 0.1},
            }
        },
    }
    onnx_meta = {
        'file': 'model.onnx',
        'sha256': ONNX_SHA256,
        'size_bytes': 41234567,
        'opset': 17,
        'ir_version': 8,
        'producer': 'ultralytics 8.4.1',
        'dynamic_batch': True,
        'max_batch_size': 8,
        'input': {
            'name': 'images',
            'shape': [1, 3, 1280, 1280],
            'dtype': 'float32',
            'layout': 'NCHW',
            'color_order': 'RGB',
        },
        'output': {
            'name': 'output0',
            'shape': [1, 6, 8400],
            'format': 'yolo_v8_xywh_conf_cls',
            'num_classes': 2,
            'num_anchors': 8400,
        },
        'runtime': {'providers': ['cuda', 'cpu'], 'fp16': False, 'threads': 4},
    }
    source = {
        'created_at': MODEL_YAML_CREATED_AT,
        'published_at': MODEL_YAML_PUBLISHED_AT,
        'git_commit': '59ec528',
        'dict_version': '20260901-1',
        'description': '门板表面缺陷检测 v3',
        'tags': ['doorpanel', 'surface'],
        'license': 'Apache-2.0',
        'benchmark': {
            'device': 'RTX 4060',
            'provider': 'cuda',
            'precision': 'fp32',
            'tile_size': 1280,
            'batch': 4,
            'latency_ms_p50': 380,
            'latency_ms_p95': 520,
            'throughput_fps': 9.6,
            'vram_gb': 3.8,
        },
    }
    return {
        'model': model,
        'defect_classes': defect_classes,
        'base_model': base_model,
        'train_job': train_job,
        'onnx_meta': onnx_meta,
        'source': source,
    }


def label_config_sample_defects() -> list[dict[str, Any]]:
    """T2.2 golden fixture 输入（index 0-based；code 与颜色稳定）。"""
    return [
        {'code': 'object_fault_type_01', 'name_cn': '划伤', 'index': 0, 'color': '#FF4D4F'},
        {'code': 'object_fault_type_02', 'name_cn': '凹坑', 'index': 1},
    ]


def build_model_yaml_sample() -> dict[str, Any]:
    from aoi.training.model_yaml import build_model_yaml

    return build_model_yaml(**model_yaml_sample_inputs())


def model_manifest_sample() -> dict[str, Any]:
    """OCI/Docker manifest 样例（与 ``model.yaml`` 同版本的镜像元数据）。"""
    return {
        'schemaVersion': 2,
        'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
        'config': {
            'mediaType': 'application/vnd.docker.container.image.v1+json',
            'size': 7023,
            'digest': MANIFEST_CONFIG_DIGEST,
        },
        'layers': [
            {
                'mediaType': 'application/vnd.docker.image.rootfs.diff.tar.gzip',
                'size': 41234567,
                'digest': MANIFEST_LAYER_DIGEST,
            }
        ],
        'annotations': {
            'org.opencontainers.image.ref.name': '3-yolo-ds1',
            'aoi.model_ref': '3-yolo@ds1',
            'aoi.model_yaml_sha256': MODEL_YAML_SHA256,
            'aoi.skillname': 'ObjectDetection',
            'aoi.precision': 'fp32',
            'aoi.registry': 'docker.io',
            'aoi.image': 'docker.io/aoi/aoi-model',
        },
    }


def ml_backend_sample() -> dict[str, Any]:
    from aoi.prelabel import protocol

    return {
        'description': 'LS 1.x ML backend 协议样例（健康/初始化/预测/校验）',
        'source': 'LS 1.24.0.dev0 label_studio/ml/api_connector.py + D2 实测',
        # 实测：LS 调用只带 User-Agent，不携带 X-Internal-Token / Authorization（无 Basic Auth 时）
        'observed_request_headers': {
            'User-Agent': 'heartex/<git-sha>',
            'X-Internal-Token': None,
            'Authorization': None,
        },
        'endpoints': {
            'health': {
                'method': 'GET',
                'path': '/api/prelabel/{task_id}/health',
                'request': {},
                'response': copy.deepcopy(protocol.HEALTH_RESPONSE),
            },
            'setup': {
                'method': 'POST',
                'path': '/api/prelabel/{task_id}/setup',
                'request': {},
                'response': copy.deepcopy(protocol.SETUP_RESPONSE),
            },
            'predict': {
                'method': 'POST',
                'path': '/api/prelabel/{task_id}/predict',
                'request': copy.deepcopy(protocol.PREDICT_REQUEST_SAMPLE),
                'response': protocol.build_predict_response(protocol.PREDICT_REQUEST_SAMPLE['tasks']),
            },
            'validate': {
                'method': 'POST',
                'path': '/api/prelabel/{task_id}/validate',
                'request': {},
                'response': copy.deepcopy(protocol.VALIDATE_RESPONSE),
            },
        },
    }


def yolo_export_layout_sample() -> dict[str, Any]:
    """LS 1.24 YOLO 导出实测布局（D2；无 data.yaml，classes.txt 为准）。"""
    return {
        'source': 'LS 1.24.0.dev0 data_export YOLO 实测（D2）',
        'entries': ['images/', 'labels/', 'classes.txt', 'notes.json'],
        'has_data_yaml': False,
        'classes_source': 'classes.txt',
        'classes_order': ['object_fault_type_01', 'object_fault_type_02'],
        'data_yaml': '由 aoi 训练包裹（D9）在训练时按需生成，不作为导出 zip 的必备产物',
    }


def review_flow_sample() -> dict[str, Any]:
    """预标三桶复审样例（D2 确认：高绿自动/中黄建议/低红强制）。"""
    return {
        'description': '预标三桶→人工复审→数据集落版样例（契约 §3.4/§4.4/§10）',
        'scope': 'unlabeled_only',
        'thresholds_priority': ['model.yaml.recommended', 'prelabel_task.route_config'],
        'dataset_version': {'status': 'draft', 'phase': 'reviewing'},
        'bucket_colors': {'high': '#52C41A', 'medium': '#FAAD14', 'low': '#FF4D4F'},
        'workitems': [
            {
                'id': 1,
                'source': 'prelabel',
                'bucket': 'high',
                'verdict': 'auto_pass',
                'forced': False,
                'status': 'finalized',
                'ls_task_id': 101,
                'ls_prediction_id': 9001,
                'model_ref': '3-yolo@ds1',
                'bucket_reason': {'reasons': ['high_score'], 'scores': {'object_fault_type_01': 0.96}},
            },
            {
                'id': 2,
                'source': 'prelabel',
                'bucket': 'medium',
                'verdict': 'recheck',
                'forced': False,
                'status': 'pending',
                'ls_task_id': 102,
                'ls_prediction_id': 9002,
                'model_ref': '3-yolo@ds1',
                'bucket_reason': {'reasons': ['mid_score'], 'scores': {'object_fault_type_01': 0.72}},
            },
            {
                'id': 3,
                'source': 'prelabel',
                'bucket': 'low',
                'verdict': 'manual',
                'forced': True,
                'status': 'pending',
                'ls_task_id': 103,
                'ls_prediction_id': 9003,
                'model_ref': '3-yolo@ds1',
                'bucket_reason': {'reasons': ['low_score'], 'scores': {'object_fault_type_01': 0.41}},
            },
        ],
        'finalize_requests': {
            'high': {'action': 'accepted_prediction', 'final_reason': 'auto_pass'},
            'medium': {
                'action': 'edited',
                'verdict': 'defect_confirmed',
                'boxes': [{'object_code': 'object_fault_type_01', 'score': 0.72, 'xyxy': [10, 12, 30, 27]}],
                'final_reason': 'misdetection',
            },
            'low': {
                'action': 'relabeled',
                'verdict': 'defect_confirmed',
                'annotation': {'result': []},
                'final_reason': 'annotation_issue',
            },
        },
    }


def aoi_api_paths() -> dict[str, Any]:
    """aoi 端点清单基线（T2.9 fixture；路径参数用 ``{name}`` 占位）。"""

    def entry(method: str, path: str, tag: str, auth: str = 'jwt') -> dict[str, str]:
        return {'method': method, 'path': path, 'tag': tag, 'auth': auth}

    paths = [
        # auth（契约 §4.0；login 匿名，logout 需 jwt）
        entry('POST', '/api/auth/login', 'aoi-auth', auth='public'),
        entry('POST', '/api/auth/logout', 'aoi-auth'),
        # core（契约 §4.0）
        entry('GET', '/api/core/permissions', 'aoi-core'),
        entry('GET', '/api/core/roles', 'aoi-core'),
        entry('POST', '/api/core/roles', 'aoi-core'),
        entry('GET', '/api/core/roles/{id}', 'aoi-core'),
        entry('PUT', '/api/core/roles/{id}', 'aoi-core'),
        entry('DELETE', '/api/core/roles/{id}', 'aoi-core'),
        entry('POST', '/api/core/users/{id}/roles', 'aoi-core'),
        # D5 组织管理（契约 §4.0）：列表 + 停用/启用
        entry('GET', '/api/core/users', 'aoi-core'),
        entry('POST', '/api/core/users/{id}/deactivate', 'aoi-core'),
        entry('POST', '/api/core/users/{id}/activate', 'aoi-core'),
        # datasets（契约 §4.1；T2.9 裁定路径）
        entry('POST', '/api/datasets/import', 'aoi-datasets'),
        entry('GET', '/api/datasets/import/{job_id}', 'aoi-datasets'),
        entry('GET', '/api/datasets/images', 'aoi-datasets'),
        entry('GET', '/api/datasets/images/{id}/download', 'aoi-datasets'),
        # D6：回传图片原始字节（B 回传图 images/{md5}.{ext} 无 /data/ 代理路由，走 aoi 流式端点）。
        # 位置在 DELETE images/{id} 之前：巡检循环按列表顺序执行，DELETE 后图片 1 已不存在
        entry('GET', '/api/datasets/images/{id}/raw', 'aoi-datasets'),
        # D5 收尾：图片详情/删除
        entry('GET', '/api/datasets/images/{id}', 'aoi-datasets'),
        entry('DELETE', '/api/datasets/images/{id}', 'aoi-datasets'),
        entry('GET', '/api/datasets/defects', 'aoi-datasets'),
        entry('POST', '/api/datasets/defects', 'aoi-datasets'),
        entry('PUT', '/api/datasets/defects', 'aoi-datasets'),
        entry('POST', '/api/datasets/defects/publish', 'aoi-datasets'),
        # D5 收尾：缺陷字典发布历史
        entry('GET', '/api/datasets/defects/versions', 'aoi-datasets'),
        entry('GET', '/api/datasets', 'aoi-datasets'),
        entry('POST', '/api/datasets', 'aoi-datasets'),
        entry('GET', '/api/datasets/{id}', 'aoi-datasets'),
        entry('PUT', '/api/datasets/{id}', 'aoi-datasets'),
        entry('DELETE', '/api/datasets/{id}', 'aoi-datasets'),
        entry('POST', '/api/datasets/{id}/versions', 'aoi-datasets'),
        entry('GET', '/api/datasets/{id}/versions/{v}/export', 'aoi-datasets'),
        entry('GET', '/api/datasets/annotation-stats', 'aoi-datasets'),
        # train（契约 §4.2）
        entry('GET', '/api/train/base-models', 'aoi-train'),
        entry('GET', '/api/train/presets', 'aoi-train'),
        entry('POST', '/api/train/jobs', 'aoi-train'),
        entry('GET', '/api/train/jobs/{id}', 'aoi-train'),
        entry('POST', '/api/train/jobs/{id}/cancel', 'aoi-train'),
        entry('GET', '/api/train/jobs/{id}/progress', 'aoi-train'),
        entry('GET', '/api/train/models', 'aoi-train'),
        entry('POST', '/api/train/models/{id}/approve', 'aoi-train'),
        entry('POST', '/api/train/models/{id}/publish', 'aoi-train'),
        entry('GET', '/api/train/models/{id}/publish', 'aoi-train'),
        # D7：批量上传 + 已上传管理（契约 §4.2 / 跨平台契约 §2.4）
        entry('POST', '/api/train/models/publish', 'aoi-train'),
        entry('POST', '/api/train/models/{id}/retire', 'aoi-train'),
        entry('GET', '/api/train/publishes', 'aoi-train'),
        entry('POST', '/api/train/publishes/{id}/delete', 'aoi-train'),
        entry('POST', '/api/train/publishes/{id}/restore', 'aoi-train'),
        # prelabel（契约 §4.3）
        entry('GET', '/api/prelabel/tasks', 'aoi-prelabel'),
        entry('POST', '/api/prelabel/tasks', 'aoi-prelabel'),
        entry('GET', '/api/prelabel/tasks/{task_id}', 'aoi-prelabel'),
        entry('PUT', '/api/prelabel/tasks/{task_id}', 'aoi-prelabel'),
        entry('DELETE', '/api/prelabel/tasks/{task_id}', 'aoi-prelabel'),
        entry('GET', '/api/prelabel/{task_id}/health', 'aoi-prelabel', auth='optional-internal-token'),
        entry('POST', '/api/prelabel/{task_id}/setup', 'aoi-prelabel', auth='optional-internal-token'),
        entry('POST', '/api/prelabel/{task_id}/predict', 'aoi-prelabel', auth='optional-internal-token'),
        entry('POST', '/api/prelabel/{task_id}/validate', 'aoi-prelabel', auth='optional-internal-token'),
        entry('POST', '/api/prelabel/{task_id}/webhook', 'aoi-prelabel', auth='optional-internal-token'),
        # review（契约 §4.4）
        entry('GET', '/api/review/workitems', 'aoi-review'),
        entry('POST', '/api/review/workitems/{id}/claim', 'aoi-review'),
        entry('POST', '/api/review/workitems/{id}/finalize', 'aoi-review'),
        entry('GET', '/api/review/suggestions', 'aoi-review'),
        entry('POST', '/api/review/suggestions/batch-confirm', 'aoi-review'),
        entry('GET', '/api/review/bad-images', 'aoi-review'),
        entry('POST', '/api/review/bad-images/{id}/handle', 'aoi-review'),
        # system / ingest（契约 §4.5/§4.6）
        entry('GET', '/api/system/audit', 'aoi-system'),
        entry('POST', '/api/ingest/findings', 'aoi-ingest', auth='internal-token'),
    ]
    return {
        'version': 'd7-20260921-1',
        'note': (
            'T2.9 datasets CRUD 路径裁定为 /api/datasets + /api/datasets/{id}；旧 /api/datasets/datasets* 不存在；'
            'D3 新增 /api/auth/login（匿名）与 /api/auth/logout（jwt）；'
            'D5 新增 /api/core/users 与 /api/core/users/{id}/deactivate|activate（组织管理，契约 §4.0）；'
            'D5 收尾新增 GET/DELETE /api/datasets/images/{id}（图片删除）与 GET /api/datasets/defects/versions（发布历史）；'
            'D7 新增 POST /api/train/models/publish（批量上传）、POST /api/train/models/{id}/retire、'
            'GET /api/train/publishes、POST /api/train/publishes/{id}/delete|restore（已上传管理，契约 §4.2）'
            '与 GET /api/datasets/images/{id}/raw（回传图片字节）'
        ),
        'paths': paths,
    }
