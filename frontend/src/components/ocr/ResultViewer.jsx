import React, { useState } from 'react';
import { X, Copy, Check, Download, FileText, Image } from 'lucide-react';

const ResultViewer = ({ task, result, onClose, onDownload }) => {
    const [copied, setCopied] = useState(false);
    const [activeTab, setActiveTab] = useState('markdown');

    const handleCopy = async () => {
        if (result?.markdown) {
            await navigator.clipboard.writeText(result.markdown);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    };

    if (!task || !result) return null;

    return (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
            <div className="bg-background rounded-2xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col">
                {/* Header */}
                <div className="flex items-center justify-between p-4 border-b border-border">
                    <div className="flex items-center gap-3">
                        <div className="p-2 bg-primary/10 rounded-lg">
                            <FileText size={20} className="text-primary" />
                        </div>
                        <div>
                            <h3 className="font-semibold">{task.filename}</h3>
                            <p className="text-xs text-muted-foreground">OCR Recognition Result</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleCopy}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted rounded-lg transition-colors"
                        >
                            {copied ? <Check size={16} className="text-success" /> : <Copy size={16} />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                        <button
                            onClick={() => onDownload?.(task)}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-muted rounded-lg transition-colors"
                        >
                            <Download size={16} />
                            Download
                        </button>
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-muted rounded-lg transition-colors"
                        >
                            <X size={20} />
                        </button>
                    </div>
                </div>

                {/* Tabs */}
                <div className="flex border-b border-border px-4">
                    <button
                        onClick={() => setActiveTab('markdown')}
                        className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                            activeTab === 'markdown'
                                ? 'border-primary text-primary'
                                : 'border-transparent text-muted-foreground hover:text-foreground'
                        }`}
                    >
                        <div className="flex items-center gap-2">
                            <FileText size={16} />
                            Markdown
                        </div>
                    </button>
                    {result.images && result.images.length > 0 && (
                        <button
                            onClick={() => setActiveTab('images')}
                            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                                activeTab === 'images'
                                    ? 'border-primary text-primary'
                                    : 'border-transparent text-muted-foreground hover:text-foreground'
                            }`}
                        >
                            <div className="flex items-center gap-2">
                                <Image size={16} />
                                Images ({result.images.length})
                            </div>
                        </button>
                    )}
                </div>

                {/* Content */}
                <div className="flex-1 overflow-auto p-4">
                    {activeTab === 'markdown' && (
                        <div className="bg-muted/30 rounded-lg p-4">
                            <pre className="whitespace-pre-wrap text-sm font-mono leading-relaxed">
                                {result.markdown || 'No content'}
                            </pre>
                        </div>
                    )}
                    {activeTab === 'images' && result.images && (
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                            {result.images.map((img, index) => (
                                <div key={index} className="border border-border rounded-lg overflow-hidden">
                                    <img
                                        src={img.url}
                                        alt={img.name || `Image ${index + 1}`}
                                        className="w-full h-40 object-cover"
                                    />
                                    {img.ocrText && (
                                        <div className="p-2 bg-muted/50 text-xs">
                                            <p className="font-medium mb-1">Recognized Text:</p>
                                            <p className="text-muted-foreground line-clamp-3">
                                                {img.ocrText}
                                            </p>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ResultViewer;
