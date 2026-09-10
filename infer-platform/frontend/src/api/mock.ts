/**
 * Mock 数据 —— 对齐平台B契约
 *
 * 后端接口未就绪时，前端用这些 mock 数据独立开发。
 * 后续接入真实后端时，只需删除 mock 目录，改为调用 api/client.ts 里的 get/post/put/del。
 *
 * 数据格式对齐契约：
 *   - §3.1 健康检查: GET /health
 *   - §3.2 模型库: GET /models, POST /models/pull
 *   - §3.3 工位与模板: CRUD /stations, PUT /stations/{code}/template
 *   - §3.5 检测记录: GET /inspections
 *   - §3.6 统计: GET /stats/summary, GET /stats/trend, GET /stats/errors
 *   - §3.7 日报: GET /reports/daily
 */

import type { HealthData, ModelInfo, StationInfo, StationTemplate, InspectionRecord, StatsSummary, TrendPoint, ErrorStats, DailyReport, OutboxItem, BadImage } from './types';

// ============ 健康检查 (§3.1) ============
export const mockHealth: HealthData = {
  status: 'UP',
  gpu: { device: 0, mem_used_gb: 3.2, mem_total_gb: 23.7 },
  disk: { free_gb: 120.4, used_pct: 62 },
  models: [{ model_ref: '3-yolo@ds1', precision: 'fp32', loaded: true, vram_gb: 3.8 }],
  stations: { total: 8, enabled: 8, online: 7, with_template: 8 },
  inspect: { queue: 0, concurrency: 2 },
  outbox: { pending: 3, dead: 0 },
};

// ============ 模型库 (§3.2) ============
export const mockModels: ModelInfo[] = [
  {
    model_ref: '3-yolo@ds1',
    skillname: 'ObjectDetection',
    precision: 'fp32',
    sha256: '9f2c8e1a...',
    source_image: 'docker.io/corp/aoi-model:3-yolo-ds1',
    image_digest: 'sha256:abc123...',
    status: 'ready',
    classes: ['object_fault_type_01', 'object_fault_type_02'],
    received_at: '2026-09-08T09:00:00Z',
  },
  {
    model_ref: '2-yolo@ds1',
    skillname: 'ObjectDetection',
    precision: 'fp32',
    sha256: '8e1d7c3b...',
    source_image: 'docker.io/corp/aoi-model:2-yolo-ds1',
    image_digest: 'sha256:def456...',
    status: 'ready',
    classes: ['object_fault_type_01', 'object_fault_type_02'],
    received_at: '2026-09-01T10:00:00Z',
  },
];

// ============ 工位 (§3.3) ============
export const mockStations: StationInfo[] = [
  { code: 'ST01', name: '1号线-左门板', enabled: true, channel_id: 'ch01', status: 'online', last_capture_at: '2026-09-08T08:31:00Z', template_version: 3 },
  { code: 'ST02', name: '1号线-右门板', enabled: true, channel_id: 'ch02', status: 'online', last_capture_at: '2026-09-08T08:30:58Z', template_version: 3 },
  { code: 'ST03', name: '2号线-左门板', enabled: true, channel_id: 'ch03', status: 'online', last_capture_at: '2026-09-08T08:30:55Z', template_version: 2 },
  { code: 'ST04', name: '2号线-右门板', enabled: true, channel_id: 'ch04', status: 'online', last_capture_at: '2026-09-08T08:30:52Z', template_version: 2 },
  { code: 'ST05', name: '3号线-左门板', enabled: true, channel_id: 'ch05', status: 'error', last_capture_at: '2026-09-08T08:20:00Z', last_error: '相机断连', template_version: 3 },
  { code: 'ST06', name: '3号线-右门板', enabled: true, channel_id: 'ch06', status: 'online', last_capture_at: '2026-09-08T08:30:45Z', template_version: 3 },
  { code: 'ST07', name: '4号线-左门板', enabled: false, channel_id: 'ch07', status: 'offline', template_version: 0 },
  { code: 'ST08', name: '4号线-右门板', enabled: false, channel_id: 'ch08', status: 'offline', template_version: 0 },
];

