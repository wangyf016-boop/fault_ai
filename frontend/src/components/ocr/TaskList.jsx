import React from 'react';
import { FileText, Clock, CheckCircle, XCircle, Loader2, Trash2, Download, Eye } from 'lucide-react';

const statusConfig = {
    pending: { icon: Clock, color: 'text-amber-500', bg: 'bg-amber-50 border-amber-100', label: 'Queued' },
    processing: { icon: Loader2, color: 'text-brand-orange-500', bg: 'bg-brand-orange-50 border-brand-orange-100', label: 'Processing', animate: true },
    completed: { icon: CheckCircle, color: 'text-emerald-500', bg: 'bg-emerald-50 border-emerald-100', label: 'Completed' },
    failed: { icon: XCircle, color: 'text-red-500', bg: 'bg-red-50 border-red-100', label: 'Failed' },
};

const TaskItem = ({ task, onView, onDownload, onDelete }) => {
    const config = statusConfig[task.status] || statusConfig.pending;
    const StatusIcon = config.icon;

    return (
        <div className={`group bg-white border border-slate-200 rounded-2xl p-5 hover:shadow-lg transition-all duration-300 relative ${
            task.status === 'processing' ? 'border-brand-orange-200 ring-1 ring-brand-orange-100' : ''
        }`}>
            <div className="flex items-start justify-between mb-4">
                <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div className={`p-2.5 rounded-xl shrink-0 ${
                        task.status === 'processing' ? 'bg-brand-orange-100 text-brand-orange-600' : 'bg-slate-100 text-slate-500'
                    }`}>
                        <FileText size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                        <h4 className="font-bold text-sm text-slate-800 truncate leading-tight" title={task.filename}>
                            {task.filename}
                        </h4>
                        <p className="text-xs text-slate-500 mt-1.5 font-medium">
                            {task.createdAt}
                        </p>
                    </div>
                </div>
                <div className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border ${config.bg}`}>
                    <StatusIcon 
                        size={14} 
                        className={`${config.color} ${config.animate ? 'animate-spin' : ''}`} 
                    />
                    <span className={`text-xs font-bold ${config.color}`}>
                        {config.label}
                    </span>
                </div>
            </div>

            {/* 进度条 */}
            {task.status === 'processing' && (
                <div className="mt-4 mb-2">
                    <div className="flex justify-between text-xs font-bold text-slate-500 mb-2 uppercase tracking-wide">
                        <span>{task.stage || 'Analyzing...'}</span>
                        <span>{task.progress !== undefined ? task.progress : 0}%</span>
                    </div>
                    <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                        <div 
                            className="h-full bg-gradient-to-r from-brand-orange-500 to-brand-orange-400 rounded-full transition-all duration-500 ease-out"
                            style={{ width: `${task.progress !== undefined ? task.progress : 0}%` }}
                        />
                    </div>
                </div>
            )}

            {/* 操作按钮 */}
            {task.status === 'completed' && (
                <div className="flex items-center gap-2 mt-4 pt-4 border-t border-slate-100">
                    <button
                        onClick={() => onView?.(task)}
                        className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs font-bold text-brand-orange-600 bg-brand-orange-50 hover:bg-brand-orange-100 rounded-xl transition-colors"
                    >
                        <Eye size={14} />
                        View
                    </button>
                    <button
                        onClick={() => onDownload?.(task)}
                        className="flex-1 flex items-center justify-center gap-2 px-3 py-2 text-xs font-bold text-slate-600 bg-slate-50 hover:bg-slate-100 rounded-xl transition-colors"
                    >
                        <Download size={14} />
                        Download
                    </button>
                    <button
                        onClick={() => onDelete?.(task)}
                        className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors"
                        title="Delete Task"
                    >
                        <Trash2 size={16} />
                    </button>
                </div>
            )}
             {/* Failed State Actions */}
            {task.status === 'failed' && (
                <div className="mt-4 pt-4 border-t border-red-100">
                    {task.error && (
                         <div className="p-3 bg-red-50 rounded-xl mb-3 text-xs text-red-600 leading-relaxed border border-red-100">
                            {task.error}
                        </div>
                    )}
                     <div className="flex justify-end">
                        <button
                            onClick={() => onDelete?.(task)}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                        >
                            <Trash2 size={14} />
                            Remove
                        </button>
                    </div>
                </div>
            )}

             {/* Pending State - Allow cancel/delete */}
             {(task.status === 'pending') && (
                 <div className="mt-2 flex justify-end">
                    <button
                        onClick={() => onDelete?.(task)}
                        className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors opacity-0 group-hover:opacity-100"
                        title="Cancel Task"
                    >
                        <Trash2 size={14} />
                    </button>
                 </div>
             )}
        </div>
    );
};

const TaskList = ({ tasks, onView, onDownload, onDelete }) => {
    if (!tasks || tasks.length === 0) {
        return (
            <div className="h-64 flex flex-col items-center justify-center text-center p-8 bg-slate-50/50 rounded-2xl border-2 border-dashed border-slate-200">
                <div className="w-16 h-16 bg-white rounded-full flex items-center justify-center shadow-sm mb-4">
                     <FileText size={32} className="text-slate-300" />
                </div>
                <h4 className="text-lg font-bold text-slate-700">No active tasks</h4>
                <p className="text-sm text-slate-500 mt-1 max-w-xs mx-auto">Upload PDF documents to start the extraction process.</p>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {tasks.map(task => (
                <TaskItem
                    key={task.id}
                    task={task}
                    onView={onView}
                    onDownload={onDownload}
                    onDelete={onDelete}
                />
            ))}
        </div>
    );
};

export default TaskList;
