import { API_BASE_URL } from './apiBase';

const handleResponse = async (response) => {
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(errorBody || `Request failed with status ${response.status}`);
  }
  return response.json();
};

export const fetchHealth = async () => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10000); // 10秒超时
  try {
    const res = await fetch(`${API_BASE_URL}/health`, { signal: controller.signal });
    clearTimeout(timeoutId);
    return handleResponse(res);
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') throw new Error('Health check timeout');
    throw error;
  }
};

export const fetchSessions = async () => {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000); // 15秒超时
  try {
    const res = await fetch(`${API_BASE_URL}/conversations`, { signal: controller.signal });
    clearTimeout(timeoutId);
    return handleResponse(res);
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') throw new Error('Failed to fetch sessions: timeout');
    throw error;
  }
};

export const fetchMessages = async (conversationId) => {
  if (!conversationId) return [];
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000); // 15秒超时
  try {
    const res = await fetch(`${API_BASE_URL}/conversations/${conversationId}/messages`, { signal: controller.signal });
    clearTimeout(timeoutId);
    return handleResponse(res);
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') throw new Error('Failed to fetch messages: timeout');
    throw error;
  }
};

export const sendMessage = async ({ message, conversationId, queryMode = 'auto', followupRecords = null, inlineFollowup = false, stream = false, onMeta, onRoute, onRecords, onContent, onDone, onError, onDiagnosisKg, onDiagnosisRecords, onDiagnosisFlowchart, onFlowPlan }) => {
  // 创建 AbortController 用于超时控制
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 300000); // 5分钟超时
  
  try {
    console.log('[QueryMode][frontend][request]', {
      queryMode,
      stream,
      conversationId,
      messagePreview: String(message || '').slice(0, 60),
    });
    // 从 localStorage 读取前端配置，通过 headers 传递给后端
    const llmConfig = JSON.parse(localStorage.getItem('llm_config') || '{}');
    const headers = { 'Content-Type': 'application/json' };
    if (llmConfig.llm_type === 'ollama' && llmConfig.ollama_base_url) {
      headers['x-ollama-baseurl'] = llmConfig.ollama_base_url;
    }
    if (llmConfig.llm_type === 'ollama' && llmConfig.ollama_model) {
      headers['x-ollama-model'] = llmConfig.ollama_model;
    }
    
    const res = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ message, conversation_id: conversationId, stream, query_mode: queryMode, followup_records: followupRecords, inline_followup: inlineFollowup }),

      signal: controller.signal,
      keepalive: true, // 保持连接活跃
    });
    
    clearTimeout(timeoutId); // 清除超时定时器

    if (!stream) {
      return handleResponse(res);
    }

    // 流式处理
    if (!res.ok) {
      const errorBody = await res.text();
      throw new Error(errorBody || `Request failed with status ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    
    // SSE 使用 \n\n 分隔事件
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';

    for (const event of events) {
      const lines = event.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const jsonStr = line.slice(6);
            console.log('[SSE] Raw data:', jsonStr.substring(0, 100));
            const data = JSON.parse(jsonStr);
            console.log('[SSE] Parsed type:', data.type);
            
            if (data.type === 'meta') {
              onMeta?.(data);
            } else if (data.type === 'route') {
              onRoute?.(data.route);
            } else if (data.type === 'records') {
              console.log('[SSE] Records received:', data.records?.length, 'show_graph:', data.show_graph);
              if (data.records && onRecords) {
                onRecords(data.records, {
                  showGraph: data.show_graph || false,
                  neo4jDisplayMode: data.neo4j_display_mode || null,
                  neo4jKeyword: data.neo4j_keyword || null,
                  neo4jQueryMode: data.neo4j_query_mode || null,
                });
              }
            } else if (data.type === 'diagnosis_kg') {
              console.log('[SSE] Diagnosis KG received:', data.graph?.nodes?.length, 'nodes');
              onDiagnosisKg?.({ graph: data.graph, summary: data.summary });
            } else if (data.type === 'diagnosis_records') {
              console.log('[SSE] Diagnosis Records received:', data.records?.length);
              onDiagnosisRecords?.({ records: data.records, summary: data.summary });
            } else if (data.type === 'diagnosis_flowchart') {
              console.log('[SSE] Diagnosis Flowchart received:', data.records?.length);
              onDiagnosisFlowchart?.({ records: data.records, summary: data.summary, plan: data.plan });
            } else if (data.type === 'flow_plan') {
              console.log('[SSE] Flow plan received:', data.plan?.steps?.length, 'steps');
              onFlowPlan?.(data.plan);
            } else if (data.type === 'content') {
              onContent?.(data.content);
            } else if (data.type === 'done') {
              onDone?.();
            } else if (data.type === 'error') {
              onError?.(data.error);
            }
          } catch (e) {
            console.error('[SSE] Parse error:', e.message, 'Line:', line.substring(0, 100));
          }
        }
      }
    }
  }
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error('Request timed out, please try again.');
    }
    throw error;
  }
};

export const deleteSession = async (conversationId) => {
  const res = await fetch(`${API_BASE_URL}/conversations/${conversationId}`, {
    method: 'DELETE',
  });
  return handleResponse(res);
};
