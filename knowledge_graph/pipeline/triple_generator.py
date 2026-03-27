"""
三元组生成器模块
从维修记录生成标准化的三元组（RDF格式）
支持修改和版本控制
"""

import pandas as pd
import json
from pathlib import Path
from typing import List, Dict, Tuple
from tqdm import tqdm


class TripleGenerator:
    """从BERT提取的实体生成RDF三元组"""
    
    # 定义关系类型
    RELATION_TYPES = {
        'contains': '包含',           # Device -> Station
        'contains_entity': '包含部件',  # Station -> Entity
        'exhibits_phenomenon': '呈现现象',  # Entity -> Problem
        'has_cause': '故障原因',    # Problem -> Cause
        'has_solution': '解决方案'     # Cause -> Solution
    }
    
    def __init__(self, output_dir: Path = None):
        """初始化三元组生成器"""
        self.output_dir = output_dir or Path(__file__).resolve().parents[2] / "data" / "output" / "knowledge_graph"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 三元组存储
        self.triples = []  # List[Tuple[str, str, str]]
        self.triple_properties = {}  # 额外属性存储
        
        print(f"初始化三元组生成器")
        print(f"  输出目录: {self.output_dir}")

    def _split_phenomenon_by_entity(self, entity_name: str, phenomenon_text: str) -> str:
        """
        尝试从现象文本中去除实体名称，返回更纯粹的现象描述。
        例: entity=工件, phenomenon_text=工件卡死 -> 卡死
        """
        if not entity_name or not phenomenon_text:
            return ""

        text = str(phenomenon_text).strip()
        entity = str(entity_name).strip()

        if not text or not entity or text == entity:
            return ""

        remainder = ""
        if text.startswith(entity):
            remainder = text[len(entity):]
        elif entity in text:
            remainder = text.replace(entity, "", 1)
        else:
            return ""

        remainder = remainder.strip(" :：-—_，,。.;；/\\()（）[]【】")
        remainder = remainder.strip()

        if len(remainder) < 1:
            return ""

        return remainder
    
    def generate_triples_from_records(self, records: List[Dict]) -> List[Tuple[str, str, str]]:
        """
        从记录生成三元组
        
        参数：
            records: 包含BERT提取的实体和信息的记录列表
        
        返回：
            三元组列表 [(subject, predicate, object), ...]
        """
        print("\n生成三元组...")
        
        triples = []
        triple_metadata = {}  # 三元组元数据（置信度、时间戳等）
        
        for record in tqdm(records, desc="生成三元组"):
            device = str(record.get('device', '')).strip()
            position = str(record.get('position', '')).strip()
            year = record.get('year', 'unknown')
            timestamp = record.get('timestamp', '')
            
            # 1. Device -> Position (contains)
            if position:
                triple = (device, 'contains', position)
                if triple not in triples:
                    triples.append(triple)
            
            # 2. Position -> Entity (contains_entity) - 站位包含元件
            phenomenon_entities_list = record.get('phenomenon_entities', [])
            entities = []
            for entity in phenomenon_entities_list:
                if entity['label'] in ['COMP', 'COMPONENT', 'COMP_FAULT']:
                    entity_name = entity.get('text', '').strip()
                    if entity_name and len(entity_name) >= 2:
                        entities.append(entity_name)
                        # 生成站位到元件的关系
                        if position:
                            triple = (position, 'contains_entity', entity_name)
                            if triple not in triples:
                                triples.append(triple)
                                triple_metadata[triple] = {'source': 'phenomenon'}
            
            # 3. Entity -> Problem (exhibits_phenomenon) - 元件呈现问题
            # 使用原始故障现象文本作为问题名称
            phenomenon_text = record.get('phenomenon_text', '').strip()
            full_description = record.get('full_description', '').strip()  # 完整故障描述
            phenomenon_nodes_for_causes = []
            
            if phenomenon_text and len(phenomenon_text) >= 2:
                # 为每个元件生成到问题的关系
                for entity_name in entities:
                    split_text = self._split_phenomenon_by_entity(entity_name, phenomenon_text)
                    final_phenomenon = split_text if split_text else phenomenon_text
                    triple = (entity_name, 'exhibits_phenomenon', final_phenomenon)
                    if triple not in triples:
                        triples.append(triple)
                        triple_metadata[triple] = {
                            'timestamp': timestamp,
                            'year': year,
                            'source': 'raw_text',
                            'description': full_description,  # 添加完整描述
                            'phenomenon_original': phenomenon_text if split_text else '',
                            'phenomenon_split': bool(split_text)
                        }
                    if split_text:
                        phenomenon_nodes_for_causes.append(split_text)
            
            # 4. Phenomenon -> Cause (has_cause) - 现象指向原因
            # 支持两种格式：causes数组（旧格式）或cause字段（新格式）
            causes_list = record.get('causes', [])
            if not causes_list:
                # 如果没有causes数组，检查cause字段
                cause_text = record.get('cause', '').strip()
                if cause_text and len(cause_text) >= 2:
                    causes_list = [{'text': cause_text, 'confidence': 1.0, 'type': 'predicted'}]
            
            # 为每个现象关联原因
            phenomenon_text = record.get('phenomenon_text', '').strip()
            full_description = record.get('full_description', '').strip()
            if phenomenon_text and len(phenomenon_text) >= 2:
                if phenomenon_nodes_for_causes:
                    target_phenomena = sorted(set(phenomenon_nodes_for_causes))
                else:
                    target_phenomena = [phenomenon_text]

                for cause in causes_list:
                    cause_text = cause.get('text', '').strip()
                    if cause_text and len(cause_text) >= 2:
                        for phen in target_phenomena:
                            triple = (phen, 'has_cause', cause_text)
                            if triple not in triples:
                                triples.append(triple)
                                confidence = cause.get('confidence', 1.0)
                                triple_metadata[triple] = {
                                    'cause_type': cause.get('type', 'general'),
                                    'confidence': confidence,
                                    'year': year,
                                    'description': full_description,  # 添加完整描述
                                    'phenomenon_original': phenomenon_text if phen != phenomenon_text else ''
                                }
            
            # 5. Cause -> Solution (has_solution) - 原因指向解决方案
            # 支持新格式：solution_items（拆分后的solution列表）
            solution_items = record.get('solution_items', [])
            if solution_items:
                # 新格式：拆分后的solution
                for cause in causes_list:
                    cause_text = cause.get('text', '').strip()
                    if cause_text and len(cause_text) >= 2:
                        for sol_item in solution_items:
                            sol_text = sol_item.get('text', '').strip()
                            if sol_text and len(sol_text) >= 2:
                                triple = (cause_text, 'has_solution', sol_text)
                                if triple not in triples:
                                    triples.append(triple)
                                    # 保存solution的实体属性
                                    triple_metadata[triple] = {
                                        'source': 'split',
                                        'year': year,
                                        'actions': sol_item.get('actions', []),
                                        'components': sol_item.get('components', [])
                                    }
            else:
                # 旧格式：solution_entities（兼容）
                for cause in causes_list:
                    cause_text = cause.get('text', '').strip()
                    if cause_text and len(cause_text) >= 2:
                        for solution in record.get('solution_entities', []):
                            sol_name = solution.get('text', '').strip()
                            if sol_name and len(sol_name) >= 2:
                                triple = (cause_text, 'has_solution', sol_name)
                                if triple not in triples:
                                    triples.append(triple)
                                    triple_metadata[triple] = {
                                        'source': solution.get('source', 'unknown'),
                                        'year': year
                                    }
        
        self.triples = triples
        self.triple_properties = triple_metadata
        
        print(f"\n[OK] 生成三元组完成")
        print(f"  总三元组数: {len(triples)}")
        
        # 统计各类关系
        rel_counts = {}
        for s, p, o in triples:
            rel_counts[p] = rel_counts.get(p, 0) + 1
        
        print(f"\n  关系类型统计:")
        for rel_type in sorted(self.RELATION_TYPES.keys()):
            count = rel_counts.get(rel_type, 0)
            if count > 0:
                print(f"    ├─ {rel_type}: {count}")
        
        return triples
    
    def save_triples_to_csv(self, filename: str = "triples.csv") -> Path:
        """保存三元组为CSV格式"""
        if not self.triples:
            print("❌ 没有三元组可保存")
            return None
        
        output_path = self.output_dir / filename
        
        # 构建DataFrame
        data = []
        for subject, predicate, obj in self.triples:
            row = {
                'subject': subject,
                'predicate': predicate,
                'object': obj
            }
            # 添加额外属性（如果有）
            triple_key = (subject, predicate, obj)
            if triple_key in self.triple_properties:
                props = self.triple_properties[triple_key]
                for key, value in props.items():
                    row[f'prop_{key}'] = value
            
            data.append(row)
        
        df = pd.DataFrame(data)
        df.to_csv(output_path, index=False, encoding='utf-8-sig')
        
        print(f"\n[OK] 三元组已保存为CSV")
        print(f"  文件: {output_path}")
        print(f"  行数: {len(df)}")
        
        return output_path
    
    def save_triples_to_json(self, filename: str = "triples.json") -> Path:
        """保存三元组为JSON格式（便于修改）"""
        if not self.triples:
            print("❌ 没有三元组可保存")
            return None
        
        output_path = self.output_dir / filename
        
        # 构建JSON结构
        data = {
            'metadata': {
                'total': len(self.triples),
                'format': 'RDF三元组',
                'relations': {
                    rel: sum(1 for s, p, o in self.triples if p == rel)
                    for rel in set(p for s, p, o in self.triples)
                }
            },
            'triples': [
                {
                    'subject': s,
                    'predicate': p,
                    'object': o,
                    **self.triple_properties.get((s, p, o), {})
                }
                for s, p, o in self.triples
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] 三元组已保存为JSON")
        print(f"  文件: {output_path}")
        print(f"  便于编辑: {output_path}")
        
        return output_path
    
    def load_triples_from_csv(self, filename: str) -> List[Tuple[str, str, str]]:
        """从CSV加载三元组"""
        file_path = self.output_dir / filename
        
        if not file_path.exists():
            print(f"[ERROR] 文件不存在: {file_path}")
            return []
        
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        triples = []
        properties = {}
        
        for idx, row in df.iterrows():
            subject = row['subject']
            predicate = row['predicate']
            obj = row['object']
            
            triple = (subject, predicate, obj)
            triples.append(triple)
            
            # 提取其他属性列
            props = {}
            for col in df.columns:
                if col.startswith('prop_'):
                    prop_name = col[5:]  # 移除'prop_'前缀
                    if pd.notna(row[col]):
                        props[prop_name] = row[col]
            
            if props:
                properties[triple] = props
        
        self.triples = triples
        self.triple_properties = properties
        
        print(f"[OK] 已加载三元组")
        print(f"  文件: {file_path}")
        print(f"  总数: {len(triples)}")
        
        return triples
    
    def load_triples_from_json(self, filename: str) -> List[Tuple[str, str, str]]:
        """从JSON加载三元组"""
        file_path = self.output_dir / filename
        
        if not file_path.exists():
            print(f"[ERROR] 文件不存在: {file_path}")
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        triples = []
        properties = {}
        
        for triple_data in data.get('triples', []):
            subject = triple_data['subject']
            predicate = triple_data['predicate']
            obj = triple_data['object']
            
            triple = (subject, predicate, obj)
            triples.append(triple)
            
            # 提取元数据（除了三个核心字段）
            props = {k: v for k, v in triple_data.items() 
                    if k not in ['subject', 'predicate', 'object']}
            
            if props:
                properties[triple] = props
        
        self.triples = triples
        self.triple_properties = properties
        
        print(f"✅ 已加载三元组")
        print(f"  文件: {file_path}")
        print(f"  总数: {len(triples)}")
        
        return triples
    
    def export_statistics(self) -> Dict:
        """导出三元组统计信息"""
        stats = {
            'total_triples': len(self.triples),
            'relation_types': {},
            'subject_types': {},
            'entities': set(),
            'relations': set()
        }
        
        for subject, predicate, obj in self.triples:
            # 关系类型统计
            stats['relation_types'][predicate] = stats['relation_types'].get(predicate, 0) + 1
            
            # 实体数量
            stats['entities'].add(subject)
            stats['entities'].add(obj)
            
            # 关系类型
            stats['relations'].add(predicate)
        
        stats['total_entities'] = len(stats['entities'])
        stats['entities'] = sorted(list(stats['entities']))
        stats['relations'] = sorted(list(stats['relations']))
        
        return stats
    
    def print_sample_triples(self, limit: int = 20):
        """打印示例三元组"""
        print(f"\n[INFO] 三元组示例 (前{limit}个):")
        print("-" * 80)
        print(f"{'Subject':<20} | {'Predicate':<20} | {'Object':<20}")
        print("-" * 80)
        
        for subject, predicate, obj in self.triples[:limit]:
            # 截断长字符串
            s = subject[:18] if len(subject) > 18 else subject
            p = predicate[:18] if len(predicate) > 18 else predicate
            o = obj[:18] if len(obj) > 18 else obj
            print(f"{s:<20} | {p:<20} | {o:<20}")
        
        if len(self.triples) > limit:
            print(f"\n... 还有 {len(self.triples) - limit} 个三元组")


if __name__ == "__main__":
    # 测试示例
    generator = TripleGenerator()
    
    # 模拟记录
    test_records = [
        {
            'device': '焊接机A',
            'position': '站位1',
            'year': 2025,
            'timestamp': '2025-01-15',
            'phenomenon_entities': [
                {'text': '焊头', 'label': 'COMP'},
                {'text': '磨损', 'label': 'PHEN'}
            ],
            'solution_entities': [
                {'text': '更换焊头', 'label': 'ACT', 'source': 'bert'}
            ],
            'causes': [
                {'type': 'direct', 'text': '高频使用', 'confidence': 0.9}
            ]
        },
        {
            'device': '焊接机A',
            'position': '站位2',
            'year': 2025,
            'timestamp': '2025-01-20',
            'phenomenon_entities': [
                {'text': '电弧', 'label': 'COMP'},
                {'text': '差异常', 'label': 'PHEN'}
            ],
            'solution_entities': [
                {'text': '调整参数', 'label': 'ACT', 'source': 'rule'}
            ],
            'causes': [
                {'type': 'root', 'text': '气压不稳定', 'confidence': 0.85}
            ]
        }
    ]
    
    # 生成三元组
    triples = generator.generate_triples_from_records(test_records)
    
    # 保存
    generator.save_triples_to_csv('test_triples.csv')
    generator.save_triples_to_json('test_triples.json')
    
    # 统计
    stats = generator.export_statistics()
    print("\n📈 统计信息:")
    print(f"  总三元组数: {stats['total_triples']}")
    print(f"  总实体数: {stats['total_entities']}")
    print(f"  关系类型: {stats['relation_types']}")
    
    # 打印示例
    generator.print_sample_triples(10)
