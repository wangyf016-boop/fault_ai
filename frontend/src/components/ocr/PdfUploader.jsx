import React, { useCallback, useState } from 'react';
import { Upload, FileText, X, AlertCircle } from 'lucide-react';

const PdfUploader = ({ onUpload, disabled }) => {
    const [dragActive, setDragActive] = useState(false);
    const [selectedFiles, setSelectedFiles] = useState([]);
    const [error, setError] = useState(null);

    const handleDrag = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === 'dragenter' || e.type === 'dragover') {
            setDragActive(true);
        } else if (e.type === 'dragleave') {
            setDragActive(false);
        }
    }, []);

    const validateFiles = (files) => {
        const validFiles = [];
        const errors = [];
        
        Array.from(files).forEach(file => {
            if (file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')) {
                validFiles.push(file);
            } else {
                errors.push(`${file.name} 不是 PDF 文件`);
            }
        });

        if (errors.length > 0) {
            setError(errors.join(', '));
        } else {
            setError(null);
        }

        return validFiles;
    };

    const handleDrop = useCallback((e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        const files = validateFiles(e.dataTransfer.files);
        if (files.length > 0) {
            setSelectedFiles(prev => [...prev, ...files]);
        }
    }, []);

    const handleFileSelect = (e) => {
        const files = validateFiles(e.target.files);
        if (files.length > 0) {
            setSelectedFiles(prev => [...prev, ...files]);
        }
    };

    const removeFile = (index) => {
        setSelectedFiles(prev => prev.filter((_, i) => i !== index));
    };

    const handleUpload = () => {
        if (selectedFiles.length > 0 && onUpload) {
            onUpload(selectedFiles);
            setSelectedFiles([]);
        }
    };

    return (
        <div className="space-y-6">
            {/* 拖拽上传区域 */}
            <div
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                className={`
                    relative group border-2 border-dashed rounded-2xl p-10 text-center transition-all duration-300
                    ${dragActive 
                        ? 'border-brand-orange-500 bg-brand-orange-50/20 scale-[1.01]' 
                        : 'border-slate-200 hover:border-brand-orange-300 hover:bg-slate-50'
                    }
                    ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                `}
            >
                <input
                    type="file"
                    accept=".pdf,application/pdf"
                    multiple
                    onChange={handleFileSelect}
                    disabled={disabled}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                />
                
                <div className={`mx-auto h-20 w-20 rounded-full flex items-center justify-center mb-6 transition-colors shadow-sm ${
                    dragActive ? 'bg-brand-orange-100' : 'bg-slate-50 group-hover:bg-brand-orange-50 border border-slate-100'
                }`}>
                     <Upload className={`h-10 w-10 transition-colors ${
                         dragActive ? 'text-brand-orange-600' : 'text-slate-400 group-hover:text-brand-orange-500'
                     }`} />
                </div>

                <p className="text-xl font-bold text-slate-700 mb-2 group-hover:text-brand-orange-600 transition-colors">
                    {dragActive ? 'Drop PDFs Here' : 'Drag & Drop PDF Documents'}
                </p>
                <p className="text-sm text-slate-500 max-w-sm mx-auto leading-relaxed">
                    Or click to browse your system. We support multiple PDF file uploads simultaneously.
                </p>
                <button className="mt-6 px-6 py-2.5 bg-white border border-slate-200 text-slate-700 font-bold rounded-xl shadow-sm group-hover:shadow group-hover:border-brand-orange-200 group-hover:text-brand-orange-600 transition-all">
                    Browse Files
                </button>
            </div>

            {/* 错误提示 */}
            {error && (
                <div className="flex items-center gap-2 text-error text-sm bg-red-50 p-4 rounded-xl border border-red-100 text-red-600">
                    <AlertCircle size={16} />
                    <span>{error}</span>
                </div>
            )}

            {/* 已选文件列表 */}
            {selectedFiles.length > 0 && (
                <div className="space-y-4 pt-2">
                    <div className="flex items-center justify-between">
                         <h4 className="text-sm font-bold text-slate-700">Selected Files ({selectedFiles.length})</h4>
                         <button 
                            onClick={() => setSelectedFiles([])}
                            className="text-xs text-red-500 hover:text-red-700 font-medium"
                         >
                            Clear All
                         </button>
                    </div>
                    
                    <div className="grid gap-3 max-h-64 overflow-y-auto custom-scrollbar pr-2">
                        {selectedFiles.map((file, index) => (
                            <div
                                key={index}
                                className="flex items-center justify-between bg-white border border-slate-200 p-3 rounded-xl shadow-sm group hover:shadow-md transition-all"
                            >
                                <div className="flex items-center gap-3">
                                    <div className="p-2.5 bg-red-50 text-red-600 rounded-lg">
                                        <FileText size={20} />
                                    </div>
                                    <div>
                                        <p className="text-sm font-bold text-slate-700 truncate max-w-[200px]">
                                            {file.name}
                                        </p>
                                        <p className="text-xs text-slate-500 font-mono">
                                            {(file.size / 1024 / 1024).toFixed(2)} MB
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={() => removeFile(index)}
                                    className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                        ))}
                    </div>
                    <button
                        onClick={handleUpload}
                        disabled={disabled}
                        className="w-full py-4 bg-gradient-to-r from-brand-orange-500 to-brand-orange-600 hover:from-brand-orange-600 hover:to-brand-orange-700 text-white rounded-xl font-bold shadow-lg shadow-brand-orange-200 hover:shadow-xl hover:-translate-y-0.5 transition-all text-sm uppercase tracking-wide disabled:opacity-50 disabled:cursor-not-allowed disabled:transform-none flex items-center justify-center gap-2"
                    >
                        <Upload size={18} />
                        Start Extraction Task
                    </button>
                </div>
            )}
        </div>
    );
};

export default PdfUploader;
