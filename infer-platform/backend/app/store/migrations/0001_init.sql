-- 0001_init.sql —— 平台 B 数据模型建表
-- 逐字对齐 docs/contracts/平台B_接口与数据契约.md §2（b_ 前缀，10 张表，无 b_plan）

CREATE TABLE b_model (
  model_ref TEXT PRIMARY KEY,
  skillname TEXT NOT NULL,                   -- ObjectDetection
  framework TEXT NOT NULL,                   -- yolo
  dataset_version TEXT,
  class_names TEXT NOT NULL,                 -- JSON 数组，索引序
  cover_classes TEXT NOT NULL,               -- JSON 数组
  precision TEXT NOT NULL DEFAULT 'fp32',    -- fp32/fp16
  config_json TEXT NOT NULL,                 -- model.yaml 原文（含推荐阈值/展示名/张量信息；预留字段原样保存）
  source_image TEXT,                         -- 拉取来源镜像，如 docker.io/<org>/aoi-model:3-yolo-ds1
  image_digest TEXT,                         -- sha256:...
  sha256 TEXT NOT NULL,                      -- model.onnx 的 sha256
  size_bytes INTEGER NOT NULL,
  opset INTEGER, input_name TEXT, output_name TEXT, input_shape TEXT,
  stored_path TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',      -- pulling/ready/active/failed
  received_at TEXT NOT NULL, activated_at TEXT
);
CREATE UNIQUE INDEX idx_b_model_sha ON b_model(sha256);

CREATE TABLE b_station (
  code TEXT PRIMARY KEY,                     -- ST01~ST08（B 自管）
  name TEXT,
  enabled INTEGER NOT NULL DEFAULT 0,
  channel_id TEXT,
  camera_config TEXT,                        -- JSON：adapter/source/trigger/fps_limit/config
  template_json TEXT,                        -- JSON：工位模板（§3.3），未配置为 NULL
  template_version INTEGER DEFAULT 0,
  status TEXT DEFAULT 'offline',             -- online/offline/error
  last_capture_at TEXT, last_error TEXT
);

CREATE TABLE b_defect_class (                -- 展示用字典（从模型 config 派生，非主数据）
  code TEXT PRIMARY KEY,                     -- object_fault_type_XX
  name_cn TEXT NOT NULL,
  risk_level INTEGER, color TEXT,
  source_model_ref TEXT, updated_at TEXT NOT NULL
);

CREATE TABLE b_inspection (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_code TEXT NOT NULL, seq INTEGER NOT NULL,
  captured_at TEXT NOT NULL, received_at TEXT NOT NULL,
  template_version INTEGER,
  model_refs TEXT,                           -- JSON 数组
  verdict TEXT NOT NULL,                     -- auto_pass/recheck/manual
  verdict_reasons TEXT,                      -- JSON 数组
  boxes TEXT,                                -- JSON 数组（DetectBox）
  tiling_meta TEXT,                          -- JSON
  latency_ms INTEGER,
  image_path TEXT, thumb_path TEXT, image_md5 TEXT,
  pushed_status TEXT DEFAULT 'n/a',          -- n/a/pending/pushing/pushed/dead
  pushed_at TEXT, created_at TEXT NOT NULL,
  UNIQUE(station_code, seq)
);
CREATE INDEX idx_b_inspection_time ON b_inspection(captured_at);
CREATE INDEX idx_b_inspection_verdict ON b_inspection(verdict);

CREATE TABLE b_bad_image (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_code TEXT NOT NULL, seq INTEGER NOT NULL,
  captured_at TEXT, error_code TEXT NOT NULL,
  image_path TEXT, image_md5 TEXT, note TEXT,
  pushed_status TEXT DEFAULT 'pending',      -- pending/pushing/pushed/dead
  pushed_at TEXT, created_at TEXT NOT NULL,
  UNIQUE(station_code, seq)
);

CREATE TABLE b_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                        -- suspicious/bad
  ref_id INTEGER NOT NULL,                   -- b_inspection.id / b_bad_image.id
  idempotency_key TEXT NOT NULL UNIQUE,      -- {station}-{seq}-{kind}
  payload TEXT NOT NULL,                     -- JSON meta（跨平台契约 §3.2）
  attempts INTEGER DEFAULT 0,
  next_retry_at TEXT,
  status TEXT DEFAULT 'pending',             -- pending/pushing/pushed/dead
  last_error TEXT, created_at TEXT NOT NULL, pushed_at TEXT
);

CREATE TABLE b_stats_daily (
  day TEXT NOT NULL,                         -- YYYY-MM-DD（captured_at 本地日）
  station_code TEXT NOT NULL,
  total INTEGER DEFAULT 0, auto_pass INTEGER DEFAULT 0,
  recheck INTEGER DEFAULT 0, manual INTEGER DEFAULT 0,
  bad_count INTEGER DEFAULT 0,
  defect_counts TEXT,                        -- JSON {object_code: count}
  error_counts TEXT,                         -- JSON {error_code: count}
  avg_latency_ms INTEGER, p95_latency_ms INTEGER,
  PRIMARY KEY (day, station_code)
);

CREATE TABLE b_report (
  day TEXT PRIMARY KEY,
  html_path TEXT, csv_path TEXT,
  stats_json TEXT, generated_at TEXT
);

CREATE TABLE b_setting (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);

CREATE TABLE b_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT, action TEXT, object_type TEXT, object_id TEXT,
  detail TEXT, request_id TEXT, created_at TEXT NOT NULL
);
