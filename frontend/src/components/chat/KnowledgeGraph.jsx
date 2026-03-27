import React, { useState, useMemo } from 'react';
import ReactECharts from 'echarts-for-react';
import { Network, Maximize2, Minimize2, X } from 'lucide-react';

// 节点颜色：保持与 `Neo4jGraph` 组件一致
// 0: Problem, 1: Cause, 2: Solution, 3: Area, 4: Equipment, 5: Component
const KG_CATEGORY_COLORS = ['#ef4444', '#f97316', '#4827AF', '#3b82f6', '#14b8a6', '#10b981'];

/**
 * 从检索记录生成知识图谱数据（匹配Neo4j数据结构）
 */
const generateGraphData = (records) => {
    if (!records || records.length === 0) return { nodes: [], links: [] };
    
    const nodes = [];
    const links = [];
    const nodeMap = new Map();
    
    // 添加节点的辅助函数（确保节点带有 itemStyle.color，避免被默认灰色覆盖）
    const addNode = (id, name, category, size = 30, fullData = {}) => {
        if (!nodeMap.has(id)) {
            nodeMap.set(id, true);
            // 从共享常量读取颜色，保证与导航栏一致
            const color = KG_CATEGORY_COLORS[category] || '#9ca3af';

            nodes.push({
                id,
                name: name.length > 20 ? name.substring(0, 20) + '...' : name,
                fullName: name,
                category,
                symbolSize: size,
                value: size,
                itemStyle: { color },
                ...fullData
            });
        }
    };
    
    // 添加边的辅助函数
    const addLink = (source, target, relation) => {
        links.push({
            source,
            target,
            name: relation,
            lineStyle: { width: 1.5 }
        });
    };
    
    // 处理每条记录 - 匹配Neo4j的Problem/Cause/Solution结构
    records.forEach((record, idx) => {
        // 从record中提取相关信息
        const problem = record.problem || record.description || record.phenomenon || '未知问题';
        const cause = record.cause || record.root_cause || '';
        const solution = record.action || record.solution || record.containment_action || '';
        
        // 只有当有实际内容时才创建节点
        if (problem && problem !== '-' && problem !== '未知问题') {
            const problemId = `problem_${idx}`;
            addNode(problemId, problem, 0, 40, { type: 'Problem' });
            
            // 添加原因节点 (如果存在)
            if (cause && cause !== '-' && cause.trim() !== '') {
                const causeId = `cause_${idx}`;
                addNode(causeId, cause, 1, 35, { type: 'Cause' });
                addLink(problemId, causeId, 'CAUSED_BY');
            }
            
            // 添加解决方案节点 (如果存在)
            if (solution && solution !== '-' && solution.trim() !== '') {
                const solutionId = `solution_${idx}`;
                addNode(solutionId, solution, 2, 35, { type: 'Solution' });
                addLink(problemId, solutionId, 'SOLVED_BY');
            }
            
            // 添加设备节点（Version2 用 equipment 替代 station）
            const station = record.station || record.equipment || record.station_name || '';
            if (station && String(station).trim() !== '' && String(station) !== '未知工位') {
                const equipId = `equipment_${String(station).replace(/\s+/g, '_')}`;
                addNode(equipId, String(station), 4, 30, { type: 'Equipment' });
                addLink(equipId, problemId, 'HAS_FAULT');

                // 如果存在区域信息
                const area = record.area || '';
                if (area && String(area).trim() !== '') {
                    const areaId = `area_${String(area).replace(/\s+/g, '_')}`;
                    addNode(areaId, String(area), 3, 30, { type: 'Area' });
                    addLink(areaId, equipId, 'INCLUDE');
                }
            }        }
    });
    
    return { nodes, links };
};

