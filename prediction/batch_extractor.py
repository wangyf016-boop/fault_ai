"""
批量实体提取器 - BERT先识别，LLM批量检查修正
大幅减少LLM调用次数，提升速度
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))

import requests
import json
import re
from typing import List, Dict, Tuple
from tqdm import tqdm

from prediction.entity_extractor import BERTEntityExtractor


class BatchEntityExtractor:
    """批量提取器：BERT批量识别 + LLM批量检查"""
    
    OLLAMA_API_URL = "http://localhost:11434/api/chat"
    OLLAMA_MODEL = "DeepSeek-R1:latest"
    BATCH_SIZE = 20  # 每批发给LLM检查的记录数
    
    # LLM批量检查Prompt模板（极简版）
    BATCH_CHECK_PROMPT = """维修记录BERT识别结果:
{bert_results}

常见遗漏: 设备编号(K06, OP60), 品牌(SMC, ABB)

检查是否有遗漏，返回JSON修正:
[{{"record_id": 0, "fixes": [{{"action": "merge", "entities": ["SMC", "电缸"], "new_entity": "SMC电缸", "label": "COMP"}}]}}]

无遗漏返回: []"""
    
    def __init__(self):
        """初始化批量提取器"""
        project_root = Path(__file__).resolve().parents[1]
        
        # 加载现象模型和解决方案模型
        self.phenomenon_extractor = BERTEntityExtractor(
            model_path=str(project_root / 'models' / 'saved' / 'model_output' / 'phenomenon')
        )
        
        self.solution_extractor = BERTEntityExtractor(
            model_path=str(project_root / 'models' / 'saved' / 'model_output' / 'solution')
        )
        
        print("✅ 批量实体提取器已初始化")
        print("   模式: BERT批量识别 + LLM批量检查")
        print(f"   批次大小: {self.BATCH_SIZE} 条/批")
    
    def extract_batch(self, records: List[Dict]) -> List[Dict]:
        """
        批量提取实体
        
        Args:
            records: 记录列表，每条包含 phenomenon_text 和 solution_text
            
        Returns:
            增强后的记录列表，包含提取的实体
        """
        print(f"\n[步骤1] BERT批量提取实体...")
        
        # BERT批量提取
        enhanced_records = []
        for record in tqdm(records, desc="BERT提取"):
            phenomenon_text = record.get('phenomenon_text', '')
            solution_text = record.get('solution_text', '')
            
            # BERT提取
            phenomenon_entities = []
            if phenomenon_text:
                phen_ents = self.phenomenon_extractor.extract(phenomenon_text)
                phenomenon_entities = [
                    {'text': e[0], 'label': e[1]} 
                    for e in phen_ents if e
                ]
            
            solution_entities = []
            if solution_text:
                sol_ents = self.solution_extractor.extract(solution_text)
                solution_entities = [
                    {'text': e[0], 'label': e[1]} 
                    for e in sol_ents if e
                ]
            
            enhanced_records.append({
                **record,
                'phenomenon_entities': phenomenon_entities,
                'solution_entities': solution_entities
            })
        
        print(f"✅ BERT提取完成: {len(enhanced_records)} 条记录")
        
        # LLM批量检查和修正
        print(f"\n[步骤2] LLM批量检查修正...")
        enhanced_records = self._llm_batch_check(enhanced_records)
        
        return enhanced_records
    
    def _llm_batch_check(self, records: List[Dict]) -> List[Dict]:
        """LLM批量检查和修正"""
        total_batches = (len(records) + self.BATCH_SIZE - 1) // self.BATCH_SIZE
        
        for batch_idx in range(0, len(records), self.BATCH_SIZE):
            batch = records[batch_idx:batch_idx + self.BATCH_SIZE]
            batch_num = batch_idx // self.BATCH_SIZE + 1
            
            print(f"\n  批次 {batch_num}/{total_batches} ({len(batch)} 条记录)")
            
            # 构建BERT结果摘要
            bert_summary = self._build_bert_summary(batch, batch_idx)
            
            # 调用LLM检查
            fixes = self._call_llm_check(bert_summary, len(batch))
            
            if fixes:
                print(f"  ✓ LLM建议修正 {len(fixes)} 条记录")
                # 应用修正
                for fix in fixes:
                    record_id = fix.get('record_id', 0)
                    actual_idx = batch_idx + record_id
                    if actual_idx < len(records):
                        self._apply_fixes(records[actual_idx], fix.get('fixes', []))
            else:
                print(f"  ✓ 无需修正")
        
        return records
    
    def _build_bert_summary(self, batch: List[Dict], start_idx: int) -> str:
        """构建BERT结果摘要"""
        summary = ""
        for i, record in enumerate(batch):
            phen_text = record.get('phenomenon_text', '')
            phen_ents = record.get('phenomenon_entities', [])
            sol_text = record.get('solution_text', '')
            sol_ents = record.get('solution_entities', [])
            
            phen_str = ', '.join([f"{e['text']}({e['label']})" for e in phen_ents]) or "(无)"
            sol_str = ', '.join([f"{e['text']}({e['label']})" for e in sol_ents]) or "(无)"
            
            summary += f"{i}. 现象:\"{phen_text}\" → {phen_str}\n"
            if sol_text:
                summary += f"   方案:\"{sol_text}\" → {sol_str}\n"
        
        return summary
    
    def _call_llm_check(self, bert_summary: str, batch_size: int) -> List[Dict]:
        """调用LLM检查"""
        prompt = self.BATCH_CHECK_PROMPT.format(
            batch_size=batch_size,
            bert_results=bert_summary
        )
        
        try:
            payload = {
                "model": self.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 2048}
            }
            
            response = requests.post(
                self.OLLAMA_API_URL,
                json=payload,
                timeout=90  # 批量处理，给更长超时
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('message', {}).get('content', '')
                
                print(f"  [DEBUG] LLM响应: {content[:200]}...")
                
                if not content:
                    return []
                
                # 提取JSON
                json_match = re.search(r'\[[\s\S]*\]', content)
                if json_match:
                    json_str = json_match.group()
                    print(f"  [DEBUG] 提取JSON: {json_str}")
                    fixes = json.loads(json_str)
                    return fixes
                else:
                    print(f"  ⚠️ 未找到JSON格式")
            
        except requests.exceptions.Timeout:
            print("  ⚠️ LLM检查超时，跳过本批")
        except Exception as e:
            print(f"  ⚠️ LLM检查失败: {e}")
        
        return []
    
    def _apply_fixes(self, record: Dict, fixes: List[Dict]):
        """应用LLM的修正建议"""
        for fix in fixes:
            action = fix.get('action', '')
            
            if action == 'merge':
                # 合并实体
                entities_to_merge = fix.get('entities', [])
                new_entity_text = fix.get('new_entity', '')
                label = fix.get('label', 'COMP')
                
                # 从phenomenon_entities或solution_entities中合并
                for field in ['phenomenon_entities', 'solution_entities']:
                    ents = record.get(field, [])
                    # 移除要合并的实体
                    ents = [e for e in ents if e['text'] not in entities_to_merge]
                    # 添加新实体
                    if new_entity_text:
                        ents.append({'text': new_entity_text, 'label': label, 'source': 'bert+llm'})
                    record[field] = ents
            
            elif action == 'add':
                # 添加新实体
                text = fix.get('text', '')
                label = fix.get('label', 'COMP')
                field = 'phenomenon_entities'  # 默认添加到现象
                
                if text:
                    record[field].append({'text': text, 'label': label, 'source': 'llm'})


if __name__ == "__main__":
    # 测试
    extractor = BatchEntityExtractor()
    
    test_records = [
        {'phenomenon_text': 'K06.01报错', 'solution_text': '重启'},
        {'phenomenon_text': 'OP60传感器异常', 'solution_text': '更换传感器'},
        {'phenomenon_text': 'SMC电缸控制器软件异常', 'solution_text': '更新软件'},
    ]
    
    results = extractor.extract_batch(test_records)
    
    print("\n结果:")
    for i, r in enumerate(results, 1):
        print(f"\n{i}. {r['phenomenon_text']}")
        print(f"   现象实体: {r['phenomenon_entities']}")
        print(f"   方案实体: {r['solution_entities']}")
