"""
BERT + LLM 混合实体提取器
===========================

策略A: BERT先行，LLM补充未覆盖部分
特点: 保证实体完整覆盖原始文本

流程:
1. BERT提取实体，记录每个实体在原文中的位置
2. 计算未覆盖的文本片段
3. 分析未覆盖片段与已识别实体的前后关系
4. LLM判断未覆盖片段是否应该合并到相邻实体，或作为新实体
5. 合并结果，确保完整覆盖原文
"""

import sys
import json
import re
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass

# 添加项目路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


@dataclass
class EntitySpan:
    """实体及其在原文中的位置"""
    text: str
    label: str
    start: int
    end: int
    source: str  # 'bert' 或 'llm'


class HybridEntityExtractor:
    """BERT + LLM 混合实体提取器"""
    
    # Ollama 配置
    OLLAMA_API_URL = "http://localhost:11434/api/chat"  # 使用chat端点
    OLLAMA_MODEL = "DeepSeek-R1:latest"
    
    # LLM Prompt 模板（极简版，DeepSeek-R1友好）
    PROMPT_TEMPLATE = """设备维修文本: "{original_text}"
BERT识别: {bert_simple}
未识别: {uncovered_simple}

判断未识别部分是什么类型：
COMP=部件/编号, PHEN=现象, ACT=动作, ignore=无意义

只返回JSON，无其他内容: {{\"actions\": [{{\"type\": \"new_entity\", \"segment\": \"...\", \"label\": \"COMP\"}}]}}"""

    def __init__(self, 
                 phenomenon_model_path: str = None,
                 solution_model_path: str = None,
                 use_llm: bool = True):
        """
        初始化混合提取器
        
        Args:
            phenomenon_model_path: 现象模型路径
            solution_model_path: 解决方案模型路径
            use_llm: 是否使用LLM补充（可关闭用于对比测试）
        """
        from prediction.entity_extractor import BERTEntityExtractor
        
        # 默认模型路径
        if phenomenon_model_path is None:
            phenomenon_model_path = str(project_root / 'models' / 'saved' / 'model_output' / 'phenomenon')
        if solution_model_path is None:
            solution_model_path = str(project_root / 'models' / 'saved' / 'model_output' / 'solution')
        
        # 加载BERT模型
        self.phenomenon_extractor = BERTEntityExtractor(model_path=phenomenon_model_path)
        self.solution_extractor = BERTEntityExtractor(model_path=solution_model_path)
        
        self.use_llm = use_llm
        
        print(f"✅ 混合实体提取器已初始化")
        print(f"   现象模型: {phenomenon_model_path}")
        print(f"   解决方案模型: {solution_model_path}")
        print(f"   LLM补充: {'启用' if use_llm else '禁用'}")
    
    def extract_phenomenon(self, text: str) -> List[Dict]:
        """
        从故障现象文本中提取实体
        
        Args:
            text: 故障现象文本
            
        Returns:
            实体列表 [{'text': str, 'label': str, 'source': str}, ...]
        """
        return self._extract_with_hybrid(text, self.phenomenon_extractor, 'phenomenon')
    
    def extract_solution(self, text: str) -> List[Dict]:
        """
        从解决方案文本中提取实体
        
        Args:
            text: 解决方案文本
            
        Returns:
            实体列表
        """
        return self._extract_with_hybrid(text, self.solution_extractor, 'solution')
    
    def _extract_with_hybrid(self, text: str, extractor, field_type: str) -> List[Dict]:
        """
        混合提取流程
        
        Args:
            text: 输入文本
            extractor: BERT提取器
            field_type: 字段类型（'phenomenon' 或 'solution'）
        """
        if not text or not text.strip():
            return []
        
        text = text.strip()
        
        # 步骤1: BERT提取实体
        bert_entities = extractor.extract(text)
        
        # 转换为EntitySpan格式，计算位置
        entity_spans = self._locate_entities_in_text(text, bert_entities)
        
        # 步骤2: 计算未覆盖片段
        uncovered = self._find_uncovered_segments(text, entity_spans)
        
        # 计算覆盖率
        covered_len = sum(e.end - e.start for e in entity_spans)
        coverage = covered_len / len(text) if text else 0
        
        # 如果覆盖率>=99%，跳过LLM（性能优化）
        if coverage >= 0.99:
            return [{'text': e.text, 'label': e.label, 'source': e.source} for e in entity_spans]
        
        # 如果没有未覆盖片段，或不使用LLM，直接返回BERT结果
        if not uncovered or not self.use_llm:
            return [{'text': e.text, 'label': e.label, 'source': e.source} for e in entity_spans]
        
        # 步骤3: 使用LLM分析未覆盖片段
        llm_actions = self._analyze_with_llm(text, entity_spans, uncovered)
        
        # 步骤4: 应用LLM的判断，合并结果
        final_entities = self._apply_llm_actions(text, entity_spans, uncovered, llm_actions)
        
        return [{'text': e.text, 'label': e.label, 'source': e.source} for e in final_entities]
    
    def _locate_entities_in_text(self, text: str, bert_entities: List[Tuple]) -> List[EntitySpan]:
        """定位BERT实体在原文中的位置"""
        spans = []
        used_positions = set()
        
        for ent in bert_entities:
            if isinstance(ent, tuple) and len(ent) >= 2:
                ent_text = ent[0]
                ent_label = ent[1]
            else:
                continue
            
            # 查找实体在文本中的位置（避免重复匹配）
            start = 0
            while True:
                pos = text.find(ent_text, start)
                if pos == -1:
                    break
                
                # 检查这个位置是否已被使用
                position_key = (pos, pos + len(ent_text))
                if position_key not in used_positions:
                    used_positions.add(position_key)
                    spans.append(EntitySpan(
                        text=ent_text,
                        label=ent_label,
                        start=pos,
                        end=pos + len(ent_text),
                        source='bert'
                    ))
                    break
                
                start = pos + 1
        
        # 按位置排序
        spans.sort(key=lambda x: x.start)
        return spans
    
    def _find_uncovered_segments(self, text: str, entity_spans: List[EntitySpan]) -> List[Dict]:
        """找出未被BERT覆盖的文本片段"""
        uncovered = []
        
        # 标记已覆盖的字符位置
        covered = [False] * len(text)
        for span in entity_spans:
            for i in range(span.start, span.end):
                if i < len(covered):
                    covered[i] = True
        
        # 找出连续的未覆盖片段
        i = 0
        while i < len(text):
            if not covered[i]:
                # 找到未覆盖片段的开始
                start = i
                while i < len(text) and not covered[i]:
                    i += 1
                end = i
                
                segment_text = text[start:end]
                
                # 过滤纯空白
                if segment_text.strip():
                    # 找出相邻的实体
                    prev_entity = None
                    next_entity = None
                    
                    for span in entity_spans:
                        if span.end <= start:
                            prev_entity = span
                        elif span.start >= end and next_entity is None:
                            next_entity = span
                    
                    uncovered.append({
                        'text': segment_text,
                        'start': start,
                        'end': end,
                        'prev_entity': prev_entity,
                        'next_entity': next_entity
                    })
            else:
                i += 1
        
        return uncovered
    
    def _analyze_with_llm(self, original_text: str, 
                          entity_spans: List[EntitySpan], 
                          uncovered: List[Dict]) -> List[Dict]:
        """使用LLM分析未覆盖片段"""
        
        # 构建简化的BERT实体列表
        bert_simple = ", ".join([f"{s.text}({s.label})" for s in entity_spans]) or "(无)"
        
        # 构建简化的未覆盖片段列表
        uncovered_simple = ", ".join([f"\"{s['text'].strip()}\"" for s in uncovered]) or "(无)"
        
        # 构建Prompt
        prompt = self.PROMPT_TEMPLATE.format(
            original_text=original_text,
            bert_simple=bert_simple,
            uncovered_simple=uncovered_simple
        )
        
        # 调用Ollama
        try:
            response = self._call_ollama(prompt)
            if not response:
                print("⚠️ LLM返回空响应")
                return []
            actions = self._parse_llm_response(response)
            return actions
        except Exception as e:
            print(f"⚠️ LLM调用失败: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _call_ollama(self, prompt: str) -> str:
        """调用Ollama API (使用chat端点)"""
        payload = {
            "model": self.OLLAMA_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,  # 低温度，更确定性的输出
                "num_predict": 1024
            }
        }
        
        try:
            response = requests.post(
                self.OLLAMA_API_URL,
                json=payload,
                timeout=30  # 降低超时时间到30秒
            )
            
            if response.status_code == 200:
                result = response.json()
                message = result.get('message', {})
                return message.get('content', '')
            else:
                print(f"⚠️ Ollama API错误: {response.status_code}")
                return ''
        except requests.exceptions.Timeout:
            print("⚠️ LLM调用超时(30s)，跳过补充")
            return ''
        except Exception as e:
            print(f"⚠️ LLM调用异常: {e}")
            return ''
    
    def _parse_llm_response(self, response: str) -> List[Dict]:
        """解析LLM的JSON响应"""
        try:
            # 尝试提取JSON部分
            # 处理deepseek-r1的思考过程输出
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                json_str = json_match.group()
                result = json.loads(json_str)
                return result.get('actions', [])
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON解析失败: {e}")
            print(f"   原始响应: {response[:200]}...")
        
        return []
    
    def _apply_llm_actions(self, original_text: str,
                           entity_spans: List[EntitySpan], 
                           uncovered: List[Dict], 
                           actions: List[Dict]) -> List[EntitySpan]:
        """应用LLM的判断结果，生成最终实体列表"""
        
        # 复制实体列表
        result_spans = list(entity_spans)
        
        # 构建片段文本到片段信息的映射
        uncovered_map = {seg['text'].strip(): seg for seg in uncovered}
        
        for action in actions:
            action_type = action.get('type', '')
            segment = action.get('segment', '').strip()
            
            if action_type == 'ignore':
                # 忽略该片段
                continue
            
            elif action_type == 'new_entity':
                # 添加新实体
                label = action.get('label', 'COMP')
                seg_info = uncovered_map.get(segment)
                if seg_info:
                    result_spans.append(EntitySpan(
                        text=segment,
                        label=label,
                        start=seg_info['start'],
                        end=seg_info['end'],
                        source='llm'
                    ))
            
            elif action_type == 'merge_before':
                # 合并到后面实体的前面
                merge_with = action.get('merge_with', '')
                new_text = action.get('new_text', '')
                label = action.get('label', '')
                
                # 找到要合并的实体
                for i, span in enumerate(result_spans):
                    if span.text == merge_with:
                        seg_info = uncovered_map.get(segment)
                        if seg_info:
                            # 更新实体
                            result_spans[i] = EntitySpan(
                                text=new_text,
                                label=label if label else span.label,
                                start=seg_info['start'],
                                end=span.end,
                                source='bert+llm'
                            )
                        break
            
            elif action_type == 'merge_after':
                # 合并到前面实体的后面
                merge_with = action.get('merge_with', '')
                new_text = action.get('new_text', '')
                label = action.get('label', '')
                
                # 找到要合并的实体
                for i, span in enumerate(result_spans):
                    if span.text == merge_with:
                        seg_info = uncovered_map.get(segment)
                        if seg_info:
                            # 更新实体
                            result_spans[i] = EntitySpan(
                                text=new_text,
                                label=label if label else span.label,
                                start=span.start,
                                end=seg_info['end'],
                                source='bert+llm'
                            )
                        break
        
        # 按位置排序
        result_spans.sort(key=lambda x: x.start)
        
        # 自动合并相邻的同类实体（如 K06 + .01 → K06.01）
        result_spans = self._merge_adjacent_entities(original_text, result_spans)
        
        return result_spans
    
    def _merge_adjacent_entities(self, original_text: str, spans: List[EntitySpan]) -> List[EntitySpan]:
        """
        自动合并相邻的同类实体
        
        例如：
        - "K06"(COMP) + ".01"(COMP) → "K06.01"(COMP)
        - "SMC"(COMP) + "电缸"(COMP) → "SMC电缸"(COMP)
        """
        if len(spans) <= 1:
            return spans
        
        merged = []
        i = 0
        
        while i < len(spans):
            current = spans[i]
            
            # 检查是否可以与下一个实体合并
            if i + 1 < len(spans):
                next_span = spans[i + 1]
                
                # 合并条件：
                # 1. 标签相同
                # 2. 在原文中连续或只有少量空白
                # 3. 合并后的文本在原文中存在
                if (current.label == next_span.label and 
                    next_span.start - current.end <= 1):  # 允许最多1个字符间隔
                    
                    # 提取合并后的文本
                    merged_text = original_text[current.start:next_span.end]
                    
                    # 判断source
                    if 'llm' in current.source and 'llm' in next_span.source:
                        merged_source = 'llm'
                    elif 'llm' in current.source or 'llm' in next_span.source:
                        merged_source = 'bert+llm'
                    else:
                        merged_source = 'bert'
                    
                    # 创建合并后的实体
                    merged.append(EntitySpan(
                        text=merged_text,
                        label=current.label,
                        start=current.start,
                        end=next_span.end,
                        source=merged_source
                    ))
                    
                    # 跳过下一个实体
                    i += 2
                else:
                    merged.append(current)
                    i += 1
            else:
                merged.append(current)
                i += 1
        
        return merged


# ============================================================
# 命令行测试入口
# ============================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="混合实体提取器测试")
    parser.add_argument("--text", type=str, help="要提取的文本")
    parser.add_argument("--field", type=str, default="phenomenon", 
                        choices=["phenomenon", "solution"],
                        help="字段类型")
    parser.add_argument("--no-llm", action="store_true", help="禁用LLM补充")
    
    args = parser.parse_args()
    
    extractor = HybridEntityExtractor(use_llm=not args.no_llm)
    
    if args.text:
        if args.field == "phenomenon":
            entities = extractor.extract_phenomenon(args.text)
        else:
            entities = extractor.extract_solution(args.text)
        
        print(f"\n输入: {args.text}")
        print(f"提取结果: {entities}")
    else:
        # 默认测试
        test_texts = [
            "K06.01报错",
            "OP60传感器异常",
            "SMC电缸控制器软件异常",
        ]
        
        print("\n测试混合提取:")
        for text in test_texts:
            entities = extractor.extract_phenomenon(text)
            print(f"\n输入: {text}")
            print(f"结果: {entities}")
