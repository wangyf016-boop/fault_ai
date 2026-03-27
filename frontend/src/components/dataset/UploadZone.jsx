import React, { useState } from 'react';
import { UploadCloud, File, X, CheckCircle, Loader2, AlertCircle } from 'lucide-react';
import { embedDataset, pollEmbeddingStatus } from '../../services/datasetApi';

const UploadZone = ({ onEmbeddingComplete }) => {
    const [isDragging, setIsDragging] = useState(false);
    const [files, setFiles] = useState([]);
    const [embedTarget, setEmbedTarget] = useState('qdrant');
    const [collectionName, setCollectionName] = useState('');
    const [clearNeo4j, setClearNeo4j] = useState(false);
    const [isProcessing, setIsProcessing] = useState(false);
    const [currentTask, setCurrentTask] = useState(null);
    const [error, setError] = useState(null);

    const handleDragOver = (e) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragging(false);
        const droppedFiles = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.csv'));
        setFiles(prev => [...prev, ...droppedFiles]);
    };

    const handleFileSelect = (e) => {
        if (e.target.files) {
            const selectedFiles = Array.from(e.target.files).filter(f => f.name.endsWith('.csv'));
            setFiles(prev => [...prev, ...selectedFiles]);
        }
    };

    const removeFile = (index) => {
        setFiles(prev => prev.filter((_, i) => i !== index));
    };

    const handleEmbed = async () => {
        if (files.length === 0) return;
        
        setIsProcessing(true);
        setError(null);
        
        try {
            for (const file of files) {
                // 未填集合名时，每个文件用自己的文件名（去掉 .csv）作为 collection 名
                const derivedName = collectionName || file.name.replace(/\.csv$/i, '').replace(/[\s-]+/g, '_');
                // 启动嵌入任务
                const { task_id } = await embedDataset(file, {
                    target: embedTarget,
                    collectionName: derivedName,
                    clearNeo4j
                });
                
                // 轮询状态
                await pollEmbeddingStatus(task_id, (status) => {
                    setCurrentTask({
                        fileName: file.name,
                        ...status
                    });
                });
            }
            
            setFiles([]);
            setCurrentTask(null);
            if (onEmbeddingComplete) {
                onEmbeddingComplete();
            }
        } catch (err) {
            setError(err.message);
        } finally {
            setIsProcessing(false);
        }
    };

    return (
        <div className="w-full space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
            {/* 上传区域 */}
            <div
                className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all duration-300 group cursor-pointer ${
                    isDragging
                        ? 'border-brand-orange-500 bg-brand-orange-50/50 scale-[1.01]'
                        : 'border-slate-200 hover:border-brand-orange-300 hover:bg-slate-50'
                }`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
                <div className="flex flex-col items-center gap-4">
                    <div className={`w-20 h-20 rounded-full flex items-center justify-center transition-colors shadow-sm ${
                        isDragging ? 'bg-brand-orange-100 text-brand-orange-600' : 'bg-white text-slate-400 group-hover:text-brand-orange-500 group-hover:bg-brand-orange-50 border border-slate-100'
                    }`}>
                        <UploadCloud size={40} />
                    </div>
                    <div>
                        <h3 className="text-xl font-bold text-slate-700 group-hover:text-brand-orange-600 transition-colors">Click or drag CSV files to upload</h3>
                        <p className="text-slate-500 mt-2 max-w-sm mx-auto leading-relaxed">
                            Support CSV files for embedding. We'll automatically process and chunk your data. (Max 50MB)
                        </p>
                    </div>
                    <label className="mt-4 px-8 py-3 bg-white border border-slate-200 text-slate-700 font-semibold rounded-xl hover:bg-slate-50 hover:border-brand-orange-200 hover:text-brand-orange-600 transition-all shadow-sm hover:shadow cursor-pointer">
                        Select Files from System
                        <input 
                            type="file" 
                            multiple 
                            accept=".csv"
                            className="hidden" 
                            onChange={handleFileSelect} 
                        />
                    </label>
                </div>
            </div>

            {/* 嵌入配置 */}
            <div className="bg-slate-50 rounded-2xl p-8 border border-slate-200/60">
                <h4 className="font-bold text-slate-800 mb-6 flex items-center gap-2">
                    <span className="w-1 h-6 bg-brand-orange-500 rounded-full"></span>
                    Embedding Configuration
                </h4>
                
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div>
                        <label className="block text-sm font-semibold text-slate-700 mb-2">Target Database</label>
                        <div className="relative">
                            <select 
                                className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 text-slate-700 font-medium appearance-none"
                                value={embedTarget}
                                onChange={(e) => setEmbedTarget(e.target.value)}
                                disabled={isProcessing}
                            >
                                <option value="qdrant">Qdrant (Vector DB)</option>
                            </select>
                            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M2.5 4.5L6 8L9.5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                            </div>
                        </div>
                        <p className="text-xs text-slate-500 mt-2 flex items-center gap-1">
                            <AlertCircle size={12} />
                            Neo4j graphs are currently managed externally
                        </p>
                    </div>
                    
                    {(embedTarget === 'qdrant' || embedTarget === 'both') && (
                        <div>
                            <label className="block text-sm font-semibold text-slate-700 mb-2">Collection Name</label>
                            <input
                                type="text"
                                className="w-full px-4 py-3 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 text-slate-700 transition-all placeholder:text-slate-400"
                                placeholder="e.g. production_issues_v1"
                                value={collectionName}
                                onChange={(e) => setCollectionName(e.target.value)}
                                disabled={isProcessing}
                            />
                        </div>
                    )}
                </div>
                
                {(embedTarget === 'neo4j' || embedTarget === 'both') && (
                    <label className="flex items-center gap-3 cursor-pointer mt-6 p-4 bg-white rounded-xl border border-slate-200 hover:border-brand-orange-200 transition-colors max-w-md">
                        <input
                            type="checkbox"
                            checked={clearNeo4j}
                            onChange={(e) => setClearNeo4j(e.target.checked)}
                            disabled={isProcessing}
                            className="w-5 h-5 rounded text-brand-orange-600 focus:ring-brand-orange-500 border-gray-300"
                        />
                        <span className="text-sm font-medium text-slate-700">Clear existing Neo4j data before import</span>
                    </label>
                )}
            </div>

            {/* 文件列表 */}
            {files.length > 0 && (
                <div className="space-y-4 pt-4 border-t border-slate-100">
                    <h4 className="text-sm font-bold text-slate-500 uppercase tracking-wider">Upload Queue</h4>
                    <div className="grid gap-3">
                        {files.map((file, index) => {
                            const derivedCollection = collectionName || file.name.replace(/\.csv$/i, '').replace(/[\s-]+/g, '_');
                            return (
                            <div key={index} className="flex items-center justify-between p-4 bg-white border border-slate-200 rounded-xl shadow-sm hover:shadow-md transition-all">
                                <div className="flex items-center gap-4">
                                    <div className="p-3 bg-purple-50 text-brand-purple-600 rounded-lg">
                                        <File size={24} />
                                    </div>
                                    <div>
                                        <p className="font-bold text-slate-700">{file.name}</p>
                                        <p className="text-xs text-slate-500 font-mono mt-0.5">{(file.size / 1024).toFixed(1)} KB</p>
                                        <p className="text-xs text-brand-orange-500 mt-1">→ collection: <span className="font-semibold">{derivedCollection}</span></p>
                                    </div>
                                </div>
                                <button 
                                    onClick={() => removeFile(index)} 
                                    className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                                    disabled={isProcessing}
                                >
                                    <X size={20} />
                                </button>
                            </div>
                            );
                        })}
                    </div>
                    
                    <button
                        onClick={handleEmbed}
                        disabled={isProcessing || files.length === 0}
                        className="w-full mt-6 flex items-center justify-center gap-3 px-8 py-4 bg-gradient-to-r from-brand-orange-500 to-brand-orange-600 hover:from-brand-orange-600 hover:to-brand-orange-700 text-white rounded-xl font-bold shadow-lg shadow-brand-orange-200 hover:shadow-xl hover:-translate-y-0.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none"
                    >
                        {isProcessing ? (
                            <>
                                <Loader2 size={24} className="animate-spin" />
                                Processing Embedding...
                            </>
                        ) : (
                            <>
                                <UploadCloud size={24} />
                                Start Embedding Process
                            </>
                        )}
                    </button>
                </div>
            )}

            {/* 处理进度 */}
            {currentTask && (
                <div className="bg-blue-50/50 border border-blue-100 rounded-2xl p-6 animate-in slide-in-from-bottom-2">
                    <div className="flex items-center gap-3 mb-4">
                        <div className="p-2 bg-blue-100/50 rounded-lg">
                            <Loader2 size={18} className="animate-spin text-blue-600" />
                        </div>
                        <span className="font-bold text-slate-700">Processing: {currentTask.fileName}</span>
                    </div>
                    <div className="w-full h-3 bg-slate-200 rounded-full overflow-hidden mb-3">
                        <div 
                            className="h-full bg-gradient-to-r from-blue-400 to-blue-600 transition-all duration-300 rounded-full"
                            style={{ width: `${currentTask.total > 0 ? (currentTask.progress / currentTask.total) * 100 : 0}%` }}
                        />
                    </div>
                    <div className="flex justify-between text-xs font-medium text-slate-500 uppercase tracking-wide">
                        <span>{currentTask.message}</span>
                        <span>{currentTask.progress} / {currentTask.total}</span>
                    </div>
                </div>
            )}

            {/* 错误提示 */}
            {error && (
                <div className="bg-red-50 border border-red-100 rounded-2xl p-6 flex items-start gap-4 shadow-sm animate-in shake">
                    <div className="p-2 bg-red-100 rounded-full text-red-600 mt-0.5">
                        <AlertCircle size={20} />
                    </div>
                    <div>
                        <p className="font-bold text-red-700 mb-1">Embedding Failed</p>
                        <p className="text-sm text-red-600/90 leading-relaxed">{error}</p>
                    </div>
                </div>
            )}
        </div>
    );
};

export default UploadZone;
