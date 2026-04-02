import React, { useState, useEffect, useCallback } from 'react';
import { FileSearch, RefreshCw, Trash2, UploadCloud, Table } from 'lucide-react';
import PdfUploader from '../components/ocr/PdfUploader';
import TaskList from '../components/ocr/TaskList';
import OcrResultsTable from '../components/ocr/OcrResultsTable';
import { 
    uploadPdfForOcr, 
    getOcrTasks, 
    getOcrTaskStatus,
    deleteOcrTask,
    getOcrResults, 
    deleteOcrResult,
    clearOcrResults 
} from '../services/ocrApi';

const OcrPage = () => {
    const [tasks, setTasks] = useState([]);
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('upload'); // 'upload' | 'results'

    // 加载任务列表
    const loadTasks = useCallback(async () => {
        try {
            const data = await getOcrTasks();
            setTasks(data.tasks || []);
        } catch (err) {
            console.error('Failed to load OCR tasks:', err);
            setTasks([]);
        }
    }, []);

    // 加载结果列表
    const loadResults = useCallback(async () => {
        try {
            setLoading(true);
            const data = await getOcrResults();
            setResults(data.results || []);
        } catch (err) {
            console.error('Failed to load OCR results:', err);
            setResults([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadTasks();
        loadResults();
    }, [loadTasks, loadResults]);

    // 轮询处理中的任务状态
    useEffect(() => {
        const processingTasks = tasks.filter(t => t.status === 'processing' || t.status === 'pending');
        if (processingTasks.length === 0) return;

        const interval = setInterval(async () => {
            let hasCompleted = false;
            for (const task of processingTasks) {
                try {
                    const status = await getOcrTaskStatus(task.id);
                    setTasks(prev => prev.map(t => 
                        t.id === task.id ? { ...t, ...status } : t
                    ));
                    if (status.status === 'completed' || status.status === 'failed') {
                        hasCompleted = true;
                    }
                } catch (err) {
                    console.error('Failed to get task status:', err);
                }
            }
            // 有任务完成时刷新结果列表
            if (hasCompleted) {
                loadResults();
            }
        }, 2000);

        return () => clearInterval(interval);
    }, [tasks, loadResults]);

    // 上传文件
    const handleUpload = async (files) => {
        try {
            setUploading(true);
            setError(null);
            const result = await uploadPdfForOcr(files);
            
            // 添加新任务到列表
            const newTasks = result.tasks || [];
            setTasks(prev => [...newTasks, ...prev]);
        } catch (err) {
            console.error('Upload failed:', err);
            setError(err.message || 'Upload failed. Please check whether the backend service is running.');
        } finally {
            setUploading(false);
        }
    };

    // 删除任务
    const handleDeleteTask = async (task) => {
        try {
            await deleteOcrTask(task.id);
            setTasks(prev => prev.filter(t => t.id !== task.id));
        } catch (err) {
            console.error('Failed to delete task:', err);
        }
    };

    // 删除结果
    const handleDeleteResult = async (result) => {
        if (!confirm(`Are you sure you want to delete the record for "${result.filename}"?`)) return;
        
        try {
            await deleteOcrResult(result.id);
            setResults(prev => prev.filter(r => r.id !== result.id));
        } catch (err) {
            console.error('Delete failed:', err);
            setError('Delete failed');
        }
    };

    // 清空所有结果
    const handleClearAll = async () => {
        if (!confirm('Are you sure you want to clear all records?')) return;
        
        try {
            await clearOcrResults();
            setResults([]);
        } catch (err) {
            console.error('Clear failed:', err);
            setError('Clear failed');
        }
    };

    // 刷新
    const handleRefresh = async () => {
        await Promise.all([loadTasks(), loadResults()]);
    };

    return (
        <div className="h-full flex flex-col space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                     <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-brand-orange-500 to-brand-purple-600 flex items-center gap-3">
                        <FileSearch className="text-brand-orange-500" />
                        PDF OCR Extraction
                    </h1>
                     <p className="text-slate-500 mt-1">
                        Extract structured data from PDF documents using VLM models.
                    </p>
                </div>
                <div className="flex items-center gap-4">
                    {/* Tab 切换 */}
                    <div className="flex bg-slate-100 rounded-xl p-1 shadow-inner">
                        <button
                            onClick={() => setActiveTab('upload')}
                            className={`flex items-center gap-2 px-6 py-2 text-sm font-bold rounded-lg transition-all duration-300 ${
                                activeTab === 'upload' 
                                    ? 'bg-white text-brand-orange-600 shadow-sm' 
                                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'
                            }`}
                        >
                            <UploadCloud size={16} />
                            Upload & Process
                        </button>
                        <button
                            onClick={() => setActiveTab('results')}
                            className={`flex items-center gap-2 px-6 py-2 text-sm font-bold rounded-lg transition-all duration-300 ${
                                activeTab === 'results' 
                                    ? 'bg-white text-brand-orange-600 shadow-sm' 
                                    : 'text-slate-500 hover:text-slate-700 hover:bg-slate-200/50'
                            }`}
                        >
                            <Table size={16} />
                            Results
                            {results.length > 0 && (
                                <span className={`ml-2 px-1.5 py-0.5 text-xs rounded-full ${
                                    activeTab === 'results' ? 'bg-brand-orange-100 text-brand-orange-700' : 'bg-slate-200 text-slate-600'
                                }`}>
                                    {results.length}
                                </span>
                            )}
                        </button>
                    </div>
                    
                    <button
                        onClick={handleRefresh}
                        disabled={loading}
                        className="p-2.5 text-slate-500 bg-white border border-slate-200 hover:border-brand-orange-300 hover:text-brand-orange-500 rounded-xl transition-all shadow-sm hover:shadow active:scale-95"
                        title="Refresh Data"
                    >
                        <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 min-h-0">
                {activeTab === 'upload' ? (
                    /* 上传页面 */
                    <div className="h-full grid grid-cols-1 lg:grid-cols-2 gap-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                        {/* 左侧：上传区域 */}
                        <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm flex flex-col h-full">
                            <h2 className="text-xl font-bold text-slate-800 mb-6 flex items-center gap-2">
                                <span className="w-1 h-6 bg-brand-orange-500 rounded-full"></span>
                                New Extraction Task
                            </h2>
                            
                            <div className="flex-1 flex flex-col">
                                <PdfUploader onUpload={handleUpload} disabled={uploading} />
                            
                                {error && (
                                    <div className="mt-6 p-4 bg-red-50 border border-red-100 text-red-600 text-sm rounded-xl flex items-start gap-2">
                                        <div className="mt-0.5 min-w-[16px]"><Trash2 size={16} className="rotate-45" /></div> {/* Reusing an icon for error */}
                                        {error}
                                    </div>
                                )}

                                {/* 功能说明 */}
                                <div className="mt-auto pt-6 border-t border-slate-100">
                                    <div className="bg-slate-50 rounded-xl p-5 border border-slate-100">
                                        <h3 className="font-bold text-slate-700 text-sm mb-3">System Capabilities</h3>
                                        <ul className="text-xs text-slate-500 space-y-2">
                                            <li className="flex items-center gap-2">
                                                <div className="w-1.5 h-1.5 rounded-full bg-brand-purple-400"></div>
                                                Batch PDF processing supported
                                            </li>
                                            <li className="flex items-center gap-2">
                                                <div className="w-1.5 h-1.5 rounded-full bg-brand-purple-400"></div>
                                                Powered by MINERU VLM for structural analysis
                                            </li>
                                            <li className="flex items-center gap-2">
                                                <div className="w-1.5 h-1.5 rounded-full bg-brand-purple-400"></div>
                                                Automatic entity extraction and database entry
                                            </li>
                                        </ul>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* 右侧：任务列表 */}
                        <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm flex flex-col min-h-0 h-full">
                            <h2 className="text-xl font-bold text-slate-800 mb-6 flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="w-1 h-6 bg-brand-purple-500 rounded-full"></span>
                                    Active Tasks
                                </div>
                                {tasks.length > 0 && (
                                    <span className="bg-brand-purple-50 text-brand-purple-700 px-3 py-1 rounded-full text-xs font-bold">
                                        {tasks.length} Pending
                                    </span>
                                )}
                            </h2>
                            <div className="flex-1 overflow-y-auto pr-2 custom-scrollbar">
                                <TaskList
                                    tasks={tasks}
                                    onDelete={handleDeleteTask}
                                />
                            </div>
                        </div>
                    </div>
                ) : (
                    /* 结果表格页面 */
                    <div className="h-full bg-white border border-slate-200 rounded-2xl p-8 shadow-sm flex flex-col animate-in fade-in slide-in-from-right-4 duration-500">
                        <div className="flex items-center justify-between mb-6">
                            <h2 className="text-xl font-bold text-slate-800 flex items-center gap-2">
                                <span className="w-1 h-6 bg-emerald-500 rounded-full"></span>
                                Extracted Data
                                <span className="ml-2 px-3 py-1 bg-slate-100 text-slate-500 rounded-full text-xs font-medium">
                                    Total: {results.length}
                                </span>
                            </h2>
                            {results.length > 0 && (
                                <button
                                    onClick={handleClearAll}
                                    className="flex items-center gap-2 px-4 py-2 text-sm font-bold text-red-500 hover:bg-red-50 hover:text-red-600 rounded-xl transition-colors"
                                >
                                    <Trash2 size={16} />
                                    Clear All History
                                </button>
                            )}
                        </div>
                        <div className="flex-1 overflow-auto bg-slate-50 rounded-xl border border-slate-100 relative">
                            {results.length === 0 ? (
                                <div className="absolute inset-0 flex flex-col items-center justify-center text-slate-400">
                                    <div className="w-20 h-20 bg-white rounded-full flex items-center justify-center mb-4 shadow-sm">
                                        <Table size={40} className="text-slate-300" />
                                    </div>
                                    <h3 className="text-lg font-bold text-slate-600">No results found</h3>
                                    <p className="max-w-xs text-center text-sm mt-2 opacity-80">Process some documents to see extracted data here.</p>
                                    <button
                                        onClick={() => setActiveTab('upload')}
                                        className="mt-6 px-6 py-2 bg-brand-orange-500 text-white rounded-xl hover:bg-brand-orange-600 font-medium shadow-md transition-colors"
                                    >
                                        Go to Upload
                                    </button>
                                </div>
                            ) : (
                                <OcrResultsTable 
                                    results={results} 
                                    onDelete={handleDeleteResult}
                                />
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default OcrPage;