const KnowledgeGraph = ({ records, title = "知识图谱", defaultExpanded = false }) => {
    const [expanded, setExpanded] = useState(defaultExpanded);
    const [fullscreen, setFullscreen] = useState(false);
    
    const graphData = useMemo(() => generateGraphData(records), [records]);
    
    if (!records || records.length === 0) return null;
    
    const categories = [
        { name: 'Problem', itemStyle: { color: KG_CATEGORY_COLORS[0] } },
        { name: 'Cause', itemStyle: { color: KG_CATEGORY_COLORS[1] } },
        { name: 'Solution', itemStyle: { color: KG_CATEGORY_COLORS[2] } },
        { name: 'Area', itemStyle: { color: KG_CATEGORY_COLORS[3] } },
        { name: 'Equipment', itemStyle: { color: KG_CATEGORY_COLORS[4] } },
        { name: 'Component', itemStyle: { color: KG_CATEGORY_COLORS[5] } }
    ];

    const option = {
        animation: false,
        tooltip: {
            trigger: 'item',
            formatter: (params) => {
                if (params.dataType === 'node') {
                    return `<div style="max-width: 300px; word-wrap: break-word;">
                        <strong>${categories[params.data.category]?.name || '节点'}</strong><br/>
                        ${params.data.fullName || params.data.name}
                    </div>`;
                }
                return params.data.name || '';
            }
        },
        legend: {
            data: categories.map(c => c.name),
            orient: 'horizontal',
            bottom: 10,
            left: 'center',
            textStyle: { fontSize: 12, color: '#fff' },
            itemGap: 20,
            symbolSize: [10, 10]
        },
        series: [{
            type: 'graph',
            layout: 'force',
            data: graphData.nodes,
            links: graphData.links,
            categories: categories,
            roam: true,
            draggable: true,
            label: {
                show: true,
                position: 'right',
                fontSize: 10,
                formatter: '{b}'
            },
            labelLayout: {
                hideOverlap: true
            },
            force: {
                repulsion: 300,
                gravity: 0.1,
                edgeLength: [80, 150],
                layoutAnimation: false
            },
            lineStyle: {
                color: 'source',
                curveness: 0.2,
                opacity: 0.6
            },
            edgeLabel: {
                show: true,
                fontSize: 9,
                formatter: '{c}',
                color: '#666'
            },
            emphasis: {
                focus: 'adjacency',
                lineStyle: { width: 3 },
                label: { fontSize: 12 }
            }
        }]
    };
    
    const containerClass = fullscreen 
        ? 'fixed inset-0 z-50 bg-white dark:bg-gray-900 p-4'
        : 'mt-3 border border-border rounded-lg overflow-hidden';
    
    const chartHeight = fullscreen ? 'calc(100vh - 100px)' : (expanded ? '400px' : '0px');
    
    return (
        <div className={containerClass}>
            <div className="flex items-center justify-between px-3 py-2 bg-muted/50">
                <button 
                    onClick={() => !fullscreen && setExpanded(!expanded)}
                    className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors"
                >
                    <Network size={16} />
                    {title} ({graphData.nodes.length} 节点, {graphData.links.length} 关系)
                </button>
                <div className="flex items-center gap-1">
                    {expanded && (
                        <button
                            onClick={() => setFullscreen(!fullscreen)}
                            className="p-1 hover:bg-muted rounded transition-colors"
                            title={fullscreen ? '退出全屏' : '全屏'}
                        >
                            {fullscreen ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
                        </button>
                    )}
                    {fullscreen && (
                        <button
                            onClick={() => { setFullscreen(false); setExpanded(false); }}
                            className="p-1 hover:bg-muted rounded transition-colors"
                            title="关闭"
                        >
                            <X size={16} />
                        </button>
                    )}
                </div>
            </div>
            
            <div
                className="overflow-hidden"
                style={{ height: expanded || fullscreen ? 'auto' : '0px' }}
            >
                {(expanded || fullscreen) && (
                    <ReactECharts 
                        option={option} 
                        style={{ height: fullscreen ? 'calc(100vh - 100px)' : '400px', width: '100%' }}
                        opts={{ renderer: 'canvas' }}
                    />
                )}
            </div>
            
            {!expanded && !fullscreen && (
                <button 
                    onClick={() => setExpanded(true)}
                    className="w-full py-2 text-xs text-muted-foreground hover:text-foreground hover:bg-muted/30 transition-colors"
                >
                    点击展开知识图谱
                </button>
            )}
        </div>
    );
};

export default KnowledgeGraph;
