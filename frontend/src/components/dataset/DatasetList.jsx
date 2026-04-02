import React, { useState, useRef, useEffect } from 'react';
import { FileText, Database, MoreVertical, Clock, Trash2, Eye } from 'lucide-react';

const DatasetList = ({ datasets, onDatasetSelect, onDatasetDelete, activeCollections = new Set(), onToggleActive }) => {
    const [menuOpen, setMenuOpen] = useState(null);
    const [deleteConfirm, setDeleteConfirm] = useState(null);
    const menuRef = useRef(null);

    // 点击外部关闭菜单
    useEffect(() => {
        const handleClickOutside = (event) => {
            if (menuRef.current && !menuRef.current.contains(event.target)) {
                setMenuOpen(null);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelect = (dataset) => {
        onDatasetSelect?.(dataset);
    };

    const handleKeyDown = (event, dataset) => {
        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            handleSelect(dataset);
        }
    };

    const handleMenuClick = (event, datasetId) => {
        event.stopPropagation();
        setMenuOpen(menuOpen === datasetId ? null : datasetId);
    };

    const handleDeleteClick = (event, dataset) => {
        event.stopPropagation();
        setMenuOpen(null);
        setDeleteConfirm(dataset);
    };

    const confirmDelete = async () => {
        if (deleteConfirm && onDatasetDelete) {
            await onDatasetDelete(deleteConfirm.name);
        }
        setDeleteConfirm(null);
    };

    return (
        <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {datasets.map((dataset) => (
                    <div
                        key={dataset.id}
                        role="button"
                        tabIndex={0}
                        onClick={() => handleSelect(dataset)}
                        onKeyDown={(event) => handleKeyDown(event, dataset)}
                        className="group relative bg-white border border-slate-200 rounded-2xl p-5 hover:shadow-xl hover:shadow-brand-orange-500/5 hover:-translate-y-1 transition-all duration-300 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-brand-orange-400 focus-visible:border-brand-orange-400"
                    >
                        <div className="absolute inset-x-0 bottom-0 h-1 bg-gradient-to-r from-brand-orange-400 to-brand-purple-500 rounded-b-2xl opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex items-start justify-between mb-4">
                            <div className={`p-3 rounded-xl transition-colors ${
                                dataset.status === 'ready' 
                                    ? 'bg-emerald-50 text-emerald-600 group-hover:bg-emerald-100' 
                                    : 'bg-amber-50 text-amber-600 group-hover:bg-amber-100'
                            }`}>
                                <Database size={24} />
                            </div>
                            <div className="relative" ref={menuOpen === dataset.id ? menuRef : null}>
                                <button
                                    type="button"
                                    onClick={(event) => handleMenuClick(event, dataset.id)}
                                    className="text-slate-400 hover:text-brand-orange-500 opacity-0 group-hover:opacity-100 transition-all p-1 hover:bg-brand-orange-50 rounded"
                                >
                                    <MoreVertical size={20} />
                                </button>
                                {menuOpen === dataset.id && (
                                    <div className="absolute right-0 top-8 w-36 bg-white border border-slate-200 rounded-xl shadow-lg z-20 py-1 animate-in fade-in zoom-in-95 duration-150">
                                        <button
                                            onClick={(event) => { event.stopPropagation(); handleSelect(dataset); setMenuOpen(null); }}
                                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50 hover:text-brand-orange-600"
                                        >
                                            <Eye size={16} />
                                            Preview
                                        </button>
                                        <button
                                            onClick={(event) => handleDeleteClick(event, dataset)}
                                            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-red-500 hover:bg-red-50"
                                        >
                                            <Trash2 size={16} />
                                            Delete
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>

                        <h3 className="font-bold text-lg text-slate-800 mb-1 group-hover:text-brand-orange-600 transition-colors">{dataset.name}</h3>
                        <p className="text-sm text-slate-500 line-clamp-2 mb-4 h-10 leading-relaxed">{dataset.description}</p>

                        <div className="flex items-center gap-4 text-xs font-medium text-slate-400 border-t border-slate-100 pt-4 mt-2">
                            <div className="flex items-center gap-1.5 px-2 py-1 bg-slate-50 rounded-md">
                                <FileText size={14} className="text-slate-500" />
                                <span>{dataset.docCount} Docs</span>
                            </div>
                            <div className="flex items-center gap-1.5 px-2 py-1 bg-slate-50 rounded-md">
                                <Database size={14} className="text-slate-500" />
                                <span>{dataset.chunkCount} Chunks</span>
                            </div>
                            <div className="flex items-center gap-1.5 ml-auto text-slate-400">
                                <Clock size={14} />
                                <span>{dataset.updatedAt}</span>
                            </div>
                        </div>
                        {/* 启用/停用开关 */}
                        <div
                            className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100"
                            onClick={e => e.stopPropagation()}
                        >
                            <span className="text-xs text-slate-400">Included in search</span>
                            <button
                                type="button"
                                onClick={() => onToggleActive?.(dataset.name)}
                                className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                                    activeCollections.has(dataset.name)
                                        ? 'bg-brand-orange-500'
                                        : 'bg-slate-200'
                                }`}
                                title={activeCollections.has(dataset.name) ? 'Click to disable' : 'Click to enable'}
                            >
                                <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                                        activeCollections.has(dataset.name) ? 'translate-x-4' : 'translate-x-0'
                                    }`}
                                />
                            </button>
                        </div>
                    </div>
                ))}
            </div>

            {/* 删除确认弹窗 */}
            {deleteConfirm && (
                <div className="fixed inset-0 z-50 flex items-center justify-center">
                    <div className="absolute inset-0 bg-slate-900/60 backdrop-blur-sm" onClick={() => setDeleteConfirm(null)} />
                    <div className="relative bg-white rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 animate-in fade-in zoom-in-95 duration-200">
                        <div className="flex items-center gap-3 mb-4">
                            <div className="p-3 bg-red-100 rounded-full">
                                <Trash2 size={24} className="text-red-500" />
                            </div>
                            <div>
                                <h3 className="text-lg font-bold text-slate-800">Confirm Deletion</h3>
                                <p className="text-sm text-slate-500">This action cannot be undone</p>
                            </div>
                        </div>
                        <p className="text-slate-600 mb-6">
                            Are you sure you want to delete collection <span className="font-semibold text-slate-800">"{deleteConfirm.name}"</span>?
                            <br />
                            <span className="text-sm text-slate-500">{deleteConfirm.chunkCount} records will be permanently deleted.</span>
                        </p>
                        <div className="flex gap-3 justify-end">
                            <button
                                onClick={() => setDeleteConfirm(null)}
                                className="px-4 py-2 text-slate-600 hover:bg-slate-100 rounded-xl font-medium transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={confirmDelete}
                                className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-xl font-medium transition-colors"
                            >
                                Confirm Delete
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
};

export default DatasetList;
