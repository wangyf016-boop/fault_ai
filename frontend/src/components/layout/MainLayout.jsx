import React, { useState } from 'react';
import { Outlet, NavLink } from 'react-router-dom';
import { MessageSquare, Network, Database, FileSearch, Settings, LogOut, ChevronLeft, ChevronRight } from 'lucide-react';

const MainLayout = () => {
    const [isCollapsed, setIsCollapsed] = useState(() => {
        try {
            return localStorage.getItem('mainLayoutSidebarCollapsed') === '1';
        } catch {
            return false;
        }
    });

    React.useEffect(() => {
        try {
            localStorage.setItem('mainLayoutSidebarCollapsed', isCollapsed ? '1' : '0');
        } catch {
            // ignore storage errors
        }

        window.dispatchEvent(new CustomEvent('layout:main-sidebar-change', {
            detail: { collapsed: isCollapsed }
        }));
    }, [isCollapsed]);

    const navItems = [
        { icon: MessageSquare, label: 'Chat', path: '/chat' },
        { icon: Network, label: 'Graph Search', path: '/graph-search' },
        { icon: Database, label: 'Datasets', path: '/datasets' },
        { icon: FileSearch, label: 'OCR', path: '/ocr' },
        { icon: Settings, label: 'Settings', path: '/settings' },
    ];

    return (
        <div className="flex h-screen bg-slate-50 overflow-hidden font-sans">
            {/* Sidebar */}
            <aside 
                className={`${isCollapsed ? 'w-16 min-w-[64px] border-r border-slate-200' : 'w-[280px] border-r border-slate-200'} shrink-0 flex flex-col bg-white transition-all duration-300 ease-[cubic-bezier(0.25,0.1,0.25,1)] relative z-30 shadow-[4px_0_24px_-12px_rgba(0,0,0,0.1)] overflow-visible`}
            >
                {/* Toggle Button */}
                <button 
                    onClick={() => setIsCollapsed(!isCollapsed)}
                    className="absolute -right-3 top-10 w-6 h-6 bg-white border border-slate-200 rounded-full flex items-center justify-center text-slate-400 hover:text-brand-orange-500 hover:border-brand-orange-300 hover:shadow-md transition-all z-50 focus:outline-none ring-offset-2 focus:ring-2 ring-brand-orange-200"
                >
                    {isCollapsed ? <ChevronRight size={14} strokeWidth={3} /> : <ChevronLeft size={14} strokeWidth={3} />}
                </button>

                {!isCollapsed ? (
                    <>
                    <div className="h-20 flex items-center px-5 border-b border-slate-100/80">
                        <div className="flex items-center gap-3">
                             <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-orange-500 to-brand-purple-500 flex items-center justify-center text-white font-bold text-lg shadow-lg shadow-brand-orange-500/30">
                                M
                            </div>
                            <div>
                                <h1 className="text-base font-bold text-slate-800 leading-tight tracking-tight">
                                    Maintenance
                                </h1>
                                <p className="text-xs font-semibold text-transparent bg-clip-text bg-gradient-to-r from-brand-orange-500 to-brand-purple-500 leading-tight">
                                    Intelligent Expert
                                </p>
                            </div>
                        </div>
                    </div>

                <nav className="flex-1 p-4 space-y-2 mt-2 overflow-y-auto custom-scrollbar">
                    {navItems.map((item) => (
                        <NavLink
                            key={item.path}
                            to={item.path}
                            className={({ isActive }) =>
                                `flex items-center gap-3 px-4 w-full h-11 rounded-xl transition-all duration-200 group relative ${isActive
                                    ? 'bg-gradient-to-r from-brand-orange-50 to-white text-brand-orange-600 font-bold shadow-sm border border-brand-orange-100/50'
                                    : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900 border border-transparent'
                                }`
                            }
                            title=""
                        >
                            {({ isActive }) => (
                                <>
                                    {isActive && (
                                        <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-6 bg-brand-orange-500 rounded-r-full" />
                                    )}
                                    <item.icon 
                                        size={22} 
                                        strokeWidth={isActive ? 2.5 : 2}
                                        className={isActive ? 'text-brand-orange-500 drop-shadow-sm' : 'text-slate-400 group-hover:text-slate-600 transition-colors'} 
                                    />
                                    <span>{item.label}</span>
                                </>
                            )}
                        </NavLink>
                    ))}
                </nav>

                <div className="p-4 border-t border-slate-100">
                    <button 
                        className="flex items-center gap-3 px-4 py-3 w-full rounded-xl text-slate-500 hover:bg-red-50 hover:text-red-500 hover:border hover:border-red-100 transition-all group"
                        title=""
                    >
                        <LogOut size={20} className="group-hover:text-red-500 transition-colors" />
                        <span className="font-semibold text-sm">Sign Out</span>
                    </button>

                        <div className="mt-4 px-3 py-3 bg-slate-50 rounded-xl border border-slate-200 flex items-center gap-3 shadow-inner">
                             <div className="w-9 h-9 rounded-full bg-white border-2 border-white shadow-sm flex items-center justify-center overflow-hidden">
                                <img src="https://ui-avatars.com/api/?name=Admin+User&background=random" alt="Admin" className="w-full h-full object-cover" />
                            </div>
                            <div className="flex-1 overflow-hidden">
                                <p className="text-sm font-bold text-slate-800 truncate">Admin User</p>
                                <p className="text-xs text-slate-400 truncate flex items-center gap-1">
                                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                                    Online
                                </p>
                            </div>
                        </div>
                </div>
                </>
                ) : (
                    <div className="flex-1 flex flex-col items-center pt-6 pb-4 gap-3">
                        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-orange-500 to-brand-purple-500 flex items-center justify-center text-white font-bold text-sm shadow-lg shadow-brand-orange-500/30">
                            M
                        </div>
                        <div className="mt-4 flex flex-col items-center gap-2">
                            {navItems.map((item) => (
                                <NavLink
                                    key={item.path}
                                    to={item.path}
                                    className={({ isActive }) =>
                                        `w-10 h-10 rounded-xl flex items-center justify-center transition-all ${isActive
                                            ? 'bg-brand-orange-50 text-brand-orange-600 border border-brand-orange-100'
                                            : 'text-slate-400 hover:text-slate-700 hover:bg-slate-50 border border-transparent'
                                        }`
                                    }
                                    title={item.label}
                                >
                                    <item.icon size={18} />
                                </NavLink>
                            ))}
                        </div>
                    </div>
                )}
            </aside>

            {/* Main Content */}
            <main className="flex-1 min-w-0 flex flex-col h-screen overflow-hidden relative">
                 {/* Top Background Decoration */}
                 <div className="absolute top-0 inset-x-0 h-64 bg-gradient-to-b from-slate-100/50 to-transparent pointer-events-none z-0" />

                <div className="flex-1 min-w-0 overflow-auto px-6 pb-6 z-10 relative mt-6">
                     <div className="max-w-[1600px] mx-auto h-full">
                        <Outlet />
                     </div>
                </div>
            </main>
        </div>
    );
};

export default MainLayout;
