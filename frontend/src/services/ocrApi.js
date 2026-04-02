import { API_BASE_URL } from './apiBase';

// ============ 任务 API（内存） ============

// 上传 PDF 文件进行 OCR 处理
export const uploadPdfForOcr = async (files) => {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });

    const response = await fetch(`${API_BASE_URL}/api/ocr/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!response.ok) {
        throw new Error('Upload failed');
    }

    return response.json();
};

// 获取所有 OCR 任务列表（内存）
export const getOcrTasks = async () => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/tasks`);
    if (!response.ok) {
        throw new Error('Failed to fetch task list');
    }
    return response.json();
};

// 获取 OCR 任务状态
export const getOcrTaskStatus = async (taskId) => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/status/${taskId}`);
    if (!response.ok) {
        throw new Error('Failed to fetch status');
    }
    return response.json();
};

// 删除 OCR 任务
export const deleteOcrTask = async (taskId) => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/task/${taskId}`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        throw new Error('Delete failed');
    }
    return response.json();
};

// ============ 结果 API（数据库） ============

// 获取所有 OCR 结果（数据库）
export const getOcrResults = async () => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/results`);
    if (!response.ok) {
        throw new Error('Failed to fetch result list');
    }
    return response.json();
};

// 获取单个 OCR 结果
export const getOcrResult = async (resultId) => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/results/${resultId}`);
    if (!response.ok) {
        throw new Error('Failed to fetch result');
    }
    return response.json();
};

// 删除 OCR 结果
export const deleteOcrResult = async (resultId) => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/results/${resultId}`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        throw new Error('Delete failed');
    }
    return response.json();
};

// 清空所有 OCR 结果
export const clearOcrResults = async () => {
    const response = await fetch(`${API_BASE_URL}/api/ocr/results`, {
        method: 'DELETE',
    });
    if (!response.ok) {
        throw new Error('Clear failed');
    }
    return response.json();
};
