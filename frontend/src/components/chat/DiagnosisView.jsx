import React, { useState, useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import {
    Network, Table, GitBranch, ChevronDown, ChevronUp,
    Maximize2, Minimize2, X, Search, ArrowDown, Clock,
    BarChart3, Zap
} from 'lucide-react';
import MermaidDiagram from './MermaidDiagram';
import Neo4jGraph from './Neo4jGraph';

// ECharts 类别颜色（与 KnowledgeGraph.jsx 一致）
const KG_CATEGORY_COLORS = ['#ef4444', '#f97316', '#4827AF', '#3b82f6', '#14b8a6'];

const EmptyPanelBody = ({ text }) => (
    <div className="px-4 py-4 text-sm text-slate-500 bg-slate-50 border-t border-slate-100">
        {text}
    </div>
);

// ─────────────────────────────────────────────
// Part 1: 知识图谱面板
// ─────────────────────────────────────────────
const KnowledgeGraphPanel = ({ graph, summary, records, sourceQuery }) => {
    const [expanded, setExpanded] = useState(true);
    const [fullscreen, setFullscreen] = useState(false);

    const hasGraph = !!(graph && ((graph.nodes?.length || 0) > 0 || (graph.links?.length || 0) > 0));

    const categories = ((graph && graph.categories) || []).map((c, i) => ({
        ...c,
        itemStyle: { color: KG_CATEGORY_COLORS[i] || '#9ca3af' },
    }));

    const option = {
        animation: false,
        tooltip: {
            trigger: 'item',
            formatter: (params) => {
                if (params.dataType === 'node') {
                    const cat = categories[params.data.category]?.name || '节点';
                    return `<div style="max-width:300px;word-wrap:break-word;">
                        <strong>${cat}</strong><br/>${params.data.fullName || params.data.name}
                    </div>`;
                }
                return params.data.name || '';
            },
        },
        legend: {
            data: categories.map(c => c.name),
            orient: 'horizontal', bottom: 10, left: 'center',
            textStyle: { fontSize: 12, color: '#64748b' },
        },
        series: [{
            type: 'graph', layout: 'force',
            data: (graph && graph.nodes) || [], links: (graph && graph.links) || [], categories,
            roam: false, draggable: true,
            label: { show: true, position: 'right', fontSize: 10, formatter: '{b}' },
            labelLayout: { hideOverlap: true },
            force: { repulsion: 350, gravity: 0.1, edgeLength: [80, 160], layoutAnimation: false },
            lineStyle: { color: 'source', curveness: 0.2, opacity: 0.6 },
            edgeLabel: { show: true, fontSize: 9, formatter: '{c}', color: '#666' },
            emphasis: { focus: 'adjacency', lineStyle: { width: 3 }, label: { fontSize: 12 } },
        }],
    };

    const containerCls = fullscreen
        ? 'fixed inset-0 z-50 bg-white dark:bg-gray-900 p-4'
        : 'border border-slate-200 rounded-xl overflow-hidden shadow-sm';
    const chartH = fullscreen ? 'calc(100vh - 100px)' : (expanded ? '420px' : '0px');

    const extractKeyword = () => {
        if (sourceQuery) {
            const cleaned = sourceQuery.replace(/[怎么办怎么解决怎么处理怎么修如何解决如何处理是什么有哪些][?？]*$/g, '').trim();
            if (cleaned.length >= 2) return cleaned.substring(0, 30);
        }
        if (records && records[0]?.problem) {
            return records[0].problem.substring(0, 20);
        }
        return '';
    };

    return (
        <div className={containerCls}>
            {/* 标题栏 */}
            <div className="flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-red-50 to-orange-50 cursor-pointer"
                onClick={() => !fullscreen && setExpanded(!expanded)}>
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                    <Network size={16} className="text-red-500" />
                    图谱
                    <span className="text-slate-400 font-normal">
                        ({((graph && graph.nodes) || []).length} 节点, {((graph && graph.links) || []).length} 关系)
                    </span>
                </span>
                <div className="flex items-center gap-1">
                    {expanded && (
                        <button onClick={e => { e.stopPropagation(); setFullscreen(!fullscreen); }}
                            className="p-1 hover:bg-white/60 rounded transition-colors">
                            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                        </button>
                    )}
                    {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
                </div>
            </div>
            {/* 图表 */}
            <div className="transition-all duration-300 ease-in-out overflow-hidden" style={{ height: expanded || fullscreen ? 'auto' : '0px' }}>
                {(expanded || fullscreen) && hasGraph && (
                    <>
                        <ReactECharts option={option} style={{ height: chartH, width: '100%' }} opts={{ renderer: 'canvas' }} />
                        {records && records.length > 0 && (
                            <div className="border-t border-slate-100 bg-white p-3">
                                <Neo4jGraph
                                    keyword={extractKeyword()}
                                    records={records}
                                    allowKeywordSearch={false}
                                    defaultExpanded={true}
                                    lightTheme={true}
                                    embedded={true}
                                    showPaths={true}
                                    defaultLimit={20}
                                />
                            </div>
                        )}
                    </>
                )}
                {(expanded || fullscreen) && !hasGraph && (
                    <EmptyPanelBody text="当前问题未检索到可展示的图谱数据。" />
                )}
            </div>
            {/* 摘要 */}
            {expanded && hasGraph && summary && (
                <div className="px-4 py-2 text-xs text-slate-500 bg-slate-50 border-t border-slate-100">
                    {summary}
                </div>
            )}
        </div>
    );
};

// ─────────────────────────────────────────────
// Part 2: 原始记录表格面板
// ─────────────────────────────────────────────
const RecordsPanel = ({ records, summary }) => {
    const [expanded, setExpanded] = useState(true);
    const [sortConfig, setSortConfig] = useState({ key: 'date', direction: 'desc' }); // 默认按日期倒序排

    const sortedRecords = useMemo(() => {
        if (!records) return [];

        return [...records].sort((a, b) => {
            if (sortConfig.key) {
                let aValue = a[sortConfig.key];
                let bValue = b[sortConfig.key];

                // 处理日期字段为空的情况
                if (sortConfig.key === 'date') {
                    aValue = aValue ? new Date(aValue) : new Date(0);
                    bValue = bValue ? new Date(bValue) : new Date(0);
                }

                if (aValue < bValue) {
                    return sortConfig.direction === 'asc' ? -1 : 1;
                }
                if (aValue > bValue) {
                    return sortConfig.direction === 'asc' ? 1 : -1;
                }
            }
            return 0;
        });
    }, [records, sortConfig]);

    const requestSort = (key) => {
        let direction = 'asc';
        if (sortConfig.key === key && sortConfig.direction === 'asc') {
            direction = 'desc';
        }
        setSortConfig({ key, direction });
    };

    const hasRecords = !!sortedRecords.length;

    return (
        <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm">
            {/* 标题栏 */}
            <button onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-blue-50 to-indigo-50 hover:from-blue-100 hover:to-indigo-100 transition-colors">
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                    <Search size={16} className="text-blue-500" />
                    表格
                    <span className="text-blue-500 font-medium">({hasRecords ? sortedRecords.length : 0} 条)</span>
                </span>
                {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
            </button>
            {expanded && (
                <>
                    {/* 摘要 */}
                    {hasRecords && summary && (
                        <div className="px-4 py-2 text-xs text-slate-500 bg-blue-50/50 border-b border-slate-100">
                            {summary}
                        </div>
                    )}
                    {/* 表格 */}
                    {hasRecords ? (
                        <div className="overflow-x-auto">
                            <table className="w-full text-xs">
                                <thead className="bg-slate-50 sticky top-0 z-10">
                                    <tr>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap">#</th>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap">工位</th>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">问题</th>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">原因</th>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap min-w-[150px]">措施</th>
                                        <th
                                            className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap cursor-pointer"
                                            onClick={() => requestSort('date')}
                                        >
                                            日期
                                            {sortConfig.key === 'date' &&
                                                (sortConfig.direction === 'asc' ? (
                                                    <ArrowDown size={12} className="inline ml-1" />
                                                ) : (
                                                    <ArrowUp size={12} className="inline ml-1" />
                                                ))}
                                        </th>
                                        <th className="px-3 py-2.5 text-left font-semibold text-slate-600 whitespace-nowrap">相似度</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sortedRecords.map((r, idx) => {
                                        const sp = r.score_percent ?? (r.score ? Math.round(r.score * 10000) / 100 : null);
                                        const cls = sp >= 80 ? 'text-emerald-600 font-semibold' : (sp >= 60 ? 'text-amber-500 font-medium' : 'text-red-500 font-medium');
                                        return (
                                            <tr key={r.id || idx} className="border-t border-slate-100 hover:bg-blue-50/30 transition-colors">
                                                <td className="px-3 py-2 text-slate-400">{idx + 1}</td>
                                                <td className="px-3 py-2 whitespace-nowrap font-medium text-indigo-600">{r.station || '-'}</td>
                                                <td className="px-3 py-2" title={r.problem}>
                                                    <div className="max-w-[200px] truncate text-slate-700">{r.problem || '-'}</div>
                                                </td>
                                                <td className="px-3 py-2" title={r.cause}>
                                                    <div className="max-w-[200px] truncate text-slate-600">{r.cause || '-'}</div>
                                                </td>
                                                <td className="px-3 py-2" title={r.action}>
                                                    <div className="max-w-[200px] truncate text-emerald-600">{r.action || '-'}</div>
                                                </td>
                                                <td className="px-3 py-2 whitespace-nowrap text-slate-400">{r.date || '-'}</td>
                                                <td className="px-3 py-2 whitespace-nowrap">
                                                    {sp !== null && sp !== undefined ? <span className={cls}>{sp}%</span> : '-'}
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <EmptyPanelBody text="当前问题未检索到可展示的记录数据。" />
                    )}
                </>
            )}
        </div>
    );
};

// ─────────────────────────────────────────────
// Part 3: 排查流程面板
// ─────────────────────────────────────────────
const FlowchartPanel = ({ records, summary, plan, answerText = '', userQuery = '' }) => {
    const [expanded, setExpanded] = useState(true);
    const hasFlowRecords = !!(records && records.length > 0);

    return (
        <div className="border border-slate-200 rounded-xl overflow-hidden shadow-sm">
            {/* 标题栏 */}
            <button onClick={() => setExpanded(!expanded)}
                className="w-full flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-purple-50 to-violet-50 hover:from-purple-100 hover:to-violet-100 transition-colors">
                <span className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                    <GitBranch size={16} className="text-purple-500" />
                    流程图
                    <span className="text-purple-500 font-medium">({hasFlowRecords ? records.length : 0} 步)</span>
                </span>
                {expanded ? <ChevronUp size={16} className="text-slate-400" /> : <ChevronDown size={16} className="text-slate-400" />}
            </button>
            {expanded && (
                <>
                    {/* 摘要 (Markdown 格式) */}
                    {hasFlowRecords && summary && (
                        <div className="px-4 py-3 text-sm text-slate-600 bg-purple-50/50 border-b border-slate-100 whitespace-pre-line leading-relaxed">
                            {summary}
                        </div>
                    )}
                    {/* 优先级卡片列表 */}
                    {hasFlowRecords ? (
                    <div className="p-4 space-y-3">
                        {records.slice(0, 10).map((r, idx) => (
                            <PriorityCard key={r.id || idx} record={r} index={idx} />
                        ))}
                    </div>
                    ) : (
                        <EmptyPanelBody text="当前问题未生成可展示的流程步骤。" />
                    )}
                    {/* 内嵌流程图插件 */}
                    <div className="px-4 pb-4 border-t border-slate-100 bg-slate-50">
                        <MermaidDiagram
                            records={hasFlowRecords ? records : []}
                            answerText={answerText || summary || ''}
                            flowPlan={plan || null}
                            userQuery={userQuery}
                            inline={true}
                        />
                    </div>
                </>
            )}
        </div>
    );
};

// ─────────────────────────────────────────────
// 优先级卡片（单条排查步骤）
// ─────────────────────────────────────────────
const PriorityCard = ({ record, index }) => {
    const r = record;
    const rank = r.priority_rank || (index + 1);
    const total = r.priority_total ?? 0;

    // 四维度条形图数据
    const dimensions = [
        { key: 'frequency', label: '频率', value: r.priority_frequency ?? 0, color: '#ef4444', icon: BarChart3 },
        { key: 'similarity', label: '相似度', value: r.priority_similarity ?? 0, color: '#f97316', icon: Search },
        { key: 'recency', label: '近期度', value: r.priority_recency ?? 0, color: '#3b82f6', icon: Clock },
        { key: 'efficiency', label: '效率', value: r.priority_efficiency ?? 0, color: '#10b981', icon: Zap },
    ];

    const rankColors = ['bg-red-500', 'bg-orange-500', 'bg-amber-500', 'bg-blue-500', 'bg-slate-400'];
    const rankBg = rankColors[Math.min(rank - 1, rankColors.length - 1)];

    return (
        <div className="bg-white border border-slate-200 rounded-lg p-4 hover:shadow-md transition-shadow">
            <div className="flex items-start gap-3">
                {/* 排名徽章 */}
                <div className={`w-8 h-8 rounded-full ${rankBg} text-white flex items-center justify-center font-bold text-sm flex-shrink-0`}>
                    {rank}
                </div>
                {/* 内容 */}
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="text-sm font-semibold text-slate-700 truncate">
                            {r.cause || '原因未知'}
                        </span>
                        <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full whitespace-nowrap">
                            综合 {(total * 100).toFixed(0)}分
                        </span>
                        {r.occurrence_count > 1 && (
                            <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded-full whitespace-nowrap">
                                出现 {r.occurrence_count} 次
                            </span>
                        )}
                    </div>
                    {/* 问题描述 */}
                    <p className="text-xs text-slate-500 mb-2 line-clamp-2">{r.problem || '-'}</p>
                    {/* 措施 */}
                    {r.action && (
                        <p className="text-xs text-emerald-600 mb-2 line-clamp-2">
                            <span className="font-medium">对策：</span>{r.action}
                        </p>
                    )}
                    {/* 四维度条形图 */}
                    <div className="grid grid-cols-4 gap-2">
                        {dimensions.map(d => (
                            <div key={d.key} className="flex flex-col">
                                <span className="text-[10px] text-slate-400 mb-0.5">{d.label}</span>
                                <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                                    <div
                                        className="h-full rounded-full transition-all duration-500"
                                        style={{ width: `${d.value * 100}%`, backgroundColor: d.color }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                    {/* 元信息 */}
                    <div className="flex items-center gap-3 mt-2 text-[10px] text-slate-400">
                        <span>工位: {r.station || '-'}</span>
                        <span>日期: {r.date || '-'}</span>
                        <span>相似度: {r.score_percent ?? '-'}%</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

// ─────────────────────────────────────────────
// 主组件：三段式诊断视图
// ─────────────────────────────────────────────
const DiagnosisView = ({ diagnosisData, answerText = '', userQuery = '' }) => {
    if (!diagnosisData) return null;

    const { kg, records, flowchart } = diagnosisData;
    const tableRecords = records?.records || [];
    const flowRecords = flowchart?.records || tableRecords;

    return (
        <div className="space-y-4 mt-3 w-full max-w-8xl mx-auto min-w-0">
            {/* Part 1: 知识图谱 */}
            <KnowledgeGraphPanel
                graph={kg?.graph}
                summary={kg?.summary}
                records={tableRecords}
                sourceQuery={userQuery}
            />
            {/* Part 2: 原始记录 */}
            <RecordsPanel
                records={tableRecords}
                summary={records?.summary}
            />
            {/* Part 3: 排查流程 */}
            <FlowchartPanel
                records={flowRecords}
                summary={flowchart?.summary}
                plan={flowchart?.plan}
                answerText={answerText}
                userQuery={userQuery}
            />
        </div>
    );
};

export default DiagnosisView;
