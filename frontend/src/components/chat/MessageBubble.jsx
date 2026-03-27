import React, { useEffect, useRef, useState } from 'react';
import Markdown from 'react-markdown';
import { User, Bot, Copy, RotateCcw, ThumbsUp, ThumbsDown, Table, ChevronDown, ChevronUp, ArrowUp, ArrowDown } from 'lucide-react';
import KnowledgeGraph from './KnowledgeGraph';
import Neo4jGraph from './Neo4jGraph';
import MermaidDiagram from './MermaidDiagram';
import DiagnosisView from './DiagnosisView';
import { sendMessage } from '../../services/chatApi';

const FOLLOWUP_HISTORY_STORAGE_PREFIX = 'chat_followup_history_v1';
const FOLLOWUP_HISTORY_STORAGE_V2_PREFIX = 'chat_followup_history_v2';
const FOLLOWUP_MEMORY_CACHE = new Map();

const isFollowupDebugEnabled = () => {
    if (typeof window === 'undefined') return false;
    try {
        return window.localStorage.getItem('debug_followup_panel') === '1';
    } catch {
        return false;
    }
};

const debugFollowup = (event, payload = {}) => {
    if (!isFollowupDebugEnabled()) return;
    console.log(`[FollowupDebug] ${event}`, payload);
};

const simpleHash = (text) => {
    const str = String(text || '');
    let hash = 0;
    for (let i = 0; i < str.length; i += 1) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
    }
    return Math.abs(hash).toString(36);
};

const buildFollowupAnchor = (message, userQuery = '') => {
    if (!message) return '';
    const diagnosisData = message?.diagnosisData || {};
    const tableRecords = diagnosisData?.records?.records || message?.qdrantRecords || [];
    const flowRecords = diagnosisData?.flowchart?.records || [];
    const keyRecords = [...tableRecords, ...flowRecords]
        .slice(0, 3)
        .map((r) => [r?.station || '', r?.problem || '', r?.cause || '', r?.date || ''].join('|'))
        .join('||');

    const base = [
        message?.role || '',
        userQuery || '',
        message?.content || '',
        keyRecords,
    ].join('###');

    return simpleHash(base);
};

const buildFollowupHistoryStorageKey = (conversationId, message, userQuery = '') => {
    if (!conversationId) return '';
    const normalizedQuery = String(userQuery || '').trim().toLowerCase();
    const queryAnchor = normalizedQuery ? `q-${simpleHash(normalizedQuery)}` : '';
    const anchor = queryAnchor || buildFollowupAnchor(message, userQuery) || String(message?.id || '').trim();
    if (!anchor) return '';
    return `${FOLLOWUP_HISTORY_STORAGE_PREFIX}:${conversationId}:${anchor}`;
};

const buildFollowupConversationStorageKey = (conversationId) => {
    if (!conversationId) return '';
    return `${FOLLOWUP_HISTORY_STORAGE_V2_PREFIX}:${conversationId}`;
};

const buildFollowupBucketId = (message, userQuery = '') => {
    const normalizedQuery = String(userQuery || '').trim().toLowerCase();
    if (normalizedQuery) {
        return `q-${simpleHash(normalizedQuery)}`;
    }
    const messageContent = String(message?.content || '').trim();
    const diagnosisData = message?.diagnosisData || {};
    const tableRecords = diagnosisData?.records?.records || message?.qdrantRecords || [];
    const recordFinger = tableRecords
        .slice(0, 2)
        .map((r) => [r?.station || '', r?.problem || '', r?.date || ''].join('|'))
        .join('||');
    const base = [message?.role || '', messageContent.slice(0, 200), recordFinger].join('###');
    const fallback = base.trim() ? simpleHash(base) : '';
    return fallback ? `m-${fallback}` : '';
};

