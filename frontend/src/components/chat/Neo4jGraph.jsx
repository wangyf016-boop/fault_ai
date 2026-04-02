import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Network, DataSet } from 'vis-network/standalone';
import { X, Search, Maximize2, Minimize2, ChevronDown, ChevronRight, Plus, History, RotateCcw, RefreshCw } from 'lucide-react';
import { buildApiUrl } from '../../services/apiBase';

// 节点类型颜色配置
const NODE_COLORS = {
  Problem: { background: '#ef4444', border: '#dc2626', highlight: { background: '#f87171', border: '#dc2626' } },
  Cause: { background: '#f97316', border: '#ea580c', highlight: { background: '#fb923c', border: '#ea580c' } },
  Solution: { background: '#4827AF', border: '#341C7D', highlight: { background: '#7E60DC', border: '#341C7D' } },
  Area: { background: '#3b82f6', border: '#2563eb', highlight: { background: '#60a5fa', border: '#2563eb' } },
  Equipment: { background: '#14b8a6', border: '#0d9488', highlight: { background: '#2dd4bf', border: '#0d9488' } },
  Component: { background: '#fffb00ff', border: '#ffc400ff', highlight: { background: '#d4d400', border: '#7e6000' } },
};

// 类型显示映射
const TYPE_LABELS = {
  Problem: '问题',
  Cause: '原因',
  Solution: '解决方案',
  Area: '区域',
  Equipment: '设备',
  Component: '部件'
};

const TYPE_LEVELS = {
  Area: 1,
  Equipment: 2,
  Component: 3,
  Problem: 4,
  Cause: 5,
  Solution: 6,
};

const DEFAULT_RELATION_TYPE = 'RELATED_TO';
const RELATION_TYPE_BY_NODE_PAIR = {
  'Area->Equipment': 'INCLUDE',
  'Equipment->Component': 'HAS_PART',
  'Component->Problem': 'HAS_FAULT',
  'Problem->Cause': 'CAUSED_BY',
  'Cause->Solution': 'SOLVED_BY',
};

function extractNodeTypeValue(node) {
  if (!node || typeof node !== 'object') return '';
  const rawData = node.rawData && typeof node.rawData === 'object' ? node.rawData : {};
  return String(
    node.nodeType
      || node.type
      || rawData.type
      || rawData.labels?.[0]
      || node.labels?.[0]
      || ''
  ).trim();
}

function suggestRelationTypeByNodes(fromNode, toNodeType) {
  const fromType = extractNodeTypeValue(fromNode);
  const targetType = String(toNodeType || '').trim();
  if (!fromType || !targetType) return DEFAULT_RELATION_TYPE;
  return RELATION_TYPE_BY_NODE_PAIR[`${fromType}->${targetType}`] || DEFAULT_RELATION_TYPE;
}

async function parseApiError(response, fallbackMessage) {
  const fallback = `${fallbackMessage} (HTTP ${response.status})`;
  try {
    const data = await response.clone().json();
    if (data && typeof data === 'object') {
      const detail = String(data.detail || data.message || '').trim();
      if (detail) return `${fallbackMessage}: ${detail}`;
    }
  } catch {
    // no-op, fallback to text parse
  }
  try {
    const text = String(await response.text()).trim();
    if (text) return `${fallbackMessage}: ${text}`;
  } catch {
    // no-op
  }
  return fallback;
}

const GRAPH_REQUEST_TIMEOUT = 60000;

const EMBEDDED_GRAPH_CACHE = new Map();
const EMBEDDED_GRAPH_CACHE_MAX = 80;

function getEmbeddedGraphCache(key) {
  if (!key || !EMBEDDED_GRAPH_CACHE.has(key)) return null;
  const value = EMBEDDED_GRAPH_CACHE.get(key);
  EMBEDDED_GRAPH_CACHE.delete(key);
  EMBEDDED_GRAPH_CACHE.set(key, value);
  return value;
}

function setEmbeddedGraphCache(key, data) {
  if (!key || !data) return;
  if (EMBEDDED_GRAPH_CACHE.has(key)) {
    EMBEDDED_GRAPH_CACHE.delete(key);
  }
  EMBEDDED_GRAPH_CACHE.set(key, data);
  if (EMBEDDED_GRAPH_CACHE.size > EMBEDDED_GRAPH_CACHE_MAX) {
    const oldestKey = EMBEDDED_GRAPH_CACHE.keys().next().value;
    if (oldestKey) EMBEDDED_GRAPH_CACHE.delete(oldestKey);
  }
}


// 从描述中提取故障现象部分
function extractPhenomenon(description) {
  if (!description) return null;
  // 格式: "故障现象：xxx | 原因：xxx | 解决方案：xxx"
  if (description.includes('故障现象：')) {
    const start = description.indexOf('故障现象：') + '故障现象：'.length;
    const end = description.indexOf(' |', start);
    if (end > start) {
      return description.slice(start, end).trim();
    }
    // 没有找到 |，返回故障现象后的全部内容
    return description.slice(start).trim();
  }
  return null;
}

// 从节点中提取显示名称
function extractDisplayName(node) {
  if (!node) return '未知';
  
  // 获取节点类型
  const nodeType = node.type || node.labels?.[0];
  
  // Version2: 所有节点统一用 name 属性
  // 优先从 props/properties 中取 name
  if (node.props?.name) return node.props.name;
  if (node.properties?.name) return node.properties.name;
  
  // 主图 API 返回的节点直接有 name 字段
  if (node.name) return node.name;
  
  // 邻居 API 返回的节点有 label 字段
  if (node.label) return node.label;
  
  // 兼容旧版 description 属性
  if (node.props?.description) return node.props.description;
  if (node.properties?.description) return node.properties.description;
  
  return '未知';
}

// 截断文本
function truncateText(text, maxLen = 15) {
  if (!text) return '';
  return text.length > maxLen ? text.slice(0, maxLen) + '...' : text;
}

function getTypeDisplayText(nodeType) {
  const raw = String(nodeType || '').trim() || 'Unknown';
  const zh = TYPE_LABELS[raw] || raw;
  return `${zh} (${raw})`;
}

function buildNodeLabel(displayName, nodeType) {
  return truncateText(displayName);
}

function normalizeNodeName(value) {
  return String(value || '').trim().toLowerCase();
}

function formatPathSource(detail) {
  if (!detail || typeof detail !== 'object') return '';
  const year = String(detail.source_year || '').trim();
  const csvLine = Number(detail.source_csv_line);
  if (year && Number.isFinite(csvLine) && csvLine > 0) {
    return `${year} CSV#${csvLine}`;
  }
  if (year) {
    return `${year}`;
  }
  return '';
}

function parsePathText(pathText) {
  const raw = String(pathText || '').trim();
  if (!raw) return null;

  const relRegex = /\s-\[([^\]]+)\]->\s/g;
  const relTypes = [];
  const nodeNames = [];
  let cursor = 0;
  let match;

  while ((match = relRegex.exec(raw)) !== null) {
    const nodePart = raw.slice(cursor, match.index).trim();
    if (nodePart) nodeNames.push(nodePart);
    relTypes.push(String(match[1] || '').trim());
    cursor = relRegex.lastIndex;
  }

  const tailNode = raw.slice(cursor).trim();
  if (tailNode) nodeNames.push(tailNode);

  if (nodeNames.length < 2 || relTypes.length !== nodeNames.length - 1) {
    return null;
  }

  return { text: raw, nodeNames, relTypes };
}

function buildPathEntries(pathItems, nodes, edges) {
  const nodeNameToIds = new Map();
  (nodes || []).forEach((node) => {
    const nodeId = String(node.id);
    const displayName = extractDisplayName(node);
    const key = normalizeNodeName(displayName);
    if (!key) return;
    if (!nodeNameToIds.has(key)) {
      nodeNameToIds.set(key, new Set());
    }
    nodeNameToIds.get(key).add(nodeId);
  });

  const edgeIndex = new Map();
  (edges || []).forEach((edge) => {
    const source = String(edge.from ?? edge.source);
    const target = String(edge.to ?? edge.target);
    const relType = String(edge.label ?? edge.type ?? '').trim();
    const key = `${source}|${relType}|${target}`;
    edgeIndex.set(key, String(edge.id));
  });

  return (pathItems || []).map((item, idx) => {
    const detail = (item && typeof item === 'object') ? item : { text: String(item || '').trim() };
    const text = String(detail.text || '').trim();
    const parsed = parsePathText(text);
    const sourceText = formatPathSource(detail);
    const entry = {
      id: `path-${idx}`,
      text,
      sharedRow: String(detail.shared_row || '').trim() || null,
      sourceYear: String(detail.source_year || '').trim() || null,
      sourceCsvLine: Number.isFinite(Number(detail.source_csv_line)) ? Number(detail.source_csv_line) : null,
      sourceCsvRow: Number.isFinite(Number(detail.source_csv_row)) ? Number(detail.source_csv_row) : null,
      sourceCsvFile: String(detail.source_csv_file || '').trim() || null,
      sourceText,
      nodeIds: new Set(),
      edgeIds: new Set(),
    };

    if (!parsed) return entry;

    parsed.nodeNames.forEach((name) => {
      const ids = nodeNameToIds.get(normalizeNodeName(name));
      if (!ids) return;
      ids.forEach((id) => entry.nodeIds.add(id));
    });

    for (let i = 0; i < parsed.relTypes.length; i += 1) {
      const fromIds = nodeNameToIds.get(normalizeNodeName(parsed.nodeNames[i]));
      const toIds = nodeNameToIds.get(normalizeNodeName(parsed.nodeNames[i + 1]));
      const relType = parsed.relTypes[i];
      if (!fromIds || !toIds) continue;
      fromIds.forEach((fromId) => {
        toIds.forEach((toId) => {
          const edgeId = edgeIndex.get(`${fromId}|${relType}|${toId}`);
          if (edgeId) entry.edgeIds.add(edgeId);
        });
      });
    }

    return entry;
  });
}

function buildLayeredCircleLayout(nodes, links) {
  const LEVEL_ORDER = ['Area', 'Equipment', 'Component', 'Problem', 'Cause', 'Solution'];
  const TYPE_RADIUS = {
    Area: 60,
    Equipment: 150,
    Component: 260,
    Problem: 380,
    Cause: 510,
    Solution: 650,
  };

  const nodeMap = new Map((nodes || []).map((node) => [String(node.id), node]));
  const adjacency = new Map();
  Array.from(nodeMap.keys()).forEach((id) => adjacency.set(id, new Set()));

  (links || []).forEach((link) => {
    const source = String(link.source);
    const target = String(link.target);
    if (!adjacency.has(source)) adjacency.set(source, new Set());
    if (!adjacency.has(target)) adjacency.set(target, new Set());
    adjacency.get(source).add(target);
    adjacency.get(target).add(source);
  });

  const visited = new Set();
  const groups = [];
  for (const id of nodeMap.keys()) {
    if (visited.has(id)) continue;
    const queue = [id];
    const group = [];
    visited.add(id);
    while (queue.length) {
      const current = queue.shift();
      group.push(current);
      (adjacency.get(current) || []).forEach((next) => {
        if (!visited.has(next)) {
          visited.add(next);
          queue.push(next);
        }
      });
    }
    groups.push(group);
  }

  const componentSpacingX = 1600;
  const componentSpacingY = 1200;
  const cols = Math.max(1, Math.ceil(Math.sqrt(groups.length || 1)));
  const positions = new Map();

  const hashCode = (value) => {
    const text = String(value || '');
    let hash = 0;
    for (let i = 0; i < text.length; i += 1) {
      hash = ((hash << 5) - hash) + text.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash);
  };

  groups.forEach((groupIds, groupIndex) => {
    const row = Math.floor(groupIndex / cols);
    const col = groupIndex % cols;
    const centerX = (col - (cols - 1) / 2) * componentSpacingX;
    const centerY = row * componentSpacingY;

    const groupedByType = new Map(LEVEL_ORDER.map((type) => [type, []]));
    const unknown = [];
    groupIds.forEach((id) => {
      const node = nodeMap.get(id);
      const nodeType = node?.type || node?.labels?.[0] || 'Unknown';
      if (groupedByType.has(nodeType)) {
        groupedByType.get(nodeType).push(id);
      } else {
        unknown.push(id);
      }
    });

    LEVEL_ORDER.forEach((type, levelIndex) => {
      const ids = groupedByType.get(type) || [];
      if (!ids.length) return;

      const baseRadius = TYPE_RADIUS[type] ?? (140 + levelIndex * 120);
      const sectorSpan = Math.min(Math.PI * 1.65, Math.PI * (0.75 + ids.length * 0.08));
      const startAngle = -Math.PI / 2 - sectorSpan / 2;

      ids.forEach((id, index) => {
        const seed = hashCode(id);
        const t = ids.length === 1 ? 0.5 : index / (ids.length - 1);
        const angleBase = startAngle + sectorSpan * t;
        const angleJitter = (((seed % 100) / 100) - 0.5) * 0.28;
        const radiusJitter = (((Math.floor(seed / 100) % 100) / 100) - 0.5) * 70;
        const radius = Math.max(40, baseRadius + radiusJitter);
        const angle = angleBase + angleJitter;

        positions.set(id, {
          x: centerX + radius * Math.cos(angle),
          y: centerY + radius * Math.sin(angle),
        });
      });
    });

    unknown.forEach((id, index) => {
      const seed = hashCode(id);
      const angle = (-Math.PI / 2) + (2 * Math.PI * index) / Math.max(unknown.length, 1);
      const radius = 760 + (((seed % 100) / 100) - 0.5) * 120;
      positions.set(id, {
        x: centerX + radius * Math.cos(angle),
        y: centerY + radius * Math.sin(angle),
      });
    });
  });

  return positions;
}

function extractStructuredConditions(query) {
  const raw = (query || '').trim();
  if (!raw) {
    return { area: '', equipment: '', component: '', problem: '', cause: '', solution: '' };
  }

  let cleaned = raw
    .replace(/(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|原因是什么|为什么|是什么|有哪些|有过什么问题)\s*[?？]*$/g, '')
    .replace(/(怎么|如何|什么|吗|呢|啊|呀|吧|嘛)\s*[?？]*$/g, '')
    .replace(/[?？!！。.]+$/g, '')
    .trim();
  const result = { area: '', equipment: '', component: '', problem: '', cause: '', solution: '' };

  const problemKeywords = ['报警', '故障', '异常', '无信号', '报错', '停机', '卡滞', '失败', '不良', '超差', '偏差'];
  const causeKeywords = ['原因', '导致', '引起'];
  const solutionKeywords = ['更换', '调整', '维修', '复位', '清理', '校准'];
  const hasAreaIntent = /(区域|产线|线体|acu|epb|fnd).*(问题|故障|异常)|有过什么问题|有哪些问题/i.test(raw);
  const hasEquipmentIntent = /(设备|工位|机台).*(问题|故障|异常)|有过什么问题|有哪些问题/i.test(raw);

  const matchedProblem = problemKeywords.find((item) => cleaned.includes(item));
  if (matchedProblem) {
    result.problem = matchedProblem;
    cleaned = cleaned.replace(matchedProblem, ' ');
  }

  const matchedCause = causeKeywords.find((item) => cleaned.includes(item));
  if (matchedCause) {
    result.cause = matchedCause;
    cleaned = cleaned.replace(matchedCause, ' ');
  }

  const matchedSolution = solutionKeywords.find((item) => cleaned.includes(item));
  if (matchedSolution) {
    result.solution = matchedSolution;
    cleaned = cleaned.replace(matchedSolution, ' ');
  }

  cleaned = cleaned.replace(/[?？,，。.!！]/g, ' ').replace(/\s+/g, ' ').trim();

  const areaMatch = cleaned.match(/^(ACU|EPB|FND)$/i);
  const equipmentMatch = cleaned.match(/^[A-Za-z]{1,4}\d{1,4}[A-Za-z0-9-]*/);
  // 优先识别标准工位号（如 PM16-B1 / AM22-A3 / OP70），避免被问题词吞掉
  const stationTokenMatch = String(raw || '').toUpperCase().match(/\b(?:[A-Z]{2,4}\d{1,3}-[A-Z]\d+|OP\d+(?:\.\d+)?)\b/);

  if (areaMatch && hasAreaIntent) {
    result.area = areaMatch[1];
    cleaned = cleaned.replace(areaMatch[1], '').trim();
  } else if (stationTokenMatch) {
    result.equipment = stationTokenMatch[0];
    const escapedStationToken = String(stationTokenMatch[0]).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    cleaned = cleaned.replace(new RegExp(escapedStationToken, 'ig'), ' ').trim();
  } else if (equipmentMatch && (hasEquipmentIntent || !matchedProblem)) {
    result.equipment = equipmentMatch[0];
    cleaned = cleaned.replace(equipmentMatch[0], '').trim();
  }

  // 默认优先保留核心部件词，避免把 "Y68轮廓监控报警" 误拆成 equipment + component
  cleaned = cleaned.replace(/^[A-Za-z]{1,4}\d{1,4}[A-Za-z0-9-]*/g, '').trim();

  let remain = cleaned.replace(/\s+/g, ' ').trim();
  // 清理残留的疑问词和标点
  remain = remain
    .replace(/(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|原因是什么|为什么|是什么|有哪些|有过什么问题)\s*[?？]*$/g, '')
    .replace(/(怎么|如何|什么|吗|呢|啊|呀|吧|嘛)\s*[?？]*$/g, '')
    .replace(/[?？!！。.,，]+$/g, '')
    .trim();
  if (remain) {
    result.component = remain;
  }

  return result;
}

