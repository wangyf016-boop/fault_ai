import React, { useMemo, useState, useRef, useEffect } from 'react';
import { Plus, MessageSquare, Search, Trash2, ChevronLeft, ChevronRight } from 'lucide-react';

const ChatSidebar = ({ sessions, activeSessionId, onSelectSession, onNewSession, onDeleteSession, canStartNewSession = true }) => {
    const [openMenuId, setOpenMenuId] = useState(null);
    const [isCollapsed, setIsCollapsed] = useState(() => {
        try {
            return localStorage.getItem('chatSidebarCollapsed') === '1';
        } catch {
            return false;
        }
    });
    const menuRef = useRef(null);

    useEffect(() => {
        const handleClickOutside = (event) => {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setOpenMenuId(null);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    useEffect(() => {
        try {
            localStorage.setItem('chatSidebarCollapsed', isCollapsed ? '1' : '0');
        } catch {
            // ignore storage errors
        }
    }, [isCollapsed]);

    const groupedSessions = useMemo(() => {
        return sessions.reduce((acc, session) => {
            const group = session.group || 'Recent';
            if (!acc[group]) {
                acc[group] = [];
            }
            acc[group].push(session);
            return acc;
        }, {});
    }, [sessions]);

    const groupEntries = Object.entries(groupedSessions);

    return (
        <div className={`${isCollapsed ? 'w-20 min-w-[80px] border-r border-slate-200' : 'w-72 border-r border-slate-200'} h-full shrink-0 flex flex-col bg-white transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] relative overflow-visible z-10`}>
            {/* Toggle Button */}
            <button 
                onClick={() => setIsCollapsed(!isCollapsed)}
                className="absolute -right-3 top-6 w-6 h-6 bg-white border border-slate-200 rounded-full flex items-center justify-center text-slate-400 hover:text-brand-orange-500 hover:border-brand-orange-300 hover:shadow-md transition-all z-50 focus:outline-none"
            >
                {isCollapsed ? <ChevronRight size={14} strokeWidth={3} /> : <ChevronLeft size={14} strokeWidth={3} />}
            </button>

            {!isCollapsed ? (
                <>
                {/* Header with gradient accent */}
                <div className="p-4 bg-gradient-to-b from-brand-orange-50 to-white">
                    <button
                        onClick={onNewSession}
                        disabled={!canStartNewSession}
                        className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl transition-all ${canStartNewSession
                            ? 'bg-gradient-to-r from-brand-orange-500 to-brand-purple-500 text-white font-semibold shadow-lg shadow-brand-orange-500/25 hover:shadow-xl hover:shadow-brand-orange-500/30 transform hover:-translate-y-0.5 active:scale-[0.98]'
                            : 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200'
                            }`}
                    >
                        <Plus size={20} className={canStartNewSession ? "text-white" : "text-slate-400"} />
                        <span className="font-semibold">New Chat</span>
                    </button>
                </div>

                <div className="px-4 pb-4">
                    <div className="relative group">
                        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-brand-orange-500 transition-colors" />
                        <input
                            type="text"
                            placeholder="Search conversations..."
                            className="w-full bg-slate-50 border border-slate-200 rounded-xl pl-10 pr-4 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-500 transition-all placeholder:text-slate-400"
                        />
                    </div>
                </div>

                <div className="flex-1 overflow-y-auto px-2 pb-4 space-y-6 custom-scrollbar">
                 {groupEntries.length === 0 && (
                    <div className="text-center text-sm text-slate-400 px-3 py-8">
                        <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-slate-100 flex items-center justify-center">
                            <MessageSquare size={24} className="text-slate-300" />
                        </div>
                        No conversations yet.
                    </div>
                )}
                
                {groupEntries.map(([group, groupSessions]) => (
                    <div key={group}>
                        <h3 className="px-4 text-xs font-bold text-brand-orange-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                            <span className="w-1.5 h-1.5 rounded-full bg-brand-orange-400"></span>
                            {group}
                        </h3>
                        <div className="space-y-1">
                            {groupSessions.map((session) => (
                                <div
                                    key={session.id}
                                    className={`group relative flex items-start gap-3 px-3 py-3 rounded-xl cursor-pointer transition-all duration-200 ${
                                        activeSessionId === session.id
                                            ? 'bg-gradient-to-r from-brand-orange-100 to-brand-purple-50 text-brand-orange-600 shadow-sm border-l-4 border-brand-orange-500'
                                            : 'hover:bg-slate-50 text-slate-600 hover:text-slate-900 border-l-4 border-transparent'
                                    }`}
                                    onClick={() => onSelectSession(session.id)}
                                >
                                    <MessageSquare size={18} className={`mt-1 shrink-0 ${
                                        activeSessionId === session.id ? 'text-brand-orange-500' : 'text-slate-400 group-hover:text-brand-orange-400'
                                    }`} />
                                    <>
                                        <div className="flex-1 min-w-0">
                                            <p className={`text-sm font-medium truncate leading-tight ${
                                                activeSessionId === session.id ? 'text-brand-orange-700 font-semibold' : 'text-slate-700'
                                            }`}>
                                                {session.title}
                                            </p>
                                            <p className={`text-xs mt-1 truncate ${
                                                activeSessionId === session.id ? 'text-brand-purple-400' : 'text-slate-400'
                                            }`}>
                                                {session.subtitle}
                                            </p>
                                        </div>
                                        
                                        <div className="absolute right-2 top-3 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <button 
                                                className="p-1.5 bg-white hover:bg-red-50 rounded-lg text-slate-400 hover:text-red-500 shadow-sm transition-all ring-1 ring-slate-200 hover:ring-red-200"
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    onDeleteSession(session.id);
                                                }}
                                                title="Delete conversation"
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </>
                                </div>
                            ))}
                        </div>
                    </div>
                ))}
            </div>
            </>
            ) : (
                <div className="h-full flex flex-col items-center pt-16 gap-3 px-3">
                    <div className="w-full rounded-2xl border border-slate-200 bg-slate-50/80 p-1.5 flex items-center justify-center">
                    <button
                        onClick={onNewSession}
                        disabled={!canStartNewSession}
                        className={`w-10 h-10 rounded-xl flex items-center justify-center transition-all ${canStartNewSession
                            ? 'bg-gradient-to-r from-brand-orange-500 to-brand-purple-500 text-white shadow-md hover:shadow-lg'
                            : 'bg-slate-100 text-slate-400 cursor-not-allowed'
                        }`}
                        title="New Chat"
                    >
                        <Plus size={18} />
                    </button>
                    </div>
                    <div className="w-10 h-10 rounded-xl bg-slate-50 border border-slate-200 flex items-center justify-center text-slate-400">
                        <MessageSquare size={18} />
                    </div>
                    <div className="mt-1 w-full flex-1 overflow-y-auto custom-scrollbar space-y-2 pb-3">
                        {sessions.slice(0, 8).map((session) => (
                            <button
                                key={session.id}
                                onClick={() => onSelectSession(session.id)}
                                className={`w-10 h-10 rounded-xl mx-auto flex items-center justify-center text-xs font-semibold transition-all ${
                                    activeSessionId === session.id
                                        ? 'bg-brand-orange-100 text-brand-orange-600 border border-brand-orange-200'
                                        : 'bg-slate-50 text-slate-500 border border-slate-200 hover:bg-slate-100'
                                }`}
                                title={session.title}
                            >
                                {(session.title || 'C').slice(0, 1).toUpperCase()}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

export default ChatSidebar;
