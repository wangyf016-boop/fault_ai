import React, { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';
import { X, GitBranch, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

// 初始化 mermaid 配置
mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'loose',
    flowchart: {
        useMaxWidth: false,
        htmlLabels: true,
        curve: 'basis',
        padding: 55,
        nodeSpacing: 100,
        rankSpacing: 120,
        diagramPadding: 40,
    },
});


/**
 * 从用户提问中提取“故障现象”短语。
 * 例："编码器报警怎么办" -> "编码器报警"
 */
const extractPhenomenonFromQuery = (queryText) => {
    const q = String(queryText || '').replace(/\r|\n/g, ' ').trim();
    if (!q) return '';

    let t = q
        .replace(/^[\s，。！？,.!?]*(请问|请教|帮我|麻烦|想问下|我想问下|我想问|咨询一下|咨询)\s*/i, '')
        .replace(/^(关于|针对)\s*/i, '');

    // 去掉常见询问尾巴，保留现象主体
    t = t.replace(/(怎么办|咋办|怎么处理|如何处理|怎么解决|如何解决|怎么排查|如何排查|怎么修|如何修|是什么原因|原因是什么|为什么|为啥|怎么回事|行吗|可以吗|呢|吗|\?|？)+\s*$/i, '');

    // 去掉末尾常见语气词
    t = t.replace(/(一下|下|呀|啊|呗)\s*$/i, '');

    t = t.replace(/[，。！？,.!?]+$/g, '').trim();
    if (t.length < 2) return '';
    return t;
};

const normalizeStepText = (text) => {
    let t = String(text || '').replace(/\r|\n/g, ' ').trim();
    if (!t) return '';

    t = t
        .replace(/^[\s\-•·*]+/, '')
        .replace(/^(?:第?\s*\d+\s*步[：:.、\-\s]*|步骤\s*\d+[：:.、\-\s]*|\d+\s*[.、)\-:：]\s*)+/i, '')
        .replace(/\s+/g, ' ')
        .trim();

    return t;
};

const detectQueryLanguage = (text = '') => {
    const t = String(text || '');
    if (/[\u4e00-\u9fff]/.test(t)) return 'zh';
    return 'en';
};

const getDiagramLabels = (queryText = '') => {
    const lang = detectQueryLanguage(queryText);
    if (lang === 'zh') {
        return {
            problem: '故障现象',
            likelyCause: '可能原因',
            step: '步骤',
            action: '处理动作',
            verification: '验证',
            causeBranchDecision: '原因分支判断',
            cause: '原因',
            branch: '分支',
            handle: '处理',
            branchFallbackStep: '执行对应处理',
            fallbackNote: '暂未生成结构化流程，请重试',
        };
    }
    return {
        problem: 'Problem',
        likelyCause: 'Likely Cause',
        step: 'Step',
        action: 'Action',
        verification: 'Verification',
        causeBranchDecision: 'Cause Branch Decision',
        cause: 'Cause',
        branch: 'Branch',
        handle: 'Handle',
        branchFallbackStep: 'Execute corresponding handling',
        fallbackNote: 'Structured flow not generated yet, please retry',
    };
};


