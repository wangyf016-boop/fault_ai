import React from 'react';
import { X, Layers, Loader2 } from 'lucide-react';

const DatasetChunkPreview = ({ dataset, chunks = [], loading, error, onClose }) => {
    return (
        <div className="fixed inset-0 z-40 flex items-center justify-center">
            <div className="absolute inset-0 bg-slate-900/70 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
            <div
                className="relative w-full max-w-5xl mx-4 bg-white rounded-3xl shadow-2xl overflow-hidden border border-slate-100 animate-in fade-in zoom-in-95 duration-200"
                role="dialog"
                aria-modal="true"
                aria-labelledby="dataset-preview-title"
            >
                <header className="bg-gradient-to-br from-brand-orange-500 to-brand-purple-600 text-white p-6 flex items-start justify-between gap-4 shadow-lg">
                    <div>
                        <p className="text-[0.6rem] font-bold uppercase tracking-widest text-white/70 mb-2">Chunk Preview</p>
                        <h2 id="dataset-preview-title" className="text-3xl font-bold leading-tight tracking-tight">
                            {dataset?.name}
                        </h2>
                        <div className="flex items-center gap-2 mt-2">
                            <span className="px-2.5 py-0.5 rounded-full bg-white/20 text-xs font-medium backdrop-blur-sm border border-white/10">
                                {chunks?.length ?? 0} snippets
                            </span>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="h-10 w-10 rounded-full bg-white/20 hover:bg-white/30 grid place-items-center transition backdrop-blur-sm border border-white/10"
                        aria-label="Close chunk preview"
                    >
                        <X size={20} />
                    </button>
                </header>

                <section className="p-6 max-h-[70vh] overflow-y-auto space-y-4 bg-slate-50/50">
                    {loading && (
                        <div className="flex flex-col items-center justify-center py-12 gap-3 text-slate-500">
                            <Loader2 className="animate-spin text-brand-orange-500" size={32} />
                            <p className="font-medium">Loading snippets…</p>
                        </div>
                    )}

                    {error && (
                        <div className="p-4 rounded-xl border border-red-200 bg-red-50 text-sm text-red-700 font-medium flex gap-2">
                             <span>Error:</span> {error}
                        </div>
                    )}

                    {!loading && !error && !chunks.length && (
                        <div className="p-12 rounded-2xl border-2 border-dashed border-slate-200 text-center flex flex-col items-center justify-center gap-4">
                            <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center">
                                <Layers className="text-slate-400" />
                            </div>
                            <div className="space-y-1">
                                <h4 className="text-slate-700 font-semibold">No chunks available</h4>
                                <p className="text-sm text-slate-500">Try refreshing or embedding new data for this collection.</p>
                            </div>
                        </div>
                    )}

                    {chunks.map((chunk, index) => (
                        <article
                            key={`${chunk.id}-${index}`}
                            className="p-5 rounded-2xl bg-white border border-slate-100 shadow-sm hover:shadow-md transition-shadow group relative overflow-hidden"
                        >
                            <div className="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-brand-orange-500/5 to-brand-purple-500/5 rounded-bl-[100px] pointer-events-none" />
                            
                            <div className="flex items-center justify-between mb-3 relative z-10">
                                <div className="flex items-center gap-2">
                                    <div className="p-1.5 bg-slate-50 rounded-lg text-slate-500">
                                        <Layers size={14} />
                                    </div>
                                    <span className="text-xs font-bold uppercase tracking-wider text-slate-500">Chunk {index + 1}</span>
                                </div>
                                <span className="text-[10px] font-mono text-slate-400">ID: {String(chunk.id ?? '').substring(0, 8) || chunk.id}</span>
                            </div>

                            <div className="flex flex-wrap gap-2 mb-4 relative z-10">
                                {chunk.record_id && (
                                    <span className="px-2.5 py-1 rounded-md bg-slate-50 border border-slate-100 text-xs text-slate-600 font-medium">
                                        Record #{chunk.record_id}
                                    </span>
                                )}
                                {chunk.line && (
                                    <span className="px-2.5 py-1 rounded-md bg-slate-50 border border-slate-100 text-xs text-slate-600 font-medium">
                                        Line {chunk.line}
                                    </span>
                                )}
                                {chunk.station && (
                                    <span className="px-2.5 py-1 rounded-md bg-brand-orange-50 border border-brand-orange-100 text-xs text-brand-orange-700 font-medium">
                                        {chunk.station}
                                    </span>
                                )}
                            </div>

                            <div className="bg-slate-50/50 rounded-xl p-4 border border-slate-100/50">
                                <div className="space-y-3 text-sm leading-relaxed">
                                    {['problem', 'cause', 'action', 'plan'].map((field) => {
                                        const value = chunk[field];
                                        if (!value) return null;
                                        return (
                                            <div key={field} className="grid grid-cols-[80px_1fr] gap-2">
                                                <span className="text-xs font-bold uppercase text-slate-400 pt-0.5">{field}</span>
                                                <span className="text-slate-700">{value}</span>
                                            </div>
                                        );
                                    })}
                                    {/* Fallback for other fields or content */}
                                    {chunk.payload && !['problem', 'cause', 'action', 'plan'].some(k => chunk[k]) && (
                                        <div className="text-slate-600">
                                            {typeof chunk.payload === 'string' ? chunk.payload : JSON.stringify(chunk.payload)}
                                        </div>
                                    )}
                                     {chunk.text && !['problem', 'cause', 'action', 'plan'].some(k => chunk[k]) && (
                                        <div className="text-slate-600">
                                            {chunk.text}
                                        </div>
                                    )}
                                </div>
                            </div>
                        </article>
                    ))}
                </section>
            </div>
        </div>
    );
};

export default DatasetChunkPreview;
