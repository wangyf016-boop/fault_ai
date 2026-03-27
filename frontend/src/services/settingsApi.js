import { API_BASE_URL } from './apiBase';

const normalizeBaseUrl = (url) => {
    if (!url) return '';
    return url.replace(/\/$/, '');
};

export async function getLLMConfig() {
    const response = await fetch(`${API_BASE_URL}/settings/llm`);
    if (!response.ok) {
        throw new Error('获取配置失败');
    }
    return response.json();
}

export async function saveLLMConfig(config) {
    const response = await fetch(`${API_BASE_URL}/settings/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    });
    if (!response.ok) {
        throw new Error('保存配置失败');
    }
    return response.json();
}

export async function testLLMConnection(config) {
    const response = await fetch(`${API_BASE_URL}/settings/llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    });
    if (!response.ok) {
        throw new Error('测试请求失败');
    }
    return response.json();
}

export async function testOllamaConnection(config) {
    const baseUrl = normalizeBaseUrl(config?.ollama_base_url || 'http://127.0.0.1:11434');
    const targetModel = (config?.ollama_model || '').trim();

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000);

    try {
        const response = await fetch(`${baseUrl}/api/tags`, {
            signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
            return {
                success: false,
                error: `Ollama 返回状态码 ${response.status}`,
            };
        }

        const data = await response.json();
        const models = Array.isArray(data?.models) ? data.models : [];
        const modelNames = models.map((m) => m?.name).filter(Boolean);

        if (targetModel) {
            const found = modelNames.some((name) => name.toLowerCase() === targetModel.toLowerCase());
            return {
                success: found,
                modelFound: found,
                response: found
                    ? `已连接，模型 ${targetModel} 可用`
                    : `已连接，但未找到模型 ${targetModel}`,
                models: modelNames,
            };
        }

        return {
            success: true,
            modelFound: true,
            response: '已连接，Ollama 服务可用',
            models: modelNames,
        };
    } catch (error) {
        clearTimeout(timeoutId);
        if (error?.name === 'AbortError') {
            return { success: false, error: '连接超时，请检查 Ollama 服务或网络' };
        }
        return { success: false, error: error?.message || '无法连接到 Ollama 服务' };
    }
}

// ======== 提示词配置 API ========

export async function getPromptsConfig() {
    const response = await fetch(`${API_BASE_URL}/settings/prompts`);
    if (!response.ok) {
        throw new Error('获取提示词配置失败');
    }
    return response.json();
}

export async function savePromptsConfig(config) {
    const response = await fetch(`${API_BASE_URL}/settings/prompts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
    });
    if (!response.ok) {
        throw new Error('保存提示词配置失败');
    }
    return response.json();
}

export async function resetPromptsConfig() {
    const response = await fetch(`${API_BASE_URL}/settings/prompts/reset`, {
        method: 'POST',
    });
    if (!response.ok) {
        throw new Error('重置提示词失败');
    }
    return response.json();
}