const generateFlowPlanDrivenFlow = (records, flowPlan, truncate, formatLabel, queryText = '', labels) => {
    const record = records?.[0] || {};
    const queryPhenomenon = extractPhenomenonFromQuery(queryText);
    const spec = flowPlan?.diagram_spec && typeof flowPlan.diagram_spec === 'object' ? flowPlan.diagram_spec : null;
    const problem = queryPhenomenon || String(spec?.problem || '').trim() || record.problem || 'Current issue';
    const likelyCause = String(spec?.likely_cause || flowPlan?.likely_cause || '').trim();

    const rawSteps = Array.isArray(spec?.steps)
        ? spec.steps.slice(0, 6)
        : (Array.isArray(flowPlan?.steps) ? flowPlan.steps.slice(0, 6) : []);
    // 兼容新旧两种后端格式
    const steps = rawSteps.map((item) => {
        if (typeof item === 'string') {
            return { check: normalizeStepText(item), yesAction: '', noAction: '' };
        }
        // DSL 格式：check / action
        if (item?.action !== undefined) {
            return {
                check: normalizeStepText(item.check || ''),
                yesAction: normalizeStepText(item.action || ''),
                noAction: '',
            };
        }
        // 新格式：check / yes_action / no_action
        if (item?.check) {
            return {
                check: normalizeStepText(item.check),
                yesAction: normalizeStepText(item.yes_action || item.yesAction || ''),
                noAction: normalizeStepText(item.no_action || item.noAction || ''),
            };
        }
        // 旧格式：title / branches
        const title = String(item?.title || '').trim();
        const branches = Array.isArray(item?.branches)
            ? item.branches.map((b) => String(b || '').trim()).filter(Boolean)
            : [];
        return {
            check: normalizeStepText(title),
            yesAction: normalizeStepText(branches[0] || ''),
            noAction: '',
        };
    }).filter((s) => s.check);

    const verify = String(spec?.verify || flowPlan?.verify || 'Retest passed continuously after handling').trim();

    // 融合分支模式（后端增强字段）
    const rawBranches = Array.isArray(spec?.branches)
        ? spec.branches
        : (Array.isArray(flowPlan?.cause_branches) ? flowPlan.cause_branches : []);

    const causeBranches = rawBranches
        .map((b) => ({
            cause: String(b?.cause || '').trim(),
            steps: (Array.isArray(b?.steps) ? b.steps : [])
                .map((s) => normalizeStepText(s))
                .filter(Boolean)
                .slice(0, 3),
            confidence: Number(b?.confidence || 0),
        }))
        .filter((b) => b.cause || b.steps.length > 0)
        .slice(0, 4);

    const modeToken = String(spec?.mode || flowPlan?.branch_mode || '').trim().toLowerCase();
    const byCauseHints = new Set(['by_cause', 'bycause', 'branch', 'branches', 'cause', 'multi_branch']);
    const branchMode = (causeBranches.length > 0 || byCauseHints.has(modeToken)) ? 'by_cause' : 'single';

    let code = 'flowchart TD\n';
    // 故障现象节点
    code += `    P["${labels.problem}:<br/>${formatLabel(truncate(problem, 20, 3))}"]\n`;

    // 可能原因节点
    if (likelyCause) {
        code += `    LC["${labels.likelyCause}:<br/>${formatLabel(truncate(likelyCause, 20, 3))}"]\n`;
        code += '    P --> LC\n';
    }

    const firstLink = likelyCause ? 'LC' : 'P';

    // 按原因分支：融合失败或分歧较大时，从原因层开始分支
    if (branchMode === 'by_cause' && causeBranches.length > 0) {
        code += `    D{"${labels.causeBranchDecision}"}\n`;
        code += `    ${firstLink} --> D\n`;

        causeBranches.forEach((b, i) => {
            const cid = `C${i + 1}`;
            const cLabel = b.cause || `Cause ${i + 1}`;
            code += `    ${cid}["${labels.cause} ${i + 1}:<br/>${formatLabel(truncate(cLabel, 18, 3))}"]\n`;
            code += `    D -->|${labels.branch} ${i + 1}| ${cid}\n`;

            const branchSteps = (b.steps.length > 0 ? b.steps : [labels.branchFallbackStep]).map((s) => normalizeStepText(s)).filter(Boolean);
            let prev = cid;
            branchSteps.forEach((st, j) => {
                const sid = `B${i + 1}S${j + 1}`;
                code += `    ${sid}["${labels.step} ${j + 1}:<br/>${formatLabel(truncate(st, 18, 3))}"]\n`;
                code += j === 0
                    ? `    ${prev} -->|${labels.handle}| ${sid}\n`
                    : `    ${prev} --> ${sid}\n`;
                prev = sid;
            });
            code += `    ${prev} --> V\n`;
        });

        code += `    V["${labels.verification}:<br/>${formatLabel(truncate(verify, 20, 3))}"]\n`;

        code += '\n    style P fill:#fee2e2,stroke:#ef4444,stroke-width:2px\n';
        if (likelyCause) code += '    style LC fill:#fef3c7,stroke:#f59e0b,stroke-width:2px\n';
        code += '    style D fill:#e0e7ff,stroke:#6366f1,stroke-width:2px\n';
        causeBranches.forEach((b, i) => {
            code += `    style C${i + 1} fill:#fef3c7,stroke:#f59e0b,stroke-width:2px\n`;
            const branchSteps = b.steps.length > 0 ? b.steps : ['Execute corresponding handling'];
            branchSteps.forEach((_, j) => {
                code += `    style B${i + 1}S${j + 1} fill:#dbeafe,stroke:#3b82f6,stroke-width:2px\n`;
            });
        });
        code += '    style V fill:#d1fae5,stroke:#10b981,stroke-width:2px\n';
        return code;
    }

    if (steps.length > 0) {
        let prev = firstLink;
        steps.forEach((s, i) => {
            const sid = `S${i + 1}`;

            // Main step node in linear flow.
            code += `    ${sid}["${labels.step} ${i + 1}:<br/>${formatLabel(truncate(s.check, 20, 3))}"]\n`;

            // Link from previous node to current step.
            code += `    ${prev} --> ${sid}\n`;
            prev = sid;

            // Optional action node after each step.
            const actionText = normalizeStepText(s.yesAction || s.noAction || '');
            if (actionText) {
                const aid = `A${i + 1}`;
                code += `    ${aid}["${labels.action}:<br/>${formatLabel(truncate(actionText, 16, 3))}"]\n`;
                code += `    ${prev} --> ${aid}\n`;
                prev = aid;
            }
        });
        code += `    ${prev} --> V\n`;
    } else {
        code += `    ${firstLink} --> V\n`;
    }

    // 验证节点
    code += `    V["${labels.verification}:<br/>${formatLabel(truncate(verify, 20, 3))}"]\n`;

    // 样式
    code += '\n    style P fill:#fee2e2,stroke:#ef4444,stroke-width:2px\n';
    if (likelyCause) code += '    style LC fill:#fef3c7,stroke:#f59e0b,stroke-width:2px\n';
    steps.forEach((s, i) => {
        code += `    style S${i + 1} fill:#dbeafe,stroke:#3b82f6,stroke-width:2px\n`;
        if (normalizeStepText(s.yesAction || s.noAction || '')) {
            code += `    style A${i + 1} fill:#fef3c7,stroke:#f59e0b,stroke-width:1.5px\n`;
        }
    });
    code += '    style V fill:#d1fae5,stroke:#10b981,stroke-width:2px\n';
    return code;
};