function buildKeywordFromQuestionOrRecords(question, records) {
  const cleanedQuestion = String(question || '').trim();
  if (cleanedQuestion) return cleanedQuestion;

  const first = Array.isArray(records) && records.length > 0 ? records[0] : null;
  if (!first) return '';

  const merged = [
    first.problem || '',
    first.component || '',
    first.station || first.equipment || '',
    first.line || first.area || '',
  ].map((v) => String(v || '').trim()).filter(Boolean);

  return merged.join(' ').trim();
}

function rankPathEntriesByQuestion(pathEntries, questionText) {
  const entries = Array.isArray(pathEntries) ? [...pathEntries] : [];
  const q = String(questionText || '').trim();
  if (!q || entries.length <= 1) return entries;

  const slots = extractStructuredConditions(q);
  const component = String(slots.component || '').trim();
  const problem = String(slots.problem || '').trim();
  const area = String(slots.area || '').trim();
  const equipment = String(slots.equipment || '').trim();
  const cause = String(slots.cause || '').trim();
  const solution = String(slots.solution || '').trim();
  const problemAliases = [problem, '无法回原点', '回不了原点', '回不到原点', '不回原点', '回原点', '回零']
    .map((x) => String(x || '').trim())
    .filter(Boolean);

  const normalizedQuestion = q
    .replace(/(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|怎么处|如何处|原因是什么|为什么|是什么|有哪些)\s*[?？]*$/g, ' ')
    .replace(/[?？!！。.,，]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  const keywordBag = [
    component,
    problem,
    area,
    equipment,
    cause,
    solution,
    ...problemAliases,
  ].filter(Boolean);

  const extraTokens = (normalizedQuestion.match(/[\u4e00-\u9fa5A-Za-z0-9]{2,}/g) || [])
    .map((x) => x.trim())
    .filter((x) => x && !['怎么', '如何', '处理', '怎么办', '原因', '问题'].includes(x));

  const keywords = Array.from(new Set([...keywordBag, ...extraTokens]));
  const hasHardConstraint = Boolean(component || equipment);
  const semanticBoostWeight = hasHardConstraint ? 75 : 60;
  const semanticStopwords = new Set([
    '怎么', '如何', '处理', '怎么办', '原因', '问题',
    '报警', '故障', '异常', '检测', '信号',
  ]);

  // 轻量语义相似度（前端最小实现）：词片段 + 中文2-gram 的 Dice 相似度
  const semanticTokens = (inputText) => {
    const base = String(inputText || '')
      .toLowerCase()
      .replace(/(怎么办|怎么解决|怎么处理|怎么修|如何解决|如何处理|原因是什么|为什么|是什么|有哪些)/g, ' ')
      .replace(/[\[\]\-\>_.,，。!?！？:：;；()]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();

    if (!base) return [];

    const wordTokens = (base.match(/[\u4e00-\u9fa5a-z0-9]{2,}/g) || []).map((x) => x.trim());
    const zhOnly = base.replace(/[^\u4e00-\u9fa5]/g, '');
    const zh2grams = [];
    for (let i = 0; i < Math.max(0, zhOnly.length - 1); i += 1) {
      zh2grams.push(zhOnly.slice(i, i + 2));
    }

    const uniq = Array.from(new Set([...wordTokens, ...zh2grams]));
    return uniq.filter((x) => x && !semanticStopwords.has(x));
  };

  const querySemanticTokens = semanticTokens(normalizedQuestion);
  const semanticDice = (pathText) => {
    const pathTokens = semanticTokens(pathText);
    if (!querySemanticTokens.length || !pathTokens.length) return 0;
    const qSet = new Set(querySemanticTokens);
    const pSet = new Set(pathTokens);
    let inter = 0;
    qSet.forEach((t) => {
      if (pSet.has(t)) inter += 1;
    });
    return (2 * inter) / (qSet.size + pSet.size);
  };

  const scoreOf = (entry) => {
    const text = String(entry?.text || '').toLowerCase();
    const textUpper = String(entry?.text || '').toUpperCase();
    let score = 0;
    const hitComp = component && text.includes(component.toLowerCase());
    const hitProb = problemAliases.some((kw) => text.includes(kw.toLowerCase()));
    const normalizedEquip = String(equipment || '').toUpperCase().trim();
    const hitEquip = normalizedEquip && textUpper.includes(normalizedEquip);
    const hardMatch = (!component || hitComp) && (!normalizedEquip || hitEquip);
    const semanticSim = semanticDice(entry?.text || '');

    if (hitComp && hitProb) score += 120;
    else {
      if (hitComp) score += 70;
      if (hitProb) score += 35;
    }

    // component 约束增强：用户明确提到部件但路径未命中时，明显降权
    if (component && !hitComp) {
      score -= 35;
    }

    // 设备命中强加权：有明确 equipment 时，优先同设备路径
    if (hitEquip) {
      score += 80;
    } else if (normalizedEquip) {
      // 存在设备约束但未命中，进行惩罚，降低跨设备同问题误入
      score -= 40;
    }

    keywords.forEach((kw) => {
      if (text.includes(kw.toLowerCase())) score += 8;
    });

    // 语义加分：区分“同为报警”但语义上下文不同的路径
    score += Math.round(semanticSim * semanticBoostWeight);

    return { score, hardMatch, semanticSim };
  };

  const scored = entries.map((entry) => {
    const { score, hardMatch, semanticSim } = scoreOf(entry);
    return {
      ...entry,
      _matchScore: score,
      _semanticScore: Number(semanticSim || 0),
      _exactHardMatch: hardMatch,
      _exactHasHardConstraint: hasHardConstraint,
    };
  });
  scored.sort((a, b) => (b._matchScore || 0) - (a._matchScore || 0));
  return scored;
}

function buildCypherPreview(keyword, structuredFilters) {
  const phrase = (keyword || '').trim();
  const entries = Object.entries(structuredFilters || {}).filter(([, value]) => (value || '').trim());
  if (!phrase && entries.length === 0) return '';

  const mapping = {
    area: 'a.name',
    equipment: 'e.name',
    component: 'c.name',
    problem: 'p.name',
    cause: 'ca.name',
    solution: 's.name',
  };

  const whereLines = ['WHERE true'];
  entries.forEach(([key, value]) => {
    whereLines.push(`  AND ${mapping[key]} CONTAINS '${value}'`);
  });

  return [
    'MATCH path = (a:Area)-[:INCLUDE]->(e:Equipment)-[:HAS_PART]->(c:Component)',
    '             -[:HAS_FAULT]->(p:Problem)-[:CAUSED_BY]->(ca:Cause)-[:SOLVED_BY]->(s:Solution)',
    `// 原始问题: ${phrase || '（空）'}`,
    ...whereLines,
    'WITH path,',
    '     r1, r2, r3, r4,',
    '     [r IN [r2, r3, r4] WHERE r.source_rows IS NOT NULL AND size(r.source_rows) > 0 | r.source_rows] AS sr_lists',
    'WITH path, r1, sr_lists,',
    '     CASE WHEN size(sr_lists) = 0 THEN NULL',
    '          ELSE head([x IN sr_lists[0] WHERE ALL(lst IN sr_lists WHERE x IN lst)])',
    '     END AS shared_row',
    'WHERE (size(sr_lists) = 0 OR shared_row IS NOT NULL)',
    '  AND (shared_row IS NULL OR shared_row IN coalesce(r1.row_ids, r1.source_rows, []))',
    'RETURN path',
  ].join('\n');
}

function getStructuredFilterChips(structuredFilters) {
  const labels = {
    area: '区域',
    equipment: '设备/工位',
    component: '部件/功能点',
    problem: '问题',
    cause: '原因',
    solution: '解决方案',
  };

  return Object.entries(structuredFilters || {})
    .filter(([, value]) => (value || '').trim())
    .map(([key, value]) => ({ key, label: labels[key] || key, value }));
}

export default function Neo4jGraph({
  keyword,
  records,
  defaultExpanded = true,
  onClose,
  allowKeywordSearch = true,
  autoLoad = true,
  lightTheme = false,
  showPaths = false,
  embedded = false,
  disableEmbeddedCache = false,
  defaultLimit = 20,
  limitOptions = [20, 50, 100, 200],
  defaultQueryMode = 'exact',
}) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const nodesDataSet = useRef(null);
  const edgesDataSet = useRef(null);
  const stabilizeTimerRef = useRef(null);
  const userInteractedRef = useRef(false);
  const graphRequestSeqRef = useRef(0);
  const inflightGraphKeyRef = useRef(null);
  const hasRecordsInput = !allowKeywordSearch && Array.isArray(records) && records.length > 0;
  const initialKeyword = buildKeywordFromQuestionOrRecords(keyword, records);
  const initialQueryMode = String(defaultQueryMode || 'exact').trim().toLowerCase() === 'normal' ? 'normal' : 'exact';

  const [loading, setLoading] = useState(false);
  const [loadingText, setLoadingText] = useState('正在加载图谱...');
  const [loadingProgress, setLoadingProgress] = useState(8);
  const [error, setError] = useState(null);
  const [searchInput, setSearchInput] = useState(initialKeyword);
  const [activeKeyword, setActiveKeyword] = useState(initialKeyword);
  const normalizedLimitOptions = Array.isArray(limitOptions) && limitOptions.length > 0
    ? Array.from(new Set(limitOptions.map((v) => Number(v)).filter((v) => Number.isFinite(v) && v > 0)))
    : [20, 50, 100, 200];
  const fallbackLimit = normalizedLimitOptions[0] || 20;
  const initialLimit = Number.isFinite(Number(defaultLimit)) && Number(defaultLimit) > 0
    ? Number(defaultLimit)
    : fallbackLimit;
  const [nodeLimit, setNodeLimit] = useState(initialLimit);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isMainSidebarCollapsed, setIsMainSidebarCollapsed] = useState(() => {
    try {
      return localStorage.getItem('mainLayoutSidebarCollapsed') === '1';
    } catch {
      return false;
    }
  });
  const [selectedNode, setSelectedNode] = useState(null);
  const [selectedEdge, setSelectedEdge] = useState(null);
  const [expandedNodes, setExpandedNodes] = useState(new Set()); // 已展开的节点
  const [childrenMap, setChildrenMap] = useState(new Map()); // 父节点 -> 子节点ID集合
  const [queryMode, setQueryMode] = useState(initialQueryMode); // exact | normal
  const [mode, setMode] = useState(hasRecordsInput ? 'records' : 'keyword'); // 双模式
  const [structuredFilters, setStructuredFilters] = useState(() => extractStructuredConditions(initialKeyword || ''));
  const [showCypherPreview, setShowCypherPreview] = useState(false);
  const [executedCypher, setExecutedCypher] = useState(null);
  const [queryTrace, setQueryTrace] = useState(null);
  const [pathList, setPathList] = useState([]);
  const [allGraphNodes, setAllGraphNodes] = useState([]);
  const [allGraphEdges, setAllGraphEdges] = useState([]);
  const [allPathEntries, setAllPathEntries] = useState([]);
  const [totalPathCount, setTotalPathCount] = useState(null);
  const [selectedNodeFilterId, setSelectedNodeFilterId] = useState(null);
  const [selectedPathId, setSelectedPathId] = useState(null);
  const [showPathPanel, setShowPathPanel] = useState(true);
  const [hasSearched, setHasSearched] = useState(autoLoad);
  const [selectedNodeTypeOnly, setSelectedNodeTypeOnly] = useState(null);
  const [pathPanelHeight, setPathPanelHeight] = useState(160); 
  const [isEditingNode, setIsEditingNode] = useState(false);
  const [editNodeForm, setEditNodeForm] = useState({ name: '', type: '', description: '' });
  const [editScope, setEditScope] = useState('path'); // path | global
  const [isAddingNode, setIsAddingNode] = useState(false);
  const [addNodeForm, setAddNodeForm] = useState({
    name: '',
    type: 'Component',
    description: '',
    relationType: DEFAULT_RELATION_TYPE,
    fromNodeId: '',
  });
  const [showMutationPanel, setShowMutationPanel] = useState(false);
  const [mutationLogs, setMutationLogs] = useState([]);
  const [loadingMutations, setLoadingMutations] = useState(false);
  const [rollbackingMutationId, setRollbackingMutationId] = useState(null);
  const [mutationNotice, setMutationNotice] = useState(null);
  const localCypherPreview = buildCypherPreview(activeKeyword || searchInput, structuredFilters);
  const cypherPreview = executedCypher || localCypherPreview;
  const structuredFilterChips = getStructuredFilterChips(structuredFilters);
  const isLight = lightTheme;
  const isRecordsContext = hasRecordsInput;
  const useRecordsRoute = isRecordsContext;
  
  // 使用 ref 保存最新状态，避免闭包问题
  const expandedNodesRef = useRef(expandedNodes);
  const childrenMapRef = useRef(childrenMap);
  const queryModeRef = useRef(queryMode);
  const useRecordsRouteRef = useRef(useRecordsRoute);
  const rankingQuestionRef = useRef(activeKeyword || searchInput || keyword || '');
  
  useEffect(() => {
    expandedNodesRef.current = expandedNodes;
  }, [expandedNodes]);

  useEffect(() => {
    queryModeRef.current = queryMode;
  }, [queryMode]);

  useEffect(() => {
    useRecordsRouteRef.current = useRecordsRoute;
  }, [useRecordsRoute]);

  useEffect(() => {
    rankingQuestionRef.current = activeKeyword || searchInput || keyword || '';
  }, [activeKeyword, searchInput, keyword]);

  useEffect(() => {
    setMode(useRecordsRoute ? 'records' : 'keyword');
  }, [useRecordsRoute]);

  useEffect(() => {
    const handleSidebarChange = (event) => {
      const collapsed = event?.detail?.collapsed;
      if (typeof collapsed === 'boolean') {
        setIsMainSidebarCollapsed(collapsed);
      }
    };

    window.addEventListener('layout:main-sidebar-change', handleSidebarChange);
    return () => window.removeEventListener('layout:main-sidebar-change', handleSidebarChange);
  }, []);
  
  useEffect(() => {
    childrenMapRef.current = childrenMap;
  }, [childrenMap]);

  useEffect(() => {
    if (!loading) return;

    const timer = window.setInterval(() => {
      setLoadingProgress((prev) => (prev >= 90 ? prev : prev + (prev < 50 ? 8 : 3)));
    }, 350);

    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    if (!selectedNode) {
      setIsEditingNode(false);
      setEditNodeForm({ name: '', type: '', description: '' });
      return;
    }
    const raw = selectedNode.rawData || {};
    const nodeType = selectedNode.nodeType || raw.type || raw.labels?.[0] || '';
    const name = extractDisplayName(raw) || selectedNode.label || '';
    const description = raw?.props?.description || raw?.properties?.description || raw?.description || '';
    setIsEditingNode(false);
    setEditScope('path');
    setEditNodeForm({
      name,
      type: nodeType,
      description: String(description || ''),
    });
  }, [selectedNode]);

  const fetchWithTimeout = useCallback(async (url, options = {}, timeout = GRAPH_REQUEST_TIMEOUT) => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(url, { ...options, signal: controller.signal, cache: 'no-store' });
      return response;
    } catch (err) {
      if (err.name === 'AbortError') {
        throw new Error('图谱查询超时，请缩小关键词后重试');
      }
      throw err;
    } finally {
      window.clearTimeout(timer);
    }
  }, []);

  const beginGraphRequest = useCallback(() => {
    graphRequestSeqRef.current += 1;
    return graphRequestSeqRef.current;
  }, []);

  const isLatestGraphRequest = useCallback((seq) => {
    return seq === graphRequestSeqRef.current;
  }, []);

  const clearGraph = useCallback((resetQueryMeta = true) => {
    window.clearTimeout(stabilizeTimerRef.current);
    nodesDataSet.current?.clear();
    edgesDataSet.current?.clear();
    setPathList([]);
    setAllGraphNodes([]);
    setAllGraphEdges([]);
    setAllPathEntries([]);
    setTotalPathCount(null);
    setSelectedNodeFilterId(null);
    setSelectedPathId(null);
    setSelectedNodeTypeOnly(null);
    setShowPathPanel(true);
    setSelectedNode(null);
    setSelectedEdge(null);
    setExpandedNodes(new Set());
    setChildrenMap(new Map());
    if (resetQueryMeta) {
      setExecutedCypher(null);
      setQueryTrace(null);
    }
  }, []);

  // 初始化 vis-network
  useEffect(() => {
    if (!containerRef.current) return;

    nodesDataSet.current = new DataSet([]);
    edgesDataSet.current = new DataSet([]);

    const options = {
      autoResize: true,
      layout: {
        hierarchical: {
          enabled: true,
          direction: 'UD',
          sortMethod: 'directed',
          nodeSpacing: 170,
          levelSeparation: 170,
          treeSpacing: 220,
          blockShifting: true,
          edgeMinimization: true,
          parentCentralization: true,
        },
      },
      nodes: {
        shape: 'dot',
        size: 18,
        font: { size: 11, color: isLight ? '#1e293b' : '#ffffff' },
        borderWidth: 1.5,
        shadow: false,
      },
      edges: {
        width: 0.9,
        color: {
          color: '#D1D5DB',
          highlight: '#60A5FA',
          hover: '#9CA3AF',
        },
        arrows: { to: { enabled: true, scaleFactor: 0.35 } },
        smooth: {
          enabled: true,
          type: 'cubicBezier',
          forceDirection: 'vertical',
          roundness: 0.35,
        },
        font: {
          size: 10,
          color: isLight ? '#64748b' : '#6B7280',
          align: 'top',
          strokeWidth: 2,
          strokeColor: isLight ? '#f8fafc' : '#ffffff',
        },
      },
      physics: {
        enabled: false,
      },
      interaction: {
        hover: true,
        tooltipDelay: 250,
        navigationButtons: true,
        zoomView: true,
        dragView: true,
        dragNodes: true,
      },
    };

    networkRef.current = new Network(
      containerRef.current,
      {
        nodes: nodesDataSet.current,
        edges: edgesDataSet.current,
      },
      options,
    );

    // 防止页面滚动与图谱滚轮缩放同时触发导致视图抖动/乱动。
    // 仅阻止浏览器默认滚动，不阻止 vis-network 在同元素上的缩放监听。
    const wheelGuard = (event) => {
      event.preventDefault();
      event.stopPropagation();
    };
    containerRef.current.addEventListener('wheel', wheelGuard, { passive: false });

    // 用户开始拖拽节点时：立即停止物理，防止节点乱飘
    networkRef.current.on('dragStart', (params) => {
      userInteractedRef.current = true;
      if (params.nodes.length > 0) {
        window.clearTimeout(stabilizeTimerRef.current);
        networkRef.current?.setOptions({ physics: { enabled: false } });
      }
    });

    // 用户拖拽节点结束后：固定该节点位置，不再漂移
    networkRef.current.on('dragEnd', (params) => {
      userInteractedRef.current = true;
      if (params.nodes.length > 0 && nodesDataSet.current) {
        const nodeId = params.nodes[0];
        const positions = networkRef.current?.getPositions([nodeId]);
        if (positions && positions[nodeId]) {
          nodesDataSet.current.update({
            id: nodeId,
            x: positions[nodeId].x,
            y: positions[nodeId].y,
            fixed: { x: true, y: true },
          });
        }
      }
    });

    // 双击事件：展开/收起节点
    networkRef.current.on('doubleClick', async (params) => {
      userInteractedRef.current = true;
      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        await toggleNodeExpansion(nodeId);
      }
    });

    networkRef.current.on('zoom', () => {
      userInteractedRef.current = true;
    });

    // 单击事件：显示节点/边详情
    networkRef.current.on('click', (params) => {
      // 点击空白区域也停止物理，防止还在跑
      window.clearTimeout(stabilizeTimerRef.current);
      networkRef.current?.setOptions({ physics: { enabled: false } });

      if (params.nodes.length > 0) {
        const nodeId = params.nodes[0];
        const node = nodesDataSet.current.get(nodeId);
        setSelectedNode(node);
        setSelectedEdge(null);
        setSelectedNodeFilterId((prev) => (prev === nodeId ? null : nodeId));
      } else if (params.edges.length > 0) {
        const edgeId = params.edges[0];
        const edge = edgesDataSet.current.get(edgeId);
        setSelectedEdge(edge || null);
        setSelectedNode(null);
      } else {
        setSelectedNode(null);
        setSelectedEdge(null);
        setSelectedNodeFilterId(null);
      }
    });

    // 稳定后停止物理模拟
    networkRef.current.on('stabilizationIterationsDone', () => {
      window.clearTimeout(stabilizeTimerRef.current);
      networkRef.current?.setOptions({ physics: { enabled: false } });
    });

    return () => {
      window.clearTimeout(stabilizeTimerRef.current);
      containerRef.current?.removeEventListener('wheel', wheelGuard);
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [isLight]);

  // 容器尺寸变化时保持当前视角，避免缩放时渲染抖动/重置
  useEffect(() => {
    if (!containerRef.current || !networkRef.current) return;

    let rafId = null;
    let lastWidth = 0;
    let lastHeight = 0;

    const getNodeCount = () => {
      const ids = nodesDataSet.current?.getIds?.();
      return Array.isArray(ids) ? ids.length : 0;
    };

    const syncViewport = () => {
      const network = networkRef.current;
      const container = containerRef.current;
      if (!network || !container) return;

      const { width, height } = container.getBoundingClientRect();
      const widthDiff = Math.abs(width - lastWidth);
      const heightDiff = Math.abs(height - lastHeight);
      const hasLargeResize = widthDiff > 40 || heightDiff > 40;

      const scale = network.getScale();
      const position = network.getViewPosition();
      network.redraw();

      if (hasLargeResize && getNodeCount() > 0) {
        network.fit({ animation: { duration: 220, easingFunction: 'easeInOutQuad' } });
        network.setOptions({ physics: { enabled: false } });
      } else if (position && Number.isFinite(scale)) {
        network.moveTo({ position, scale, animation: false });
      }

      lastWidth = width;
      lastHeight = height;
    };

    const scheduleSync = () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      rafId = window.requestAnimationFrame(syncViewport);
    };

    const observer = new ResizeObserver(scheduleSync);
    observer.observe(containerRef.current);
    window.addEventListener('resize', scheduleSync);
    scheduleSync();

    return () => {
      if (rafId) window.cancelAnimationFrame(rafId);
      observer.disconnect();
      window.removeEventListener('resize', scheduleSync);
    };
  }, [isFullscreen]);

  // 切换节点展开/收起
  const toggleNodeExpansion = useCallback(async (nodeId) => {
    if (!networkRef.current) return;

    const isExpanded = expandedNodesRef.current.has(nodeId);
    console.log('toggleNodeExpansion:', nodeId, 'isExpanded:', isExpanded);

    if (isExpanded) {
      // 收起：删除该节点展开的子节点和相关边
      const children = childrenMapRef.current.get(nodeId);
      console.log('收起节点，子节点:', children);
      
      if (children && children.size > 0) {
        // 先找到这些子节点的所有相关边
        const edgesToRemove = edgesDataSet.current.get({
          filter: (edge) => children.has(edge.from) || children.has(edge.to)
        });
        console.log('删除边:', edgesToRemove.length);
        edgesDataSet.current.remove(edgesToRemove.map(e => e.id));

        // 删除子节点
        console.log('删除子节点:', Array.from(children));
        nodesDataSet.current.remove(Array.from(children));
      }
      
      // 无论如何都要更新状态
      setExpandedNodes(prev => {
        const next = new Set(prev);
        next.delete(nodeId);
        return next;
      });
      setChildrenMap(prev => {
        const next = new Map(prev);
        next.delete(nodeId);
        return next;
      });
    } else {
      // 展开：获取邻居节点
      setLoading(true);
      setLoadingText('正在展开关联节点...');
      setLoadingProgress(12);
      try {
        const encodedId = encodeURIComponent(nodeId);
        const res = await fetchWithTimeout(buildApiUrl(`/graph/node/${encodedId}/neighbors?limit=20`));
        if (!res.ok) throw new Error('获取邻居节点失败');
        const data = await res.json();

        const newNodes = [];
        const newEdges = [];
        const newChildIds = new Set();

        // 处理邻居节点
        console.log('邻居节点数据:', data.nodes);
        (data.nodes || []).forEach((n) => {
          const nid = String(n.id);
          if (nid === nodeId) return; // 跳过自身
          if (nodesDataSet.current.get(nid)) return; // 已存在则跳过

          // 邻居 API 返回 labels 数组，主图 API 返回 type 字符串
          const nodeType = n.labels?.[0] || n.type || 'Unknown';
          const displayName = extractDisplayName(n);
          console.log('节点:', nid, '类型:', nodeType, '显示名:', displayName);
          const colors = NODE_COLORS[nodeType] || { background: '#888', border: '#666' };

          newNodes.push({
            id: nid,
            label: buildNodeLabel(displayName, nodeType),
            title: `[${nodeType}]\n${displayName}`,
            color: colors,
            nodeType,
            rawData: n,
            level: TYPE_LEVELS[nodeType] || 99,
          });
          newChildIds.add(nid);
        });

        // 处理边 - 兼容 relations, links 和 relationships
        const neighborLinks = data.relations || data.links || data.relationships || [];
        console.log('邻居边数据:', neighborLinks);
        neighborLinks.forEach((r) => {
          const source = String(r.source);
          const target = String(r.target);
          const edgeId = String(r.id || `${[source, target].sort().join('-')}-${r.type}`);

          // 检查边是否已存在（包括正向和反向）
          if (!edgesDataSet.current.get(edgeId)) {
            newEdges.push({
              id: edgeId,
              from: source,
              to: target,
              label: r.type || '',
              rawData: r,
            });
          }
        });

        // 添加新节点和边
        if (newNodes.length > 0) {
          nodesDataSet.current.add(newNodes);
        }
        if (newEdges.length > 0) {
          edgesDataSet.current.add(newEdges);
        }

        // 分层布局下触发重排
        if (newNodes.length > 0) {
          networkRef.current?.stabilize(100);
          networkRef.current?.fit({ animation: { duration: 250, easingFunction: 'easeInOutQuad' } });
        }

        setExpandedNodes(prev => new Set(prev).add(nodeId));
        setChildrenMap(prev => {
          const next = new Map(prev);
          next.set(nodeId, newChildIds);
          return next;
        });
      } catch (err) {
        console.error('展开节点失败:', err);
        setError(err.message || '展开节点失败');
      } finally {
        setLoading(false);
      }
    }
  }, [fetchWithTimeout]); // 移除依赖，使用 ref 来获取最新状态

  // 加载图数据（Mode B: 关键词搜索 / 无关键词全图）
  const loadGraphData = useCallback(async (kw, limit, slots = structuredFilters) => {
    const hasKeyword = Boolean((kw || '').trim());
    const hasStructuredFilters = Object.values(slots || {}).some((value) => (value || '').trim());

    if (!hasKeyword && !hasStructuredFilters) {
      clearGraph();
      setError(null);
      return;
    }
    const requestKey = JSON.stringify({ mode: 'keyword', kw: (kw || '').trim(), limit, slots: slots || {} });
    if (embedded && !disableEmbeddedCache) {
      const cached = getEmbeddedGraphCache(requestKey);
      if (cached) {
        if (cached.executed_cypher) setExecutedCypher(cached.executed_cypher);
        if (cached.query_trace) setQueryTrace(cached.query_trace);
        renderGraphData(cached);
        return;
      }
    }
    if (inflightGraphKeyRef.current === requestKey) {
      return;
    }

    setLoading(true);
    setLoadingText('正在按原始CSV整行链路搜索...');
    setLoadingProgress(10);
    setError(null);
    clearGraph();
    const reqSeq = beginGraphRequest();
    inflightGraphKeyRef.current = requestKey;

    try {
      let url = buildApiUrl('/graph');
      const timestamp = Date.now();  // 防止缓存
      const params = new URLSearchParams({
        limit: String(limit),
        single_path: 'true',
        strict_only: 'true',
        include_total: 'true',
        _t: String(timestamp),
      });
      if (hasKeyword) {
        params.set('keyword', (kw || '').trim());
      }
      Object.entries(slots || {}).forEach(([key, value]) => {
        if ((value || '').trim()) {
          params.set(key, value.trim());
        }
      });
      url = `${buildApiUrl('/graph/search')}?${params.toString()}`;

      const res = await fetchWithTimeout(url);
      if (!res.ok) throw new Error(`请求失败: ${res.status}`);
      if (!isLatestGraphRequest(reqSeq)) return;
      setLoadingText('正在渲染原始CSV整行链路...');
      setLoadingProgress(72);
      const data = await res.json();
      if (!isLatestGraphRequest(reqSeq)) return;

      if (embedded && !disableEmbeddedCache) {
        setEmbeddedGraphCache(requestKey, data);
      }

      if (data.executed_cypher) setExecutedCypher(data.executed_cypher);
      if (data.query_trace) setQueryTrace(data.query_trace);

      renderGraphData(data);
    } catch (err) {
      console.error('加载图数据失败:', err);
      if (isLatestGraphRequest(reqSeq)) {
        clearGraph();
        setError(err.message || '加载失败');
      }
    } finally {
      if (isLatestGraphRequest(reqSeq)) {
        inflightGraphKeyRef.current = null;
        setLoading(false);
      }
    }
  }, [beginGraphRequest, clearGraph, fetchWithTimeout, isLatestGraphRequest, structuredFilters, embedded, disableEmbeddedCache]);

  // 加载图数据（Mode A: Qdrant 记录反查 Neo4j 六节点链路）
  const loadGraphFromRecords = useCallback(async (recs, limit) => {
    const recordsToSend = Array.isArray(recs) && recs.length > 0
      ? recs.slice(0, limit)
      : [];
    const requestQueryMode = String(queryModeRef.current || 'exact').trim().toLowerCase();
    const strictOnly = requestQueryMode === 'exact';
    const requestQuestion = String(rankingQuestionRef.current || '').trim();
    const requestKey = JSON.stringify({
      mode: 'records',
      limit,
      queryMode: requestQueryMode,
      question: requestQuestion,
      records: recordsToSend,
    });
    if (embedded && !disableEmbeddedCache) {
      const cached = getEmbeddedGraphCache(requestKey);
      if (cached) {
        if (cached.executed_cypher) setExecutedCypher(cached.executed_cypher);
        if (cached.query_trace) setQueryTrace(cached.query_trace);
        renderGraphData(cached);
        return;
      }
    }
    if (inflightGraphKeyRef.current === requestKey) {
      return;
    }

    setLoading(true);
    setLoadingText('正在按原始CSV整行链路反查...');
    setLoadingProgress(10);
    setError(null);
    clearGraph();
    const reqSeq = beginGraphRequest();
    inflightGraphKeyRef.current = requestKey;

    try {
      const res = await fetchWithTimeout(buildApiUrl('/graph/search-by-records'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          records: recordsToSend,
          question: requestQuestion,
          query_mode: requestQueryMode,
          limit: limit,
          single_path: false,
          strict_only: strictOnly,
          include_total: true,
        }),
      });
      if (!res.ok) throw new Error(`请求失败: ${res.status}`);
      if (!isLatestGraphRequest(reqSeq)) return;
      setLoadingText('正在渲染原始CSV整行链路...');
      setLoadingProgress(72);
      const data = await res.json();
      if (!isLatestGraphRequest(reqSeq)) return;

      if (embedded && !disableEmbeddedCache) {
        setEmbeddedGraphCache(requestKey, data);
      }

      if (!data.nodes || data.nodes.length === 0) {
        if (isLatestGraphRequest(reqSeq)) {
          clearGraph();
          setError('未找到相近链路');
        }
        return;
      }

      if (data.executed_cypher) setExecutedCypher(data.executed_cypher);
      if (data.query_trace) setQueryTrace(data.query_trace);

      renderGraphData(data);
    } catch (err) {
      console.error('记录反查图数据失败:', err);
      if (isLatestGraphRequest(reqSeq)) {
        clearGraph();
        setError(err.message || '加载失败');
      }
    } finally {
      if (isLatestGraphRequest(reqSeq)) {
        inflightGraphKeyRef.current = null;
        setLoading(false);
      }
    }
  }, [beginGraphRequest, clearGraph, fetchWithTimeout, isLatestGraphRequest, embedded, disableEmbeddedCache]);

  // 将后端返回的数据渲染到 vis-network
  const renderGraphData = useCallback((data) => {
    if (!data.nodes || data.nodes.length === 0) {
      clearGraph();
      setError('未找到对应的原始CSV整行链路');
      return;
    }

    const backendPaths = Array.isArray(data.paths) ? data.paths : [];
    const backendPathDetails = Array.isArray(data.path_details) ? data.path_details : [];

    const normalizedPathDetails = backendPathDetails
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const text = String(item.text || '').trim();
        if (!text) return null;
        return {
          text,
          shared_row: String(item.shared_row || '').trim() || null,
          source_year: String(item.source_year || '').trim() || null,
          source_csv_line: Number.isFinite(Number(item.source_csv_line)) ? Number(item.source_csv_line) : null,
          source_csv_row: Number.isFinite(Number(item.source_csv_row)) ? Number(item.source_csv_row) : null,
          source_csv_file: String(item.source_csv_file || '').trim() || null,
        };
      })
      .filter(Boolean);

    const fallbackPathDetails = backendPaths
      .map((item) => String(item || '').trim())
      .filter(Boolean)
      .map((text) => ({ text }));

    const mergedPathDetails = normalizedPathDetails.length > 0 ? normalizedPathDetails : fallbackPathDetails;
    const detailSeen = new Set();
    const uniqPathDetails = [];
    mergedPathDetails.forEach((item) => {
      const key = `${item.text}||${item.shared_row || ''}`;
      if (detailSeen.has(key)) return;
      detailSeen.add(key);
      uniqPathDetails.push(item);
    });

    // 转换节点数据
    const visNodes = data.nodes.map((n) => {
      const nodeType = n.type || n.labels?.[0] || 'Unknown';
      const displayName = extractDisplayName(n);
      const colors = NODE_COLORS[nodeType] || { background: '#888', border: '#666' };

      return {
        id: String(n.id),
        label: buildNodeLabel(displayName, nodeType),
        title: `[${nodeType}]\n${displayName}`,
        color: colors,
        nodeType,
        level: TYPE_LEVELS[nodeType] || 99,
        shape: 'dot',
        size: nodeType === 'Area' ? 24 : nodeType === 'Equipment' ? 22 : 20,
        rawData: n,
      };
    });

    // 转换边数据 - 兼容 links 和 relationships 两种格式（去重）
    const links = data.links || data.relationships || [];
    const edgeSeen = new Set();
    const visEdges = [];
    links.forEach((r) => {
      const source = String(r.source);
      const target = String(r.target);
      const edgeId = String(r.id || `${source}-${r.type}-${target}`);
      const dedupeKey = String(r.id || `${source}-${r.type}-${target}`);
      if (!edgeSeen.has(dedupeKey)) {
        edgeSeen.add(dedupeKey);
        visEdges.push({ id: edgeId, from: source, to: target, label: r.type || '', rawData: r });
      }
    });

    const pathEntries = buildPathEntries(uniqPathDetails, data.nodes, visEdges);
    const currentUseRecordsRoute = Boolean(useRecordsRouteRef.current);
    const currentQueryMode = String(queryModeRef.current || 'exact');
    const rankedPathEntries = (currentUseRecordsRoute && currentQueryMode === 'exact')
      ? rankPathEntriesByQuestion(pathEntries, rankingQuestionRef.current)
      : pathEntries;
    const finalPathEntries = rankedPathEntries;

    const shouldSyncExactGraphWithPaths = Boolean(
      currentUseRecordsRoute && currentQueryMode === 'exact' && finalPathEntries.length > 0
    );
    let renderNodes = visNodes;
    let renderEdges = visEdges;
    if (shouldSyncExactGraphWithPaths) {
      const exactNodeIds = new Set();
      const exactEdgeIds = new Set();
      finalPathEntries.forEach((entry) => {
        entry.nodeIds.forEach((id) => exactNodeIds.add(String(id)));
        entry.edgeIds.forEach((id) => exactEdgeIds.add(String(id)));
      });
      renderNodes = visNodes.filter((node) => exactNodeIds.has(String(node.id)));
      renderEdges = visEdges.filter((edge) => exactEdgeIds.has(String(edge.id)));
    }

    setAllGraphNodes(renderNodes);
    setAllGraphEdges(renderEdges);
    setAllPathEntries(finalPathEntries);
    {
      const rawTotal = data?.total_paths;
      const hasTotal = rawTotal !== null && rawTotal !== undefined && String(rawTotal).trim() !== '';
      const parsedTotal = hasTotal ? Number(rawTotal) : NaN;
      setTotalPathCount(Number.isFinite(parsedTotal) ? parsedTotal : null);
    }
    setSelectedNodeFilterId(null);
    setSelectedPathId(null);
    setSelectedEdge(null);

    // 首次渲染全量数据
    nodesDataSet.current.clear();
    edgesDataSet.current.clear();
    nodesDataSet.current.add(renderNodes);
    edgesDataSet.current.add(renderEdges);
    userInteractedRef.current = false;
    setPathList(finalPathEntries.map((entry) => entry.text));

    setLoadingProgress(88);

    networkRef.current?.stabilize(120);

    // 适应视图
    setTimeout(() => {
      networkRef.current?.fit({ animation: { duration: 500, easingFunction: 'easeInOutQuad' } });
    }, 100);
  }, [clearGraph]);

  const persistNodeUpdate = useCallback(async (nodeId, payload, operationGroupId = '', operationType = '') => {
    const headers = { 'Content-Type': 'application/json' };
    if (operationGroupId) headers['X-Operation-Group-Id'] = operationGroupId;
    if (operationType) headers['X-Operation-Type'] = operationType;
    
    const res = await fetchWithTimeout(buildApiUrl(`/graph/node/${encodeURIComponent(String(nodeId))}`), {
      method: 'PUT',
      headers,
      body: JSON.stringify(payload),
    });

    if (res.status === 404 || res.status === 405) {
      return { localOnly: true };
    }
    if (!res.ok) {
      throw new Error(`保存失败: ${res.status}`);
    }
    return { localOnly: false };
  }, [fetchWithTimeout]);

  const persistNodeDelete = useCallback(async (nodeId) => {
    const res = await fetchWithTimeout(buildApiUrl(`/graph/node/${encodeURIComponent(String(nodeId))}?detach=true`), {
      method: 'DELETE',
    });

    if (res.status === 404 || res.status === 405) {
      return { localOnly: true };
    }
    if (!res.ok) {
      throw new Error(`删除失败: ${res.status}`);
    }
    return { localOnly: false };
  }, [fetchWithTimeout]);

  const persistNodeDeleteWithDetach = useCallback(async (nodeId, detach = true, operationGroupId = '', operationType = '') => {
    const headers = {};
    if (operationGroupId) headers['X-Operation-Group-Id'] = operationGroupId;
    if (operationType) headers['X-Operation-Type'] = operationType;
    
    const queryStr = `detach=${detach ? 'true' : 'false'}`;
    const url = Object.keys(headers).length > 0
      ? buildApiUrl(`/graph/node/${encodeURIComponent(String(nodeId))}?${queryStr}`)
      : buildApiUrl(`/graph/node/${encodeURIComponent(String(nodeId))}?${queryStr}`);
    
    const res = await fetchWithTimeout(url, {
      method: 'DELETE',
      headers: Object.keys(headers).length > 0 ? headers : undefined,
    });
    if (res.status === 404 || res.status === 405) return { localOnly: true, notFound: true };
    if (res.status === 409) return { localOnly: false, conflict: true };
    if (!res.ok) throw new Error(`删除失败: ${res.status}`);
    return { localOnly: false };
  }, [fetchWithTimeout]);

    const persistNodeCreate = useCallback(async (payload, operationGroupId = '', operationType = '') => {
    const headers = { 'Content-Type': 'application/json' };
    if (operationGroupId) headers['X-Operation-Group-Id'] = operationGroupId;
    if (operationType) headers['X-Operation-Type'] = operationType;

    const res = await fetchWithTimeout(buildApiUrl('/graph/node'), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(await parseApiError(res, '创建节点失败'));
    }
    const data = await res.json().catch(() => null);
    const nodeId = data?.id ? String(data.id) : '';
    if (!nodeId) {
      throw new Error(`创建节点失败 (HTTP ${res.status}): missing node id`);
    }
    return {
      nodeId,
      deduplicated: Boolean(data?.deduplicated),
    };
  }, [fetchWithTimeout]);

    const persistEdgeCreate = useCallback(async (payload, operationGroupId = '', operationType = '') => {
    const headers = { 'Content-Type': 'application/json' };
    if (operationGroupId) headers['X-Operation-Group-Id'] = operationGroupId;
    if (operationType) headers['X-Operation-Type'] = operationType;

    const res = await fetchWithTimeout(buildApiUrl('/graph/edge'), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      throw new Error(await parseApiError(res, '创建关系失败'));
    }
    const data = await res.json().catch(() => null);
    const edgeId = data?.id ? String(data.id) : '';
    if (!edgeId) {
      throw new Error(`创建关系失败 (HTTP ${res.status}): missing edge id`);
    }
    return { edgeId };
  }, [fetchWithTimeout]);

  const persistEdgeDelete = useCallback(async (edgeId, operationGroupId = '', operationType = '') => {
    const headers = {};
    if (operationGroupId) headers['X-Operation-Group-Id'] = operationGroupId;
    if (operationType) headers['X-Operation-Type'] = operationType;
    
    const res = await fetchWithTimeout(buildApiUrl(`/graph/edge/${encodeURIComponent(String(edgeId))}`), {
      method: 'DELETE',
      headers: Object.keys(headers).length > 0 ? headers : undefined,
    });

    if (res.status === 404 || res.status === 405) {
      return { localOnly: true };
    }
    if (!res.ok) {
      throw new Error(`删除关系失败: ${res.status}`);
    }
    return { localOnly: false };
  }, [fetchWithTimeout]);

    const handleCreateNode = useCallback(async () => {
    const name = String(addNodeForm.name || '').trim();
    const type = String(addNodeForm.type || 'Component').trim() || 'Component';
    const description = String(addNodeForm.description || '').trim();
    const relationType = String(addNodeForm.relationType || DEFAULT_RELATION_TYPE).trim() || DEFAULT_RELATION_TYPE;
    const lockedFromNodeId = String(addNodeForm.fromNodeId || '').trim();
    const lockedSourceNode = lockedFromNodeId ? nodesDataSet.current?.get(lockedFromNodeId) : null;
    const sourceNode = lockedSourceNode
      || selectedNode
      || (selectedNodeFilterId ? nodesDataSet.current?.get(String(selectedNodeFilterId)) : null);
    const fromNodeId = sourceNode ? String(sourceNode.id) : (lockedFromNodeId || '');

    if (!name) {
      setMutationNotice({ type: 'error', text: 'Node name is required.' });
      return;
    }

    if (!fromNodeId) {
      setMutationNotice({ type: 'error', text: 'Please select a source node first.' });
      return;
    }

    const operationGroupId = `op-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    const operationType = 'create_node_with_edge';
    const normalizedTargetName = normalizeNodeName(name);
    const reusedNode = allGraphNodes.find((node) => {
      const nodeType = extractNodeTypeValue(node);
      const nodeRaw = node?.rawData && typeof node.rawData === 'object' ? node.rawData : node;
      const nodeName = normalizeNodeName(extractDisplayName(nodeRaw));
      return nodeType === type && nodeName === normalizedTargetName;
    });

    if (reusedNode) {
      const reusedNodeId = String(reusedNode.id || '').trim();
      if (!reusedNodeId) {
        setMutationNotice({ type: 'error', text: 'Existing node found but id is missing.' });
        return;
      }
      if (reusedNodeId === fromNodeId) {
        setMutationNotice({ type: 'error', text: 'Source and target cannot be the same node.' });
        return;
      }

      const existingEdge = allGraphEdges.find((edge) => (
        String(edge.from) === fromNodeId
        && String(edge.to) === reusedNodeId
        && String(edge.label || edge.type || edge.rawData?.type || '').trim() === relationType
      ));
      const selectedExistingNode = nodesDataSet.current?.get(reusedNodeId) || reusedNode;
      setSelectedNode(selectedExistingNode);
      setSelectedNodeFilterId(null);
      setSelectedPathId(null);
      setIsAddingNode(false);

      if (existingEdge) {
        setMutationNotice({ type: 'info', text: 'Node already exists and the edge already exists.' });
        return;
      }

      const tempEdgeId = `tmp-edge-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
      const optimisticEdge = {
        id: tempEdgeId,
        from: fromNodeId,
        to: reusedNodeId,
        label: relationType,
      };
      try {
        edgesDataSet.current?.add(optimisticEdge);
      } catch (e) {
        setMutationNotice({ type: 'error', text: e?.message || '前端关系渲染失败，请重试' });
        return;
      }
      setAllGraphEdges((prev) => [...prev, optimisticEdge]);
      setMutationNotice({ type: 'info', text: 'Node exists, creating edge now...' });

      try {
        const edgeResult = await persistEdgeCreate(
          { from_id: fromNodeId, to_id: reusedNodeId, type: relationType },
          operationGroupId,
          'link_existing_node',
        );
        const persistedEdgeId = String(edgeResult?.edgeId || '').trim();
        if (!persistedEdgeId) {
          throw new Error('Create edge failed: missing edge id.');
        }
        edgesDataSet.current?.remove(tempEdgeId);
        edgesDataSet.current?.add({ ...optimisticEdge, id: persistedEdgeId });
        setAllGraphEdges((prev) => prev.map((edge) => (
          String(edge.id) === tempEdgeId ? { ...edge, id: persistedEdgeId } : edge
        )));
        setMutationNotice({ type: 'success', text: 'Node reused and edge created successfully.' });
      } catch (err) {
        edgesDataSet.current?.remove(tempEdgeId);
        setAllGraphEdges((prev) => prev.filter((edge) => String(edge.id) !== tempEdgeId));
        setMutationNotice({ type: 'error', text: err?.message || 'Create edge failed.' });
      }
      return;
    }

    const tempNodeId = `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    const colors = NODE_COLORS[type] || { background: '#888', border: '#666' };
    const center = networkRef.current?.getViewPosition() || { x: 0, y: 0 };
    const newNode = {
      id: tempNodeId,
      label: buildNodeLabel(name, type),
      title: `[${type}]\n${name}`,
      color: colors,
      nodeType: type,
      level: TYPE_LEVELS[type] || 99,
      x: center.x,
      y: center.y,
      rawData: {
        id: tempNodeId,
        type,
        name,
        description,
        props: { name, description },
      },
    };

    const optimisticEdgeId = `${fromNodeId}-${relationType}-${tempNodeId}`;
    const newEdge = {
      id: optimisticEdgeId,
      from: fromNodeId,
      to: tempNodeId,
      label: relationType,
    };

    try {
      nodesDataSet.current?.add(newNode);
      edgesDataSet.current?.add(newEdge);
    } catch (e) {
      setMutationNotice({ type: 'error', text: e?.message || '前端节点渲染失败，请重试' });
      return;
    }
    setAllGraphNodes((prev) => [...prev, newNode]);
    setAllGraphEdges((prev) => [...prev, newEdge]);
    setSelectedNode(newNode);
    setSelectedNodeFilterId(null);
    setSelectedPathId(null);
    setIsAddingNode(false);
    setMutationNotice({ type: 'info', text: 'Creating node and edge...' });

    let finalNodeId = tempNodeId;
    let persistedEdgeId = '';
    let createdBackendNodeId = '';
    let shouldRollbackBackendNode = false;

    try {
      const createResult = await persistNodeCreate(
        { type, name, description },
        operationGroupId,
        operationType,
      );
      finalNodeId = String(createResult?.nodeId || '').trim();
      if (!finalNodeId) {
        throw new Error('Create node failed: missing node id.');
      }
      createdBackendNodeId = finalNodeId;
      shouldRollbackBackendNode = !createResult?.deduplicated;

      if (finalNodeId !== tempNodeId) {
        const replacedNode = { ...newNode, id: finalNodeId, rawData: { ...(newNode.rawData || {}), id: finalNodeId } };
        nodesDataSet.current?.remove(tempNodeId);
        const existingNode = nodesDataSet.current?.get(finalNodeId);
        if (!existingNode) {
          nodesDataSet.current?.add(replacedNode);
          setAllGraphNodes((prev) => prev.map((node) => (
            String(node.id) === tempNodeId ? replacedNode : node
          )));
          setSelectedNode(replacedNode);
        } else {
          setAllGraphNodes((prev) => prev.filter((node) => String(node.id) !== tempNodeId));
          setSelectedNode(existingNode);
          shouldRollbackBackendNode = false;
        }

        edgesDataSet.current?.remove(optimisticEdgeId);
        const replacedEdge = {
          ...newEdge,
          id: `${fromNodeId}-${relationType}-${finalNodeId}`,
          to: finalNodeId,
        };
        edgesDataSet.current?.add(replacedEdge);
        setAllGraphEdges((prev) => prev.map((edge) => (
          String(edge.id) === optimisticEdgeId ? replacedEdge : edge
        )));
      }

      const edgeResult = await persistEdgeCreate(
        { from_id: fromNodeId, to_id: finalNodeId, type: relationType },
        operationGroupId,
        operationType,
      );
      persistedEdgeId = String(edgeResult?.edgeId || '').trim();
      if (!persistedEdgeId) {
        throw new Error('Create edge failed: missing edge id.');
      }

      const edgeBeforePersistId = `${fromNodeId}-${relationType}-${finalNodeId}`;
      const edgeInDataset = edgesDataSet.current?.get(edgeBeforePersistId);
      if (edgeInDataset) {
        edgesDataSet.current?.remove(edgeBeforePersistId);
        edgesDataSet.current?.add({ ...edgeInDataset, id: persistedEdgeId });
        setAllGraphEdges((prev) => prev.map((edge) => (
          String(edge.id) === edgeBeforePersistId ? { ...edge, id: persistedEdgeId } : edge
        )));
      }

      setMutationNotice({ type: 'success', text: 'Node and edge created successfully.' });
    } catch (err) {
      const cleanupNodeIds = new Set([tempNodeId, finalNodeId, createdBackendNodeId].filter(Boolean).map((id) => String(id)));
      cleanupNodeIds.forEach((id) => {
        nodesDataSet.current?.remove(id);
      });
      setAllGraphNodes((prev) => prev.filter((node) => !cleanupNodeIds.has(String(node.id))));

      const cleanupEdgeIds = new Set([
        optimisticEdgeId,
        `${fromNodeId}-${relationType}-${finalNodeId}`,
        persistedEdgeId,
      ].filter(Boolean).map((id) => String(id)));
      cleanupEdgeIds.forEach((id) => {
        edgesDataSet.current?.remove(id);
      });
      setAllGraphEdges((prev) => prev.filter((edge) => !cleanupEdgeIds.has(String(edge.id))));

      let rollbackErrorText = '';
      if (shouldRollbackBackendNode && createdBackendNodeId) {
        try {
          const rollbackRes = await persistNodeDeleteWithDetach(
            createdBackendNodeId,
            true,
            operationGroupId,
            `${operationType}_rollback`,
          );
          if (rollbackRes?.localOnly && !rollbackRes?.notFound) {
            rollbackErrorText = 'Backend rollback endpoint unavailable.';
          }
        } catch (rollbackErr) {
          rollbackErrorText = String(rollbackErr?.message || 'Rollback failed.');
        }
      }

      const baseError = String(err?.message || 'Create node failed.');
      const mergedError = rollbackErrorText
        ? `${baseError} Rollback error: ${rollbackErrorText}`
        : `${baseError} Rolled back.`;
      setSelectedNode(sourceNode || null);
      setMutationNotice({ type: 'error', text: mergedError });
    }
  }, [
    addNodeForm,
    allGraphEdges,
    allGraphNodes,
    persistEdgeCreate,
    persistNodeCreate,
    persistNodeDeleteWithDetach,
    selectedNode,
    selectedNodeFilterId,
  ]);

  const handleEditNodeSave = useCallback(async () => {
    if (!selectedNode) return;
    const nodeId = String(selectedNode.id);
    const oldNode = nodesDataSet.current?.get(nodeId);
    if (!oldNode) return;

    const nextType = (editNodeForm.type || oldNode.nodeType || 'Unknown').trim();
    const nextName = (editNodeForm.name || '').trim();
    const nextDescription = String(editNodeForm.description || '').trim();
    if (!nextName) {
      setMutationNotice({ type: 'error', text: '名称不能为空' });
      return;
    }

    const rawData = { ...(oldNode.rawData || {}), type: nextType, name: nextName };
    if (rawData.props) {
      rawData.props = { ...rawData.props, description: nextDescription };
    } else if (rawData.properties) {
      rawData.properties = { ...rawData.properties, description: nextDescription };
    } else {
      rawData.description = nextDescription;
    }

    // 默认按路径修改：仅迁移当前所选路径上该节点关联的关系
    if (editScope === 'path') {
      if (!selectedPathId) {
        setMutationNotice({ type: 'error', text: '请先在 Paths 中选中具体路径，再执行“按路径修改”' });
        return;
      }

      const pathEntry = allPathEntries.find((entry) => entry.id === selectedPathId);
      if (!pathEntry) {
        setMutationNotice({ type: 'error', text: '未找到选中的路径，请重新选择' });
        return;
      }

      const connectedPathEdges = allGraphEdges.filter((edge) => {
        const edgeId = String(edge.id);
        const inPath = pathEntry.edgeIds.has(edgeId);
        const touchesNode = String(edge.from) === nodeId || String(edge.to) === nodeId;
        return inPath && touchesNode;
      });

      if (connectedPathEdges.length === 0) {
        setMutationNotice({ type: 'error', text: '当前路径上未找到该节点可迁移的关系，请改用“全局修改”' });
        return;
      }

      setMutationNotice({ type: 'info', text: '正在按路径拆分节点并迁移关系...' });
      
      // 为此次按路径修改生成唯一的 operation_group_id
      const operationGroupId = `op-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
      const operationType = 'edit_node_by_path';
      
      try {
        const createResult = await persistNodeCreate({ type: nextType, name: nextName, description: nextDescription }, operationGroupId, operationType);
        if (createResult.localOnly || !createResult.nodeId) {
          throw new Error('后端不支持按路径拆分，请改用全局修改');
        }
        const newNodeId = String(createResult.nodeId);
        const targetNodeReused = Boolean(createResult.deduplicated);
        if (targetNodeReused && newNodeId === nodeId) {
          setMutationNotice({ type: 'info', text: 'No path split applied: target node is the same as current node.' });
          setIsEditingNode(false);
          return;
        }

        for (const edge of connectedPathEdges) {
          const fromId = String(edge.from);
          const toId = String(edge.to);
          const relType = String(edge.label || edge.type || edge.rawData?.type || 'RELATED_TO');
          const relProps = edge.rawData?.props && typeof edge.rawData.props === 'object'
            ? edge.rawData.props
            : undefined;

          const newFromId = fromId === nodeId ? newNodeId : fromId;
          const newToId = toId === nodeId ? newNodeId : toId;

          const createEdgeRes = await persistEdgeCreate({
            from_id: newFromId,
            to_id: newToId,
            type: relType,
            properties: relProps,
          }, operationGroupId, operationType);
          if (createEdgeRes.localOnly) {
            throw new Error('后端不支持关系迁移，已中止');
          }

          const oldEdgeId = String(edge.id || '');
          if (oldEdgeId) {
            const delRes = await persistEdgeDelete(oldEdgeId, operationGroupId, operationType);
            if (delRes.localOnly) {
              throw new Error('后端不支持关系删除，已中止');
            }
          }
        }

        // 尝试删除旧节点：仅在关系清零时成功（detach=false）
        try {
          await persistNodeDeleteWithDetach(nodeId, false, operationGroupId, operationType);
        } catch {
          // 旧节点仍被其它路径引用时会保留，属于预期
        }

        setMutationNotice({ type: 'success', text: `按路径修改完成：已拆分节点并迁移 ${connectedPathEdges.length} 条关系` });
        setIsEditingNode(false);
        if (embedded) EMBEDDED_GRAPH_CACHE.clear();
        if (useRecordsRoute) {
          await loadGraphFromRecords(records, nodeLimit);
        } else {
          await loadGraphData(activeKeyword, nodeLimit, structuredFilters);
        }
        return;
      } catch (err) {
        setMutationNotice({ type: 'error', text: err.message || '按路径修改失败，请在“修改历史”中回滚' });
        return;
      }
    }

    const colors = NODE_COLORS[nextType] || { background: '#888', border: '#666' };
    const optimisticNode = {
      ...oldNode,
      nodeType: nextType,
      label: buildNodeLabel(nextName, nextType),
      title: `[${nextType}]\n${nextName}`,
      color: colors,
      rawData,
    };

    nodesDataSet.current?.update(optimisticNode);
    setAllGraphNodes((prev) => prev.map((item) => (String(item.id) === nodeId ? { ...item, ...optimisticNode } : item)));
    setSelectedNode(optimisticNode);
    setMutationNotice({ type: 'info', text: '正在保存...' });

    try {
      const persisted = await persistNodeUpdate(nodeId, {
        type: nextType,
        name: nextName,
        description: nextDescription,
      });

      if (persisted.localOnly) {
        setMutationNotice({ type: 'warn', text: '已在前端更新（后端未提供节点编辑接口）' });
      } else {
        setMutationNotice({ type: 'success', text: '保存成功' });
      }
      setIsEditingNode(false);
    } catch (err) {
      nodesDataSet.current?.update(oldNode);
      setAllGraphNodes((prev) => prev.map((item) => (String(item.id) === nodeId ? oldNode : item)));
      setSelectedNode(oldNode);
      setMutationNotice({ type: 'error', text: err.message || '保存失败，已回滚' });
    }
  }, [
    editNodeForm,
    selectedNode,
    editScope,
    selectedPathId,
    allPathEntries,
    allGraphEdges,
    persistNodeCreate,
    persistEdgeCreate,
    persistEdgeDelete,
    persistNodeDeleteWithDetach,
    persistNodeUpdate,
    embedded,
    useRecordsRoute,
    records,
    nodeLimit,
    loadGraphFromRecords,
    loadGraphData,
    activeKeyword,
    structuredFilters,
  ]);

  const handleDeleteNode = useCallback(async () => {
    if (!selectedNode) return;
    const nodeId = String(selectedNode.id);
    const nodeBackup = nodesDataSet.current?.get(nodeId);
    if (!nodeBackup) return;

    const relatedEdges = edgesDataSet.current?.get({
      filter: (edge) => String(edge.from) === nodeId || String(edge.to) === nodeId,
    }) || [];

    const confirmed = window.confirm(`确认删除节点「${extractDisplayName(nodeBackup.rawData || nodeBackup)}」？`);
    if (!confirmed) return;

    nodesDataSet.current?.remove(nodeId);
    if (relatedEdges.length > 0) {
      edgesDataSet.current?.remove(relatedEdges.map((edge) => edge.id));
    }

    setAllGraphNodes((prev) => prev.filter((item) => String(item.id) !== nodeId));
    setAllGraphEdges((prev) => prev.filter((edge) => String(edge.from) !== nodeId && String(edge.to) !== nodeId));
    setAllPathEntries((prev) => prev
      .map((entry) => {
        const nextNodeIds = new Set(Array.from(entry.nodeIds).filter((id) => String(id) !== nodeId));
        const nextEdgeIds = new Set(Array.from(entry.edgeIds).filter((eid) => !relatedEdges.some((edge) => String(edge.id) === String(eid))));
        return { ...entry, nodeIds: nextNodeIds, edgeIds: nextEdgeIds };
      })
      .filter((entry) => entry.nodeIds.size > 0));
    setSelectedNode(null);
    setSelectedEdge(null);
    setSelectedNodeFilterId(null);
    setSelectedPathId(null);
    setMutationNotice({ type: 'info', text: '正在删除...' });

    try {
      const persisted = await persistNodeDelete(nodeId);
      if (persisted.localOnly) {
        setMutationNotice({ type: 'warn', text: '已在前端删除（后端未提供节点删除接口）' });
      } else {
        setMutationNotice({ type: 'success', text: '删除成功' });
      }
    } catch (err) {
      nodesDataSet.current?.add(nodeBackup);
      if (relatedEdges.length > 0) {
        edgesDataSet.current?.add(relatedEdges);
      }
      setAllGraphNodes((prev) => [...prev, nodeBackup]);
      setAllGraphEdges((prev) => [...prev, ...relatedEdges]);
      setSelectedNode(nodeBackup);
      setMutationNotice({ type: 'error', text: err.message || '删除失败，已回滚' });
    }
  }, [persistNodeDelete, selectedNode]);

  const handleDeleteEdge = useCallback(async () => {
    if (!selectedEdge) return;
    const edgeId = String(selectedEdge.id || '');
    if (!edgeId) {
      setMutationNotice({ type: 'error', text: '当前关系缺少ID，无法删除' });
      return;
    }

    const edgeBackup = edgesDataSet.current?.get(edgeId);
    if (!edgeBackup) {
      setMutationNotice({ type: 'error', text: '未找到要删除的关系' });
      return;
    }

    const confirmed = window.confirm(`确认删除关系「${edgeBackup.label || 'RELATION'}」？`);
    if (!confirmed) return;

    edgesDataSet.current?.remove(edgeId);
    setAllGraphEdges((prev) => prev.filter((edge) => String(edge.id) !== edgeId));
    setAllPathEntries((prev) => prev.map((entry) => {
      const nextEdgeIds = new Set(Array.from(entry.edgeIds).filter((eid) => String(eid) !== edgeId));
      return { ...entry, edgeIds: nextEdgeIds };
    }).filter((entry) => entry.edgeIds.size > 0));
    setSelectedEdge(null);
    setMutationNotice({ type: 'info', text: '正在删除关系...' });

    try {
      const persisted = await persistEdgeDelete(edgeId);
      if (persisted.localOnly) {
        setMutationNotice({ type: 'warn', text: '关系已在前端删除（后端未提供关系删除接口）' });
      } else {
        setMutationNotice({ type: 'success', text: '关系删除成功' });
      }
    } catch (err) {
      edgesDataSet.current?.add(edgeBackup);
      setAllGraphEdges((prev) => [...prev, edgeBackup]);
      setSelectedEdge(edgeBackup);
      setMutationNotice({ type: 'error', text: err.message || '关系删除失败，已回滚' });
    }
  }, [persistEdgeDelete, selectedEdge]);

  const loadMutationLogs = useCallback(async () => {
    setLoadingMutations(true);
    try {
      const res = await fetchWithTimeout(buildApiUrl('/graph/mutations?limit=100'));
      if (!res.ok) throw new Error(`获取修改历史失败: ${res.status}`);
      const data = await res.json();
      const items = Array.isArray(data?.items) ? [...data.items] : [];
      items.sort((a, b) => String(b?.timestamp || '').localeCompare(String(a?.timestamp || '')));
      setMutationLogs(items);
    } catch (err) {
      setMutationNotice({ type: 'error', text: err.message || '获取修改历史失败' });
    } finally {
      setLoadingMutations(false);
    }
  }, [fetchWithTimeout]);

  const handleClearMutationLogs = useCallback(async () => {
    const confirmed = window.confirm('确认清空修改历史？该操作不可撤销。');
    if (!confirmed) return;
    try {
      const res = await fetchWithTimeout(buildApiUrl('/graph/mutations'), { method: 'DELETE' });
      if (!res.ok) throw new Error(`清空修改历史失败: ${res.status}`);
      setMutationLogs([]);
      setMutationNotice({ type: 'success', text: '修改历史已清空' });
    } catch (err) {
      setMutationNotice({ type: 'error', text: err.message || '清空修改历史失败' });
    }
  }, [fetchWithTimeout]);

  const handleToggleMutationPanel = useCallback(async () => {
    const nextOpen = !showMutationPanel;
    setShowMutationPanel(nextOpen);
    if (nextOpen) {
      await loadMutationLogs();
    }
  }, [loadMutationLogs, showMutationPanel]);

  const handleRollbackMutation = useCallback(async (mutationId) => {
    const id = String(mutationId || '').trim();
    if (!id) return;

    const confirmed = window.confirm(`确认回滚这条修改记录？\nmutation_id=${id}`);
    if (!confirmed) return;

    setRollbackingMutationId(id);
    setMutationNotice({ type: 'info', text: '正在回滚修改...' });
    try {
      const res = await fetchWithTimeout(buildApiUrl(`/graph/mutations/${encodeURIComponent(id)}/rollback`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(`回滚失败: ${res.status}`);
      setMutationNotice({ type: 'success', text: '回滚成功，建议点击搜索重新加载图谱' });
      await loadMutationLogs();
    } catch (err) {
      setMutationNotice({ type: 'error', text: err.message || '回滚失败' });
    } finally {
      setRollbackingMutationId(null);
    }
  }, [fetchWithTimeout, loadMutationLogs]);

  const handleRollbackMutationGroup = useCallback(async (groupId) => {
    const id = String(groupId || '').trim();
    if (!id) return;

    const groupMutations = mutationLogs.filter((m) => String(m?.operation_group_id || '').trim() === id);
    if (groupMutations.length === 0) return;

    const actionsList = groupMutations.map((m) => m.action).join(', ');
    const confirmed = window.confirm(
      `确认一键回滚此操作组？\n操作数: ${groupMutations.length}\n操作: ${actionsList}\n\n此操作不可撤销，请谨慎！`
    );
    if (!confirmed) return;

    setRollbackingMutationId(id);
    setMutationNotice({ type: 'info', text: '正在回滚操作组...' });
    try {
      const res = await fetchWithTimeout(buildApiUrl(`/graph/mutations/${encodeURIComponent(id)}/rollback-group`), {
        method: 'POST',
      });
      if (!res.ok) throw new Error(`组回滚失败: ${res.status}`);
      setMutationNotice({ type: 'success', text: '操作组回滚成功，已重新加载修改历史' });
      await loadMutationLogs();
    } catch (err) {
      setMutationNotice({ type: 'error', text: err.message || '操作组回滚失败' });
    } finally {
      setRollbackingMutationId(null);
    }
  }, [fetchWithTimeout, loadMutationLogs, mutationLogs]);

  useEffect(() => {
    if (!nodesDataSet.current || !edgesDataSet.current) return;
    if (allGraphNodes.length === 0) return;

    const hasPathFilter = Boolean(selectedPathId && allPathEntries.length > 0);

    const isNodeHiddenByType = (node) => {
      if (!selectedNodeTypeOnly) return false;
      const nodeType = String(node?.nodeType || node?.rawData?.type || node?.rawData?.labels?.[0] || 'Unknown');
      return nodeType !== selectedNodeTypeOnly;
    };

    if (!hasPathFilter) {
      // 无路径筛选：仅按“类型筛选”控制可见性
      const visibleNodeIds = new Set();
      const nodeUpdates = allGraphNodes.map((n) => {
        const hidden = isNodeHiddenByType(n);
        if (!hidden) visibleNodeIds.add(String(n.id));
        return { id: n.id, hidden };
      });

      const edgeUpdates = allGraphEdges.map((e) => {
        const fromVisible = visibleNodeIds.has(String(e.from));
        const toVisible = visibleNodeIds.has(String(e.to));
        return { id: e.id, hidden: !(fromVisible && toVisible) };
      });

      nodesDataSet.current.update(nodeUpdates);
      edgesDataSet.current.update(edgeUpdates);
      return;
    }

    const nodeFilteredPaths = selectedNodeFilterId
      ? allPathEntries.filter((entry) => entry.nodeIds.has(String(selectedNodeFilterId)))
      : allPathEntries;

    if (selectedPathId && !nodeFilteredPaths.some((entry) => entry.id === selectedPathId)) {
      setSelectedPathId(null);
      return;
    }

    const activePaths = selectedPathId
      ? nodeFilteredPaths.filter((entry) => entry.id === selectedPathId)
      : nodeFilteredPaths;

    const visibleNodeIds = new Set();
    const visibleEdgeIds = new Set();
    activePaths.forEach((entry) => {
      entry.nodeIds.forEach((id) => visibleNodeIds.add(String(id)));
      entry.edgeIds.forEach((id) => visibleEdgeIds.add(String(id)));
    });

    const finalVisibleNodeIds = new Set();
    allGraphNodes.forEach((n) => {
      const id = String(n.id);
      if (!visibleNodeIds.has(id)) return;
      if (isNodeHiddenByType(n)) return;
      finalVisibleNodeIds.add(id);
    });

    // 用 hidden 属性 show/hide，保留节点坐标，不触发物理重算
    nodesDataSet.current.update(
      allGraphNodes.map((n) => ({ id: n.id, hidden: !finalVisibleNodeIds.has(String(n.id)) }))
    );
    edgesDataSet.current.update(
      allGraphEdges.map((e) => {
        const inPath = visibleEdgeIds.has(String(e.id));
        const fromVisible = finalVisibleNodeIds.has(String(e.from));
        const toVisible = finalVisibleNodeIds.has(String(e.to));
        return { id: e.id, hidden: !(inPath && fromVisible && toVisible) };
      })
    );

  }, [allGraphNodes, allGraphEdges, allPathEntries, selectedNodeFilterId, selectedPathId, selectedNodeTypeOnly]);

  const visiblePathEntries = selectedNodeFilterId
    ? allPathEntries.filter((entry) => entry.nodeIds.has(String(selectedNodeFilterId)))
    : allPathEntries;

  // 初始加载：根据模式选择加载方式
  useEffect(() => {
    if (!autoLoad) {
      clearGraph();
      return;
    }
    if (useRecordsRoute) {
      loadGraphFromRecords(records, nodeLimit);
    } else if (activeKeyword !== undefined) {
      loadGraphData(activeKeyword, nodeLimit);
    }
  }, [autoLoad]);  // 只在首次挂载时执行

  // 节点数量变化时重新加载（跳过首次）
  const nodeLimitInitRef = useRef(true);
  useEffect(() => {
    if (nodeLimitInitRef.current) { nodeLimitInitRef.current = false; return; }
    if (!autoLoad && !hasSearched) return;
    if (useRecordsRoute) {
      loadGraphFromRecords(records, nodeLimit);
    } else {
      loadGraphData(activeKeyword, nodeLimit, structuredFilters);
    }
  }, [nodeLimit, autoLoad, hasSearched]); // eslint-disable-line react-hooks/exhaustive-deps

  const queryModeInitRef = useRef(true);
useEffect(() => {
  if (queryModeInitRef.current) { queryModeInitRef.current = false; return; }
  if (!autoLoad && !hasSearched) return;
  if (useRecordsRoute) {
    loadGraphFromRecords(records, nodeLimit);
  } else {
    const kw = (activeKeyword ?? searchInput ?? '').trim();
    loadGraphData(kw, nodeLimit, structuredFilters);
  }
}, [queryMode, useRecordsRoute, autoLoad, hasSearched, records, nodeLimit, activeKeyword, searchInput, structuredFilters, loadGraphFromRecords, loadGraphData]);
  // 搜索处理 - 搜索框始终使用关键词模式
  const handleSearch = useCallback(() => {
    if (!allowKeywordSearch) return;
    const kw = searchInput.trim();
    const hasStructuredFilters = Object.values(structuredFilters || {}).some((value) => (value || '').trim());
    if (!kw && !hasStructuredFilters) {
      setHasSearched(false);
      setActiveKeyword('');
      setError(null);
      clearGraph();
      return;
    }
    setHasSearched(true);
    setMode('keyword');
    setQueryMode('exact');
    setActiveKeyword(kw);
    loadGraphData(kw, nodeLimit, structuredFilters);
  }, [allowKeywordSearch, searchInput, nodeLimit, loadGraphData, structuredFilters, clearGraph]);

  const handleStructuredSearch = useCallback(() => {
    if (!allowKeywordSearch) return;
    const kw = searchInput.trim();
    const hasStructuredFilters = Object.values(structuredFilters || {}).some((value) => (value || '').trim());
    if (!kw && !hasStructuredFilters) {
      setHasSearched(false);
      setActiveKeyword('');
      setError(null);
      clearGraph();
      return;
    }
    setHasSearched(true);
    setMode('keyword');
    setQueryMode('exact');
    setActiveKeyword(kw);
    loadGraphData(kw, nodeLimit, structuredFilters);
  }, [allowKeywordSearch, searchInput, structuredFilters, clearGraph, loadGraphData, nodeLimit]);

  const updateStructuredField = useCallback((field, value) => {
    setStructuredFilters((prev) => ({ ...prev, [field]: value }));
  }, []);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter') handleSearch();
  }, [handleSearch]);

  const handleSearchSubmit = useCallback((e) => {
    e.preventDefault();
    handleSearch();
  }, [handleSearch]);

  const handleRefreshGraph = useCallback(async () => {
    setError(null);
    setMutationNotice({ type: 'info', text: '正在刷新图谱...' });
    try {
      if (embedded) EMBEDDED_GRAPH_CACHE.clear();
      if (useRecordsRoute) {
        await loadGraphFromRecords(records, nodeLimit);
      } else {
        const kw = (activeKeyword ?? searchInput ?? '').trim();
        await loadGraphData(kw, nodeLimit, structuredFilters);
      }
      setMutationNotice({ type: 'success', text: '图谱已刷新' });
    } catch (err) {
      setMutationNotice({ type: 'error', text: err.message || '刷新失败' });
    }
  }, [embedded, useRecordsRoute, records, nodeLimit, activeKeyword, searchInput, structuredFilters, loadGraphFromRecords, loadGraphData]);

  const toggleNodeTypeFilter = useCallback((nodeType) => {
    const normalized = String(nodeType || '').trim();
    if (!normalized) return;
    setSelectedNodeTypeOnly((prev) => (prev === normalized ? null : normalized));
  }, []);

  const clearNodeTypeFilter = useCallback(() => {
    setSelectedNodeTypeOnly(null);
  }, []);

  // 全屏切换
  const toggleFullscreen = useCallback(() => {
    const prevPosition = networkRef.current?.getViewPosition();
    const prevScale = networkRef.current?.getScale();

    setIsFullscreen(!isFullscreen);
    setTimeout(() => {
      networkRef.current?.redraw();
      if (prevPosition && Number.isFinite(prevScale)) {
        networkRef.current?.moveTo({
          position: prevPosition,
          scale: prevScale,
          animation: false,
        });
      }
      networkRef.current?.setOptions({ physics: { enabled: false } });
    }, 200);
  }, [isFullscreen]);

  const fullscreenStyle = isFullscreen
    ? {
        top: 16,
        right: 16,
        bottom: 16,
        left: `${(isMainSidebarCollapsed ? 64 : 280) + 16}px`,
      }
    : undefined;

  return (
    <div
      className={`${isLight ? 'bg-white border border-slate-200' : 'bg-gray-900'} rounded-lg shadow-xl flex flex-col ${
        isFullscreen ? 'fixed z-50' : (embedded ? 'min-h-[420px] h-auto' : 'h-full')
      }`}
      style={fullscreenStyle}
    >
      {/* 头部 */}
      <div className={`flex items-center justify-between p-3 ${isLight ? 'border-b border-slate-200' : 'border-b border-gray-700'}`}>
        <div className="flex items-center gap-2">
          <h3 className={`${isLight ? 'text-slate-800' : 'text-white'} font-medium`}>知识图谱</h3>
          {mode === 'records' && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-emerald-700 text-emerald-100">
              记录反查
            </span>
          )}
          {mode === 'keyword' && allowKeywordSearch && (
            <span className="px-2 py-0.5 text-xs rounded-full bg-blue-700 text-blue-100">
              Graph Search
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* 搜索框（仅 keyword 模式开放） */}
          {allowKeywordSearch && (
            <form onSubmit={handleSearchSubmit} className="flex items-center gap-2">
              <div className={`flex items-center rounded px-2 ${isLight ? 'bg-slate-100' : 'bg-gray-800'}`}>
                <input
                  type="text"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="输入关键词..."
                  className={`bg-transparent text-sm py-1 px-2 w-40 outline-none ${isLight ? 'text-slate-700 placeholder:text-slate-400' : 'text-white'}`}
                />
              </div>
              <button
                type="submit"
                className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border ${isLight ? 'bg-white border-slate-200 text-slate-700 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 border-gray-700 text-gray-200 hover:text-white'}`}
              >
                <Search size={14} />
                搜索
              </button>
            </form>
          )}

          <button
            type="button"
            onClick={() => {
              const source = selectedNode
                || (selectedNodeFilterId ? nodesDataSet.current?.get(String(selectedNodeFilterId)) : null);
              setAddNodeForm((prev) => ({
                ...prev,
                fromNodeId: source ? String(source.id) : '',
                relationType: suggestRelationTypeByNodes(source, prev.type),
              }));
              setIsAddingNode(true);
            }}
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border ${isLight ? 'bg-white border-slate-200 text-slate-700 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 border-gray-700 text-gray-200 hover:text-white'}`}
          >
            <Plus size={14} />
            新增节点
          </button>

          <button
            type="button"
            onClick={handleToggleMutationPanel}
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border ${isLight ? 'bg-white border-slate-200 text-slate-700 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 border-gray-700 text-gray-200 hover:text-white'}`}
          >
            <History size={14} />
            修改历史
          </button>

          <button
            type="button"
            onClick={handleRefreshGraph}
            disabled={loading}
            className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border disabled:opacity-60 disabled:cursor-not-allowed ${isLight ? 'bg-white border-slate-200 text-slate-700 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 border-gray-700 text-gray-200 hover:text-white'}`}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            刷新
          </button>

          {isRecordsContext && (
            <select
              value={queryMode}
              onChange={(e) => setQueryMode(String(e.target.value || 'exact'))}
              className={`${isLight ? 'bg-slate-100 text-slate-700 border border-slate-200' : 'bg-gray-800 text-white'} text-sm rounded px-2 py-1 outline-none`}
              title="查询模式"
            >
              <option value="exact">精确模式</option>
              <option value="normal">普通模式</option>
            </select>
          )}

          {/* 节点数量选择 */}
          <select
            value={nodeLimit}
            onChange={(e) => setNodeLimit(Number(e.target.value))}
            disabled={isRecordsContext && queryMode === 'exact'}
            className={`${isLight ? 'bg-slate-100 text-slate-700 border border-slate-200' : 'bg-gray-800 text-white'} text-sm rounded px-2 py-1 outline-none disabled:opacity-50 disabled:cursor-not-allowed`}
            title={isRecordsContext && queryMode === 'exact' ? '精确模式下数量固定为匹配结果，无法手动调整' : '节点数量上限'}
          >
            {normalizedLimitOptions.map((opt) => (
              <option key={opt} value={opt}>{opt}条</option>
            ))}
          </select>

          {/* 全屏按钮 */}
          <button
            onClick={toggleFullscreen}
            className={`${isLight ? 'text-slate-500 hover:text-slate-700' : 'text-gray-400 hover:text-white'} p-1`}
          >
            {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
          </button>

          {/* 关闭按钮 */}
          {onClose && (
            <button onClick={onClose} className={`${isLight ? 'text-slate-500 hover:text-slate-700' : 'text-gray-400 hover:text-white'} p-1`}>
              <X size={18} />
            </button>
          )}
        </div>
      </div>

      {/* 图例 */}
      <div className={`flex items-center gap-4 px-3 py-2 text-xs flex-wrap ${isLight ? 'border-b border-slate-200' : 'border-b border-gray-700'}`}>
        {Object.entries(NODE_COLORS).map(([type, colors]) => (
          <button
            key={type}
            type="button"
            onClick={() => toggleNodeTypeFilter(type)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border transition-colors ${(selectedNodeTypeOnly === type)
              ? (isLight ? 'bg-orange-50 border-orange-300 text-orange-700' : 'bg-orange-900/30 border-orange-700 text-orange-200')
              : (selectedNodeTypeOnly && selectedNodeTypeOnly !== type)
                ? (isLight ? 'bg-slate-100 border-slate-300 text-slate-400' : 'bg-gray-800 border-gray-700 text-gray-500')
                : (isLight ? 'bg-white border-slate-200 text-slate-600 hover:border-orange-300' : 'bg-gray-900 border-gray-700 text-gray-300 hover:border-gray-500')}`}
            title={(selectedNodeTypeOnly === type)
              ? `已仅显示${TYPE_LABELS[type] || type}，再点恢复全部`
              : `点击后仅显示${TYPE_LABELS[type] || type}`}
          >
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: colors.background }}
            />
            <span>{TYPE_LABELS[type] || type}</span>
          </button>
        ))}
        {selectedNodeTypeOnly && (
          <button
            type="button"
            onClick={clearNodeTypeFilter}
            className={`text-[11px] px-2 py-1 rounded border ${isLight ? 'bg-white border-slate-200 text-slate-600 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-900 border-gray-700 text-gray-300 hover:text-white'}`}
          >
            显示全部类型
          </button>
        )}
        <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}></span>
        <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'} ml-auto`}>当前为原始CSV整行模式</span>
      </div>

      {allowKeywordSearch && cypherPreview && (
        <div className={`${isLight ? 'border-b border-slate-200 bg-slate-50/80' : 'border-b border-gray-700 bg-gray-950/80'}`}>
          <button
            type="button"
            onClick={() => setShowCypherPreview((prev) => !prev)}
            className={`w-full px-3 py-2 flex items-center justify-between text-left ${isLight ? 'hover:bg-slate-100/80' : 'hover:bg-gray-900/40'}`}
          >
            <div className="flex items-center gap-2">
              <span className={`text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                {executedCypher ? '实际执行 Cypher' : '查询语句预览'}（点击展开）
              </span>
              {queryTrace && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-400/20">
                  {queryTrace}
                </span>
              )}
            </div>
            {showCypherPreview ? (
              <ChevronDown size={14} className={`${isLight ? 'text-slate-500' : 'text-gray-400'}`} />
            ) : (
              <ChevronRight size={14} className={`${isLight ? 'text-slate-500' : 'text-gray-400'}`} />
            )}
          </button>
          {showCypherPreview && (
            <div className="px-3 pb-2">
              <pre className={`max-h-40 overflow-auto text-[11px] leading-5 whitespace-pre-wrap break-all ${isLight ? 'text-emerald-700' : 'text-emerald-300'}`}>{cypherPreview}</pre>
            </div>
          )}
        </div>
      )}

      {allowKeywordSearch && mode === 'keyword' && (
        <div className={`px-3 py-2 ${isLight ? 'border-b border-slate-200 bg-slate-50/70' : 'border-b border-gray-700 bg-gray-900/70'}`}>
          <div className={`text-[11px] mb-2 ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>问题拆解结果（可手工修改）</div>
          <div className="flex flex-wrap gap-2 mb-3">
            {structuredFilterChips.length > 0 ? structuredFilterChips.map((item) => (
              <span
                key={item.key}
                className="inline-flex items-center gap-1 rounded-full bg-blue-500/15 text-blue-200 border border-blue-400/20 px-2 py-1 text-[11px]"
              >
                <span className="text-blue-300">{item.label}</span>
                <span>{item.value}</span>
              </span>
            )) : (
              <span className={`text-[11px] ${isLight ? 'text-slate-400' : 'text-gray-500'}`}>当前未自动识别到明确条件，可手工填写。</span>
            )}
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {[
              ['area', '区域'],
              ['equipment', '设备/工位'],
              ['component', '部件/功能点'],
              ['problem', '问题'],
              ['cause', '原因'],
              ['solution', '解决方案'],
            ].map(([field, label]) => (
              <label key={field} className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                <span>{label}</span>
                <input
                  type="text"
                  value={structuredFilters[field] || ''}
                  onChange={(e) => updateStructuredField(field, e.target.value)}
                  className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-800 text-white border-gray-700'}`}
                />
              </label>
            ))}
          </div>
          <div className="mt-3 flex justify-end">
            <button
              type="button"
              onClick={handleStructuredSearch}
              className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded text-xs border ${isLight ? 'bg-white border-slate-200 text-slate-700 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 border-gray-700 text-gray-200 hover:text-white'}`}
            >
              <Search size={14} />
              筛选搜索
            </button>
          </div>
        </div>
      )}

      {/* 图容器：全屏时强制使用非嵌入布局，撑满剩余空间 */}
      <div className={(embedded && !isFullscreen) ? 'flex flex-col' : 'flex-1 min-h-0 flex flex-col'}>
        <div className={(embedded && !isFullscreen) ? 'relative' : 'flex-1 relative min-h-0'}>
          <div
            ref={containerRef}
            className={(embedded && !isFullscreen) ? 'w-full' : 'w-full h-full'}
            style={(embedded && !isFullscreen)
              ? { height: '280px', backgroundColor: isLight ? '#ffffff' : '#111827' }
              : { backgroundColor: isLight ? '#ffffff' : '#111827' }}
          />

          {!loading && allowKeywordSearch && mode === 'keyword' && !hasSearched && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className={`${isLight ? 'text-slate-500' : 'text-gray-300'} text-sm`}>请输入关键词后搜索</div>
            </div>
          )}

        {/* 加载遮罩 */}
          {loading && (
            <div className={`absolute inset-0 flex items-center justify-center ${isLight ? 'bg-white/80' : 'bg-gray-900/70'}`}>
              <div className="flex flex-col items-center w-72 max-w-[80%]">
                <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <span className={`${isLight ? 'text-slate-600' : 'text-gray-300'} text-sm mt-2`}>{loadingText}</span>
                <div className={`w-full h-2 mt-3 rounded-full overflow-hidden ${isLight ? 'bg-slate-200' : 'bg-gray-800'}`}>
                  <div
                    className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-300"
                    style={{ width: `${loadingProgress}%` }}
                  />
                </div>
                <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'} text-xs mt-2`}>{loadingProgress}%</span>
              </div>
            </div>
          )}

          {/* 错误提示 */}
          {error && !loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-red-500 text-center">
                <p>{error}</p>
                <button
                  onClick={() => {
                    if (useRecordsRoute) {
                      loadGraphFromRecords(records, nodeLimit);
                    } else {
                      loadGraphData(activeKeyword, nodeLimit, structuredFilters);
                    }
                  }}
                  className={`mt-2 px-3 py-1 rounded text-sm ${isLight ? 'bg-slate-200 hover:bg-slate-300 text-slate-700' : 'bg-gray-700 hover:bg-gray-600 text-white'}`}
                >
                  重试
                </button>
              </div>
            </div>
          )}

          {isAddingNode && (
            <div className={`absolute top-4 right-4 z-20 w-[320px] rounded-lg p-3 shadow-lg ${isLight ? 'bg-white border border-slate-200' : 'bg-gray-800 border border-gray-700'}`}>
              <div className="flex items-center justify-between mb-2">
                <h4 className={`${isLight ? 'text-slate-700' : 'text-gray-100'} text-sm font-semibold`}>新增节点</h4>
                <button
                  type="button"
                  onClick={() => setIsAddingNode(false)}
                  className={`${isLight ? 'text-slate-400 hover:text-slate-600' : 'text-gray-400 hover:text-white'}`}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="space-y-2">
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>名称</span>
                  <input
                    type="text"
                    value={addNodeForm.name}
                    onChange={(e) => setAddNodeForm((prev) => ({ ...prev, name: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>类型</span>
                  <select
                    value={addNodeForm.type}
                    onChange={(e) => {
                      const nextType = String(e.target.value || '').trim();
                      setAddNodeForm((prev) => {
                        const lockedSource = prev.fromNodeId
                          ? nodesDataSet.current?.get(String(prev.fromNodeId))
                          : (selectedNode || (selectedNodeFilterId ? nodesDataSet.current?.get(String(selectedNodeFilterId)) : null));
                        return {
                          ...prev,
                          type: nextType,
                          relationType: suggestRelationTypeByNodes(lockedSource, nextType),
                        };
                      });
                    }}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  >
                    {Object.keys(TYPE_LABELS).map((type) => (
                      <option key={type} value={type}>{TYPE_LABELS[type]} ({type})</option>
                    ))}
                  </select>
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>描述</span>
                  <input
                    type="text"
                    value={addNodeForm.description}
                    onChange={(e) => setAddNodeForm((prev) => ({ ...prev, description: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>源节点</span>
                  <select
                    value={addNodeForm.fromNodeId || ''}
                    onChange={(e) => {
                      const nextFromNodeId = String(e.target.value || '').trim();
                      const nextSource = nextFromNodeId
                        ? nodesDataSet.current?.get(nextFromNodeId)
                        : null;
                      setAddNodeForm((prev) => ({
                        ...prev,
                        fromNodeId: nextFromNodeId,
                        relationType: suggestRelationTypeByNodes(nextSource, prev.type),
                      }));
                    }}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  >
                    <option value="">请选择源节点</option>
                    {allGraphNodes.map((node) => {
                      const nodeId = String(node?.id || '');
                      const nodeType = extractNodeTypeValue(node) || 'Unknown';
                      const nodeName = extractDisplayName(node?.rawData || node);
                      return (
                        <option key={nodeId} value={nodeId}>
                          {nodeName}（{nodeType}）
                        </option>
                      );
                    })}
                  </select>
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>Relation type (auto-filled by type, editable)</span>
                  <input
                    type="text"
                    value={addNodeForm.relationType}
                    onChange={(e) => setAddNodeForm((prev) => ({ ...prev, relationType: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <div className={`text-[11px] ${isLight ? 'text-slate-400' : 'text-gray-500'}`}>
                  {(() => {
                    const lockedSource = addNodeForm.fromNodeId
                      ? nodesDataSet.current?.get(String(addNodeForm.fromNodeId))
                      : (selectedNode || (selectedNodeFilterId ? nodesDataSet.current?.get(String(selectedNodeFilterId)) : null));
                    return lockedSource
                      ? `Source node: ${extractDisplayName(lockedSource.rawData || lockedSource)}`
                      : 'No source node selected.';
                  })()}
                </div>
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setIsAddingNode(false)}
                    className={`text-xs px-2.5 py-1 rounded border ${isLight ? 'bg-white text-slate-700 border-slate-200 hover:border-slate-300' : 'bg-gray-900 text-gray-200 border-gray-700 hover:text-white'}`}
                  >
                    取消
                  </button>
                  <button
                    type="button"
                    onClick={handleCreateNode}
                    className={`text-xs px-2.5 py-1 rounded border ${isLight ? 'bg-white text-slate-700 border-slate-200 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-900 text-gray-200 border-gray-700 hover:text-white'}`}
                  >
                    确认新增
                  </button>
                </div>
              </div>
            </div>
          )}

          {showMutationPanel && (
            <div className={`absolute top-4 left-4 z-20 w-[520px] max-w-[92%] rounded-lg p-3 shadow-lg ${isLight ? 'bg-white border border-slate-200' : 'bg-gray-800 border border-gray-700'}`}>
              <div className="flex items-center justify-between mb-2">
                <h4 className={`${isLight ? 'text-slate-700' : 'text-gray-100'} text-sm font-semibold`}>修改历史（可选回滚）</h4>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={loadMutationLogs}
                    className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-slate-600 border-slate-200 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-900 text-gray-300 border-gray-700 hover:text-white'}`}
                  >
                    刷新
                  </button>
                  <button
                    type="button"
                    onClick={handleClearMutationLogs}
                    className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-red-600 border-red-200 hover:bg-red-50' : 'bg-gray-900 text-red-300 border-red-900/50 hover:text-red-200'}`}
                  >
                    清空
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowMutationPanel(false)}
                    className={`${isLight ? 'text-slate-400 hover:text-slate-600' : 'text-gray-400 hover:text-white'}`}
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>

              <div className={`text-[11px] mb-2 ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                选择一条记录后点击“回滚”，按 mutation_id 精确回滚。
              </div>

              <div className={`max-h-64 overflow-auto space-y-2 pr-1 ${isLight ? 'text-slate-600' : 'text-gray-300'}`}>
                {loadingMutations && (
                  <div className={`text-xs ${isLight ? 'text-slate-400' : 'text-gray-500'}`}>正在加载修改历史...</div>
                )}

                {!loadingMutations && mutationLogs.length === 0 && (
                  <div className={`text-xs ${isLight ? 'text-slate-400' : 'text-gray-500'}`}>暂无可用修改记录</div>
                )}

                {!loadingMutations && mutationLogs.length > 0 && (() => {
                  const groups = new Map();
                  const ungrouped = [];
                  mutationLogs.forEach((item) => {
                    const groupId = String(item?.operation_group_id || '').trim();
                    if (groupId) {
                      if (!groups.has(groupId)) groups.set(groupId, []);
                      groups.get(groupId).push(item);
                    } else {
                      ungrouped.push(item);
                    }
                  });
                  
                  return (
                    <>
                      {Array.from(groups.entries()).map(([groupId, items]) => {
                        const operationType = String(items[0]?.operation_type || '').trim();
                        const typeLabel = operationType === 'edit_node_by_path' ? '按路径修改节点' : '批量操作';
                        const firstTime = String(items[0]?.timestamp || '');
                        const lastTime = String(items[items.length - 1]?.timestamp || '');
                        
                        return (
                          <div key={groupId} className={`rounded-lg border p-3 ${isLight ? 'border-orange-200 bg-orange-50' : 'border-orange-800/50 bg-orange-900/20'}`}>
                            <div className="flex items-start justify-between gap-2 mb-2">
                              <div className="min-w-0 flex-1">
                                <div className={`text-sm font-semibold ${isLight ? 'text-orange-900' : 'text-orange-200'}`}>{typeLabel}</div>
                                <div className={`text-xs ${isLight ? 'text-orange-700' : 'text-orange-300'}`}>{items.length} 个操作 · {firstTime.slice(11, 19)} 到 {lastTime.slice(11, 19)}</div>
                              </div>
                              <button type="button" disabled={rollbackingMutationId === groupId} onClick={() => handleRollbackMutationGroup(groupId)} className={`inline-flex items-center gap-1 text-[11px] px-2 py-1.5 rounded border font-medium whitespace-nowrap disabled:opacity-60 disabled:cursor-not-allowed transition ${isLight ? 'bg-white text-red-700 border-red-300 hover:bg-red-50' : 'bg-red-900/40 text-red-200 border-red-700/60 hover:bg-red-900/60'}`}>
                                <RotateCcw size={12} />
                                {rollbackingMutationId === groupId ? '回滚中...' : '一键回滚'}
                              </button>
                            </div>
                            <details className={`text-[10px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                              <summary className="cursor-pointer mb-1 select-none">详细操作步骤</summary>
                              <div className="space-y-1.5 ml-2 border-l-2 border-current pl-2 opacity-85">
                                {items.map((item, idx) => {
                                  const action = String(item?.action || '').trim();
                                  const t = item?.target || {};
                                  const nodeName = String(t?.node_name || '').trim();
                                  const nodeLabel = String(t?.node_label || '').trim();
                                  const beforeName = String(t?.node_name_before || '').trim();
                                  const afterName = String(t?.node_name_after || '').trim();
                                  const beforeLabel = String(t?.node_label_before || '').trim();
                                  const afterLabel = String(t?.node_label_after || '').trim();
                                  const fromName = String(t?.from_name || '').trim();
                                  const toName = String(t?.to_name || '').trim();
                                  const relType = String(t?.type || '').trim();

                                  let desc = '';
                                  if (action === 'create_node') {
                                    desc = `新增节点：${nodeName || '未命名'}${nodeLabel ? `（${nodeLabel}）` : ''}`;
                                  } else if (action === 'delete_node') {
                                    desc = `删除节点：${nodeName || '未命名'}${nodeLabel ? `（${nodeLabel}）` : ''}`;
                                  } else if (action === 'update_node') {
                                    if (beforeName && afterName && beforeName !== afterName) {
                                      desc = `名称变更：${beforeName} → ${afterName}`;
                                    } else if (beforeLabel && afterLabel && beforeLabel !== afterLabel) {
                                      desc = `类型变更：${beforeLabel} → ${afterLabel}`;
                                    } else {
                                      desc = `更新节点：${afterName || beforeName || t?.node_id || '-'}`;
                                    }
                                  } else if (action === 'create_edge') {
                                    desc = `新增路径：${fromName || t?.from_id || '-'} → ${toName || t?.to_id || '-'}${relType ? `（${relType}）` : ''}`;
                                  } else if (action === 'delete_edge') {
                                    desc = `删除路径：${fromName || t?.from_id || '-'} → ${toName || t?.to_id || '-'}${relType ? `（${relType}）` : ''}`;
                                  } else {
                                    desc = `${action}: ${t?.node_id || t?.rel_id || '-'}`;
                                  }

                                  return (
                                    <div key={idx} className="text-[11px] leading-4">
                                      {idx + 1}. {desc}
                                    </div>
                                  );
                                })}
                              </div>
                            </details>
                          </div>
                        );
                      })}
                      {ungrouped.map((item) => {
                        const mutationId = String(item?.mutation_id || '');
                        const action = String(item?.action || 'unknown');
                        const timestamp = String(item?.timestamp || '');
                        const targetNodeId = item?.target?.node_id ? String(item.target.node_id) : '';
                        const targetRelId = item?.target?.rel_id ? String(item.target.rel_id) : '';
                        const targetDesc = targetNodeId ? `node: ${targetNodeId}` : (targetRelId ? `edge: ${targetRelId}` : 'target: -');

                        return (
                          <div key={mutationId || `${action}-${timestamp}`} className={`rounded border px-2 py-2 ${isLight ? 'border-slate-200 bg-slate-50' : 'border-gray-700 bg-gray-900/60'}`}>
                            <div className="flex items-start justify-between gap-2">
                              <div className="min-w-0">
                                <div className={`text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>{timestamp}</div>
                                <div className={`text-xs font-medium ${isLight ? 'text-slate-700' : 'text-gray-200'}`}>{action}</div>
                                <div className="text-[11px] break-all">{targetDesc}</div>
                              </div>
                              <button type="button" disabled={!mutationId || rollbackingMutationId === mutationId} onClick={() => handleRollbackMutation(mutationId)} className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded border disabled:opacity-60 disabled:cursor-not-allowed ${isLight ? 'bg-white text-red-600 border-red-200 hover:bg-red-50' : 'bg-gray-900 text-red-300 border-red-900/50 hover:text-red-200'}`}>
                                <RotateCcw size={12} />
                                {rollbackingMutationId === mutationId ? '回滚中...' : '回滚'}
                              </button>
                            </div>
                          </div>
                        );
                      })}
                    </>
                  );
                })()}
              </div>
            </div>
          )}

        {/* 节点详情面板 */}
          {selectedNode && (
            <div className={`absolute bottom-4 left-4 right-4 rounded-lg p-3 max-h-40 overflow-auto ${isLight ? 'bg-white border border-slate-200' : 'bg-gray-800'}`}>
            <div className="flex items-center justify-between mb-2">
              <span
                className="px-2 py-0.5 rounded text-xs text-white"
                style={{ backgroundColor: NODE_COLORS[selectedNode.nodeType]?.background || '#888' }}
              >
                {getTypeDisplayText(selectedNode.nodeType)}
              </span>
              <div className="flex items-center gap-2">
                {!isEditingNode ? (
                  <button
                    type="button"
                    onClick={() => setIsEditingNode(true)}
                    className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-slate-600 border-slate-200 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-900 text-gray-300 border-gray-700 hover:text-white'}`}
                  >
                    编辑
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => setIsEditingNode(false)}
                    className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-slate-600 border-slate-200 hover:border-slate-300' : 'bg-gray-900 text-gray-300 border-gray-700 hover:text-white'}`}
                  >
                    取消
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleDeleteNode}
                  className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-red-600 border-red-200 hover:bg-red-50' : 'bg-gray-900 text-red-300 border-red-900/50 hover:text-red-200'}`}
                >
                  删除
                </button>
                <button
                  onClick={() => setSelectedNode(null)}
                  className={`${isLight ? 'text-slate-400 hover:text-slate-600' : 'text-gray-400 hover:text-white'}`}
                >
                  <X size={14} />
                </button>
              </div>
            </div>
            {!isEditingNode ? (
              <>
                <div className={`${isLight ? 'text-slate-800' : 'text-white'} text-sm font-medium mb-2`}>
                  {selectedNode.rawData ? extractDisplayName(selectedNode.rawData) : selectedNode.label}
                </div>
                <div className={`text-xs space-y-1 ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <div className="truncate">
                    <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}>节点种类: </span>
                    <span>{getTypeDisplayText(selectedNode.nodeType)}</span>
                  </div>
                  {selectedNode.rawData && Object.entries(selectedNode.rawData).filter(([k]) => !['id'].includes(k)).slice(0, 5).map(([k, v]) => (
                    <div key={k} className="truncate">
                      <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}>{k}: </span>
                      <span>{String(v).slice(0, 100)}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setEditScope('path')}
                    className={`text-[11px] px-2 py-0.5 rounded border ${editScope === 'path'
                      ? (isLight ? 'bg-orange-50 text-orange-700 border-orange-200' : 'bg-orange-900/30 text-orange-200 border-orange-700/60')
                      : (isLight ? 'bg-white text-slate-600 border-slate-200' : 'bg-gray-900 text-gray-300 border-gray-700')}`}
                  >
                    按当前路径修改（默认）
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditScope('global')}
                    className={`text-[11px] px-2 py-0.5 rounded border ${editScope === 'global'
                      ? (isLight ? 'bg-blue-50 text-blue-700 border-blue-200' : 'bg-blue-900/30 text-blue-200 border-blue-700/60')
                      : (isLight ? 'bg-white text-slate-600 border-slate-200' : 'bg-gray-900 text-gray-300 border-gray-700')}`}
                  >
                    全局修改（影响所有路径）
                  </button>
                </div>
                <div className={`text-[11px] ${isLight ? 'text-slate-400' : 'text-gray-500'}`}>
                  {editScope === 'path'
                    ? (selectedPathId ? `当前将仅修改已选路径：${selectedPathId}` : '请先在 Paths 区域点击一条路径，再执行按路径修改')
                    : '将直接修改当前节点ID，所有引用该节点的路径都会变化'}
                </div>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>名称</span>
                  <input
                    type="text"
                    value={editNodeForm.name}
                    onChange={(e) => setEditNodeForm((prev) => ({ ...prev, name: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>类型</span>
                  <input
                    type="text"
                    value={editNodeForm.type}
                    onChange={(e) => setEditNodeForm((prev) => ({ ...prev, type: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <label className={`flex flex-col gap-1 text-[11px] ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                  <span>描述</span>
                  <input
                    type="text"
                    value={editNodeForm.description}
                    onChange={(e) => setEditNodeForm((prev) => ({ ...prev, description: e.target.value }))}
                    className={`text-sm rounded px-2 py-1 outline-none border ${isLight ? 'bg-white text-slate-700 border-slate-200' : 'bg-gray-900 text-white border-gray-700'}`}
                  />
                </label>
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={handleEditNodeSave}
                    className={`text-xs px-2.5 py-1 rounded border ${isLight ? 'bg-white text-slate-700 border-slate-200 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-900 text-gray-200 border-gray-700 hover:text-white'}`}
                  >
                    保存修改
                  </button>
                </div>
              </div>
            )}
            </div>
          )}

          {!selectedNode && selectedEdge && (
            <div className={`absolute bottom-4 left-4 right-4 rounded-lg p-3 max-h-32 overflow-auto ${isLight ? 'bg-white border border-slate-200' : 'bg-gray-800'}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="px-2 py-0.5 rounded text-xs text-white bg-indigo-600">关系</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleDeleteEdge}
                    className={`text-[11px] px-2 py-0.5 rounded border ${isLight ? 'bg-white text-red-600 border-red-200 hover:bg-red-50' : 'bg-gray-900 text-red-300 border-red-900/50 hover:text-red-200'}`}
                  >
                    删除关系
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedEdge(null)}
                    className={`${isLight ? 'text-slate-400 hover:text-slate-600' : 'text-gray-400 hover:text-white'}`}
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
              <div className={`${isLight ? 'text-slate-800' : 'text-white'} text-sm font-medium mb-2`}>
                {selectedEdge.label || 'RELATION'}
              </div>
              <div className={`text-xs space-y-1 ${isLight ? 'text-slate-500' : 'text-gray-400'}`}>
                <div>
                  <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}>ID: </span>
                  <span>{String(selectedEdge.id || '')}</span>
                </div>
                <div>
                  <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}>from: </span>
                  <span>{String(selectedEdge.from || '')}</span>
                </div>
                <div>
                  <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'}`}>to: </span>
                  <span>{String(selectedEdge.to || '')}</span>
                </div>
              </div>
            </div>
          )}
        </div>

      {showPaths && pathList.length > 0 && (
        <div className={`flex-shrink-0 ${isLight ? 'border-t border-slate-200 bg-white' : 'border-t border-gray-700 bg-gray-900/60'}`}>
          {/* 拖拽手柄 */}
          <div 
            className="w-full h-1.5 bg-gray-600 cursor-row-resize hover:bg-blue-500 transition-colors"
            onMouseDown={(e) => {
              e.preventDefault();
              const startY = e.clientY;
              const startHeight = pathPanelHeight;

              const doDrag = (moveEvent) => {
                const newHeight = startHeight + (startY - moveEvent.clientY);
                setPathPanelHeight(Math.max(80, newHeight));
              };

              const stopDrag = () => {
                document.removeEventListener('mousemove', doDrag);
                document.removeEventListener('mouseup', stopDrag);
              };

              document.addEventListener('mousemove', doDrag);
              document.addEventListener('mouseup', stopDrag);
            }}
          />
          
          {/* 路径面板内容 */}
          <div className="px-3 py-2">
            <div className="flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setShowPathPanel((prev) => !prev)}
                className="flex-1 flex items-center justify-between"
              >
                <span className={`${isLight ? 'text-slate-700' : 'text-gray-200'} text-xs font-semibold`}>
                  {isRecordsContext && queryMode === 'exact'
                    ? `Paths（全量${allPathEntries.length}）`
                    : `Paths（可见${visiblePathEntries.length} / 已加载${allPathEntries.length} / 上限${nodeLimit}${Number.isFinite(totalPathCount) ? ` / 全量${totalPathCount}` : ''}）`}
                </span>
                {showPathPanel ? (
                  <ChevronDown size={14} className={`${isLight ? 'text-slate-500' : 'text-gray-400'}`} />
                ) : (
                  <ChevronRight size={14} className={`${isLight ? 'text-slate-500' : 'text-gray-400'}`} />
                )}
              </button>
              {(selectedNodeFilterId || selectedPathId) && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedNodeFilterId(null);
                    setSelectedPathId(null);
                  }}
                  className={`text-[11px] px-2 py-1 rounded border ${isLight ? 'bg-white text-slate-600 border-slate-200 hover:border-orange-300 hover:text-orange-600' : 'bg-gray-800 text-gray-300 border-gray-700 hover:text-white'}`}
                >
                  清除筛选
                </button>
              )}
            </div>
            
            {/* 应用高度的路径列表容器 */}
            <div 
              className={`${showPathPanel ? 'mt-2' : 'hidden'} overflow-auto space-y-1 pr-1`}
              style={{ maxHeight: `${pathPanelHeight}px` }}
              onWheel={(e) => e.stopPropagation()}
            >
              {visiblePathEntries.map((entry, idx) => (
                <div
                  key={entry.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelectedPathId((prev) => (prev === entry.id ? null : entry.id))}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      setSelectedPathId((prev) => (prev === entry.id ? null : entry.id));
                    }
                  }}
                  className={`text-xs rounded px-2 py-1 cursor-pointer ${selectedPathId === entry.id
                    ? (isLight ? 'bg-orange-50 text-orange-700 border border-orange-200' : 'bg-orange-900/30 text-orange-200 border border-orange-700/60')
                    : (isLight ? 'bg-slate-50 text-slate-600 border border-slate-200 hover:border-orange-200' : 'bg-gray-800 text-gray-300 border border-gray-700 hover:border-gray-500')}`}
                  title={entry.text}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <span className={`${isLight ? 'text-slate-400' : 'text-gray-500'} mr-1`}>{idx + 1}.</span>
                      <span>{entry.text}</span>
                    </div>
                    {entry.sourceText ? (
                      <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border ${isLight ? 'text-blue-700 bg-blue-50 border-blue-200' : 'text-blue-200 bg-blue-900/30 border-blue-700/60'}`}>
                        {entry.sourceText}
                      </span>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {mutationNotice && (
        <div className={`px-3 py-2 text-xs border-t ${
          mutationNotice.type === 'success'
            ? (isLight ? 'bg-emerald-50 text-emerald-700 border-emerald-200' : 'bg-emerald-900/20 text-emerald-200 border-emerald-700/40')
            : mutationNotice.type === 'warn'
              ? (isLight ? 'bg-amber-50 text-amber-700 border-amber-200' : 'bg-amber-900/20 text-amber-200 border-amber-700/40')
              : mutationNotice.type === 'error'
                ? (isLight ? 'bg-red-50 text-red-700 border-red-200' : 'bg-red-900/20 text-red-200 border-red-700/40')
                : (isLight ? 'bg-slate-50 text-slate-600 border-slate-200' : 'bg-gray-900 text-gray-300 border-gray-700')
        }`}>
          {mutationNotice.text}
        </div>
      )}
      </div>
    </div>
  );
}
