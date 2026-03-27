import React from 'react';
import { Trash2, CheckCircle, XCircle, Copy, Check, File } from 'lucide-react';

const OcrResultsTable = ({ results, onDelete, compact = false }) => {
    const [copiedId, setCopiedId] = React.useState(null);

    const handleCopy = async (text, id) => {
        try {
            await navigator.clipboard.writeText(text);
            setCopiedId(id);
            setTimeout(() => setCopiedId(null), 2000);
        } catch (err) {
            console.error('Copy failed:', err);
        }
    };

    if (results.length === 0) {
        return (
            <div className="text-center text-slate-400 py-12">
                No data available
            </div>
        );
    }

    return (
        <div className="overflow-x-auto rounded-xl border border-slate-200">
            <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 text-slate-500 uppercase tracking-wider text-xs font-semibold">
                    <tr>
                        <th className="py-4 px-6 border-b border-slate-200">Filename</th>
                        <th className="py-4 px-6 border-b border-slate-200">Package ID</th>
                        <th className="py-4 px-6 border-b border-slate-200">UCH Codes</th>
                        {!compact && (
                            <>
                                <th className="py-4 px-6 border-b border-slate-200">Status</th>
                                <th className="py-4 px-6 border-b border-slate-200">Date</th>
                            </>
                        )}
                        <th className="py-4 px-6 border-b border-slate-200 text-right">Actions</th>
                    </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                    {results.map((result) => (
                        <tr 
                            key={result.id} 
                            className="bg-white hover:bg-slate-50 transition-colors group"
                        >
                            {/* 文件名 */}
                            <td className="py-4 px-6">
                                <div className="flex items-center gap-3">
                                    <div className="p-2 bg-slate-100 rounded text-slate-500">
                                        <File size={16} />
                                    </div>
                                    <span className="font-bold text-slate-700 truncate max-w-[180px] block" title={result.filename}>
                                        {result.filename}
                                    </span>
                                </div>
                            </td>
                            
                            {/* Package ID */}
                            <td className="py-4 px-6">
                                {result.package_id ? (
                                    <div className="flex items-center gap-2 group/copy">
                                        <div className="px-2.5 py-1.5 bg-brand-orange-50 text-brand-orange-700 border border-brand-orange-100 rounded-lg text-xs font-mono font-semibold">
                                            {result.package_id}
                                        </div>
                                        <button
                                            onClick={() => handleCopy(result.package_id, `pkg-${result.id}`)}
                                            className="p-1.5 text-slate-300 hover:text-brand-orange-500 hover:bg-brand-orange-50 rounded-md transition-all opacity-0 group-hover/copy:opacity-100"
                                            title="Copy Package ID"
                                        >
                                            {copiedId === `pkg-${result.id}` ? (
                                                <Check size={14} className="text-emerald-500" />
                                            ) : (
                                                <Copy size={14} />
                                            )}
                                        </button>
                                    </div>
                                ) : (
                                    <span className="text-slate-300 font-mono text-xs">N/A</span>
                                )}
                            </td>
                            
                            {/* UCH 编码 */}
                            <td className="py-4 px-6">
                                {result.uch_codes && result.uch_codes.length > 0 ? (
                                    <div className="flex flex-wrap gap-2">
                                        {result.uch_codes.map((code, idx) => (
                                            <div key={idx} className="flex items-center gap-1 group/uch">
                                                <div className="px-2.5 py-1.5 bg-brand-purple-50 text-brand-purple-700 border border-brand-purple-100 rounded-lg text-xs font-mono font-semibold">
                                                    {code}
                                                </div>
                                                <button
                                                    onClick={() => handleCopy(code, `uch-${result.id}-${idx}`)}
                                                    className="p-1 text-slate-300 hover:text-brand-purple-500 hover:bg-brand-purple-50 rounded-md transition-all opacity-0 group-hover/uch:opacity-100"
                                                    title="Copy UCH Code"
                                                >
                                                    {copiedId === `uch-${result.id}-${idx}` ? (
                                                        <Check size={12} className="text-emerald-500" />
                                                    ) : (
                                                        <Copy size={12} />
                                                    )}
                                                </button>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <span className="text-slate-300 font-mono text-xs">No codes found</span>
                                )}
                            </td>
                            
                            {!compact && (
                                <>
                                    {/* 状态 */}
                                    <td className="py-4 px-6">
                                        {result.status === '成功' || result.status === 'SUCCESS' ? (
                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-600 text-xs font-bold border border-emerald-100">
                                                <CheckCircle size={12} className="fill-current" />
                                                Success
                                            </span>
                                        ) : (
                                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-50 text-red-600 text-xs font-bold border border-red-100" title={result.status}>
                                                <XCircle size={12} className="fill-current" />
                                                Failed
                                            </span>
                                        )}
                                    </td>
                                    
                                    {/* 时间 */}
                                    <td className="py-4 px-6 text-slate-400 text-xs font-medium">
                                        {result.created_at}
                                    </td>
                                </>
                            )}
                            
                            {/* 操作 */}
                            <td className="py-4 px-6 text-right">
                                <button
                                    onClick={() => onDelete(result)}
                                    className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-xl transition-colors"
                                    title="Delete Record"
                                >
                                    <Trash2 size={16} />
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

export default OcrResultsTable;