/**
 * 从结构化 flowPlan 生成 Mermaid 流程图（仅保留新逻辑）
 */
const generateMermaidCode = (records, flowPlan = null, userQuery = '') => {
    const labels = getDiagramLabels(userQuery);
    // 清理节点文案中的 Markdown/噪声符号
    const sanitizeNodeText = (text) => {
        return String(text || '')
            .replace(/```[\s\S]*?```/g, ' ')
            .replace(/`([^`]+)`/g, '$1')
            .replace(/\*\*([^*]+)\*\*/g, '$1')
            .replace(/\*([^*]+)\*/g, '$1')
            .replace(/__([^_]+)__/g, '$1')
            .replace(/_([^_]+)_/g, '$1')
            .replace(/[•·]/g, ' ')
            .replace(/^\s*[-*]\s+/gm, '')
            .replace(/\s*\*+\s*/g, ' ')
            .replace(/[\n\r]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    };

    const truncate = (text, maxLen = 50, maxLines = 5) => {
        if (!text) return '';
        const cleaned = sanitizeNodeText(text);
        if (cleaned.length <= maxLen) return cleaned;

        let lines = [];
        let current = '';
        for (let i = 0; i < cleaned.length; i++) {
            current += cleaned[i];
            if (current.length >= maxLen && (i < cleaned.length - 1)) {
                const lastPunc = current.lastIndexOf('，') > current.lastIndexOf('。')
                    ? current.lastIndexOf('，')
                    : current.lastIndexOf('。');
                const lastComma = current.lastIndexOf(',');
                const lastSpace = current.lastIndexOf(' ');
                const splitPos = Math.max(lastPunc, lastComma, lastSpace);

                if (splitPos > current.length * 0.6) {
                    lines.push(current.substring(0, splitPos + 1).trim());
                    current = current.substring(splitPos + 1).trim();
                } else {
                    lines.push(current.substring(0, maxLen).trim());
                    current = current.substring(maxLen).trim();
                }

                if (lines.length >= maxLines) {
                    lines[lines.length - 1] = lines[lines.length - 1].replace(/\s*$/, '') + '...';
                    current = '';
                    break;
                }
            }
        }
        if (current) lines.push(current);
        return lines.slice(0, maxLines).join('<br/>');
    };

    const formatLabel = (text) => {
        return text
            .replace(/"/g, "'")
            .replace(/[\[\]()]/g, ' ')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/&lt;br\/&gt;/g, '<br/>');
    };

    if (flowPlan && (
        flowPlan.likely_cause ||
        (Array.isArray(flowPlan.steps) && flowPlan.steps.length > 0) ||
        flowPlan.verify ||
        (flowPlan.diagram_spec && typeof flowPlan.diagram_spec === 'object')
    )) {
        return generateFlowPlanDrivenFlow(records, flowPlan, truncate, formatLabel, userQuery, labels);
    }

    const problem = extractPhenomenonFromQuery(userQuery) || records?.[0]?.problem || 'Current issue';
    return `flowchart TD
    P["${labels.problem}:<br/>${formatLabel(truncate(problem, 20, 3))}"]
    T["Note:<br/>${labels.fallbackNote}"]
    P --> T

    style P fill:#fee2e2,stroke:#ef4444,stroke-width:2px
    style T fill:#dbeafe,stroke:#3b82f6,stroke-width:2px`;
};

/**
 * Mermaid 流程图组件
 */
