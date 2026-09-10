/**
 * API 客户端 —— 对齐平台B契约 §1.2 统一信封与错误码
 *
 * 信封格式：
 *   成功: { code:0, message:"ok", request_id:"req-...", data:{...} }
 *   失败: { code:4xxxx, message:"...", request_id:"req-...", data:{ detail: {...} } }
 *
 * 错误码（契约 §1.2）：
 *   40010 坏图/参数不可读
 *   40401 资源不存在
 *   40402 工位未注册未启用
 *   40900 状态冲突
 *   42200 业务校验失败（data.detail.fields）
 *   42900 队列背压
 *   50000 内部错误
 *   50300 未就绪
 */

const BASE_URL = '/api/v1';

/** 统一信封返回 */
export interface Envelope<T = unknown> {
  code: number;
  message: string;
  request_id: string;
  data: T;
}

/** 业务校验失败详情：42200 为 {字段:消息}；40010 参数错误为 pydantic 校验对象数组 */
export type FieldErrors = Record<string, string> | unknown[];

interface FieldError {
  detail?: { fields?: FieldErrors };
}

class ApiError extends Error {
  code: number;
  requestId: string;
  fields?: FieldErrors;

  constructor(code: number, message: string, requestId: string, fields?: FieldErrors) {
    super(message);
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

/** 生成请求链路 ID（契约 §1.3 X-Request-ID） */
function genRequestId(): string {
  return `req-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const requestId = genRequestId();

  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId,
      ...options?.headers,
    },
    ...options,
  });

  // 解析信封；后端可能返回非 JSON（如框架默认 404），做容错
  let envelope: Envelope<T & FieldError> | null = null;
  try {
    envelope = (await res.json()) as Envelope<T & FieldError>;
  } catch {
    envelope = null;
  }

  if (!res.ok || envelope === null || envelope.code !== 0) {
    throw new ApiError(
      envelope?.code ?? res.status,
      envelope?.message ?? `HTTP ${res.status}`,
      envelope?.request_id ?? requestId,
      envelope?.data?.detail?.fields,
    );
  }

  return envelope.data;
}

/** GET 请求 */
export async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const search = params ? '?' + new URLSearchParams(params).toString() : '';
  return request<T>(`${path}${search}`);
}

/** POST 请求 */
export async function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/** PUT 请求 */
export async function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: 'PUT',
    body: body ? JSON.stringify(body) : undefined,
  });
}

/** DELETE 请求 */
export async function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'DELETE' });
}

export { ApiError };