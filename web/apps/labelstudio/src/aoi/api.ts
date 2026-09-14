/**
 * aoi API 调用基础封装：统一解包信封 `{code, message, request_id, data}`（契约 §2.3）。
 * SPA 走 session cookie 鉴权；CSRF 由上游 `core.middleware.DisableCSRF` 对 API 请求豁免。
 */
export async function aoiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || !body || body.code !== 0) {
    throw new Error(body?.message ?? `aoi request failed: ${response.status}`);
  }
  return body.data as T;
}
