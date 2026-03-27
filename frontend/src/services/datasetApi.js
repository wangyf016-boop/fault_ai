/**
 * 数据集嵌入 API 服务
 */

import { API_BASE_URL } from './apiBase';

/**
 * 上传并嵌入数据集
 */
export async function embedDataset(file, options = {}) {
    const { target = 'qdrant', collectionName = '', clearNeo4j = false } = options;
    
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target', target);
    if (collectionName) {
        formData.append('collection_name', collectionName);
    }
    formData.append('clear_neo4j', clearNeo4j.toString());
    
    const response = await fetch(`${API_BASE_URL}/api/datasets/embed`, {
        method: 'POST',
        body: formData,
    });
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '上传失败');
    }
    
    return response.json();
}

/**
 * 获取嵌入任务状态
 */
export async function getEmbeddingStatus(taskId) {
    const response = await fetch(`${API_BASE_URL}/api/datasets/embed/${taskId}`);
    
    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '获取状态失败');
    }
    
    return response.json();
}

/**
 * 轮询任务状态直到完成
 */
export async function pollEmbeddingStatus(taskId, onProgress, interval = 1000) {
    return new Promise((resolve, reject) => {
        const poll = async () => {
            try {
                const status = await getEmbeddingStatus(taskId);
                
                if (onProgress) {
                    onProgress(status);
                }
                
                if (status.status === 'completed') {
                    resolve(status);
                } else if (status.status === 'failed') {
                    reject(new Error(status.message));
                } else {
                    setTimeout(poll, interval);
                }
            } catch (error) {
                reject(error);
            }
        };
        
        poll();
    });
}

/**
 * 获取集合列表
 */
export async function listCollections() {
    const response = await fetch(`${API_BASE_URL}/api/datasets/collections`);
    
    if (!response.ok) {
        throw new Error('获取集合列表失败');
    }
    
    return response.json();
}

/**
 * 获取集合详情
 */
export async function getCollectionInfo(name) {
    const response = await fetch(`${API_BASE_URL}/api/datasets/collections/${name}/info`);
    
    if (!response.ok) {
        throw new Error('获取集合信息失败');
    }
    
    return response.json();
}

export async function getCollectionChunks(name, options = {}) {
    const { limit = 6, offset = 0 } = options;
    const params = new URLSearchParams({
        limit: limit.toString(),
        offset: offset.toString(),
    });
    const response = await fetch(`${API_BASE_URL}/api/datasets/collections/${encodeURIComponent(name)}/chunks?${params}`);

    if (!response.ok) {
        throw new Error('获取集合切片失败');
    }

    return response.json();
}

/**
 * 删除集合
 */
export async function deleteCollection(name) {
    const response = await fetch(`${API_BASE_URL}/api/datasets/collections/${encodeURIComponent(name)}`, {
        method: 'DELETE',
    });

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || '删除集合失败');
    }

    return response.json();
}

/**
 * 获取活跃（参与搜索）的 collection 名称列表
 */
export async function getActiveCollections() {
    const response = await fetch(`${API_BASE_URL}/api/datasets/collections/active`);
    if (!response.ok) throw new Error('获取活跃集合失败');
    return response.json(); // { active: string[] }
}

/**
 * 切换一个 collection 的启用/停用状态
 */
export async function toggleCollection(name) {
    const response = await fetch(
        `${API_BASE_URL}/api/datasets/collections/${encodeURIComponent(name)}/toggle`,
        { method: 'POST' }
    );
    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || '操作失败');
    }
    return response.json(); // { name, active: bool }
}
