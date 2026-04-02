import React, { useState, useEffect } from 'react';
import { Plus, Filter, RefreshCw, Database, AlertCircle } from 'lucide-react';
import DatasetList from '../components/dataset/DatasetList';
import DatasetChunkPreview from '../components/dataset/DatasetChunkPreview';
import UploadZone from '../components/dataset/UploadZone';
import ChunkConfig from '../components/dataset/ChunkConfig';
import { listCollections, getCollectionInfo, getCollectionChunks, deleteCollection, getActiveCollections, toggleCollection } from '../services/datasetApi';

const DatasetPage = () => {
    const [view, setView] = useState('list');
    const [datasets, setDatasets] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [previewDataset, setPreviewDataset] = useState(null);
    const [previewChunks, setPreviewChunks] = useState([]);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [previewError, setPreviewError] = useState(null);
    const [activeCollections, setActiveCollections] = useState(new Set());

    const fetchCollections = async () => {
        setLoading(true);
        setError(null);
        try {
            const [{ collections }, { active }] = await Promise.all([
                listCollections(),
                getActiveCollections(),
            ]);
            setActiveCollections(new Set(active));
            const datasetsWithInfo = await Promise.all(
                collections.map(async (col) => {
                    try {
                        const info = await getCollectionInfo(col.name);
                        return {
                            id: col.name,
                            name: col.name,
                            description: `Vector collection with ${info.distance} distance`,
                            status: info.status === 'GREEN' ? 'ready' : 'processing',
                            docCount: info.docs || info.points || 0,
                            chunkCount: info.chunks || info.points || 0,
                            updatedAt: 'Now'
                        };
                    } catch {
                        return {
                            id: col.name, name: col.name, description: 'Vector collection',
                            status: 'ready', docCount: 0, chunkCount: 0, updatedAt: '-'
                        };
                    }
                })
            );
            setDatasets(datasetsWithInfo);
        } catch (err) {
            setError(err.message || 'Failed to load collections');
        } finally {
            setLoading(false);
        }
    };

    const handleToggleActive = async (name) => {
        try {
            const { active } = await toggleCollection(name);
            setActiveCollections(prev => {
                const next = new Set(prev);
                if (active) next.add(name); else next.delete(name);
                return next;
            });
        } catch (err) {
            setError(err.message || 'Operation failed');
        }
    };

    useEffect(() => { fetchCollections(); }, []);

    const openChunkPreview = async (dataset) => {
        setPreviewDataset(dataset);
        setPreviewLoading(true);
        setPreviewError(null);
        setPreviewChunks([]);

        try {
            const { chunks } = await getCollectionChunks(dataset.name, { limit: 6 });
            setPreviewChunks(chunks || []);
        } catch (err) {
            setPreviewError(err.message || 'Unable to load chunk preview');
        } finally {
            setPreviewLoading(false);
        }
    };

    const closeChunkPreview = () => {
        setPreviewDataset(null);
        setPreviewChunks([]);
        setPreviewLoading(false);
        setPreviewError(null);
    };

    const handleEmbeddingComplete = () => {
        fetchCollections();
        setView('list');
    };

    const handleDeleteDataset = async (name) => {
        try {
            await deleteCollection(name);
            fetchCollections(); // 刷新列表
        } catch (err) {
            setError(err.message || 'Delete failed');
        }
    };

    return (
        <div className="h-full flex flex-col space-y-6">
            <div className="flex items-center justify-between">
                <div>
                     <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-brand-orange-500 to-brand-purple-600">
                        Knowledge Base
                    </h1>
                    <p className="text-slate-500">Manage your datasets and knowledge sources.</p>
                </div>
                <div className="flex gap-3">
                    {view !== 'list' && (
                        <button 
                            onClick={() => setView('list')} 
                            className="px-4 py-2 text-slate-500 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition-colors font-medium border border-transparent hover:border-slate-200"
                        >
                            Cancel
                        </button>
                    )}
                    {view === 'list' ? (
                        <>
                            <button 
                                onClick={fetchCollections} 
                                className="flex items-center gap-2 px-4 py-2.5 bg-white border border-slate-200 text-slate-600 hover:text-brand-orange-600 hover:border-brand-orange-200 hover:bg-brand-orange-50 rounded-xl transition-all font-medium shadow-sm hover:shadow"
                                disabled={loading}
                            >
                                <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
                                Refresh
                            </button>
                            <button 
                                onClick={() => setView('upload')} 
                                className="flex items-center gap-2 px-6 py-2.5 bg-gradient-to-r from-brand-orange-500 to-brand-orange-600 text-white rounded-xl font-semibold shadow-md shadow-brand-orange-200 hover:shadow-lg hover:from-brand-orange-600 hover:to-brand-orange-700 transition-all transform hover:-translate-y-0.5"
                            >
                                <Plus size={18} />
                                Import Dataset
                            </button>
                        </>
                    ) : view === 'upload' ? (
                        <button 
                            onClick={() => setView('config')} 
                            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-200 text-slate-600 rounded-xl hover:bg-slate-50 transition-colors"
                        >
                            Configure Chunking
                        </button>
                    ) : (
                        <button 
                            onClick={() => setView('list')} 
                            className="flex items-center gap-2 px-6 py-2 bg-brand-orange-500 text-white rounded-xl hover:bg-brand-orange-600 transition-colors shadow-md"
                        >
                            Done
                        </button>
                    )}
                </div>
            </div>

            <div className="flex-1 overflow-y-auto">
                {view === 'list' && (
                    <>
                        {error && (
                            <div className="mb-6 p-4 bg-red-50 border border-red-100 rounded-xl flex items-center gap-3">
                                <AlertCircle size={20} className="text-red-500" />
                                <span className="text-red-600 font-medium">{error}</span>
                            </div>
                        )}
                        <div className="flex items-center gap-4 mb-8">
                            <div className="relative flex-1 max-w-md">
                                <input 
                                    type="text" 
                                    placeholder="Search datasets..." 
                                    className="w-full pl-10 pr-4 py-2.5 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 transition-all"
                                />
                                <Filter className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                            </div>
                        </div>
                        
                        {loading ? (
                            <div className="flex flex-col items-center justify-center py-20 gap-4">
                                <RefreshCw size={32} className="animate-spin text-brand-orange-500" />
                                <p className="text-slate-400 font-medium">Loading datasets...</p>
                            </div>
                        ) : datasets.length > 0 ? (
                                <DatasetList datasets={datasets} onDatasetSelect={openChunkPreview} onDatasetDelete={handleDeleteDataset} activeCollections={activeCollections} onToggleActive={handleToggleActive} />
                        ) : (
                            <div className="flex flex-col items-center justify-center py-20 text-center">
                                <div className="w-20 h-20 bg-slate-50 rounded-full flex items-center justify-center mb-6">
                                    <Database size={40} className="text-slate-300" />
                                </div>
                                <h3 className="text-lg font-bold text-slate-700">No datasets found</h3>
                                <p className="text-slate-500 max-w-xs mt-2 mb-6">Import your first CSV dataset to start building your knowledge base.</p>
                                <button 
                                    onClick={() => setView('upload')}
                                    className="px-6 py-2.5 bg-white border border-slate-200 text-slate-600 font-medium rounded-xl hover:bg-slate-50 transition-colors"
                                >
                                    Import Now
                                </button>
                            </div>
                        )}
                    </>
                )}
                {view === 'upload' && (
                    <div className="max-w-4xl mx-auto bg-white border border-slate-200 rounded-2xl shadow-sm p-8 animate-in fade-in slide-in-from-bottom-2 duration-300">
                        <div className="mb-8 border-b border-slate-100 pb-4">
                            <h2 className="text-xl font-bold text-slate-800 mb-2">Import & Embed Dataset</h2>
                            <p className="text-slate-500">Upload CSV files to embed into Qdrant or Neo4j</p>
                        </div>
                        <UploadZone onEmbeddingComplete={handleEmbeddingComplete} />
                    </div>
                )}
                {view === 'config' && (
                    <div className="h-full flex flex-col bg-white border border-slate-200 rounded-2xl shadow-sm p-8 animate-in fade-in slide-in-from-bottom-2">
                        <div className="mb-6 border-b border-slate-100 pb-4">
                            <h2 className="text-xl font-bold text-slate-800 mb-2">Chunking Configuration</h2>
                            <p className="text-slate-500">Preview and adjust how your data is split.</p>
                        </div>
                        <ChunkConfig />
                    </div>
                )}
            </div>
            {previewDataset && (
                <DatasetChunkPreview
                    dataset={previewDataset}
                    chunks={previewChunks}
                    loading={previewLoading}
                    error={previewError}
                    onClose={closeChunkPreview}
                />
            )}
        </div>
    );
};

export default DatasetPage;
