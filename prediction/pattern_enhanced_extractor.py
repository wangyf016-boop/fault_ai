"""
模式增强提取器 - BERT + 正则表达式模式识别
快速且可靠，无需LLM
"""

import sys
from pathlib import Path
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import re
from typing import List, Dict, Tuple
from prediction.entity_extractor import BERTEntityExtractor


class PatternEnhancedExtractor:
    """模式增强提取器：BERT基础识别 + 正则模式补充"""
    
    # 设备/站位编号模式（按长度优先匹配）
    DEVICE_CODE_PATTERNS = [
        r'[A-Z]+\d+\.?\d*',   # K06.01, OP60, G39（优先匹配数字编号）
        r'(?<![A-Za-z])[A-Z]{2,}(?![a-z])',  # SMC, ABB, SKF
    ]
    
    def __init__(self):
        """初始化模式增强提取器"""
        # 加载BERT模型
        self.phenomenon_extractor = BERTEntityExtractor(
            model_path=str(project_root / 'models' / 'saved' / 'model_output' / 'phenomenon')
        )
        
        self.solution_extractor = BERTEntityExtractor(
            model_path=str(project_root / 'models' / 'saved' / 'model_output' / 'solution')
        )
        
        print("✅ 模式增强提取器已初始化")
        print("   模式: BERT + 正则表达式")
    
    def extract_phenomenon(self, text: str) -> List[Dict]:
        """提取现象实体（BERT + 模式）"""
        return self._extract_with_patterns(text, self.phenomenon_extractor, 'phenomenon')
    
    def extract_solution(self, text: str) -> List[Dict]:
        """提取解决方案实体（BERT + 模式）"""
        return self._extract_with_patterns(text, self.solution_extractor, 'solution')
    
    def _extract_with_patterns(self, text: str, extractor, field_type: str) -> List[Dict]:
        """BERT提取 + 模式补充"""
        if not text:
            return []
        
        # 1. BERT提取
        bert_entities = extractor.extract(text)
        entities = []
        bert_covered = set()
        
        for ent_text, label in bert_entities:
            if ent_text:
                # 找到实体在原文中的位置
                start = text.find(ent_text)
                if start >= 0:
                    end = start + len(ent_text)
                    bert_covered.update(range(start, end))
                    entities.append({
                        'text': ent_text,
                        'label': label,
                        'start': start,
                        'end': end,
                        'source': 'bert'
                    })
        
        # 2. 正则模式补充（查找设备编号）
        pattern_covered = set()  # 追踪模式匹配已覆盖的位置
        
        for pattern in self.DEVICE_CODE_PATTERNS:
            for match in re.finditer(pattern, text):
                start, end = match.span()
                matched_text = match.group()
                
                # 检查是否与已有模式匹配重叠
                if any(pos in pattern_covered for pos in range(start, end)):
                    continue
                
                # 计算与BERT的重叠度
                overlap = sum(1 for pos in range(start, end) if pos in bert_covered)
                coverage = overlap / (end - start) if end > start else 0
                
                # 如果重叠度<=50%，说明有BERT遗漏的部分
                if coverage <= 0.5:
                    entities.append({
                        'text': matched_text,
                        'label': 'COMP',
                        'start': start,
                        'end': end,
                        'source': 'pattern'
                    })
                    pattern_covered.update(range(start, end))
        
        # 3. 合并相邻实体（如K06 + .01）
        entities = self._merge_adjacent_entities(text, entities)
        
        # 4. 按位置排序，去掉位置信息
        entities.sort(key=lambda x: x['start'])
        return [{'text': e['text'], 'label': e['label'], 'source': e['source']} 
                for e in entities]
    
    def _merge_adjacent_entities(self, text: str, entities: List[Dict]) -> List[Dict]:
        """合并相邻的同标签实体"""
        if len(entities) <= 1:
            return entities
        
        # 按开始位置排序
        entities.sort(key=lambda x: x['start'])
        
        merged = []
        i = 0
        while i < len(entities):
            current = entities[i]
            
            # 查找可以合并的后续实体
            j = i + 1
            while j < len(entities):
                next_ent = entities[j]
                
                # 条件：同标签 + 位置相邻（间隔<=1字符）
                if (current['label'] == next_ent['label'] and 
                    next_ent['start'] - current['end'] <= 1):
                    
                    # 合并
                    merged_text = text[current['start']:next_ent['end']]
                    current = {
                        'text': merged_text,
                        'label': current['label'],
                        'start': current['start'],
                        'end': next_ent['end'],
                        'source': 'bert+pattern' if 'pattern' in [current['source'], next_ent['source']] else current['source']
                    }
                    j += 1
                else:
                    break
            
            merged.append(current)
            i = j
        
        return merged


if __name__ == "__main__":
    # 测试
    extractor = PatternEnhancedExtractor()
    
    test_cases = [
        ('K06.01报错', 'phenomenon'),
        ('OP60传感器异常', 'phenomenon'),
        ('SMC电缸控制器软件异常', 'phenomenon'),
        ('更换焊头', 'solution'),
        ('重启SMC电缸控制器', 'solution'),
    ]
    
    print("\n测试结果:")
    for text, field_type in test_cases:
        print(f"\n文本: {text} ({field_type})")
        
        if field_type == 'phenomenon':
            result = extractor.extract_phenomenon(text)
        else:
            result = extractor.extract_solution(text)
        
        for ent in result:
            print(f"  - {ent['text']} ({ent['label']}, {ent['source']})")
