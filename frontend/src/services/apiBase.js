const normalizeBaseUrl = (value) => String(value || '').trim().replace(/\/+$/, '');

const fallbackApiBaseUrl = (() => {
  if (import.meta.env.PROD) return '/backend';

  // Dev 模式下优先使用当前访问页面的主机名，避免“远程打开前端却请求到本机 localhost”
  // 的情况（例如 Ubuntu 服务器部署，Windows 浏览器访问）。
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  return `http://${host}:8000`;
})();

// Prefer the canonical Vite key, but keep legacy aliases to avoid breaking
// existing local setups while we consolidate configuration.
const rawApiBaseUrl =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  import.meta.env.VITE_API_BASE ||
  fallbackApiBaseUrl;

export const API_BASE_URL = normalizeBaseUrl(rawApiBaseUrl);

export const buildApiUrl = (path = '') => {
  const normalizedPath = String(path || '').trim();
  if (!normalizedPath) return API_BASE_URL;
  if (/^https?:\/\//i.test(normalizedPath)) return normalizedPath;
  return `${API_BASE_URL}${normalizedPath.startsWith('/') ? '' : '/'}${normalizedPath}`;
};
