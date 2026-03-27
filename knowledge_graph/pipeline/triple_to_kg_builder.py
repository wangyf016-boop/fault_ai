"""
从三元组构建知识图谱
支持灵活修改三元组后重新生成图谱
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple
from tqdm import tqdm


class TripleToKGBuilder:
    """从三元组构建RDF知识图谱"""
    
    def __init__(self, output_dir: Path = None):
        """初始化KG构建器"""
        self.output_dir = output_dir or Path(__file__).resolve().parents[2] / "data" / "output" / "knowledge_graph"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.kg = {
            'devices': {},
            'positions': {},
            'entities': {},
            'phenomena': {},
            'causes': {},
            'solutions': {},
            'relationships': []
        }
        
        print(f"初始化三元组->图谱构建器")
        print(f"  输出目录: {self.output_dir}")
    
    @staticmethod
    def _clean_solution_text(text: str) -> str:
        """
        清理Solution文本：去序号和分段符
        
        示例：
            "1.更换焊头" -> "更换焊头"
            "1. 更换焊头\n2. 调试系统" -> "更换焊头\n调试系统" (但本方法只处理单个文本)
            "更换焊头\n调试系统" -> "更换焊头\n调试系统"
        
        参数：
            text: 原始Solution文本
        
        返回：
            清理后的文本
        """
        if not text:
            return text
        
        # 处理序号的正则表达式（匹配"1."或"1)"或"1、"等形式）
        # 仅在字符串开头或换行后处理
        cleaned = re.sub(r'(?:^|\n)\s*\d+[\.\)、]\s*', lambda m: '\n' if m.group(0).startswith('\n') else '', text)
        
        # 清理多余的换行符
        cleaned = cleaned.strip()
        
        return cleaned

    
    def build_kg_from_triples(self, triples: List[Tuple[str, str, str]], 
                             triple_properties: Dict = None) -> Dict:
        """
        从三元组构建知识图谱
        
        参数：
            triples: 三元组列表 [(subject, predicate, object), ...]
            triple_properties: 三元组的附加属性
        
        返回：
            知识图谱字典
        """
        print("\n从三元组构建图谱...")
        
        if triple_properties is None:
            triple_properties = {}
        
        # 节点ID计数器
        node_counters = {
            'device': 0,
            'position': 0,
            'entity': 0,
            'phenomenon': 0,
            'cause': 0,
            'solution': 0
        }
        
        # 节点名称到ID的映射
        node_id_map = {}
        
        seen_relationships = set()  # 去重关系
        
        for subject, predicate, obj in tqdm(triples, desc="处理三元组"):
            props = triple_properties.get((subject, predicate, obj), {})
            
            if predicate == 'contains':
                # Device -> Position
                # 识别设备节点
                if subject not in node_id_map:
                    device_id = f"device_{node_counters['device']}"
                    node_counters['device'] += 1
                    node_id_map[subject] = device_id
                    self.kg['devices'][subject] = {
                        'id': device_id,
                        'name': subject,
                        'type': 'Device'
                    }
                else:
                    device_id = node_id_map[subject]
                
                # 识别站位节点
                if obj not in node_id_map:
                    position_id = f"position_{node_counters['position']}"
                    node_counters['position'] += 1
                    node_id_map[obj] = position_id
                    self.kg['positions'][obj] = {
                        'id': position_id,
                        'name': obj,
                        'type': 'Station'
                    }
                else:
                    position_id = node_id_map[obj]
                
                # 创建关系
                rel_key = (device_id, position_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    self.kg['relationships'].append({
                        'from': device_id,
                        'to': position_id,
                        'type': predicate
                    })
            
            elif predicate == 'contains_entity':
                # Position -> Entity
                # 识别站位节点
                if subject not in node_id_map:
                    position_id = f"position_{node_counters['position']}"
                    node_counters['position'] += 1
                    node_id_map[subject] = position_id
                    self.kg['positions'][subject] = {
                        'id': position_id,
                        'name': subject,
                        'type': 'Station'
                    }
                else:
                    position_id = node_id_map[subject]
                
                # 识别实体节点
                if obj not in node_id_map:
                    entity_id = f"entity_{node_counters['entity']}"
                    node_counters['entity'] += 1
                    node_id_map[obj] = entity_id
                    self.kg['entities'][obj] = {
                        'id': entity_id,
                        'name': obj,
                        'type': 'Entity'
                    }
                else:
                    entity_id = node_id_map[obj]
                
                # 创建关系
                rel_key = (position_id, entity_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    self.kg['relationships'].append({
                        'from': position_id,
                        'to': entity_id,
                        'type': predicate
                    })
            
            elif predicate == 'exhibits_phenomenon':
                # Entity -> Phenomenon
                # 识别实体节点
                if subject not in node_id_map:
                    entity_id = f"entity_{node_counters['entity']}"
                    node_counters['entity'] += 1
                    node_id_map[subject] = entity_id
                    self.kg['entities'][subject] = {
                        'id': entity_id,
                        'name': subject,
                        'type': 'Entity'
                    }
                else:
                    entity_id = node_id_map[subject]
                
                # 识别问题节点 (Problem)
                if obj not in node_id_map:
                    phenomenon_id = f"phenomenon_{node_counters['phenomenon']}"
                    node_counters['phenomenon'] += 1
                    node_id_map[obj] = phenomenon_id
                    self.kg['phenomena'][obj] = {
                        'id': phenomenon_id,
                        'name': obj,
                        'type': 'Problem',
                        'description': props.get('description', obj),  # 完整故障描述
                        'timestamp': props.get('timestamp', '')  # 时间戳
                    }
                else:
                    phenomenon_id = node_id_map[obj]
                    # 更新已存在节点的description和timestamp（只在新值更完整时更新）
                    if obj in self.kg['phenomena']:  # 检查节点是否存在
                        if 'description' in props and props['description']:
                            # 只在新description更长时才更新（完整描述通常更长）
                            current_desc = self.kg['phenomena'][obj].get('description', '')
                            if len(props['description']) > len(current_desc):
                                self.kg['phenomena'][obj]['description'] = props['description']
                        if 'timestamp' in props and props['timestamp']:
                            self.kg['phenomena'][obj]['timestamp'] = props['timestamp']
                
                # 创建关系（含属性）
                rel_key = (entity_id, phenomenon_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': entity_id,
                        'to': phenomenon_id,
                        'type': predicate
                    }
                    # 添加属性
                    if 'timestamp' in props:
                        rel['timestamp'] = props['timestamp']
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
            
            elif predicate == 'causes_phenomenon':
                # Cause -> Phenomenon
                # 识别原因节点
                if subject not in node_id_map:
                    cause_id = f"cause_{node_counters['cause']}"
                    node_counters['cause'] += 1
                    node_id_map[subject] = cause_id
                    self.kg['causes'][subject] = {
                        'id': cause_id,
                        'text': subject,
                        'type': 'Cause',
                        'cause_type': props.get('cause_type', 'general')
                    }
                    if 'confidence' in props:
                        self.kg['causes'][subject]['confidence'] = props['confidence']
                else:
                    cause_id = node_id_map[subject]
                
                # 识别现象节点
                if obj not in node_id_map:
                    phenomenon_id = f"phenomenon_{node_counters['phenomenon']}"
                    node_counters['phenomenon'] += 1
                    node_id_map[obj] = phenomenon_id
                    self.kg['phenomena'][obj] = {
                        'id': phenomenon_id,
                        'name': obj,
                        'type': 'Phenomenon'
                    }
                else:
                    phenomenon_id = node_id_map[obj]
                
                # 创建关系
                rel_key = (cause_id, phenomenon_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': cause_id,
                        'to': phenomenon_id,
                        'type': predicate
                    }
                    if 'confidence' in props:
                        rel['confidence'] = props['confidence']
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
            
            elif predicate == 'solves_phenomenon':
                # Solution -> Phenomenon
                # 清理Solution文本：去序号和分段
                solution_text_cleaned = self._clean_solution_text(subject)
                
                # 识别解决方案节点（使用清理后的文本）
                if solution_text_cleaned not in node_id_map:
                    solution_id = f"solution_{node_counters['solution']}"
                    node_counters['solution'] += 1
                    node_id_map[solution_text_cleaned] = solution_id
                    self.kg['solutions'][solution_text_cleaned] = {
                        'id': solution_id,
                        'text': solution_text_cleaned,
                        'type': 'Solution'
                    }
                else:
                    solution_id = node_id_map[solution_text_cleaned]
                
                # 识别问题节点
                if obj not in node_id_map:
                    phenomenon_id = f"phenomenon_{node_counters['phenomenon']}"
                    node_counters['phenomenon'] += 1
                    node_id_map[obj] = phenomenon_id
                    self.kg['phenomena'][obj] = {
                        'id': phenomenon_id,
                        'name': obj,
                        'type': 'Problem',
                        'description': obj,
                        'timestamp': ''
                    }
                else:
                    phenomenon_id = node_id_map[obj]
                
                # 创建关系（使用清理后的Solution文本）
                rel_key = (solution_id, phenomenon_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': solution_id,
                        'to': phenomenon_id,
                        'type': predicate
                    }
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
            
            elif predicate == 'OCCURRED_AT_STATION':
                # Problem -> Station (问题发生于站位)
                # 识别问题节点
                if subject not in node_id_map:
                    phenomenon_id = f"phenomenon_{node_counters['phenomenon']}"
                    node_counters['phenomenon'] += 1
                    node_id_map[subject] = phenomenon_id
                    self.kg['phenomena'][subject] = {
                        'id': phenomenon_id,
                        'name': subject,
                        'type': 'Problem',
                        'description': props.get('description', subject),
                        'timestamp': props.get('timestamp', '')
                    }
                else:
                    phenomenon_id = node_id_map[subject]
                    # 更新已存在节点的description和timestamp（只在新值更完整时更新）
                    if subject in self.kg['phenomena']:  # 检查节点是否存在
                        if 'description' in props and props['description']:
                            current_desc = self.kg['phenomena'][subject].get('description', '')
                            if len(props['description']) > len(current_desc):
                                self.kg['phenomena'][subject]['description'] = props['description']
                        if 'timestamp' in props and props['timestamp']:
                            self.kg['phenomena'][subject]['timestamp'] = props['timestamp']
                
                # 识别站位节点
                if obj not in node_id_map:
                    position_id = f"position_{node_counters['position']}"
                    node_counters['position'] += 1
                    node_id_map[obj] = position_id
                    self.kg['positions'][obj] = {
                        'id': position_id,
                        'name': obj,
                        'type': 'Station'
                    }
                else:
                    position_id = node_id_map[obj]
                
                # 创建关系
                rel_key = (phenomenon_id, position_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': phenomenon_id,
                        'to': position_id,
                        'type': predicate
                    }
                    if 'timestamp' in props:
                        rel['timestamp'] = props['timestamp']
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
            
            elif predicate == 'has_cause':
                # Problem -> Cause (新的线性关系)
                # 识别问题节点
                if subject not in node_id_map:
                    phenomenon_id = f"phenomenon_{node_counters['phenomenon']}"
                    node_counters['phenomenon'] += 1
                    node_id_map[subject] = phenomenon_id
                    self.kg['phenomena'][subject] = {
                        'id': phenomenon_id,
                        'name': subject,
                        'type': 'Problem',
                        'description': props.get('description', subject),
                        'timestamp': ''
                    }
                else:
                    phenomenon_id = node_id_map[subject]
                    # 更新已存在节点的description（只在新值更完整时更新）
                    if subject in self.kg['phenomena']:  # 检查节点是否存在
                        if 'description' in props and props['description']:
                            current_desc = self.kg['phenomena'][subject].get('description', '')
                            if len(props['description']) > len(current_desc):
                                self.kg['phenomena'][subject]['description'] = props['description']
                
                # 识别原因节点
                if obj not in node_id_map:
                    cause_id = f"cause_{node_counters['cause']}"
                    node_counters['cause'] += 1
                    node_id_map[obj] = cause_id
                    self.kg['causes'][obj] = {
                        'id': cause_id,
                        'text': obj,
                        'type': 'Cause',
                        'cause_type': props.get('cause_type', 'general')
                    }
                    if 'confidence' in props:
                        self.kg['causes'][obj]['confidence'] = props['confidence']
                else:
                    cause_id = node_id_map[obj]
                
                # 创建关系
                rel_key = (phenomenon_id, cause_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': phenomenon_id,
                        'to': cause_id,
                        'type': predicate
                    }
                    if 'confidence' in props:
                        rel['confidence'] = props['confidence']
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
            
            elif predicate == 'has_solution':
                # Cause -> Solution (新的线性关系)
                # 识别原因节点
                if subject not in node_id_map:
                    cause_id = f"cause_{node_counters['cause']}"
                    node_counters['cause'] += 1
                    node_id_map[subject] = cause_id
                    self.kg['causes'][subject] = {
                        'id': cause_id,
                        'text': subject,
                        'type': 'Cause',
                        'cause_type': props.get('cause_type', 'general')
                    }
                else:
                    cause_id = node_id_map[subject]
                
                # 清理Solution文本：去序号和分段
                solution_text_cleaned = self._clean_solution_text(obj)
                
                # 识别解决方案节点（使用清理后的文本）
                if solution_text_cleaned not in node_id_map:
                    solution_id = f"solution_{node_counters['solution']}"
                    node_counters['solution'] += 1
                    node_id_map[solution_text_cleaned] = solution_id
                    self.kg['solutions'][solution_text_cleaned] = {
                        'id': solution_id,
                        'text': solution_text_cleaned,
                        'type': 'Solution',
                        'actions': props.get('actions', []),      # 动作实体
                        'components': props.get('components', [])  # 部件实体
                    }
                else:
                    solution_id = node_id_map[solution_text_cleaned]
                
                # 创建关系（使用清理后的文本）
                rel_key = (cause_id, solution_id, predicate)
                if rel_key not in seen_relationships:
                    seen_relationships.add(rel_key)
                    rel = {
                        'from': cause_id,
                        'to': solution_id,
                        'type': predicate
                    }
                    if 'year' in props:
                        rel['year'] = props['year']
                    
                    self.kg['relationships'].append(rel)
        
        print(f"\n[OK] 从三元组构建图谱完成")
        print(f"  设备节点: {len(self.kg['devices'])}")
        print(f"  站位节点: {len(self.kg['positions'])}")
        print(f"  实体节点: {len(self.kg['entities'])}")
        print(f"  现象节点: {len(self.kg['phenomena'])}")
        print(f"  原因节点: {len(self.kg['causes'])}")
        print(f"  方案节点: {len(self.kg['solutions'])}")
        print(f"  关系数量: {len(self.kg['relationships'])}")
        
        return self.kg
    
    def save_kg_to_json(self, filename: str = "kg_from_triples.json") -> Path:
        """保存图谱为JSON"""
        if not any(self.kg.values()):
            print("[ERROR] 图谱为空，无法保存")
            return None
        
        output_path = self.output_dir / filename
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.kg, f, ensure_ascii=False, indent=2)
        
        print(f"\n[OK] 图谱已保存为JSON")
        print(f"  文件: {output_path}")
        
        return output_path
    
    def print_kg_summary(self):
        """打印图谱摘要"""
        print("\n[INFO] 知识图谱摘要")
        print("-" * 60)
        print(f"节点统计:")
        print(f"  设备: {len(self.kg['devices'])}")
        print(f"  站位: {len(self.kg['positions'])}")
        print(f"  实体: {len(self.kg['entities'])}")
        print(f"  现象: {len(self.kg['phenomena'])}")
        print(f"  原因: {len(self.kg['causes'])}")
        print(f"  方案: {len(self.kg['solutions'])}")
        print(f"\n关系统计:")
        rel_types = {}
        for rel in self.kg['relationships']:
            rel_type = rel['type']
            rel_types[rel_type] = rel_types.get(rel_type, 0) + 1
        
        for rel_type in sorted(rel_types.keys()):
            print(f"  {rel_type}: {rel_types[rel_type]}")
        
        print(f"\n总计: {sum(len(v) for k, v in self.kg.items() if k != 'relationships')} 节点, {len(self.kg['relationships'])} 关系")


if __name__ == "__main__":
    # 测试示例
    builder = TripleToKGBuilder()
    
    # 模拟三元组
    test_triples = [
        ('焊接机A', 'contains', '站位1'),
        ('焊接机A', 'contains', '站位2'),
        ('站位1', 'contains_entity', '焊头'),
        ('站位2', 'contains_entity', '电弧'),
        ('焊头', 'exhibits_phenomenon', '磨损'),
        ('电弧', 'exhibits_phenomenon', '差异常'),
        ('高频使用', 'causes_phenomenon', '磨损'),
        ('气压不稳定', 'causes_phenomenon', '差异常'),
        ('更换焊头', 'solves_phenomenon', '磨损'),
        ('调整参数', 'solves_phenomenon', '差异常'),
    ]
    
    test_properties = {
        ('焊头', 'exhibits_phenomenon', '磨损'): {'timestamp': '2025-01-15', 'year': 2025},
        ('高频使用', 'causes_phenomenon', '磨损'): {'cause_type': 'direct', 'confidence': 0.9},
    }
    
    # 构建KG
    kg = builder.build_kg_from_triples(test_triples, test_properties)
    
    # 保存
    builder.save_kg_to_json('test_kg.json')
    
    # 摘要
    builder.print_kg_summary()
