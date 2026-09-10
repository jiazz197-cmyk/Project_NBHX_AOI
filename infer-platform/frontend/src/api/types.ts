/**
 * 类型定义 —— 对齐平台B契约数据模型
 */

// ============ 健康检查 (§3.1) ============
export interface HealthData {
  status: string;
  gpu: { device: number; mem_used_gb: number; mem_total_gb: number };
  disk: { free_gb: number; used_pct: number };
  models: { model_ref: string; precision: string; loaded: boolean; vram_gb: number }[];
  stations: { total: number; enabled: number; online: number; with_template: number };
  inspect: { queue: number; concurrency: number };
  outbox: { pending: number; dead: number };
}

// ============ 模型库 (§3.2) ============
export interface ModelInfo {
  model_ref: string;
  skillname: string;
  precision: string;
  sha256: string;
  source_image: string;
  image_digest: string;
  status: string; // pulling/ready/active/failed
  classes: string[];
  received_at: string;
}

// ============ 工位 (§3.3) ============
export interface StationInfo {
  code: string;
  name: string;
  enabled: boolean;
  channel_id?: string;
  status: string; // online/offline/error
  last_capture_at?: string;
  last_error?: string;
  template_version: number; // 当前工位模板版本（0 = 未配置）
}

/** 工位模板（存 b_station.template_json，每工位一份；无"模板预设"概念） */
export interface StationTemplate {
  template_version: number;
  model_ref: string;
  skillname: string;
  tile_size: number;
  overlap: number;
  objects: TemplateObject[];
}

export interface TemplateObject {
  code: string;
  class_map: Record<string, string>;
  thresholds: { recheck_min: number; auto_min: number };
  risk_level: number;
}

// ============ 检测记录 (§3.5) ============
export interface DetectBox {
  object_code: string;
  score: number;
  model_ref: string;
  xyxy: [number, number, number, number];
}

export interface InspectionRecord {
  id: number;
  station_code: string;
  seq: number;
  captured_at: string;
  verdict: string; // auto_pass/recheck/manual
  verdict_reasons: string[];
  boxes: DetectBox[];
  latency_ms: number;
  template_version: number;
  pushed_status: string; // n/a/pending/pushing/pushed/dead
}

// ============ 统计 (§3.6) ============
export interface StatsSummary {
  total: number;
  auto_pass: number;
  recheck: number;
  manual: number;
  bad_count: number;
  pass_rate: number;
  defect_topn: { code: string; name_cn: string; count: number; image_count: number }[];
  avg_latency_ms: number;
  p95_latency_ms: number;
  stations_online: number;
  stations_total: number;
}

export interface TrendPoint {
  time: string;
  total: number;
  auto_pass: number;
  recheck: number;
  manual: number;
  avg_latency_ms: number;
}

export interface ErrorStats {
  bad_by_code: Record<string, number>;
  suspicious_by_code: Record<string, number>;
  suspicious_by_verdict: Record<string, number>;
  top_stations: { station_code: string; bad_count: number; suspicious_count: number }[];
  pushed_status: { pushed: number; pending: number; dead: number };
}

// ============ 日报 (§3.7) ============
export interface DailyReport {
  day: string;
  total: number;
  auto_pass: number;
  recheck: number;
  manual: number;
  bad_count: number;
  html_path: string;
  csv_path: string;
}