const MermaidDiagram = ({ records, flowPlan = null, userQuery = '', onClose, inline = false, inlineHeight = null }) => {
    const containerRef = useRef(null);
    const modalRef = useRef(null);
    const scrollAreaRef = useRef(null);
    const [scale, setScale] = useState(1);
    const [isZoomed, setIsZoomed] = useState(false);
    const prevScaleRef = useRef(1);
    const initialScaleRef = useRef(1);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const prevModalStyleRef = useRef(null);
    const [error, setError] = useState(null);
    const [mermaidCode, setMermaidCode] = useState('');
    const renderSeqRef = useRef(0);
    const adjustTimeoutRef = useRef(null);
    
    // 图表平移（拖拽）状态
    const [pan, setPan] = useState({ x: 0, y: 0 });
    const isPanningRef = useRef(false);
    const panStartRef = useRef({ x: 0, y: 0 });
    const panOffsetRef = useRef({ x: 0, y: 0 });
    
    // 防止拖拽/调整大小结束后立即触发关闭
    const blockCloseUntilRef = useRef(0);

    // 弹窗模式下禁止背景滚动
    useEffect(() => {
        if (inline) return;
        const originalStyle = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => {
            document.body.style.overflow = originalStyle;
        };
    }, [inline]);

    // 在流程图区域捕获 wheel 事件，防止滚动冒泡到页面导致页面滚动
    useEffect(() => {
        const sc = scrollAreaRef.current;
        if (!sc) return;

        const onWheel = (e) => {
            try {
                if (e.defaultPrevented) return;

                // Ctrl + wheel -> 缩放图表
                if (e.ctrlKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    // 使用更大的缩放步长，允许更高的最大缩放
                    const zoomAmount = e.deltaY < 0 ? 0.2 : -0.2;
                    setScale(prev => {
                        const next = Math.min(8, Math.max(0.3, +(prev + zoomAmount).toFixed(2)));
                        return next;
                    });
                    return;
                }

                const delta = e.deltaY;
                const canScrollUp = sc.scrollTop > 0;
                const canScrollDown = sc.scrollTop + sc.clientHeight < sc.scrollHeight;

                if ((delta < 0 && canScrollUp) || (delta > 0 && canScrollDown)) {
                    // 在容器内滚动
                    sc.scrollTop += delta;
                    e.preventDefault();
                    e.stopPropagation();
                } else {
                    // 到达边界时也阻止冒泡，避免触发页面滚动
                    e.preventDefault();
                    e.stopPropagation();
                }
            } catch (err) {
                try { e.preventDefault(); e.stopPropagation(); } catch (e2) {}
            }
        };

        sc.addEventListener('wheel', onWheel, { passive: false });
        return () => sc.removeEventListener('wheel', onWheel);
    }, []);

    useEffect(() => {
        let disposed = false;
        const renderSeq = ++renderSeqRef.current;
        if (adjustTimeoutRef.current) {
            clearTimeout(adjustTimeoutRef.current);
            adjustTimeoutRef.current = null;
        }

        const renderDiagram = async () => {
            if (!containerRef.current) return;
            
            console.log('[MermaidDiagram] render with flowPlan:', flowPlan ? JSON.stringify(flowPlan).substring(0, 200) : 'null');

            let code;
            try {
                code = generateMermaidCode(records, flowPlan, userQuery);
            } catch (genErr) {
                console.error('[MermaidDiagram] code gen error, fallback to records:', genErr);
                code = generateMermaidCode(records, null, userQuery);
            }

            try {
                setMermaidCode(code);
                
                // 清空容器
                containerRef.current.innerHTML = '';
                
                // 生成唯一ID
                const id = `mermaid-${renderSeq}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
                
                // 渲染 Mermaid 图表
                const { svg } = await mermaid.render(id, code);
                if (disposed || renderSeq !== renderSeqRef.current || !containerRef.current) return;
                containerRef.current.innerHTML = svg;

                // =====================================================
                // 核心修复：节点框自适应文字实际尺寸（宽 + 高）
                // 方案：用离屏 DOM 元素测量文字真实宽高（完全绕开
                // foreignObject 内部布局约束问题），再扩展 rect + fo。
                // =====================================================

                // 1) 等待字体加载完毕——这是文字溢出框的主要原因：
                //    字体未就绪时用 fallback 字体测量宽度偏小，节点框不够大
                if (document.fonts?.ready) {
                    await document.fonts.ready;
                    if (disposed || renderSeq !== renderSeqRef.current || !containerRef.current) return;
                }
                // 2) 等待浏览器完成布局（rAF + 小延时双保险）
                await new Promise(r => requestAnimationFrame(() => setTimeout(r, 60)));
                if (disposed || renderSeq !== renderSeqRef.current || !containerRef.current) return;

                // 先设置 foreignObject / nodeLabel 的 flex 居中样式，
                // 确保后续测量时文字在 fo 里已按最终样式排列
                containerRef.current.querySelectorAll('foreignObject').forEach((fo) => {
                    fo.style.overflow = 'visible';
                });
                containerRef.current.querySelectorAll('foreignObject > div, foreignObject > body').forEach((el) => {
                    el.style.width = '100%';
                    el.style.height = '100%';
                    el.style.display = 'flex';
                    el.style.alignItems = 'center';
                    el.style.justifyContent = 'center';
                    el.style.textAlign = 'center';
                });
                containerRef.current.querySelectorAll('.nodeLabel, .nodeLabel p').forEach((el) => {
                    el.style.textAlign = 'center';
                    el.style.lineHeight = '1.4';
                    el.style.wordBreak = 'break-word';
                    el.style.overflowWrap = 'break-word';
                    el.style.maxWidth = '100%';
                });

                // 强制触发一次同步回流，确保上面的样式已生效
                void containerRef.current.offsetHeight;

                /**
                 * 测量并扩展所有节点框，使文字完全包含在 rect 内
                 */
                const adjustNodeBoxes = () => {
                    const svgEl2 = containerRef.current?.querySelector('svg');
                    if (!svgEl2) return;

                    // 创建离屏测量元素，复制 Mermaid 节点的字体样式
                    const measurer = document.createElement('div');
                    measurer.style.cssText = 'position:fixed;left:-9999px;top:-9999px;visibility:hidden;pointer-events:none;white-space:nowrap;';
                    document.body.appendChild(measurer);

                    // 从真实 nodeLabel 复制字体样式
                    const sampleLabel = containerRef.current.querySelector('.nodeLabel');
                    if (sampleLabel) {
                        const cs = getComputedStyle(sampleLabel);
                        measurer.style.fontFamily = cs.fontFamily;
                        measurer.style.fontSize = cs.fontSize;
                        measurer.style.fontWeight = cs.fontWeight;
                        measurer.style.letterSpacing = cs.letterSpacing;
                        measurer.style.lineHeight = cs.lineHeight;
                    }

                    svgEl2.querySelectorAll('.node').forEach((node) => {
                        const fo = node.querySelector('foreignObject');
                        if (!fo) return;

                        // 仅处理主形状为“直接子 rect”的节点。
                        // 对菱形/多边形判定节点，Mermaid 常使用 polygon/path，
                        // 若误拿到 label 组内部辅助 rect 会导致文字框错位、看起来不居中。
                        let mainRect = null;
                        for (const child of node.children) {
                            if (child.tagName?.toLowerCase() === 'rect') {
                                mainRect = child;
                                break;
                            }
                        }
                        if (!mainRect) return;

                        const label = fo.querySelector('.nodeLabel');
                        if (!label) return;

                        const htmlContent = label.innerHTML;

                        // 按 <br/> 拆行，逐行测量最大宽度
                        const lineHtmls = htmlContent.split(/<br\s*\/?>/gi);
                        let maxLineW = 0;
                        lineHtmls.forEach(lineHtml => {
                            measurer.style.whiteSpace = 'nowrap';
                            measurer.innerHTML = lineHtml;
                            maxLineW = Math.max(maxLineW, measurer.offsetWidth);
                        });

                        // 测量总高度
                        measurer.style.whiteSpace = 'normal';
                        measurer.style.width = maxLineW + 'px';
                        measurer.innerHTML = htmlContent;
                        const totalH = measurer.offsetHeight;

                        const rectW = parseFloat(mainRect.getAttribute('width') || '0');
                        const rectH = parseFloat(mainRect.getAttribute('height') || '0');
                        const rectX = parseFloat(mainRect.getAttribute('x') || '0');
                        const rectY = parseFloat(mainRect.getAttribute('y') || '0');

                        const PAD_X = 56;
                        const PAD_Y = 36;
                        const needW = maxLineW + PAD_X;
                        const needH = totalH + PAD_Y;
                        const newW = Math.max(rectW, needW);
                        const newH = Math.max(rectH, needH);
                        const dw = newW - rectW;
                        const dh = newH - rectH;

                        if (dw > 0 || dh > 0) {
                            // 1) 对称扩展主背景 rect
                            const newRectX = rectX - dw / 2;
                            const newRectY = rectY - dh / 2;
                            mainRect.setAttribute('width', String(newW));
                            mainRect.setAttribute('height', String(newH));
                            mainRect.setAttribute('x', String(newRectX));
                            mainRect.setAttribute('y', String(newRectY));

                            // 2) ★ 关键修复：foreignObject 在 <g class="label"> 内，
                            //    该 <g> 有自己的 transform，不能直接用 rect 的坐标设 fo
                            const foParent = fo.parentElement;
                            if (foParent && foParent !== node && foParent.tagName?.toLowerCase() === 'g') {
                                // fo 在 label 组内部 → 重设 label 组的 transform 到新 rect 左上角
                                foParent.setAttribute('transform', `translate(${newRectX}, ${newRectY})`);
                                fo.setAttribute('x', '0');
                                fo.setAttribute('y', '0');
                                // 同步更新 label 组内的辅助 rect（如果有）
                                foParent.querySelectorAll('rect').forEach((innerRect) => {
                                    innerRect.setAttribute('x', '0');
                                    innerRect.setAttribute('y', '0');
                                    innerRect.setAttribute('width', String(newW));
                                    innerRect.setAttribute('height', String(newH));
                                });
                            } else {
                                // fo 直接在 .node 下（无 label 组包裹）→ 坐标系和 rect 相同
                                fo.setAttribute('x', String(newRectX));
                                fo.setAttribute('y', String(newRectY));
                            }
                            fo.setAttribute('width', String(newW));
                            fo.setAttribute('height', String(newH));
                        }
                    });

                    document.body.removeChild(measurer);

                    // 更新 SVG viewBox 以容纳扩展后的节点
                    try {
                        const bbox = svgEl2.getBBox();
                        const pad = 40;
                        svgEl2.setAttribute('viewBox',
                            `${bbox.x - pad} ${bbox.y - pad} ${bbox.width + pad * 2} ${bbox.height + pad * 2}`
                        );
                    } catch (e) { /* getBBox may fail */ }
                };

                // 第一次测量 + 扩展
                adjustNodeBoxes();

                // 延迟二次校正：兜底处理极端慢加载场景（如首次打开字体延迟）
                adjustTimeoutRef.current = setTimeout(() => {
                    if (disposed || renderSeq !== renderSeqRef.current) return;
                    if (containerRef.current?.querySelector('svg')) {
                        adjustNodeBoxes();
                    }
                }, 300);
                
                // 移除 SVG 上的尺寸限制，让图表以自然尺寸渲染（含分支节点）
                const svgEl = containerRef.current.querySelector('svg');
                if (svgEl) {
                    svgEl.style.maxWidth = 'none';
                    svgEl.style.width = 'auto';
                    svgEl.style.height = 'auto';
                    svgEl.removeAttribute('height');
                    
                    // 自动适配：根据图表实际尺寸与容器比例计算初始缩放
                    requestAnimationFrame(() => {
                        const area = scrollAreaRef.current;
                        if (!area || !svgEl) return;
                        const aW = area.clientWidth - 48;
                        const aH = area.clientHeight - 48;
                        const sW = svgEl.scrollWidth || svgEl.getBBox?.()?.width || 800;
                        const sH = svgEl.scrollHeight || svgEl.getBBox?.()?.height || 400;
                        
                        let fit = 1;
                        if (sW > aW || sH > aH) {
                            fit = Math.max(0.2, +(Math.min(aW / sW, aH / sH) * 0.92).toFixed(2));
                        }
                        setScale(fit);
                        initialScaleRef.current = fit;
                        setPan({ x: 0, y: 0 });
                    });
                }
                
                setError(null);
            } catch (err) {
                console.error('Mermaid render error:', err);
                if (!disposed && renderSeq === renderSeqRef.current) {
                    setError('Flowchart rendering failed');
                }
            }
        };

        renderDiagram();

        return () => {
            disposed = true;
            if (adjustTimeoutRef.current) {
                clearTimeout(adjustTimeoutRef.current);
                adjustTimeoutRef.current = null;
            }
        };
    }, [records, flowPlan, userQuery]);

    // 监听 fullscreenchange，以在进入/退出全屏时调整 modal 样式
    useEffect(() => {
        const onFsChange = () => {
            const el = modalRef.current;
            const isFs = !!document.fullscreenElement;
            setIsFullscreen(isFs);
            if (!el) return;
            if (isFs) {
                // 进入全屏：放大 modal 到全屏尺寸
                el.style.width = '100vw';
                el.style.height = '100vh';
                el.style.maxWidth = 'none';
                el.style.maxHeight = 'none';
                el.style.borderRadius = '0';
            } else {
                // 退出全屏：恢复之前样式
                const prev = prevModalStyleRef.current || {};
                el.style.width = prev.width || '';
                el.style.height = prev.height || '';
                el.style.maxWidth = prev.maxWidth || '';
                el.style.maxHeight = prev.maxHeight || '';
                el.style.borderRadius = prev.borderRadius || '';
            }
        };

        document.addEventListener('fullscreenchange', onFsChange);
        return () => document.removeEventListener('fullscreenchange', onFsChange);
    }, []);

    // 统一缩放步长为 0.2，扩大允许的缩放范围到 [0.3, 4]
    const handleZoomIn = () => setScale(prev => Math.min(+(prev + 0.2).toFixed(2), 4));
    const handleZoomOut = () => setScale(prev => Math.max(+(prev - 0.2).toFixed(2), 0.3));
    const handleReset = () => {
        setScale(initialScaleRef.current || 1);
        setPan({ x: 0, y: 0 });  // 重置时也重置平移
    };

    // 图表拖拽平移处理
    const startPan = (e) => {
        // 只响应鼠标左键或触摸
        if (e.button && e.button !== 0) return;
        isPanningRef.current = true;
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        panStartRef.current = { x: clientX, y: clientY };
        panOffsetRef.current = { x: pan.x, y: pan.y };
        
        // 设置拖拽光标
        document.body.style.cursor = 'grabbing';
        document.body.style.userSelect = 'none';
        
        document.addEventListener('mousemove', onPanning);
        document.addEventListener('mouseup', stopPan);
        document.addEventListener('touchmove', onPanning, { passive: false });
        document.addEventListener('touchend', stopPan);
    };

    const onPanning = (ev) => {
        if (!isPanningRef.current) return;
        ev.preventDefault();
        const clientX = ev.touches ? ev.touches[0].clientX : ev.clientX;
        const clientY = ev.touches ? ev.touches[0].clientY : ev.clientY;
        
        const dx = clientX - panStartRef.current.x;
        const dy = clientY - panStartRef.current.y;
        
        setPan({
            x: panOffsetRef.current.x + dx,
            y: panOffsetRef.current.y + dy
        });
    };

    const stopPan = () => {
        isPanningRef.current = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        
        // 阻止接下来 300ms 内的关闭操作
        blockCloseUntilRef.current = Date.now() + 300;
        
        document.removeEventListener('mousemove', onPanning);
        document.removeEventListener('mouseup', stopPan);
        document.removeEventListener('touchmove', onPanning);
        document.removeEventListener('touchend', stopPan);
    };

    // 可拖拽调整模态框大小的状态/refs
    const [modalSize, setModalSize] = useState(null); // { width, height }
    const resizingRef = useRef(false);
    const startPosRef = useRef({ x: 0, y: 0 });
    const startSizeRef = useRef({ w: 0, h: 0 });

    const getMaxBounds = () => {
        if (typeof window === 'undefined') return { maxW: Infinity, maxH: Infinity };
        return { maxW: Infinity, maxH: Infinity };
    };

    const startResize = (e) => {
        if (isFullscreen) return; // 全屏时禁用
        e.preventDefault();
        e.stopPropagation();
        resizingRef.current = true;
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        startPosRef.current = { x: clientX, y: clientY };

        const rect = modalRef.current?.getBoundingClientRect();
        startSizeRef.current = { w: rect?.width || 800, h: rect?.height || 600 };
        
        // 设置拖拽光标
        document.body.style.cursor = 'se-resize';
        document.body.style.userSelect = 'none';

        document.addEventListener('mousemove', onResizing);
        document.addEventListener('mouseup', stopResize, true);  // 使用 capture 确保优先处理
        document.addEventListener('touchmove', onResizing, { passive: false });
        document.addEventListener('touchend', stopResize, true);
    };

    const onResizing = (ev) => {
        if (!resizingRef.current) return;
        ev.preventDefault();
        ev.stopPropagation();
        const clientX = ev.touches ? ev.touches[0].clientX : ev.clientX;
        const clientY = ev.touches ? ev.touches[0].clientY : ev.clientY;

        const dx = clientX - startPosRef.current.x;
        const dy = clientY - startPosRef.current.y;
        const minW = 300;
        const minH = 200;

        const newW = Math.max(minW, Math.round(startSizeRef.current.w + dx));
        const newH = Math.max(minH, Math.round(startSizeRef.current.h + dy));

        setModalSize({ width: newW, height: newH });
    };

    const stopResize = (e) => {
        if (!resizingRef.current) return;  // 防止重复触发
        resizingRef.current = false;
        
        // 阻止事件冒泡，防止触发 onClose
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        // 阻止接下来 300ms 内的关闭操作（click 事件会在 mouseup 之后触发）
        blockCloseUntilRef.current = Date.now() + 300;
        
        // 恢复光标
        document.body.style.cursor = '';
        document.body.style.userSelect = '';

        document.removeEventListener('mousemove', onResizing);
        document.removeEventListener('mouseup', stopResize, true);
        document.removeEventListener('touchmove', onResizing);
        document.removeEventListener('touchend', stopResize, true);

        // 保存当前样式以便退出全屏时恢复
        if (modalRef.current && modalSize) {
            prevModalStyleRef.current = {
                width: `${modalSize.width}px`,
                height: `${modalSize.height}px`,
                maxWidth: modalRef.current.style.maxWidth,
                maxHeight: modalRef.current.style.maxHeight,
                borderRadius: modalRef.current.style.borderRadius,
            };
        }
    };

    // 处理背景点击关闭（调整大小或拖动图表时不关闭）
    const handleBackdropClick = (e) => {
        if (!onClose) return;
        // 如果正在拖拽或调整大小，阻止关闭
        if (resizingRef.current || isPanningRef.current) {
            e.stopPropagation();
            return;
        }
        // 如果刚刚结束拖拽/调整大小（300ms 内），阻止关闭
        if (Date.now() < blockCloseUntilRef.current) {
            e.stopPropagation();
            return;
        }
        onClose();
    };

    if (inline) {
        const hasFixedInlineHeight = Number.isFinite(Number(inlineHeight)) && Number(inlineHeight) > 0;
        return (
            <div className="mt-3 border border-slate-200 rounded-xl overflow-hidden shadow-sm bg-white">
                <div
                    ref={modalRef}
                    className="w-full flex flex-col"
                    style={hasFixedInlineHeight ? { height: `${inlineHeight}px` } : { minHeight: '420px' }}
                >
                    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gradient-to-r from-[#4827AF] to-[#FF693B]">
                        <div className="flex items-center gap-2 text-white">
                            <GitBranch size={18} />
                            <h3 className="font-medium">Resolution Flowchart</h3>
                        </div>
                        <div className="flex items-center gap-2">
                            <button onClick={handleZoomOut} className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors" title="Zoom out">
                                <ZoomOut size={14} />
                            </button>
                            <span className="text-white text-sm min-w-[50px] text-center">{Math.round(scale * 100)}%</span>
                            <button onClick={handleZoomIn} className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors" title="Zoom in">
                                <ZoomIn size={14} />
                            </button>
                            <button onClick={handleReset} className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors text-xs" title="Reset view">
                                Reset
                            </button>
                        </div>
                    </div>

                    <div
                        ref={scrollAreaRef}
                        className={`${hasFixedInlineHeight ? 'flex-1 overflow-hidden' : 'overflow-auto'} p-4 bg-gray-50`}
                        style={{ overscrollBehavior: 'contain' }}
                    >
                        {error ? (
                            <div className="flex items-center justify-center h-full text-red-500">{error}</div>
                        ) : (
                            <div
                                className="flex items-center justify-center min-h-[300px] cursor-grab active:cursor-grabbing"
                                style={{
                                    transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`,
                                    transformOrigin: 'center center',
                                    transition: isPanningRef.current ? 'none' : 'transform 0.1s ease-out'
                                }}
                                onMouseDown={startPan}
                                onTouchStart={startPan}
                            >
                                <div ref={containerRef} className="mermaid-container" style={{ pointerEvents: 'none', overflow: 'visible' }} />
                            </div>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div 
            className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
            onClick={handleBackdropClick}
        >
            <div 
                ref={modalRef}
                onClick={(e) => e.stopPropagation()}
                className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-5xl max-h-[90vh] flex flex-col relative"
                style={{
                    width: modalSize?.width ? `${modalSize.width}px` : undefined,
                    height: modalSize?.height ? `${modalSize.height}px` : undefined,
                    maxWidth: isFullscreen ? 'none' : undefined,
                    maxHeight: isFullscreen ? 'none' : undefined,
                }}
            >
                {/* 标题栏 */}
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-gradient-to-r from-[#4827AF] to-[#FF693B] rounded-t-xl">
                    <div className="flex items-center gap-2 text-white">
                        <GitBranch size={20} />
                        <h3 className="font-medium">Solution Flowchart</h3>
                    </div>
                    <div className="flex items-center gap-2">
                        {/* 缩放控制 */}
                        <button
                            onClick={handleZoomOut}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors"
                            title="Zoom out"
                        >
                            <ZoomOut size={16} />
                        </button>
                        <span className="text-white text-sm min-w-[50px] text-center">
                            {Math.round(scale * 100)}%
                        </span>
                        <button
                            onClick={handleZoomIn}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors"
                            title="Zoom in"
                        >
                            <ZoomIn size={16} />
                        </button>
                        <button
                            onClick={() => {
                                // 切换放大/还原：放大到 2.5x，或还原到之前缩放
                                if (!isZoomed) {
                                    prevScaleRef.current = scale;
                                    setScale(2.5);
                                    setIsZoomed(true);
                                } else {
                                    setScale(prevScaleRef.current || 1);
                                    setIsZoomed(false);
                                }
                            }}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors text-xs"
                            title={isZoomed ? 'Restore view' : 'Zoom view'}
                        >
                            {isZoomed ? 'Restore' : 'Zoom'}
                        </button>
                        <button
                            onClick={handleReset}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors text-xs"
                            title="Reset view (restore initial pan and zoom)"
                        >
                            Reset
                        </button>
                        <button
                            onClick={async () => {
                                // 切换浏览器全屏（针对 modal）
                                const el = modalRef.current;
                                if (!el) return;
                                try {
                                    if (!document.fullscreenElement) {
                                        // 保存当前样式以便退出时恢复
                                        prevModalStyleRef.current = {
                                            width: el.style.width,
                                            height: el.style.height,
                                            maxWidth: el.style.maxWidth,
                                            maxHeight: el.style.maxHeight,
                                            borderRadius: el.style.borderRadius,
                                        };
                                        // 请求全屏
                                        await el.requestFullscreen();
                                    } else {
                                        await document.exitFullscreen();
                                    }
                                } catch (err) {
                                    console.warn('Fullscreen toggle failed', err);
                                }
                            }}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors ml-2"
                            title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
                        >
                            <Maximize2 size={16} />
                        </button>
                        {/* resize handle - 右下角 */}
                        <div
                            onMouseDown={startResize}
                            onTouchStart={startResize}
                            onClick={(e) => e.stopPropagation()}
                            className="absolute right-2 bottom-2 w-4 h-4 cursor-se-resize z-50"
                            title="Drag to resize"
                            style={{ opacity: 0.9 }}
                        >
                            <svg width="100%" height="100%" viewBox="0 0 10 10" xmlns="http://www.w3.org/2000/svg" fill="none" stroke="#9CA3AF" strokeWidth="1">
                                <path d="M1 9 L9 1 M5 9 L9 5" strokeLinecap="round" />
                            </svg>
                        </div>
                        {/* 关闭按钮 */}
                        <button
                            onClick={onClose}
                            className="p-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-white transition-colors ml-2"
                        >
                            <X size={18} />
                        </button>
                    </div>
                </div>

                {/* 图表区域 */}
                <div 
                    ref={scrollAreaRef}
                    className="flex-1 overflow-hidden p-6 bg-gray-50 dark:bg-gray-900"
                    style={{ overscrollBehavior: 'contain' }}
                >
                    {error ? (
                        <div className="flex items-center justify-center h-full text-red-500">
                            {error}
                        </div>
                    ) : (
                        <div 
                            className="flex items-center justify-center min-h-[400px] cursor-grab active:cursor-grabbing"
                            style={{ 
                                transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, 
                                transformOrigin: 'center center',
                                transition: isPanningRef.current ? 'none' : 'transform 0.1s ease-out'
                            }}
                            onMouseDown={startPan}
                            onTouchStart={startPan}
                        >
                            <div ref={containerRef} className="mermaid-container" style={{ pointerEvents: 'none', overflow: 'visible' }} />
                        </div>
                    )}
                </div>

                {/* 底部信息 */}
                <div className="px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-100 dark:bg-gray-800 rounded-b-xl">
                    <div className="flex items-center justify-between text-xs text-gray-500">
                        <div className="flex items-center gap-4">
                            <span>Generated from {records?.length || 0} retrieved records</span>
                            <div className="flex items-center gap-3 text-gray-400">
                                <span className="flex items-center gap-1">
                                    <span className="w-3 h-3 rounded bg-red-200 border border-red-400"></span>
                                    Problem
                                </span>
                                <span className="flex items-center gap-1">
                                    <span className="w-3 h-3 rounded bg-amber-100 border border-amber-400"></span>
                                    Cause
                                </span>
                                <span className="flex items-center gap-1">
                                    <span className="w-3 h-3 rounded bg-blue-100 border border-blue-400"></span>
                                    Action
                                </span>
                                <span className="flex items-center gap-1">
                                    <span className="w-3 h-3 rounded bg-green-100 border border-green-400"></span>
                                    Complete
                                </span>
                            </div>
                        </div>
                        <details className="cursor-pointer">
                            <summary className="hover:text-gray-700">View Mermaid code</summary>
                            <pre className="mt-2 p-2 bg-gray-200 dark:bg-gray-700 rounded text-xs max-h-32 overflow-auto">
                                {mermaidCode}
                            </pre>
                        </details>
                    </div>
                </div>
                {/* 【核心修改】自由拖拽手柄：必须放在 Modal 容器的绝对右下角 */}
                {!isFullscreen && (
                    <div
                        onMouseDown={startResize}
                        onTouchStart={startResize}
                        className="absolute right-0 bottom-0 w-6 h-6 cursor-se-resize z-[60] flex items-end justify-end p-1 hover:bg-black/5 transition-colors"
                    >
                        <svg width="12" height="12" viewBox="0 0 10 10" fill="none" stroke="#9CA3AF" strokeWidth="1.5">
                            <path d="M1 9 L9 1 M5 9 L9 5" strokeLinecap="round" />
                        </svg>
                    </div>
                )}
        </div>
    </div>
);
        
};

export default MermaidDiagram;