// ============ '2026-09-01T10:00:00Z',
  },
  {
    id: 'tpl-interior',
    name: '内饰件-通用检测',
    model_ref: '3-yolo@ds1',
    skillname: 'ObjectDetection',
    tile_size: 1024,
    overlap: 0.25,
    objects: [
      { code: 'object_fault_type_01', class_map: { '0': 'object_fault_type_01' }, thresholds: { recheck_min: 0.50, auto_min: 0.85 }, risk_level: 3 },
      { code: 'object_fault_type_02', class_map: { '1': 'object_fault_type_02' }, thresholds: { recheck_min: 0.50, auto_min: 0.85 }, risk_level: 2 },
    ],
    updated_at: '2026-09-05T14:00:00Z',
  },
  {
    id: 'tpl-highp',
    name: '高精度复检模板',
    model_ref: '3-yolo@ds1',
    skillname: 'ObjectDetection',
    tile_size: 1920,
    overlap: 0.3,
    objects: [
      { code: 'object_fault_type_01', class_map: { '0': 'object_fault_type_01' }, thresholds: { recheck_min: 0.75, auto_min: 0.95 }, risk_level: 3 },
      { code: 'object_fault_type_02', class_map: { '1': 'object_fault_type_02' }, thresholds: { recheck_min: 0.70, auto_min: 0.93 }, risk_level: 2 },
    ],
    updated_at: '2026-09-07T16:00:00Z',
  },
];

// ============ 检测记录 (§3.5) ============
export const mockInspections: InspectionRecord[] = [
  { id: 98765, station_code: 'ST01', seq: 1042, captured_at: '2026-09-08T08:31:00Z', verdict: 'recheck', verdict_reasons: ['mid_score'], boxes: [{ object_code: 'object_fault_type_01', score: 0.72, model_ref: '3-yolo@ds1', xyxy: [100, 200, 180, 260] }], latency_ms: 1400, template_version: 3, pushed_status: 'pushed' },
  { id: 98764, station_code: 'ST01', seq: 1041, captured_at: '2026-09-08T08:30:58Z', verdict: 'auto_pass', verdict_reasons: [], boxes: [], latency_ms: 1200, template_version: 3, pushed_status: 'n/a' },
  { id: 98763, station_code: 'ST02', seq: 2041, captured_at: '2026-09-08T08:30:55Z', verdict: 'recheck', verdict_reasons: ['mid_score'], boxes: [{ object_code: 'object_fault_type_02', score: 0.65, model_ref: '3-yolo@ds1', xyxy: [200, 150, 280, 230] }], latency_ms: 1350, template_version: 3, pushed_status: 'pushing' },
  { id: 98762, station_code: 'ST03', seq: 3041, captured_at: '2026-09-08T08:30:50Z', verdict: 'manual', verdict_reasons: ['low_score'], boxes: [{ object_code: 'object_fault_type_01', score: 0.35, model_ref: '3-yolo@ds1', xyxy: [50, 300, 130, 380] }], latency_ms: 1500, template_version: 2, pushed_status: 'pending' },
  { id: 98761, station_code: 'ST05', seq: 5041, captured_at: '2026-09-08T08:20:00Z', verdict: 'manual', verdict_reasons: ['model_error'], boxes: [], latency_ms: 0, template_version: 3, pushed_status: 'dead' },
];

// ============ 统计 (§3.6) ============
export const mockStatsSummary: StatsSummary = {
  total: 12480,
  auto_pass: 11232,
  recheck: 936,
  manual: 312,
  bad_count: 45,
  pass_rate: 90.0,
  defect_topn: [
    { code: 'object_fault_type_01', name_cn: '划伤', count: 520, image_count: 380 },
    { code: 'object_fault_type_02', name_cn: '凹坑', count: 416, image_count: 290 },
  ],
  avg_latency_ms: 1350,
  p95_latency_ms: 2100,
  stations_online: 6,
  stations_total: 8,
};

