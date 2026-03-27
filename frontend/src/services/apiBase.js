const normalizeBaseUrl = (value) => String(value || '').trim().replace(/\/+$/, '');

const fallbackApiBaseUrl = import.meta.env.PROD ? '/backend' : 'http://localhost:8000';

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
