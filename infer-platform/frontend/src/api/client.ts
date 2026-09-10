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
interface Envelope<T = unknown> {
  code: number;
  message: string;
  request_id: string;
  data: T;
}

/** 业务校验失败详情 */
interface FieldError {
  detail?: { fields?: Record<string, string> };
}

class ApiError extends Error {
  code: number;
  requestId: string;
  fields?: Record<string, string>;

  constructor(code: number, message: string, requestId: string, fields?: Record<string, string>) {
    super(message);
    this.code = code;
    this.requestId = requestId;
    this.fields = fields;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    ...options,
  });

  const envelope: Envelope<T & FieldError> = await res.json();

  if (envelope.code !== 0) {
    throw new ApiError(
      envelope.code,
      envelope.message,
      envelope.request_id,
      envelope.data?.detail?.fields
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
export type { Envelope, FieldError };