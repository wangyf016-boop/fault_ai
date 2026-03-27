import React, { useState } from 'react';
import { Settings, RefreshCw, ChevronRight } from 'lucide-react';

const ChunkConfig = () => {
    const [chunkSize, setChunkSize] = useState(500);
    const [overlap, setOverlap] = useState(50);

    const MOCK_TEXT = `The fault diagnosis system is designed to identify root causes of equipment failures. 
It utilizes a combination of rule-based reasoning and machine learning models. 
When a fault occurs, the system first checks the error codes against the knowledge graph. 
If no direct match is found, it queries the vector database for similar historical cases. 
This hybrid approach ensures high accuracy and robustness. 
Operators can also provide feedback to improve the system over time.`;

    // Simple mock chunking for visualization
    const chunks = MOCK_TEXT.match(new RegExp(`.{1,${chunkSize}}`, 'g')) || [];

    return (
        <div className="flex h-[600px] border border-slate-200 rounded-2xl overflow-hidden bg-white shadow-sm">
            {/* Config Panel */}
            <div className="w-1/3 border-r border-slate-100 p-6 bg-slate-50 overflow-y-auto">
                <div className="flex items-center gap-2 mb-8">
                    <div className="p-2 bg-brand-orange-100 text-brand-orange-600 rounded-lg">
                        <Settings size={20} />
                    </div>
                    <h3 className="font-bold text-slate-800">Chunking Strategy</h3>
                </div>

                <div className="space-y-8">
                    <div>
                        <label className="block text-sm font-bold text-slate-700 mb-3">Strategy</label>
                        <div className="relative">
                            <select className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-brand-orange-100 focus:border-brand-orange-400 text-slate-700 font-medium appearance-none">
                                <option>Fixed Size</option>
                                <option>Semantic (Sentence)</option>
                                <option>Markdown Header</option>
                            </select>
                            <div className="absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400">
                                <ChevronRight className="rotate-90" size={16} />
                            </div>
                        </div>
                    </div>

                    <div>
                        <div className="flex justify-between items-center mb-3">
                            <label className="block text-sm font-bold text-slate-700">Chunk Size</label>
                            <span className="text-xs font-mono px-2 py-1 bg-white border border-slate-200 rounded text-slate-500">{chunkSize} tokens</span>
                        </div>
                        <div className="flex flex-col gap-2">
                            <input
                                type="range"
                                min="100"
                                max="2000"
                                step="50"
                                value={chunkSize}
                                onChange={(e) => setChunkSize(Number(e.target.value))}
                                className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-brand-orange-500"
                            />
                            <div className="flex justify-between text-xs text-slate-400 font-medium">
                                <span>100</span>
                                <span>2000</span>
                            </div>
                        </div>
                    </div>

                    <div>
                        <div className="flex justify-between items-center mb-3">
                            <label className="block text-sm font-bold text-slate-700">Overlap</label>
                            <span className="text-xs font-mono px-2 py-1 bg-white border border-slate-200 rounded text-slate-500">{overlap} chars</span>
                        </div>
                        <div className="flex flex-col gap-2">
                            <input
                                type="range"
                                min="0"
                                max="200"
                                step="10"
                                value={overlap}
                                onChange={(e) => setOverlap(Number(e.target.value))}
                                className="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-brand-orange-500"
                            />
                            <div className="flex justify-between text-xs text-slate-400 font-medium">
                                <span>0</span>
                                <span>200</span>
                            </div>
                        </div>
                    </div>

                    <div className="pt-6 border-t border-slate-200">
                        <button className="w-full flex items-center justify-center gap-2 px-6 py-3 bg-brand-orange-500 text-white rounded-xl font-bold hover:bg-brand-orange-600 transition-colors shadow-sm">
                            <RefreshCw size={18} />
                            Apply & Preview
                        </button>
                    </div>
                </div>
            </div>

            {/* Preview Panel */}
            <div className="flex-1 flex flex-col bg-white">
                <div className="h-14 border-b border-slate-100 flex items-center justify-between px-6 bg-slate-50/50">
                    <span className="font-bold text-slate-700 text-sm uppercase tracking-wide">Preview Output</span>
                    <span className="text-xs font-medium px-2 py-1 bg-slate-200 text-slate-600 rounded-md">{chunks.length} Chunks</span>
                </div>
                <div className="flex-1 overflow-y-auto p-6 space-y-4">
                    {chunks.map((chunk, idx) => (
                        <div key={idx} className="group relative border border-slate-200 rounded-xl p-5 hover:border-brand-orange-300 hover:bg-brand-orange-50/10 hover:shadow-md transition-all">
                            <div className="absolute top-3 right-3 opacity-0 group-hover:opacity-100 bg-brand-orange-100 text-brand-orange-700 text-xs font-bold px-2 py-1 rounded">
                                #{idx + 1} | {chunk.length} chars
                            </div>
                            <p className="text-sm leading-7 text-slate-600 group-hover:text-slate-800 transition-colors">
                                {chunk}
                            </p>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

export default ChunkConfig;
