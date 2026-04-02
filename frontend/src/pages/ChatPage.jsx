import React, { useCallback, useEffect, useState, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import ChatSidebar from '../components/chat/ChatSidebar';
import MessageBubble from '../components/chat/MessageBubble';
import InputBox from '../components/chat/InputBox';
import { fetchMessages, fetchSessions, sendMessage, deleteSession } from '../services/chatApi';

const GROUP_LABELS = {
    TODAY: 'Today',
    WEEK: 'Previous 7 Days',
    OLDER: 'Older',
    RECENT: 'Recent'
};

const getGroupLabel = (timestamp) => {
    if (!timestamp) return GROUP_LABELS.RECENT;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return GROUP_LABELS.RECENT;

    const now = new Date();
    const sameDay = date.toDateString() === now.toDateString();
    if (sameDay) return GROUP_LABELS.TODAY;

    const diffMs = now.getTime() - date.getTime();
    const diffDays = diffMs / (1000 * 60 * 60 * 24);
    if (diffDays <= 7) return GROUP_LABELS.WEEK;
    return GROUP_LABELS.OLDER;
};

const formatSubtitle = (timestamp) => {
    if (!timestamp) return undefined;
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return undefined;
    return date.toLocaleString();
};

const normalizeSessions = (sessions) =>
    sessions.map((conv, index) => {
        const shortId = conv.conversation_id?.slice(0, 8) || `${index + 1}`;
        // 优先使用后端返回的 title，如果没有则用 ID
        const title = conv.title || `Conversation ${shortId}`;
        return {
            id: conv.conversation_id,
            title: title,
            subtitle: formatSubtitle(conv.last_activity),
            group: getGroupLabel(conv.last_activity),
            messageCount: conv.message_count
        };
    });

const generateSessionId = () => {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
};

const ChatPage = () => {
    const { sessionId } = useParams();
    const navigate = useNavigate();
    const messagesEndRef = useRef(null);
    const newSessionIds = useRef(new Set()); // 跟踪新创建的会话ID

    const [sessions, setSessions] = useState([]);
    const [activeSessionId, setActiveSessionId] = useState(sessionId || null);
    const [messages, setMessages] = useState([]);
    const [sessionsLoading, setSessionsLoading] = useState(false);
    const [isHistoryLoading, setIsHistoryLoading] = useState(false);
    const [isSending, setIsSending] = useState(false);
    const [error, setError] = useState(null);
    
    // 使用时间戳锁定机制，防止消息加载覆盖刚发送的消息
    const loadLockUntilRef = useRef(0);
    const loadLockSessionIdRef = useRef(null);
    const messagesCacheRef = useRef(new Map());
    const latestLoadReqRef = useRef(0);
    const currentMessagesSessionRef = useRef(sessionId || null);

    const shouldDisplayError = useCallback((message) => {
        if (!message) return false;
        const normalized = message.toLowerCase();
        return !/timeout|超时|failed to fetch/.test(normalized);
    }, []);

    const reportError = useCallback((message) => {
        if (shouldDisplayError(message)) {
            setError(message);
        }
    }, [shouldDisplayError]);

    const scrollToBottom = (immediate = false) => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ 
                behavior: immediate ? 'auto' : 'smooth',
                block: 'end'
            });
        }
    };

    const isLocalDraftSession = (conversationId) => (
        !!conversationId && newSessionIds.current.has(conversationId)
    );

    const removeSessionLocally = (conversationId) => {
        const remainingSessions = sessions.filter((session) => session.id !== conversationId);

        setSessions(remainingSessions);
        messagesCacheRef.current.delete(conversationId);
        newSessionIds.current.delete(conversationId);

        if (conversationId !== activeSessionId) {
            return;
        }

        if (remainingSessions.length > 0) {
            const nextSession = remainingSessions[0];
            const cached = messagesCacheRef.current.get(nextSession.id);
            currentMessagesSessionRef.current = nextSession.id;
            setMessages(cached || []);
            setIsHistoryLoading(!cached);
            setActiveSessionId(nextSession.id);
            navigate(`/chat/${nextSession.id}`);
            return;
        }

        currentMessagesSessionRef.current = null;
        setIsHistoryLoading(false);
        setActiveSessionId(null);
        setMessages([]);
        navigate('/chat');
    };

    const loadSessions = useCallback(async () => {
        setSessionsLoading(true);
        try {
            const response = await fetchSessions();
            setSessions(normalizeSessions(response));
        } catch (err) {
            console.error(err);
            reportError(err.message || 'Failed to load conversations');
        } finally {
            setSessionsLoading(false);
        }
    }, [reportError]);

    const loadMessages = useCallback(async (conversationId) => {
        if (!conversationId) {
            currentMessagesSessionRef.current = null;
            setMessages([]);
            return;
        }

        // 检查时间锁：仅锁定被发送中的同一个会话，避免切换到其他会话时卡顿
        if (Date.now() < loadLockUntilRef.current && loadLockSessionIdRef.current === conversationId) {
            console.log('[loadMessages] 锁定中，跳过加载');
            return;
        }

        // 新创建的会话不需要从后端加载
        if (newSessionIds.current.has(conversationId)) {
            console.log('[loadMessages] 跳过新会话:', conversationId);
            return;
        }

        const cached = messagesCacheRef.current.get(conversationId);
        if (cached) {
            currentMessagesSessionRef.current = conversationId;
            setMessages(cached);
            setIsHistoryLoading(false);
        } else {
            currentMessagesSessionRef.current = conversationId;
            setMessages([]);
            setIsHistoryLoading(true);
        }

        const reqId = ++latestLoadReqRef.current;
        try {
            const response = await fetchMessages(conversationId);

            if (reqId !== latestLoadReqRef.current) {
                console.log('[loadMessages] 过期请求，丢弃结果:', conversationId);
                return;
            }
            
            // 再次检查锁：防止异步期间锁被设置
            if (Date.now() < loadLockUntilRef.current && loadLockSessionIdRef.current === conversationId) {
                console.log('[loadMessages] 加载完成但锁定中，丢弃结果');
                return;
            }
            
            const loadedMessages = response.map((msg, index) => ({
                id: `${conversationId}-${index}`,
                role: msg.role,
                content: msg.content,
                timestamp: msg.timestamp ? new Date(msg.timestamp).toLocaleString() : undefined,
                qdrantRecords: msg.qdrant_records || null,
                flowPlan: msg.flow_plan || null,
                diagnosisData: msg.diagnosis_data || null,
                showGraph: !!msg.show_graph,
                neo4jQueryMode: msg.neo4j_query_mode || null,
            }));
            messagesCacheRef.current.set(conversationId, loadedMessages);
            currentMessagesSessionRef.current = conversationId;
            setMessages(loadedMessages);
            
            // Scroll to bottom after messages are loaded
            setTimeout(() => scrollToBottom(true), 100);
        } catch (err) {
            console.error(err);
            // Don't show error for new sessions that don't exist yet
            if (!err.message?.includes('404') && !err.message?.includes('Not Found')) {
                reportError(err.message || 'Failed to load messages');
            } else {
                // 如果在锁定期间，不要清空消息
                if (!(Date.now() < loadLockUntilRef.current && loadLockSessionIdRef.current === conversationId)) {
                    currentMessagesSessionRef.current = conversationId;
                    setMessages([]);
                }
            }
        } finally {
            if (reqId === latestLoadReqRef.current) {
                setIsHistoryLoading(false);
            }
        }
    }, [reportError]);

    useEffect(() => {
        const sessionForCurrentMessages = currentMessagesSessionRef.current;
        if (!sessionForCurrentMessages) return;
        messagesCacheRef.current.set(sessionForCurrentMessages, messages);
    }, [messages]);

    useEffect(() => {
        loadSessions();
    }, [loadSessions]);

    useEffect(() => {
        // 如果在锁定期间，不要同步 URL 参数
        if (Date.now() < loadLockUntilRef.current) {
            return;
        }
        if (sessionId) {
            setActiveSessionId(sessionId);
        } else if (!sessionId && sessions.length > 0 && !activeSessionId) {
            setActiveSessionId(sessions[0].id);
        }
    }, [sessionId, sessions, activeSessionId]);

    useEffect(() => {
        if (activeSessionId) {
            loadMessages(activeSessionId);
        }
    }, [activeSessionId, loadMessages]);

    useEffect(() => {
        scrollToBottom();
    }, [messages]);

    const handleSelectSession = (id) => {
        if (!id || id === activeSessionId) {
            return;
        }

        if (activeSessionId) {
            messagesCacheRef.current.set(activeSessionId, messages);
        }

        setError(null);
        const cached = messagesCacheRef.current.get(id);
        if (cached) {
            currentMessagesSessionRef.current = id;
            setMessages(cached);
            setIsHistoryLoading(false);
        } else {
            currentMessagesSessionRef.current = id;
            setMessages([]);
            setIsHistoryLoading(true);
        }

        setActiveSessionId(id);
        navigate(`/chat/${id}`);
    };

    const hasActiveMessages = messages.length > 0;

    const handleNewSession = () => {
        if (!hasActiveMessages) {
            return;
        }
        const newSessionId = generateSessionId();
        newSessionIds.current.add(newSessionId); // 标记为新会话
        setSessions((prev) => {
            const exists = prev.some((session) => session.id === newSessionId);
            if (exists) {
                return prev;
            }
            const placeholder = {
                id: newSessionId,
                title: `Conversation ${newSessionId.slice(0, 8)}`,
                subtitle: undefined,
                group: GROUP_LABELS.RECENT,
                messageCount: 0,
            };
            return [placeholder, ...prev];
        });
        setMessages([]);
        currentMessagesSessionRef.current = newSessionId;
        setActiveSessionId(newSessionId);
        navigate(`/chat/${newSessionId}`);
    };

    const handleDeleteSession = async (conversationId) => {
        setError(null);

        if (isLocalDraftSession(conversationId)) {
            removeSessionLocally(conversationId);
            return;
        }

        try {
            await deleteSession(conversationId);
            messagesCacheRef.current.delete(conversationId);
            newSessionIds.current.delete(conversationId);
            
            // 计算删除后剩余的会话
            const remainingSessions = sessions.filter((s) => s.id !== conversationId);
            
            // 更新会话列表
            setSessions(remainingSessions);
            
            // 如果删除的是当前活动会话，需要切换到其他会话
            if (conversationId === activeSessionId) {
                if (remainingSessions.length > 0) {
                    const nextSession = remainingSessions[0];
                    setActiveSessionId(nextSession.id);
                    navigate(`/chat/${nextSession.id}`);
                } else {
                    // 没有剩余会话，清空状态并返回主页
                    setActiveSessionId(null);
                    setMessages([]);
                    navigate('/chat');
                }
            }
        } catch (err) {
            console.error(err);
            const errorText = String(err.message || '');
            if (errorText.includes('Conversation not found') || errorText.includes('404')) {
                removeSessionLocally(conversationId);
                return;
            }
            setError(err.message || 'Failed to delete conversation');
        }
    };

    const handleSendMessage = async (text, options = {}) => {
        const queryMode = options?.queryMode || 'auto';
        const draftSessionId = isLocalDraftSession(activeSessionId) ? activeSessionId : null;
        // Fallback: send latest records so follow-up can still work on stateless backend nodes.
        const latestFollowupRecords = (() => {
            for (let i = messages.length - 1; i >= 0; i -= 1) {
                const recs = messages[i]?.qdrantRecords;
                if (Array.isArray(recs) && recs.length > 0) {
                    return recs.slice(0, 80);
                }
            }
            return null;
        })();
        console.log('[handleSendMessage] 开始发送:', text.substring(0, 50));
        
        // 设置锁定：未来5秒内不允许 loadMessages 覆盖消息
        loadLockUntilRef.current = Date.now() + 5000;
        loadLockSessionIdRef.current = activeSessionId;
        
        const userMessage = {
            id: `user-${Date.now()}`,
            role: 'user',
            content: text,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        };
        setMessages((prev) => [...prev, userMessage]);
        setIsSending(true);
        
        // 将当前会话添加到newSessionIds，防止发送过程中被重新加载
        setError(null);

        const assistantMessageId = `assistant-${Date.now()}`;
        let currentContent = '';
        let currentRecords = null;
        let currentShowGraph = false;
        let newConversationId = null; // 保存后端返回的新会话ID
        let currentDiagnosisKg = null;
        let currentDiagnosisRecords = null;
        let currentDiagnosisFlowchart = null;

        // 添加空的助手消息用于流式更新
        setMessages((prev) => [...prev, {
            id: assistantMessageId,
            role: 'assistant',
            content: '',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            qdrantRecords: null,
            flowPlan: null,
            showGraph: false,
            neo4jQueryMode: null,
            isStreaming: true,
            diagnosisData: null,
            routeUsed: null,
            progressStatus: 'Analyzing issue...'
        }]);

        try {
            await sendMessage({
                message: text,
                conversationId: activeSessionId,
                queryMode,
                followupRecords: latestFollowupRecords,
                stream: true,
                onMeta: (meta) => {
                    console.log('[UI-V2][meta]', {
                        uiLayoutVersion: meta?.ui_layout_version,
                        queryMode: meta?.query_mode,
                        conversationId: meta?.conversation_id,
                        isFollowup: meta?.is_followup,
                    });
                    // 只保存会话ID，不立即更新状态和URL（避免触发重新加载）
                    newConversationId = meta.conversation_id;
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId
                                ? { ...msg, progressStatus: 'Analyzing issue...' }
                            : msg
                    ));
                },
                onRoute: (route) => {
                    const status = route === 'diagnosis'
                                ? 'Retrieving graph...'
                                : (route === 'search' ? 'Retrieving graph...' : 'Processing...');
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId
                            ? { ...msg, routeUsed: route, progressStatus: status }
                            : msg
                    ));
                },
                onRecords: (records, recordsMeta = {}) => {
                    const nextShowGraph = recordsMeta.showGraph ?? false;
                    const nextNeo4jQueryMode = recordsMeta.neo4jQueryMode || null;
                    console.log('[DEBUG] onRecords called with', records?.length, 'records, meta:', recordsMeta);
                    console.log('[DEBUG] records data:', JSON.stringify(records?.[0]));
                    currentRecords = records;
                    currentShowGraph = nextShowGraph;
                    setMessages((prev) => {
                        console.log('[DEBUG] Setting qdrantRecords on message', assistantMessageId);
                        return prev.map((msg) => 
                            msg.id === assistantMessageId
                                    ? { ...msg, qdrantRecords: records, showGraph: nextShowGraph, neo4jQueryMode: nextNeo4jQueryMode, progressStatus: 'Retrieving table...' }
                                : msg
                        );
                    });
                },
                onFlowPlan: (plan) => {
                    console.log('[DEBUG] onFlowPlan received:', plan?.steps?.length, 'steps');
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId ? { ...msg, flowPlan: plan, progressStatus: 'Generating flowchart...' } : msg
                    ));
                },
                onDiagnosisKg: (data) => {
                    console.log('[DEBUG] onDiagnosisKg received');
                    currentDiagnosisKg = data;
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId
                                    ? { ...msg, diagnosisData: { kg: data, records: currentDiagnosisRecords, flowchart: currentDiagnosisFlowchart }, progressStatus: 'Retrieving table...' }
                            : msg
                    ));
                },
                onDiagnosisRecords: (data) => {
                    console.log('[DEBUG] onDiagnosisRecords received:', data?.records?.length);
                    currentDiagnosisRecords = data;
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId
                                    ? { ...msg, diagnosisData: { kg: currentDiagnosisKg, records: data, flowchart: currentDiagnosisFlowchart }, progressStatus: 'Generating flowchart...' }
                            : msg
                    ));
                },
                onDiagnosisFlowchart: (data) => {
                    console.log('[DEBUG] onDiagnosisFlowchart received:', data?.records?.length);
                    currentDiagnosisFlowchart = data;
                    setMessages((prev) => prev.map((msg) =>
                        msg.id === assistantMessageId
                                    ? { ...msg, diagnosisData: { kg: currentDiagnosisKg, records: currentDiagnosisRecords, flowchart: data }, progressStatus: 'Generating flowchart...' }
                            : msg
                    ));
                },
                onContent: (chunk) => {
                    currentContent += chunk;
                    // 从 prev 状态获取当前的 records，避免闭包问题
                    setMessages((prev) => prev.map((msg) => {
                        if (msg.id === assistantMessageId) {
                            return { 
                                ...msg, 
                                content: currentContent, 
                                qdrantRecords: msg.qdrantRecords || currentRecords,
                                showGraph: msg.showGraph || currentShowGraph
                            };
                        }
                        return msg;
                    }));
                },
                onDone: () => {
                    // 构建诊断数据（如果有的话）
                    const diagnosisData = (currentDiagnosisKg || currentDiagnosisRecords || currentDiagnosisFlowchart)
                        ? { kg: currentDiagnosisKg, records: currentDiagnosisRecords, flowchart: currentDiagnosisFlowchart }
                        : null;
                    setMessages((prev) => prev.map((msg) => {
                        if (msg.id === assistantMessageId) {
                            return { 
                                ...msg, 
                                isStreaming: false, 
                                qdrantRecords: msg.qdrantRecords || currentRecords,
                                showGraph: msg.showGraph || currentShowGraph,
                                diagnosisData: msg.diagnosisData || diagnosisData,
                                progressStatus: ''
                            };
                        }
                        return msg;
                    }));
                    
                    // 延长锁定时间：确保后端有足够时间保存
                    loadLockUntilRef.current = Date.now() + 3000;
                    loadLockSessionIdRef.current = newConversationId || activeSessionId;
                    
                    // 消息发送成功后，更新会话ID和URL
                    if (draftSessionId) {
                        newSessionIds.current.delete(draftSessionId);
                    }
                    if (newConversationId) {
                        newSessionIds.current.delete(newConversationId);
                    }
                    
                    // 更新会话列表
                    fetchSessions().then(response => {
                        setSessions(normalizeSessions(response));
                    }).catch(console.error);
                    
                    // 更新会话ID和URL
                    if (newConversationId && newConversationId !== activeSessionId) {
                        setActiveSessionId(newConversationId);
                        navigate(`/chat/${newConversationId}`, { replace: true });
                    }
                },
                onError: (err) => {
                    reportError(err || 'Failed to send message');
                    setMessages((prev) => prev.filter((msg) => msg.id !== userMessage.id && msg.id !== assistantMessageId));
                    // 出错时清除锁定
                    loadLockUntilRef.current = 0;
                    loadLockSessionIdRef.current = null;
                }
            });
        } catch (err) {
            console.error('[handleSendMessage] 错误:', err);
            reportError(err.message || 'Failed to send message');
            setMessages((prev) => prev.filter((msg) => msg.id !== userMessage.id && msg.id !== assistantMessageId));
            // 出错时清除锁定
            loadLockUntilRef.current = 0;
            loadLockSessionIdRef.current = null;
        } finally {
            console.log('[handleSendMessage] 完成');
            setIsSending(false);
        }
    };

    // 重新生成回答
    const handleRegenerate = async (messageId) => {
        // 找到该AI回答对应的用户消息
        const messageIndex = messages.findIndex(msg => msg.id === messageId);
        if (messageIndex <= 0) return; // 找不到或没有前一条消息
        
        // 向前找到最近的用户消息
        let userMessageIndex = messageIndex - 1;
        while (userMessageIndex >= 0 && messages[userMessageIndex].role !== 'user') {
            userMessageIndex--;
        }
        if (userMessageIndex < 0) return;
        
        const userMessage = messages[userMessageIndex];
        const originalText = userMessage.content;
        
        // 删除当前AI回答
        setMessages(prev => prev.filter(msg => msg.id !== messageId));
        
        // 重新发送用户消息内容
        await handleSendMessage(originalText);
    };

    return (
        <div className="flex w-full min-w-0 h-full bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden relative">
            {error && (
                <div className="absolute top-4 right-4 z-50 bg-red-50 border border-red-200 text-red-600 text-sm px-4 py-3 rounded-xl shadow-lg flex items-center gap-2 animate-in slide-in-from-top-2">
                    <span className="w-2 h-2 rounded-full bg-red-500 animate-pulse"/>
                    {error}
                </div>
            )}

            <ChatSidebar
                sessions={sessions}
                activeSessionId={activeSessionId}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewSession}
                onDeleteSession={handleDeleteSession}
                canStartNewSession={hasActiveMessages}
                isLoading={sessionsLoading}
            />

            <div className="flex-1 min-w-0 flex flex-col h-full relative bg-slate-50/50">
                <div className="flex-1 overflow-y-auto p-4 space-y-6 scrollbar-thin scrollbar-thumb-slate-200 scrollbar-track-transparent">
                    {isHistoryLoading && (
                        <div className="flex flex-col items-center justify-center h-full space-y-3">
                            <div className="w-8 h-8 border-4 border-brand-orange-200 border-t-brand-orange-500 rounded-full animate-spin"></div>
                            <div className="text-sm text-slate-400 font-medium">Loading conversation...</div>
                        </div>
                    )}

                    {!isHistoryLoading && messages.length === 0 && (
                        <div className="flex flex-col items-center justify-center h-full space-y-4 text-center p-8">
                            <div className="w-16 h-16 bg-gradient-to-br from-brand-orange-100 to-brand-purple-100 rounded-2xl flex items-center justify-center shadow-inner">
                                <div className="text-3xl">👋</div>
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-slate-700">Welcome to Maintenance Intelligent Expert</h3>
                                <p className="text-slate-400 max-w-sm mt-1">Start a new conversation to diagnose faults or search the knowledge base.</p>
                            </div>
                        </div>
                    )}

                    {messages.map((msg, idx) => {
                        // 为 assistant 消息找到前一条 user 消息的内容
                        let userQuery = '';
                        if (msg.role === 'assistant' && idx > 0) {
                            for (let i = idx - 1; i >= 0; i--) {
                                if (messages[i].role === 'user') {
                                    userQuery = messages[i].content || '';
                                    break;
                                }
                            }
                        }
                        return (
                            <MessageBubble
                                key={msg.id}
                                message={msg}
                                userQuery={userQuery}
                                onRegenerate={handleRegenerate}
                                conversationId={activeSessionId}
                                onSendMessage={handleSendMessage}
                            />
                        );
                    })}

                    <div ref={messagesEndRef} />
                </div>

                <div className="border-t border-slate-200 bg-white/80 backdrop-blur-md p-2">
                    <InputBox onSend={(text) => handleSendMessage(text, { queryMode: 'new' })} isLoading={isSending} />
                </div>
            </div>
        </div>
    );
};

export default ChatPage;