export const mockTrend: TrendPoint[] = Array.from({ length: 24 }, (_, i) => ({
  time: `${String(i).padStart(2, '0')}:00`,
  total: 500 + Math.floor(Math.random() * 100),
  auto_pass: 440 + Math.floor(Math.random() * 80),
  recheck: 40 + Math.floor(Math.random() * 20),
  manual: 15 + Math.floor(Math.random() * 10),
  avg_latency_ms: 1200 + Math.floor(Math.random() * 800),
}));

export const mockErrorStats: ErrorStats = {
  bad_by_code: { capture_failed: 20, decode_failed: 15, timeout: 8, model_error: 2 },
  suspicious_by_code: { object_fault_type_01: 520, object_fault_type_02: 416 },
  suspicious_by_verdict: { recheck: 936, manual: 312 },
  top_stations: [
    { station_code: 'ST01', bad_count: 8, suspicious_count: 200 },
    { station_code: 'ST02', bad_count: 5, suspicious_count: 180 },
  ],
  pushed_status: { pushed: 1200, pending: 30, dead: 5 },
};

// ============ 日报 (§3.7) ============
export const mockReports: DailyReport[] = [
  { day: '2026-09-08', total: 12480, auto_pass: 11232, recheck: 936, manual: 312, bad_count: 45, html_path: '/data/reports/2026-09-08.html', csv_path: '/data/reports/2026-09-08.csv' },
  { day: '2026-09-07', total: 11800, auto_pass: 10620, recheck: 880, manual: 300, bad_count: 40, html_path: '/data/reports/2026-09-07.html', csv_path: '/data/reports/2026-09-07.csv' },
  { day: '2026-09-06', total: 12100, auto_pass: 10890, recheck: 910, manual: 300, bad_count: 42, html_path: '/data/reports/2026-09-06.html', csv_path: '/data/reports/2026-09-06.csv' },
];

// ============ 回传队列 (§3.1 system/outbox) ============
export const mockOutbox: OutboxItem[] = [
  { id: 31, kind: 'suspicious', ref_id: 98762, idempotency_key: 'ST03-3041-suspicious', attempts: 0, status: 'pending', created_at: '2026-09-08T08:30:50Z' },
  { id: 30, kind: 'suspicious', ref_id: 98763, idempotency_key: 'ST02-2041-suspicious', attempts: 2, next_retry_at: '2026-09-08T08:32:00Z', status: 'pushing', created_at: '2026-09-08T08:30:55Z' },
  { id: 29, kind: 'suspicious', ref_id: 98761, idempotency_key: 'ST05-5041-suspicious', attempts: 5, next_retry_at: '2026-09-08T09:30:00Z', status: 'dead', last_error: 'connect timeout after 60s', created_at: '2026-09-08T08:20:00Z' },
  { id: 28, kind: 'bad', ref_id: 12, idempotency_key: 'ST05-5040-bad', attempts: 5, next_retry_at: '2026-09-08T09:20:00Z', status: 'dead', last_error: '40100 internal token rejected', created_at: '2026-09-08T08:19:58Z' },
];

// ============ 坏图清单 (§3.5 bad-images) ============
export const mockBadImages: BadImage[] = [
  { id: 12, station_code: 'ST05', seq: 5040, captured_at: '2026-09-08T08:19:58Z', error_code: 'capture_failed', note: '相机断连', pushed_status: 'dead', created_at: '2026-09-08T08:19:58Z' },
  { id: 11, station_code: 'ST02', seq: 2040, captured_at: '2026-09-08T08:19:50Z', error_code: 'decode_failed', image_md5: 'c4d2...a9', pushed_status: 'pending', created_at: '2026-09-08T08:19:50Z' },
  { id: 10, station_code: 'ST01', seq: 1040, captured_at: '2026-09-08T08:19:42Z', error_code: 'timeout', pushed_status: 'pushed', pushed_at: '2026-09-08T08:20:10Z', created_at: '2026-09-08T08:19:42Z' },
];