const buildFollowupRecords = (message) => {
    const diagnosisData = message?.diagnosisData || {};
    const tableRecords = diagnosisData?.records?.records || message?.qdrantRecords || [];
    const flowRecords = diagnosisData?.flowchart?.records || [];
    const merged = [...tableRecords, ...flowRecords];
    const seen = new Set();

    return merged
        .filter(Boolean)
        .map((r, idx) => ({
            id: r.id || `${r.station || 'station'}-${r.date || 'date'}-${idx}`,
            line: r.line || '',
            station: r.station || '',
            component: r.component || '',
            problem: r.problem || '',
            cause: r.cause || '',
            action: r.action || '',
            plan: r.plan || '',
            date: r.date || '',
            score: r.score ?? null,
            score_percent: r.score_percent ?? null,
            priority_rank: r.priority_rank ?? null,
        }))
        .filter((r) => {
            const key = [r.line, r.station, r.component, r.problem, r.cause, r.action, r.date].join('|');
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
};

const getDefaultRecordSort = () => ({ key: 'similarity', direction: 'desc' });

const RecordsTable = ({ records, title = "检索记录" }) => {
    const [expanded, setExpanded] = useState(true);
    const [sortState, setSortState] = useState(getDefaultRecordSort); // key: 'date' | 'similarity'

    const toggleSort = (key) => {
        setSortState((prev) => {
            if (prev.key !== key) {
                return { key, direction: 'desc' };
            }
            if (prev.direction === 'desc') {
                return { key, direction: 'asc' };
            }
            if (prev.direction === 'asc') {
                return getDefaultRecordSort();
            }
            return { key, direction: 'desc' };
        });
    };

    if (!records || records.length === 0) return null;
    const MAX_DISPLAY = 20;

    const sortedRecords = [...records].sort((a, b) => {
        if (sortState.key === 'date') {
            const aDate = a.date ? new Date(a.date) : new Date(0);
            const bDate = b.date ? new Date(b.date) : new Date(0);
            return sortState.direction === 'asc' ? aDate - bDate : bDate - aDate;
        }

        const aSp = Number(a.score_percent ?? ((a.score ?? null) !== null ? (a.score || 0) * 100 : -1));
        const bSp = Number(b.score_percent ?? ((b.score ?? null) !== null ? (b.score || 0) * 100 : -1));
        return sortState.direction === 'asc' ? aSp - bSp : bSp - aSp;
    });

    const displayRecords = sortedRecords.slice(0, MAX_DISPLAY);
    
    return (
        <div className="mt-3 border border-slate-200 rounded-xl overflow-hidden shadow-sm">
            <button 
                onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-brand-orange-50 to-brand-purple-50 hover:from-brand-orange-100 hover:to-brand-purple-100 transition-colors"
            >
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                    <Table size={16} className="text-brand-orange-500" />
                    {title} <span className="text-brand-purple-500">({displayRecords.length}/{records.length} 条)</span>
                </span>
                {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
            </button>
            {expanded && (
                <div className="overflow-x-auto max-h-80 overflow-y-auto custom-scrollbar">
                    <table className="w-full text-xs">
                        <thead className="bg-slate-50 sticky top-0">
                            <tr>
                                <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap">产线</th>
                                <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap">工位</th>
                                <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">问题</th>
                                <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">原因</th>
                                <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">措施</th>
                                <th
                                    className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap cursor-pointer select-none hover:text-brand-orange-500 transition-colors"
                                    onClick={() => toggleSort('date')}
                                    title={sortState.key !== 'date' || sortState.direction === null ? '点击按日期降序' : sortState.direction === 'desc' ? '点击按日期升序' : '点击恢复默认排序'}
                                >
                                    日期
                                    {sortState.key === 'date' && sortState.direction === 'asc' && <ArrowUp size={11} className="inline ml-1 text-brand-orange-500" />}
                                    {sortState.key === 'date' && sortState.direction === 'desc' && <ArrowDown size={11} className="inline ml-1 text-brand-orange-500" />}
                                    {(sortState.key !== 'date' || !sortState.direction) && <ArrowDown size={11} className="inline ml-1 text-slate-300" />}
                                </th>
                                <th
                                    className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap cursor-pointer select-none hover:text-brand-orange-500 transition-colors"
                                    onClick={() => toggleSort('similarity')}
                                    title={sortState.key !== 'similarity' || sortState.direction === null ? '点击按相似度降序' : sortState.direction === 'desc' ? '点击按相似度升序' : '点击恢复默认排序'}
                                >
                                    相似度
                                    {sortState.key === 'similarity' && sortState.direction === 'asc' && <ArrowUp size={11} className="inline ml-1 text-brand-orange-500" />}
                                    {sortState.key === 'similarity' && sortState.direction === 'desc' && <ArrowDown size={11} className="inline ml-1 text-brand-orange-500" />}
                                    {(sortState.key !== 'similarity' || !sortState.direction) && <ArrowDown size={11} className="inline ml-1 text-slate-300" />}
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                                {displayRecords.map((record, idx) => (
                                    <tr key={record.id || idx} className="border-t border-slate-100 hover:bg-brand-orange-50/30 transition-colors">
                                    <td className="px-3 py-2.5 whitespace-nowrap text-slate-500">{record.line || '-'}</td>
                                    <td className="px-3 py-2.5 whitespace-nowrap font-medium text-brand-purple-600">{record.station || '-'}</td>
                                    <td className="px-3 py-2.5" title={record.problem}>
                                        <div className="max-w-[200px] truncate text-slate-700">{record.problem || '-'}</div>
                                    </td>
                                    <td className="px-3 py-2.5" title={record.cause}>
                                        <div className="max-w-[200px] truncate text-slate-600">{record.cause || '-'}</div>
                                    </td>
                                    <td className="px-3 py-2.5" title={record.action}>
                                        <div className="max-w-[200px] truncate text-emerald-600">{record.action || '-'}</div>
                                    </td>
                                    <td className="px-3 py-2.5 whitespace-nowrap text-slate-400">{record.date || '-'}</td>
                                    <td className="px-3 py-2.5 whitespace-nowrap">
                                        {(() => {
                                            const sp = record.score_percent ?? (record.score ? Math.round(record.score * 10000) / 100 : null);
                                            if (sp === null || sp === undefined) return '-';
                                            const cls = sp >= 80 ? 'text-emerald-600 font-semibold' : (sp >= 60 ? 'text-amber-500 font-medium' : 'text-red-500 font-medium');
                                            return (<span className={cls}>{sp}%</span>);
                                        })()}
                                    </td>
                                </tr>
                            ))}
                            {records.length > MAX_DISPLAY && (
                                <tr className="border-t border-slate-100 bg-slate-50">
                                    <td colSpan={7} className="px-3 py-2.5 text-xs text-slate-500">只显示最相关的 {MAX_DISPLAY} 条记录，更多请到详细页面查看。</td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
};

const MessageBubble = ({ message, userQuery = '', onRegenerate, conversationId = null, onSendMessage }) => {
    const MIN_ASSISTANT_WIDTH = 352;
    const RESULTS_NARROW_CLASS = 'w-full max-w-8xl mx-auto min-w-0';
    const [followupInput, setFollowupInput] = useState('');
    const [followupLoading, setFollowupLoading] = useState(false);
    const [followupHistory, setFollowupHistory] = useState([]);
    const [assistantWidth, setAssistantWidth] = useState(null);
    const rowRef = useRef(null);
    const contentRef = useRef(null);
    const resizeStateRef = useRef(null);
    const followupHydratedRef = useRef(false);
    const followupHistoryRef = useRef([]);
    
    const isUser = message.role === 'user';
    const hasQdrantRecords = !isUser && message.qdrantRecords && message.qdrantRecords.length > 0;
    const hasDiagnosisData = !isUser && message.diagnosisData;
    const isStreaming = message.isStreaming;
    const diagnosisComplete = !!(
        hasDiagnosisData &&
        !isStreaming &&
        message.diagnosisData?.kg?.graph &&
        (message.diagnosisData?.records?.records?.length || 0) > 0 &&
        (message.diagnosisData?.flowchart?.records?.length || 0) > 0
    );
    const canShowQueryModePanel = !isUser && !isStreaming && (diagnosisComplete || (hasQdrantRecords && !hasDiagnosisData));
    const shouldShowFollowupPanel = !isUser && !isStreaming && (
        canShowQueryModePanel ||
        followupLoading ||
        followupHistory.length > 0 ||
        !!followupInput.trim()
    );

    const persistFollowupHistoryDirect = (history, reason = 'direct') => {
        const nextHistory = Array.isArray(history) ? history.slice(-20) : [];
        followupHistoryRef.current = nextHistory;
        const memKey = `${conversationId || 'unknown'}:${followupBucketId || 'unknown'}`;
        const memExisting = FOLLOWUP_MEMORY_CACHE.get(memKey);
        const protectedHistory = (nextHistory.length === 0 && Array.isArray(memExisting) && memExisting.length > 0)
            ? memExisting.slice(-20)
            : nextHistory;
        FOLLOWUP_MEMORY_CACHE.set(memKey, protectedHistory);

        if (!followupConversationStorageKey || !followupBucketId || typeof window === 'undefined') {
            debugFollowup('persist-direct-skip', {
                reason,
                conversationId,
                followupBucketId,
                savedCount: protectedHistory.length,
            });
            return protectedHistory;
        }

        try {
            const currentRaw = window.localStorage.getItem(followupConversationStorageKey);
            const currentObj = currentRaw ? JSON.parse(currentRaw) : {};
            const safeObj = (currentObj && typeof currentObj === 'object') ? currentObj : {};
            const existingBucket = Array.isArray(safeObj[followupBucketId]) ? safeObj[followupBucketId] : [];
            const finalToSave = (protectedHistory.length === 0 && existingBucket.length > 0)
                ? existingBucket.slice(-20)
                : protectedHistory;
            safeObj[followupBucketId] = finalToSave;
            window.localStorage.setItem(followupConversationStorageKey, JSON.stringify(safeObj));
            debugFollowup('persist-direct-done', {
                reason,
                conversationId,
                followupBucketId,
                v2Key: followupConversationStorageKey,
                savedCount: finalToSave.length,
            });
            return finalToSave;
        } catch {
            debugFollowup('persist-direct-error', {
                reason,
                conversationId,
                followupBucketId,
                v2Key: followupConversationStorageKey,
            });
        }

        return protectedHistory;
    };
    // 过滤掉表格占位符
    const displayContent = message.content === '[表格数据]' ? '' : message.content;
    const shouldUseLeadContent = hasDiagnosisData || hasQdrantRecords;
    const diagnosisLeadContent = shouldUseLeadContent
        ? (displayContent ? String(displayContent).split('\n').find((line) => line.trim()) || '' : '')
        : '';
    
    // 检测是否请求知识图谱
    const userContent = message.role === 'user' ? message.content : '';
    const showGraph = message.showGraph || false;
    const followupHistoryStorageKey = buildFollowupHistoryStorageKey(conversationId, message, userQuery);
    const followupConversationStorageKey = buildFollowupConversationStorageKey(conversationId);
    const followupBucketId = buildFollowupBucketId(message, userQuery);

    useEffect(() => {
        debugFollowup('mount-meta', {
            conversationId,
            messageId: message?.id,
            userQuery,
            followupBucketId,
            followupConversationStorageKey,
            followupHistoryStorageKey,
        });
    }, [conversationId, message?.id, userQuery, followupBucketId, followupConversationStorageKey, followupHistoryStorageKey]);
    
    // 从用户问题或检索记录中提取搜索关键词（用于 Neo4j 搜索）
    const extractKeyword = () => {
        // 优先使用用户原始问题（更短、更聚焦）
        if (userQuery) {
            // 去除常见后缀
            const cleaned = userQuery.replace(/[怎么办怎么解决怎么处理怎么修如何解决如何处理是什么有哪些][?？]*$/g, '').trim();
            if (cleaned.length >= 2) return cleaned.substring(0, 30);
        }
        // 回退：从第一条检索记录的 problem 取关键词
        if (hasQdrantRecords && message.qdrantRecords[0]?.problem) {
            return message.qdrantRecords[0].problem.substring(0, 20);
        }
        return '';
    };
    
    // Debug log
    if (!isUser) {
        console.log('[MessageBubble] Rendering assistant message:', {
            id: message.id,
            hasQdrantRecords,
            recordsCount: message.qdrantRecords?.length,
            content: message.content?.substring(0, 50),
            isStreaming,
            showGraph
        });
    }

    useEffect(() => {
        const handleMouseMove = (event) => {
            if (!resizeStateRef.current) return;

            const { startX, startWidth, maxWidth } = resizeStateRef.current;
            const deltaX = event.clientX - startX;
            const nextWidth = Math.min(maxWidth, Math.max(MIN_ASSISTANT_WIDTH, startWidth + deltaX));
            setAssistantWidth(nextWidth);
        };

        const handleMouseUp = () => {
            resizeStateRef.current = null;
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);

        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, []);

    useEffect(() => {
        followupHydratedRef.current = false;
        if (isUser) {
            setFollowupHistory([]);
            followupHydratedRef.current = true;
            return;
        }

        if ((!followupConversationStorageKey && !followupHistoryStorageKey) || !followupBucketId || typeof window === 'undefined') {
            const memKey = `${conversationId || 'unknown'}:${followupBucketId || 'unknown'}`;
            const memHistory = FOLLOWUP_MEMORY_CACHE.get(memKey);
            if (Array.isArray(memHistory)) {
                setFollowupHistory(memHistory);
            }
            debugFollowup('hydrate-skip-storage', {
                conversationId,
                followupBucketId,
                memKey,
                memCount: Array.isArray(memHistory) ? memHistory.length : 0,
            });
            followupHydratedRef.current = true;
            return;
        }

        try {
            let nextHistory = [];

            // v2：按会话聚合存储，再按 bucket 读取
            const v2Raw = followupConversationStorageKey
                ? window.localStorage.getItem(followupConversationStorageKey)
                : null;
            if (v2Raw) {
                const v2Parsed = JSON.parse(v2Raw);
                if (v2Parsed && typeof v2Parsed === 'object') {
                    const bucketHistory = v2Parsed[followupBucketId];
                    if (Array.isArray(bucketHistory)) {
                        nextHistory = bucketHistory;
                    }
                }
            }

            // 兼容 v1：若 v2 没有，尝试读取旧 key，并迁移到 v2
            if (nextHistory.length === 0 && followupHistoryStorageKey) {
                const legacyRaw = window.localStorage.getItem(followupHistoryStorageKey);
                if (legacyRaw) {
                    const legacyParsed = JSON.parse(legacyRaw);
                    if (Array.isArray(legacyParsed)) {
                        nextHistory = legacyParsed;
                        if (followupConversationStorageKey) {
                            const currentRaw = window.localStorage.getItem(followupConversationStorageKey);
                            const currentObj = currentRaw ? JSON.parse(currentRaw) : {};
                            const safeObj = (currentObj && typeof currentObj === 'object') ? currentObj : {};
                            safeObj[followupBucketId] = legacyParsed.slice(-20);
                            window.localStorage.setItem(followupConversationStorageKey, JSON.stringify(safeObj));
                        }
                    }
                }
            }

            setFollowupHistory(Array.isArray(nextHistory) ? nextHistory : []);
            const memKey = `${conversationId || 'unknown'}:${followupBucketId}`;
            FOLLOWUP_MEMORY_CACHE.set(memKey, Array.isArray(nextHistory) ? nextHistory : []);
            debugFollowup('hydrate-done', {
                conversationId,
                followupBucketId,
                v2Key: followupConversationStorageKey,
                legacyKey: followupHistoryStorageKey,
                loadedCount: Array.isArray(nextHistory) ? nextHistory.length : 0,
            });
            followupHydratedRef.current = true;
        } catch {
            const memKey = `${conversationId || 'unknown'}:${followupBucketId}`;
            const memHistory = FOLLOWUP_MEMORY_CACHE.get(memKey);
            setFollowupHistory(Array.isArray(memHistory) ? memHistory : []);
            debugFollowup('hydrate-error-fallback-memory', {
                conversationId,
                followupBucketId,
                memKey,
                memCount: Array.isArray(memHistory) ? memHistory.length : 0,
            });
            followupHydratedRef.current = true;
        }
    }, [followupConversationStorageKey, followupBucketId, followupHistoryStorageKey, isUser]);

    useEffect(() => {
        if (!followupConversationStorageKey || !followupBucketId || isUser || typeof window === 'undefined') return;
        if (!followupHydratedRef.current) return;
        try {
            const currentRaw = window.localStorage.getItem(followupConversationStorageKey);
            const currentObj = currentRaw ? JSON.parse(currentRaw) : {};
            const safeObj = (currentObj && typeof currentObj === 'object') ? currentObj : {};
            const finalHistory = followupHistory.slice(-20);
            const existingBucket = Array.isArray(safeObj[followupBucketId]) ? safeObj[followupBucketId] : [];
            const protectedHistory = (finalHistory.length === 0 && existingBucket.length > 0)
                ? existingBucket.slice(-20)
                : finalHistory;
            safeObj[followupBucketId] = protectedHistory;
            window.localStorage.setItem(followupConversationStorageKey, JSON.stringify(safeObj));
            const memKey = `${conversationId || 'unknown'}:${followupBucketId}`;
            FOLLOWUP_MEMORY_CACHE.set(memKey, protectedHistory);
            debugFollowup('persist-done', {
                conversationId,
                followupBucketId,
                v2Key: followupConversationStorageKey,
                savedCount: protectedHistory.length,
            });
        } catch {
            // 忽略 localStorage 写入异常（如隐身模式/容量限制）
            debugFollowup('persist-error', {
                conversationId,
                followupBucketId,
                v2Key: followupConversationStorageKey,
            });
        }
    }, [followupConversationStorageKey, followupBucketId, followupHistory, isUser, conversationId]);

    useEffect(() => {
        followupHistoryRef.current = Array.isArray(followupHistory) ? followupHistory : [];
    }, [followupHistory]);

    const handleResizeStart = (event) => {
        if (isUser) return;

        event.preventDefault();
        event.stopPropagation();

        const currentWidth = contentRef.current?.offsetWidth || MIN_ASSISTANT_WIDTH;
        const rowWidth = rowRef.current?.offsetWidth || currentWidth;
        const maxWidth = Math.max(MIN_ASSISTANT_WIDTH, rowWidth - 56);

        resizeStateRef.current = {
            startX: event.clientX,
            startWidth: currentWidth,
            maxWidth,
        };

        setAssistantWidth(currentWidth);
    };

    const handleFollowupSend = async () => {
        const question = followupInput.trim();
        if (!question || followupLoading) return;

        const qaId = `fq-${Date.now()}`;
        const startHistory = persistFollowupHistoryDirect(
            [...(followupHistoryRef.current || []), { id: qaId, q: question, a: '', isStreaming: true }],
            'followup-start'
        );
        setFollowupHistory(startHistory);
        setFollowupInput('');
        setFollowupLoading(true);
        debugFollowup('followup-send-start', {
            conversationId,
            followupBucketId,
            question,
        });

        const followupRecords = buildFollowupRecords(message);

        let answer = '';
        try {
            await sendMessage({
            message: question,
                conversationId,
                queryMode: 'followup',
                followupRecords,
                inlineFollowup: true,
                stream: true,
                onContent: (chunk) => {
                    answer += chunk;
                    const nextHistory = persistFollowupHistoryDirect(
                        (followupHistoryRef.current || []).map((item) => (
                            item.id === qaId ? { ...item, a: answer } : item
                        )),
                        'followup-onContent'
                    );
                    setFollowupHistory(nextHistory);
                },
                onDone: () => {
                    const nextHistory = persistFollowupHistoryDirect(
                        (followupHistoryRef.current || []).map((item) => (
                            item.id === qaId ? { ...item, isStreaming: false } : item
                        )),
                        'followup-onDone'
                    );
                    setFollowupHistory(nextHistory);
                    debugFollowup('followup-send-done', {
                        conversationId,
                        followupBucketId,
                        answerLength: answer.length,
                    });
                },
                onError: (err) => {
                    const msg = err || '追问失败，请重试。';
                    const nextHistory = persistFollowupHistoryDirect(
                        (followupHistoryRef.current || []).map((item) => (
                            item.id === qaId ? { ...item, a: msg, isStreaming: false } : item
                        )),
                        'followup-onError'
                    );
                    setFollowupHistory(nextHistory);
                    debugFollowup('followup-send-onError', {
                        conversationId,
                        followupBucketId,
                        error: msg,
                    });
                }
            });
        } catch (err) {
            const msg = err?.message || '追问失败，请重试。';
            const nextHistory = persistFollowupHistoryDirect(
                (followupHistoryRef.current || []).map((item) => (
                    item.id === qaId ? { ...item, a: msg, isStreaming: false } : item
                )),
                'followup-catch'
            );
            setFollowupHistory(nextHistory);
            debugFollowup('followup-send-catch', {
                conversationId,
                followupBucketId,
                error: msg,
            });
        } finally {
            setFollowupLoading(false);
        }
    };

    return (
        <div ref={rowRef} className={`flex gap-3 w-full max-w-7xl mx-auto p-4 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
            {/* Avatar */}
            <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${isUser 
                ? 'bg-brand-orange-500 text-white' 
                : 'bg-slate-600 text-white'
                }`}>
                {isUser ? <User size={16} /> : <Bot size={16} />}
            </div>

            {/* Content */}
            <div
                ref={contentRef}
                className={`flex flex-col min-w-0 ${isUser
                    ? 'items-end max-w-[70%]'
                    : 'relative items-start w-[min(78%,56rem)] max-w-full min-w-[22rem] overflow-visible'
                    }`}
                style={!isUser && assistantWidth ? { width: `${assistantWidth}px`, maxWidth: '100%' } : undefined}
            >
                {!isUser && (
                    <div
                        onMouseDown={handleResizeStart}
                        className="absolute top-0 -right-2 h-full w-3 cursor-col-resize select-none"
                        title="拖动右侧边缘调整宽度"
                    >
                        <div className="mx-auto h-full w-px bg-slate-200 hover:bg-brand-orange-400 transition-colors" />
                    </div>
                )}
                <div className={`w-full min-w-0 overflow-hidden px-4 py-3 rounded-2xl ${isUser
                        ? 'bg-white border border-brand-orange-300 text-slate-800 rounded-tr-sm'
                        : 'bg-white border border-slate-200 rounded-tl-sm'
                    }`}>
                    {/* 文本内容 */}
                    {displayContent && !shouldUseLeadContent && (
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                            <Markdown>{displayContent}</Markdown>
                            {isStreaming && (
                                <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />
                            )}
                        </div>
                    )}
                    {shouldUseLeadContent && diagnosisLeadContent && (
                        <div className="text-sm text-slate-600 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
                            {diagnosisLeadContent}
                        </div>
                    )}
                    {/* 流式加载中且无内容 */}
                    {!displayContent && isStreaming && !hasQdrantRecords && (
                        <span className="text-muted-foreground animate-pulse">思考中...</span>
                    )}
                    {/* 三段式诊断视图 */}
                    {hasDiagnosisData && (
                        <div className={RESULTS_NARROW_CLASS}>
                            <DiagnosisView
                                diagnosisData={message.diagnosisData}
                                answerText={displayContent}
                                userQuery={userQuery}
                            />
                        </div>
                    )}
                    {/* 非诊断模式：也固定为 图谱 -> 表格 -> 流程图 */}
                    {hasQdrantRecords && !hasDiagnosisData && !isStreaming && (
                        <div className={`space-y-4 mt-3 ${RESULTS_NARROW_CLASS}`}>
                            <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm bg-white p-3">
                                <Neo4jGraph
                                    keyword={extractKeyword()}
                                    records={message.qdrantRecords}
                                    allowKeywordSearch={false}
                                    defaultExpanded={true}
                                    lightTheme={true}
                                    embedded={true}
                                    showPaths={true}
                                    defaultLimit={20}
                                    defaultQueryMode={message.neo4jQueryMode || 'exact'}
                                />
                            </div>

                            <RecordsTable records={message.qdrantRecords} title="检索记录" />

                            <MermaidDiagram
                                records={message.qdrantRecords}
                                answerText={displayContent || ''}
                                flowPlan={message.flowPlan}
                                userQuery={userQuery}
                                inline={true}
                            />

                            {showGraph && (
                                <KnowledgeGraph
                                    records={message.qdrantRecords}
                                    title="补充关系图"
                                    defaultExpanded={false}
                                />
                            )}
                        </div>
                    )}
                    {/* 纯文字追问区（仅在三段结果全部生成后显示） */}
                    {shouldShowFollowupPanel && (
                        <div className="mt-4 border border-slate-200 rounded-xl bg-slate-50/60 p-3">
                            <div className="text-sm font-semibold text-slate-700 mb-2">追问</div>

                            {followupHistory.length > 0 && (
                                <div className="space-y-2 mb-3 max-h-64 overflow-y-auto pr-1">
                                    {followupHistory.map((item) => (
                                        <div key={item.id} className="space-y-1">
                                            <div className="text-xs text-slate-500">追问：{item.q}</div>
                                            <div className="text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-3 py-2 whitespace-pre-wrap">
                                                {item.a || '思考中...'}
                                                {item.isStreaming && <span className="inline-block w-2 h-4 bg-current animate-pulse ml-1" />}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}

                            <div className="flex items-end gap-2">
                                <textarea
                                    value={followupInput}
                                    onChange={(e) => setFollowupInput(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                            e.preventDefault();
                                            handleFollowupSend();
                                        }
                                    }}
                                    placeholder="继续追问当前结果"
                                    className="flex-1 min-h-[44px] max-h-[120px] resize-y rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400"
                                />
                                <button
                                    onClick={handleFollowupSend}
                                    disabled={followupLoading || !followupInput.trim()}
                                    className={`px-3 py-2 rounded-lg text-sm transition-colors ${followupLoading || !followupInput.trim()
                                        ? 'bg-slate-200 text-slate-400 cursor-not-allowed'
                                        : 'bg-gradient-to-r from-brand-orange-500 to-brand-orange-400 text-white hover:opacity-95'
                                        }`}
                                >
                                    {followupLoading ? '回答中...' : '追问'}
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Actions (Only for AI, not during streaming) */}
                {!isUser && !isStreaming && (
                    <div className="flex items-center gap-1 mt-2 ml-1">
                        <button className="p-1.5 text-slate-400 hover:text-brand-orange-500 hover:bg-brand-orange-50 rounded-lg transition-all" title="Copy">
                            <Copy size={14} />
                        </button>
                        <button 
                            className="p-1.5 text-slate-400 hover:text-brand-orange-500 hover:bg-brand-orange-50 rounded-lg transition-all" 
                            title="Regenerate"
                            onClick={() => onRegenerate && onRegenerate(message.id)}
                        >
                            <RotateCcw size={14} />
                        </button>
                        <div className="flex items-center gap-1 ml-2 border-l border-slate-200 pl-2">
                            <button className="p-1.5 text-slate-400 hover:text-emerald-500 hover:bg-emerald-50 rounded-lg transition-all">
                                <ThumbsUp size={14} />
                            </button>
                            <button className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all">
                                <ThumbsDown size={14} />
                            </button>
                        </div>
                        <span className="text-xs text-slate-400 ml-auto">{message.timestamp}</span>
                    </div>
                )}

                {/* Timestamp for User */}
                {isUser && (
                    <span className="text-xs text-brand-purple-300 mt-1.5 mr-1">{message.timestamp}</span>
                )}
            </div>
            
        </div>
    );
};

export default MessageBubble;
