"""
多年度数据融合处理脚本
处理2019+2022+2023年数据，与2025年数据融合构建知识图谱
"""

import pandas as pd
import json
from pathlib import Path
import torch
from transformers import BertTokenizer, BertForTokenClassification
from tqdm import tqdm
import sys

# 添加项目路径
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# 定义标签列表（基于模型实际的标签体系）
# 故障现象模型：COMP=故障部件, PHEN=故障现象
PHENOMENON_LABELS = ['O', 'B-COMP', 'I-COMP', 'B-PHEN', 'I-PHEN']
# 解决方案模型：COMP=涉及部件, ACT=动作/方案
SOLUTION_LABELS = ['O', 'B-COMP', 'I-COMP', 'B-ACT', 'I-ACT']


class MultiYearDataProcessor:
    """多年度维修数据处理器"""
    
    def __init__(self):
        self.project_root = Path(__file__).resolve().parents[2]
        self.data_input_dir = self.project_root / "data" / "input"
        self.output_dir = self.project_root / "data" / "output" / "knowledge_graph"
        self.predictions_dir = self.project_root / "data" / "predictions"  # 预测数据目录
        
        # 预测数据文件（包含LLM预测的原因）
        self.prediction_file = self.predictions_dir / "step1_2_data_and_prediction.csv"
        self.prediction_data = None  # 延迟加载
        
        # 加载BERT模型
        self.phenomenon_model_path = self.project_root / "models" / "saved" / "model_output" / "phenomenon"
        self.solution_model_path = self.project_root / "models" / "saved" / "model_output" / "solution"
        
        print("正在加载BERT-CRF模型...")
        print(f"  现象模型路径: {self.phenomenon_model_path}")
        print(f"  解决方案模型路径: {self.solution_model_path}")
        
        # 使用local_files_only参数加载本地模型
        self.tokenizer = BertTokenizer.from_pretrained(
            str(self.phenomenon_model_path),
            local_files_only=True
        )
        self.phenomenon_model = BertForTokenClassification.from_pretrained(
            str(self.phenomenon_model_path),
            local_files_only=True
        )
        self.solution_model = BertForTokenClassification.from_pretrained(
            str(self.solution_model_path),
            local_files_only=True
        )
        
        # 设备选择：优先GPU（支持CUDA和DirectML）
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
            device_name = f"NVIDIA {torch.cuda.get_device_name(0)}"
        else:
            try:
                import torch_directml
                self.device = torch_directml.device()
                device_name = "AMD GPU (DirectML)"
            except:
                self.device = torch.device("cpu")
                device_name = "CPU"
        
        self.phenomenon_model.eval()
        self.solution_model.eval()
        self.phenomenon_model.to(self.device)
        self.solution_model.to(self.device)
        
        print(f"✅ 模型已加载到 {device_name}")
        
        if torch.cuda.is_available():
            print(f"   GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    
    def load_prediction_data(self):
        """加载预测数据（包含LLM预测的原因）"""
        if self.prediction_data is not None:
            return self.prediction_data
        
        if not self.prediction_file.exists():
            print(f"⚠️ 预测数据文件不存在: {self.prediction_file}")
            return None
        
        try:
            # 尝试不同编码
            for encoding in ['gbk', 'gb18030', 'utf-8-sig', 'utf-8']:
                try:
                    df = pd.read_csv(self.prediction_file, encoding=encoding)
                    print(f"✅ 已加载预测数据: {len(df)} 条 (编码: {encoding})")
                    self.prediction_data = df
                    return df
                except:
                    continue
            print(f"❌ 无法读取预测数据文件")
            return None
        except Exception as e:
            print(f"❌ 加载预测数据失败: {e}")
            return None
    
    def normalize_entity_text(self, text):
        """规范化实体文本（去除多余空格、统一格式）"""
        if not text:
            return None
        # 去除[UNK]标记（多种格式）
        text = text.replace('[UNK]', '').replace('[unk]', '').replace('UNK', '')
        # 去除##子词标记残留
        text = text.replace('##', '')
        # 去除多余空格
        text = ' '.join(text.split())
        # 去除常见前后缀符号
        text = text.strip('，。、；：""''！？（）【】《》·-—_1234567890. ')
        # 最终检查：如果包含[或]，或长度不足，返回None
        if not text or len(text) < 2 or '[' in text or ']' in text:
            return None
        return text
    
    def extract_solutions_by_rules(self, text):
        """使用规则从解决对策文本中提取解决方案实体"""
        import re
        
        if not text or pd.isna(text) or len(str(text).strip()) < 3:
            return []
        
        text = str(text)
        solutions = []
        
        # 常见动作词（用于匹配解决方案）
        action_words = [
            '更换', '更新', '替换', '调整', '调试', '校准', '修复', '维修', '修理',
            '清洁', '清洗', '清理', '擦拭', '检查', '检测', '排查', '复位', '重启',
            '紧固', '拧紧', '固定', '安装', '拆卸', '拆除', '添加', '补充', '加注',
            '润滑', '上油', '涂抹', '焊接', '补焊', '打磨', '抛光', '疏通', '清堵',
            '校正', '对齐', '调节', '设置', '配置', '升级', '刷新', '初始化',
            '更改', '修改', '优化', '改进', '处理', '解决'
        ]
        
        # 方法1：按序号分割（如 "1.xxx 2.xxx" 或 "1、xxx 2、xxx"）
        # 匹配 "数字." 或 "数字、" 或 "数字:" 开头的部分
        parts = re.split(r'[;；\n]|(?=\d+[.、:：])', text)
        
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # 去除开头的序号
            part = re.sub(r'^\d+[.、:：\s]*', '', part).strip()
            
            if len(part) < 2:
                continue
            
            # 方法2：提取"动作词+对象"模式
            for action in action_words:
                if action in part:
                    # 提取动作词及其后面的对象（最多10个字符）
                    pattern = f'{action}[^，。；\n]{{0,15}}'
                    matches = re.findall(pattern, part)
                    for match in matches:
                        match = match.strip('，。、；：""''！？（）【】《》·-—_ ')
                        if len(match) >= 2 and len(match) <= 20:
                            solutions.append({
                                'text': match,
                                'label': 'ACT',
                                'source': 'rule'
                            })
        
        # 去重
        seen = set()
        unique_solutions = []
        for sol in solutions:
            if sol['text'] not in seen:
                seen.add(sol['text'])
                unique_solutions.append(sol)
        
        return unique_solutions
    
    def load_and_clean_data(self, year):
        """加载并清洗指定年份数据（支持2019-2025所有年份）"""
        file_mapping = {
            2019: "2019年度维修交接班记录表 .csv",
            2020: "2020年度维修交接班记录表 .csv",
            2021: "2021年度维修交接班记录表  .csv",  # 注意：有两个空格
            2022: "2022年度维修交接班记录表  .csv",
            2023: "2023年度维修交接班记录表 1 .csv",
            2024: "2024年度维修交接班记录表新1 .csv",
            2025: "data/predictions/step1_2_data_and_prediction.csv"
        }
        
        file_path = self.data_input_dir / file_mapping[year]
        print(f"\n加载 {year} 年数据: {file_path.name}")
        
        # 尝试多种编码方式读取CSV
        encodings = ['utf-8-sig', 'gbk', 'gb18030', 'latin1']
        df = None
        
        for encoding in encodings:
            try:
                # 2019/2022/2023格式：第一行是标题，第二行是列名，需要跳过第一行
                if year in [2019, 2022, 2023]:
                    df = pd.read_csv(file_path, encoding=encoding, skiprows=1, low_memory=False)
                else:
                    # 2020/2021/2024/2025格式：列名可能是"2020年, Unnamed: 1..."，实际列名在第一行数据中
                    df_temp = pd.read_csv(file_path, encoding=encoding, nrows=1, low_memory=False)
                    # 检查列名是否包含"Unnamed"（说明第一行数据是真正的列名）
                    if any('Unnamed' in str(col) for col in df_temp.columns):
                        # 从第一行数据中提取列名
                        column_names = df_temp.iloc[0].tolist()
                        # 跳过原标题行(0) + 列名行(1) = skiprows=2
                        df = pd.read_csv(file_path, encoding=encoding, skiprows=2, names=column_names, low_memory=False)
                    else:
                        # 正常格式
                        df = pd.read_csv(file_path, encoding=encoding, low_memory=False)
                
                print(f"  使用编码: {encoding}")
                break
            except Exception as e:
                continue
        
        if df is None:
            raise ValueError(f"无法读取 {year} 年数据文件，尝试了所有编码")
        
        original_count = len(df)
        
        # 标准化列名（不同年份格式不同）
        # 2019/2022/2023: 有标准列名（设备、站位、故障现象等）
        # 2020/2021/2024/2025: 列名可能是序号、年、月等
        
        # 自动识别关键字段
        col_mapping = {}
        for col in df.columns:
            # 跳过NaN列名
            if pd.isna(col):
                continue
            
            # 统一转换为字符串进行比较
            col_str = str(col)
            col_lower = col_str.lower()
            
            if '设备' in col_str or col_str == 'EPB' or col_str == 'C11' or col_str == 'C12':
                col_mapping['设备'] = col
            if '站位' in col_str or 'op' in col_lower:
                col_mapping['站位'] = col
            if '故障现象' in col_str or '现象' in col_str:
                col_mapping['故障现象'] = col
            if '解决对策' in col_str or '对策' in col_str or '措施' in col_str:
                col_mapping['解决对策'] = col
            if '故障直接原因' in col_str or '直接原因' in col_str:
                col_mapping['故障直接原因'] = col
            if '故障根本原因' in col_str or '根本原因' in col_str:
                col_mapping['故障根本原因'] = col
            if '故障原因' in col_str and '直接' not in col_str and '根本' not in col_str:
                col_mapping['故障原因'] = col
        
        # 删除完全空白的行
        df = df.dropna(how='all')
        
        # 删除关键字段全部为空的行（如果识别到了这些字段）
        if '设备' in col_mapping:
            df = df.dropna(subset=[col_mapping['设备']], how='all')
        
        cleaned_count = len(df)
        print(f"  原始行数: {original_count:,}")
        print(f"  清洗后行数: {cleaned_count:,}")
        print(f"  删除空白行: {original_count - cleaned_count:,}")
        print(f"  识别到字段: {list(col_mapping.keys())}")
        
        return df, col_mapping
    
    def extract_entities_with_bert(self, text, model, label_list):
        """使用BERT-CRF提取实体"""
        if pd.isna(text) or not text.strip():
            return []
        
        # Tokenize
        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True
        ).to(self.device)
        
        with torch.no_grad():
            outputs = model(**inputs)
            predictions = torch.argmax(outputs.logits, dim=-1)[0]
        
        # 解码实体
        tokens = self.tokenizer.convert_ids_to_tokens(inputs['input_ids'][0])
        entities = []
        current_entity = []
        current_label = None
        
        for token, pred_idx in zip(tokens, predictions):
            # 跳过特殊标记
            if token in ['[CLS]', '[SEP]', '[PAD]', '[UNK]']:
                # 如果遇到[UNK]，结束当前实体
                if token == '[UNK]' and current_entity:
                    entities.append({
                        'text': ''.join(current_entity).replace('##', ''),
                        'label': current_label.replace('B-', '').replace('I-', '')
                    })
                    current_entity = []
                    current_label = None
                continue
            
            pred_label = label_list[pred_idx.item()]
            
            if pred_label.startswith('B-'):
                if current_entity:
                    entities.append({
                        'text': ''.join(current_entity).replace('##', ''),
                        'label': current_label.replace('B-', '').replace('I-', '')
                    })
                current_entity = [token]
                current_label = pred_label
            elif pred_label.startswith('I-') and current_entity:
                current_entity.append(token)
            else:
                if current_entity:
                    entities.append({
                        'text': ''.join(current_entity).replace('##', ''),
                        'label': current_label.replace('B-', '').replace('I-', '')
                    })
                current_entity = []
                current_label = None
        
        if current_entity:
            entities.append({
                'text': ''.join(current_entity).replace('##', ''),
                'label': current_label.replace('B-', '').replace('I-', '')
            })
        
        # 过滤无效实体：单字、纯符号、空白、包含[UNK]
        valid_entities = []
        for ent in entities:
            text = ent['text'].strip()
            # 过滤条件：
            # 1. 长度>=2
            # 2. 不是纯符号
            # 3. 不包含[UNK]标记
            # 4. 不是纯数字
            if (len(text) >= 2 and 
                not all(c in '，。、；：""''！？（）【】《》·-—' for c in text) and
                '[UNK]' not in text and
                not text.isdigit()):
                ent['text'] = text
                ent['source'] = 'bert'  # 标记来源为BERT
                valid_entities.append(ent)
        
        return valid_entities
    
    def _calculate_entity_stats(self, records):
        """计算各类实体提取统计"""
        stats = {
            'records': len(records),
            'devices': set(),
            'positions': set(),
            'components': 0,      # 部件实体（COMP）
            'phenomena': 0,       # 现象实体（PHEN）
            'solutions_bert': 0,  # BERT提取的解决方案
            'solutions_rule': 0,  # 规则提取的解决方案
            'solutions_total': 0, # 解决方案总数
            'causes': 0           # 原因数量
        }
        
        for record in records:
            stats['devices'].add(record['device'])
            stats['positions'].add(record['position'])
            
            # 现象实体统计
            for ent in record.get('phenomenon_entities', []):
                if ent['label'] in ['COMP', 'COMPONENT']:
                    stats['components'] += 1
                elif ent['label'] in ['PHEN', 'PHENOMENON']:
                    stats['phenomena'] += 1
            
            # 解决方案实体统计
            for ent in record.get('solution_entities', []):
                if ent['label'] == 'ACT':
                    stats['solutions_total'] += 1
                    # 使用source字段区分来源
                    if ent.get('source') == 'rule':
                        stats['solutions_rule'] += 1
                    elif ent.get('source') == 'bert':
                        stats['solutions_bert'] += 1
                    else:
                        stats['solutions_rule'] += 1  # 默认归类为规则
            
            # 原因统计
            stats['causes'] += len(record.get('causes', []))
        
        stats['devices'] = len(stats['devices'])
        stats['positions'] = len(stats['positions'])
        
        return stats
    
    def _print_entity_stats(self, year, stats):
        """打印实体提取统计"""
        print(f"\n  📊 {year}年实体提取统计:")
        print(f"     ├─ 记录数: {stats['records']}")
        print(f"     ├─ 设备: {stats['devices']} 个")
        print(f"     ├─ 站位: {stats['positions']} 个")
        print(f"     ├─ 部件(COMP): {stats['components']} 个")
        print(f"     ├─ 现象(PHEN): {stats['phenomena']} 个")
        print(f"     ├─ 解决方案: {stats['solutions_total']} 个 (BERT:{stats['solutions_bert']} + 规则:{stats['solutions_rule']})")
        print(f"     └─ 原因: {stats['causes']} 个")
    
    def process_year_data(self, df, year, col_mapping):
        """处理单个年份数据（适配不同年份的列名格式）"""
        print(f"\n处理 {year} 年数据...")
        
        records = []
        
        for idx, row in tqdm(df.iterrows(), total=len(df), desc=f"处理{year}年"):
            # 使用列名映射提取基本信息
            device = str(row.get(col_mapping.get('设备', list(df.columns)[5] if len(df.columns) > 5 else ''), '')).strip()
            position = str(row.get(col_mapping.get('站位', list(df.columns)[6] if len(df.columns) > 6 else ''), '')).strip()
            
            if not device or device == 'nan' or len(device) == 0:
                continue
            
            # 提取故障现象实体
            phenomenon_col = col_mapping.get('故障现象', '故障现象')
            phenomenon_text = str(row.get(phenomenon_col, ''))
            phenomenon_entities = self.extract_entities_with_bert(
                phenomenon_text, 
                self.phenomenon_model, 
                PHENOMENON_LABELS
            )
            
            # 提取解决方案实体（BERT + 规则混合）
            solution_col = col_mapping.get('解决对策', col_mapping.get('短期措施', '解决对策'))
            solution_text = str(row.get(solution_col, ''))
            
            # 方法1: BERT模型提取
            solution_entities = self.extract_entities_with_bert(
                solution_text,
                self.solution_model,
                SOLUTION_LABELS
            )
            
            # 方法2: 规则提取（补充BERT遗漏的）
            rule_solutions = self.extract_solutions_by_rules(solution_text)
            
            # 合并去重（BERT优先，规则补充）
            bert_texts = set(e['text'] for e in solution_entities if e['label'] == 'ACT')
            for rule_sol in rule_solutions:
                if rule_sol['text'] not in bert_texts:
                    solution_entities.append(rule_sol)
            
            # 提取原因（根据年份和可用字段）
            causes = []
            
            if '故障直接原因' in col_mapping or '故障根本原因' in col_mapping:
                # 2019/2022格式：有直接原因和根本原因
                direct_cause = str(row.get(col_mapping.get('故障直接原因', ''), '')).strip()
                root_cause = str(row.get(col_mapping.get('故障根本原因', ''), '')).strip()
                
                if direct_cause and direct_cause != 'nan' and len(direct_cause) > 0:
                    causes.append({'type': 'direct', 'text': direct_cause})
                
                if root_cause and root_cause != 'nan' and len(root_cause) > 0:
                    causes.append({'type': 'root', 'text': root_cause})
            
            elif '故障原因' in col_mapping:
                # 2023格式：只有故障原因
                cause = str(row.get(col_mapping.get('故障原因', ''), '')).strip()
                if cause and cause != 'nan' and len(cause) > 0:
                    causes.append({'type': 'general', 'text': cause})
            
            # 其他年份可能没有原因字段，留空
            
            # 提取时间戳
            try:
                year_val = int(row.get('年', row.get('2024', row.get('2020', year))))
                month_val = int(row.get('月', row.get('1', 1)))
                day_val = int(row.get('日', row.get('1.1', 1)))
                timestamp = f"{year_val}-{month_val:02d}-{day_val:02d}"
            except:
                timestamp = f"{year}-01-01"
            
            record = {
                'year': year,
                'device': device,
                'position': position,
                'phenomenon_text': phenomenon_text,
                'solution_text': solution_text,
                'phenomenon_entities': phenomenon_entities,
                'solution_entities': solution_entities,
                'causes': causes,
                'timestamp': timestamp
            }
            
            records.append(record)
        
        # 统计各类实体提取数量
        stats = self._calculate_entity_stats(records)
        self._print_entity_stats(year, stats)
        
        return records
    
    def process_prediction_data(self):
        """处理预测数据文件（2025年带LLM预测原因的数据）"""
        print("\n处理预测数据（2025年抽样+原因预测）...")
        
        pred_df = self.load_prediction_data()
        if pred_df is None:
            return []
        
        records = []
        
        for idx, row in tqdm(pred_df.iterrows(), total=len(pred_df), desc="处理预测数据"):
            # 提取基本信息
            device = str(row.get('设备', '')).strip()
            position = str(row.get('站位', '')).strip()
            
            if not device or device == 'nan':
                continue
            
            # 提取故障现象实体
            phenomenon_text = str(row.get('故障现象', ''))
            phenomenon_entities = self.extract_entities_with_bert(
                phenomenon_text, 
                self.phenomenon_model, 
                PHENOMENON_LABELS
            )
            
            # 提取解决方案实体（BERT + 规则混合）
            solution_text = str(row.get('解决对策', ''))
            
            # 方法1: BERT模型提取
            solution_entities = self.extract_entities_with_bert(
                solution_text,
                self.solution_model,
                SOLUTION_LABELS
            )
            
            # 方法2: 规则提取（补充BERT遗漏的）
            rule_solutions = self.extract_solutions_by_rules(solution_text)
            
            # 合并去重
            bert_texts = set(e['text'] for e in solution_entities if e['label'] == 'ACT')
            for rule_sol in rule_solutions:
                if rule_sol['text'] not in bert_texts:
                    solution_entities.append(rule_sol)
            
            # 使用LLM预测的原因
            causes = []
            predicted_cause = str(row.get('预测原因', '')).strip()
            confidence = row.get('预测置信度', 0.8)
            
            if predicted_cause and predicted_cause != 'nan' and len(predicted_cause) > 2:
                causes.append({
                    'type': 'predicted',
                    'text': predicted_cause,
                    'confidence': float(confidence) if pd.notna(confidence) else 0.8
                })
            
            # 提取时间戳
            try:
                year_val = int(row.get('年', 2025))
                month_val = int(row.get('月', 1))
                day_val = int(row.get('日', 1))
                timestamp = f"{year_val}-{month_val:02d}-{day_val:02d}"
            except:
                timestamp = "2025-01-01"
            
            record = {
                'year': 2025,
                'device': device,
                'position': position,
                'phenomenon_text': phenomenon_text,
                'solution_text': solution_text,
                'phenomenon_entities': phenomenon_entities,
                'solution_entities': solution_entities,
                'causes': causes,
                'timestamp': timestamp,
                'has_prediction': True  # 标记为预测数据
            }
            
            records.append(record)
        
        # 统计各类实体提取数量
        stats = self._calculate_entity_stats(records)
        self._print_entity_stats('2025(预测)', stats)
        
        return records
    
    def _consolidate_entities_by_hierarchy(self, entities_dict):
        """
        处理实体层级关系：如果同时出现"更换"和"更换连接头"，
        只保留更长/更完整的形式，去除短的前缀形式
        
        参数：
            entities_dict: {'entity_name': {'id': '', 'text': '', ...}, ...}
        
        返回：
            consolidated_dict: 处理后的实体字典
            mapping: {'old_key': 'new_key', ...} 用于关系更新
        """
        if not entities_dict:
            return entities_dict, {}
        
        entity_names = list(entities_dict.keys())
        consolidated = {}
        mapping = {}  # 旧key到新key的映射
        
        # 按长度降序排序，优先处理长的实体（确保更长的保留）
        sorted_names = sorted(entity_names, key=lambda x: (-len(x), x))
        
        for name in sorted_names:
            # 检查这个实体是否包含于任何保留的实体中
            merged_into = None
            
            for retained_name in consolidated.keys():
                # 如果当前名称是已保留名称的前缀，则合并
                if name != retained_name and retained_name.startswith(name):
                    # name是retained_name的前缀，应该被合并
                    merged_into = retained_name
                    break
            
            if merged_into:
                # 这个实体是其他保留实体的前缀，映射到那个实体
                mapping[name] = merged_into
            else:
                # 这个实体应该保留
                consolidated[name] = entities_dict[name]
                mapping[name] = name  # 自己映射到自己
        
        return consolidated, mapping
    
    def _update_relationships_with_mapping(self, relationships, entity_mapping, source_type='solution'):
        """
        根据实体映射关系更新关系列表
        
        参数：
            relationships: 关系列表
            entity_mapping: {'old_entity_id': 'new_entity_id', ...}
            source_type: 'solution' 或 'entity' 或 'cause'
        """
        updated_relationships = []
        seen_rels = set()
        
        for rel in relationships:
            # 对于Solution -> Phenomenon关系，需要更新Solution的ID
            if source_type == 'solution' and rel['type'] == 'solves_phenomenon':
                new_from_id = entity_mapping.get(rel['from'], rel['from'])
                new_rel = rel.copy()
                new_rel['from'] = new_from_id
            # 对于Entity -> Phenomenon关系，需要更新Entity的ID
            elif source_type == 'entity' and rel['type'] == 'exhibits_phenomenon':
                new_from_id = entity_mapping.get(rel['from'], rel['from'])
                new_rel = rel.copy()
                new_rel['from'] = new_from_id
            # 对于Cause -> Phenomenon关系，需要更新Cause的ID
            elif source_type == 'cause' and rel['type'] == 'causes_phenomenon':
                new_from_id = entity_mapping.get(rel['from'], rel['from'])
                new_rel = rel.copy()
                new_rel['from'] = new_from_id
            else:
                new_rel = rel
            
            # 生成关系签名用于去重（包括ID和类型）
            rel_sig = (new_rel['from'], new_rel['to'], new_rel['type'])
            if rel_sig not in seen_rels:
                seen_rels.add(rel_sig)
                updated_relationships.append(new_rel)
        
        return updated_relationships
    
    def build_knowledge_graph(self, records):
        """构建知识图谱（原因节点去重、部件规范化、层级感知去重）"""
        
        kg = {
            'devices': {},
            'positions': {},
            'entities': {},
            'phenomena': {},
            'causes': {},  # 去重的原因节点
            'solutions': {},
            'relationships': []
        }
        
        cause_id_map = {}  # 原因文本 -> ID映射，用于去重
        entity_name_map = {}  # 规范化部件名称 -> 实际使用的名称
        solution_id_map = {}  # 解决方案ID映射
        entity_id_map = {}  # 实体ID映射
        cause_text_map = {}  # 原因文本映射
        seen_relations = set()  # 用于关系去重
        
        for record in tqdm(records, desc="构建图谱"):
            device = record['device']
            position = record['position']
            year = record.get('year', 'unknown')
            
            # 设备节点
            if device not in kg['devices']:
                kg['devices'][device] = {
                    'id': f"device_{len(kg['devices'])}",
                    'name': device,
                    'type': 'Device'
                }
            
            # 站位节点 - 按站位名称全局唯一，不同设备可指向同一站位
            pos_name = position.strip()
            
            if pos_name and pos_name not in kg['positions']:
                kg['positions'][pos_name] = {
                    'id': f"position_{len(kg['positions'])}",
                    'name': pos_name,
                    'type': 'Position'
                }
            
            # 关系：Device -> Position（避免重复）
            if pos_name:
                rel_key = (kg['devices'][device]['id'], kg['positions'][pos_name]['id'], 'contains')
                if rel_key not in seen_relations:
                    seen_relations.add(rel_key)
                    kg['relationships'].append({
                        'from': kg['devices'][device]['id'],
                        'to': kg['positions'][pos_name]['id'],
                        'type': 'contains'
                    })
            
            # 实体节点（部件）- 使用规范化名称去重
            for entity in record['phenomenon_entities']:
                if entity['label'] in ['COMP', 'COMPONENT', 'COMP_FAULT']:
                    # 规范化部件名称
                    entity_name = self.normalize_entity_text(entity['text'])
                    if not entity_name or len(entity_name) < 2:
                        continue
                    
                    # 使用规范化名称作为全局唯一键（跨站位去重）
                    entity_key = entity_name  # 改为全局唯一
                    
                    if entity_key not in kg['entities']:
                        kg['entities'][entity_key] = {
                            'id': f"entity_{len(kg['entities'])}",
                            'name': entity_name,
                            'type': 'Entity'
                        }
                    
                    # 关系：Position -> Entity（允许多个站位关联同一部件）
                    if pos_name and pos_name in kg['positions']:
                        rel_key = (kg['positions'][pos_name]['id'], kg['entities'][entity_key]['id'], 'contains_entity')
                        if rel_key not in seen_relations:
                            seen_relations.add(rel_key)
                            kg['relationships'].append({
                                'from': kg['positions'][pos_name]['id'],
                                'to': kg['entities'][entity_key]['id'],
                                'type': 'contains_entity'
                            })
                    
                    # 更新entity引用为规范化名称
                    entity['_normalized_key'] = entity_key
            
            # 故障现象节点（规范化去重）
            for entity in record['phenomenon_entities']:
                if entity['label'] in ['PHEN', 'PHENOMENON']:
                    phen_name = self.normalize_entity_text(entity['text'])
                    if not phen_name or len(phen_name) < 2:
                        continue
                    
                    phen_key = phen_name
                    if phen_key not in kg['phenomena']:
                        kg['phenomena'][phen_key] = {
                            'id': f"phenomenon_{len(kg['phenomena'])}",
                            'name': phen_name,
                            'type': 'Phenomenon'
                        }
                    
                    # 关系：Entity -> Phenomenon（如果有对应部件）
                    for comp_entity in record['phenomenon_entities']:
                        if comp_entity['label'] in ['COMP', 'COMPONENT', 'COMP_FAULT']:
                            entity_key = comp_entity.get('_normalized_key')
                            if entity_key and entity_key in kg['entities']:
                                kg['relationships'].append({
                                    'from': kg['entities'][entity_key]['id'],
                                    'to': kg['phenomena'][phen_key]['id'],
                                    'type': 'exhibits_phenomenon',
                                    'timestamp': record['timestamp']
                                })
            
            # 原因节点（去重，支持预测原因的置信度）
            for cause in record['causes']:
                cause_text = self.normalize_entity_text(cause['text'])
                if not cause_text or len(cause_text) < 2:
                    continue
                
                # 去重：相同文本的原因使用同一个节点
                if cause_text not in cause_id_map:
                    cause_id = f"cause_{len(kg['causes'])}"
                    cause_id_map[cause_text] = cause_id
                    cause_text_map[cause_text] = cause_text  # 记录原始映射
                    
                    cause_node = {
                        'id': cause_id,
                        'text': cause_text,
                        'type': 'Cause',
                        'cause_type': cause['type']  # direct/root/general/predicted
                    }
                    
                    # 如果是预测原因，添加置信度
                    if 'confidence' in cause:
                        cause_node['confidence'] = cause['confidence']
                    
                    kg['causes'][cause_text] = cause_node
                
                # 关系：Cause -> Phenomenon
                for phen_entity in record['phenomenon_entities']:
                    if phen_entity['label'] in ['PHEN', 'PHENOMENON']:
                        phen_name = self.normalize_entity_text(phen_entity['text'])
                        # 确保现象节点已存在
                        if phen_name and phen_name in kg['phenomena']:
                            kg['relationships'].append({
                                'from': cause_id_map[cause_text],
                                'to': kg['phenomena'][phen_name]['id'],
                                'type': 'causes_phenomenon',
                                'year': record['year'],
                                'confidence': cause.get('confidence', 1.0)
                            })
            
            # 解决方案节点（规范化去重）
            for solution in record['solution_entities']:
                if solution['label'] in ['ACT', 'SOLUTION']:
                    sol_name = self.normalize_entity_text(solution['text'])
                    if not sol_name or len(sol_name) < 2:
                        continue
                    
                    sol_key = sol_name
                    if sol_key not in kg['solutions']:
                        kg['solutions'][sol_key] = {
                            'id': f"solution_{len(kg['solutions'])}",
                            'text': sol_name,
                            'type': 'Solution'
                        }
                    
                    # 关系：Solution -> Phenomenon
                    for phen_entity in record['phenomenon_entities']:
                        if phen_entity['label'] in ['PHEN', 'PHENOMENON']:
                            phen_name = self.normalize_entity_text(phen_entity['text'])
                            # 确保现象节点已存在
                            if phen_name and phen_name in kg['phenomena']:
                                kg['relationships'].append({
                                    'from': kg['solutions'][sol_key]['id'],
                                    'to': kg['phenomena'][phen_name]['id'],
                                    'type': 'solves_phenomenon'
                                })
        
        # 📌 应用层级感知去重：处理"更换"vs"更换连接头"等情况
        print("  应用实体层级去重...")
        
        # 1. 去重解决方案（最重要）
        solutions_consolidated, solution_mapping = self._consolidate_entities_by_hierarchy(kg['solutions'])
        
        # 统计被合并的解决方案
        merged_solutions = len(kg['solutions']) - len(solutions_consolidated)
        if merged_solutions > 0:
            print(f"    ✓ 解决方案去重: {merged_solutions} 个重复节点被合并")
            
            # 建立ID映射（旧ID -> 新ID）
            solution_id_remap = {}
            for old_key, new_key in solution_mapping.items():
                if old_key != new_key:  # 只有不相等的才是真正的映射
                    old_id = kg['solutions'][old_key]['id']
                    new_id = solutions_consolidated[new_key]['id']
                    solution_id_remap[old_id] = new_id
            
            # 更新关系：使用新的ID
            kg['relationships'] = self._update_relationships_with_mapping(
                kg['relationships'], solution_id_remap, source_type='solution'
            )
            kg['solutions'] = solutions_consolidated
        
        # 2. 去重实体（部件）
        entities_consolidated, entity_mapping = self._consolidate_entities_by_hierarchy(kg['entities'])
        merged_entities = len(kg['entities']) - len(entities_consolidated)
        if merged_entities > 0:
            print(f"    ✓ 实体(部件)去重: {merged_entities} 个重复节点被合并")
            
            # 建立ID映射
            entity_id_remap = {}
            for old_key, new_key in entity_mapping.items():
                if old_key != new_key:
                    old_id = kg['entities'][old_key]['id']
                    new_id = entities_consolidated[new_key]['id']
                    entity_id_remap[old_id] = new_id
            
            kg['relationships'] = self._update_relationships_with_mapping(
                kg['relationships'], entity_id_remap, source_type='entity'
            )
            kg['entities'] = entities_consolidated
        
        # 3. 去重原因
        causes_consolidated, cause_mapping = self._consolidate_entities_by_hierarchy(kg['causes'])
        merged_causes = len(kg['causes']) - len(causes_consolidated)
        if merged_causes > 0:
            print(f"    ✓ 原因去重: {merged_causes} 个重复节点被合并")
            
            # 建立ID映射
            cause_id_remap = {}
            for old_key, new_key in cause_mapping.items():
                if old_key != new_key:
                    old_id = kg['causes'][old_key]['id']
                    new_id = causes_consolidated[new_key]['id']
                    cause_id_remap[old_id] = new_id
            
            kg['relationships'] = self._update_relationships_with_mapping(
                kg['relationships'], cause_id_remap, source_type='cause'
            )
            kg['causes'] = causes_consolidated
        
        return kg
    
    
    def run(self):
        """主流程 - 处理所有年份并分层存储"""
        print("=" * 60)
        print("多年度数据融合处理（2019-2025全年份）")
        print("=" * 60)
        
        # 1. 处理所有年份数据
        all_records_by_year = {}  # 按年份分组
        
        for year in [2019, 2020, 2021, 2022, 2023, 2024, 2025]:
            try:
                df, col_mapping = self.load_and_clean_data(year)
                records = self.process_year_data(df, year, col_mapping)
                all_records_by_year[year] = records
                print(f"  {year}年提取记录: {len(records)}")
            except FileNotFoundError:
                print(f"  {year}年数据文件不存在，跳过")
            except Exception as e:
                print(f"  {year}年处理失败: {e}")
        
        # 1.5 整合预测数据到2025年（如果有）
        prediction_records = self.process_prediction_data()
        if prediction_records:
            # 使用预测数据替换或补充2025年数据（预测数据优先，因为有原因）
            print(f"\n整合预测数据到2025年...")
            
            if 2025 in all_records_by_year:
                # 创建一个基于(设备,站位,时间戳)的索引来合并
                existing_keys = set()
                for r in all_records_by_year[2025]:
                    key = (r['device'], r['position'], r.get('phenomenon_text', '')[:50])
                    existing_keys.add(key)
                
                # 只添加不重复的预测记录
                added = 0
                for pr in prediction_records:
                    key = (pr['device'], pr['position'], pr.get('phenomenon_text', '')[:50])
                    if key not in existing_keys:
                        all_records_by_year[2025].append(pr)
                        existing_keys.add(key)
                        added += 1
                    else:
                        # 更新已存在记录的原因（如果预测数据有原因）
                        for r in all_records_by_year[2025]:
                            if (r['device'], r['position'], r.get('phenomenon_text', '')[:50]) == key:
                                if pr.get('causes') and not r.get('causes'):
                                    r['causes'] = pr['causes']
                                break
                
                print(f"  新增预测记录: {added}")
                print(f"  2025年总记录: {len(all_records_by_year[2025])}")
            else:
                all_records_by_year[2025] = prediction_records
                print(f"  使用预测数据作为2025年数据: {len(prediction_records)} 条")
        
        # 2. 分年份构建和保存知识图谱
        print("\n构建分年份知识图谱...")
        kg_by_year = {}
        
        for year, records in all_records_by_year.items():
            print(f"\n  构建{year}年图谱...")
            kg = self.build_knowledge_graph(records)
            kg_by_year[year] = kg
            
            # 保存单年份KG
            output_file = self.output_dir / f"kg_{year}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(kg, f, ensure_ascii=False, indent=2)
            
            print(f"    设备:{len(kg['devices'])} 站位:{len(kg['positions'])} "
                  f"实体:{len(kg['entities'])} 现象:{len(kg['phenomena'])} "
                  f"原因:{len(kg['causes'])} 方案:{len(kg['solutions'])} "
                  f"关系:{len(kg['relationships'])}")
        
        # 3. 合并构建全年份知识图谱
        print("\n构建全年份融合知识图谱...")
        all_records = []
        for records in all_records_by_year.values():
            all_records.extend(records)
        
        kg_all = self.build_knowledge_graph(all_records)
        
        # 保存全年份KG
        output_file_all = self.output_dir / "kg_all_years.json"
        with open(output_file_all, 'w', encoding='utf-8') as f:
            json.dump(kg_all, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 全年份知识图谱已保存: {output_file_all}")
        print(f"  设备节点: {len(kg_all['devices'])}")
        print(f"  站位节点: {len(kg_all['positions'])}")
        print(f"  实体节点: {len(kg_all['entities'])}")
        print(f"  现象节点: {len(kg_all['phenomena'])}")
        print(f"  原因节点: {len(kg_all['causes'])} (去重后)")
        print(f"  方案节点: {len(kg_all['solutions'])}")
        print(f"  关系数量: {len(kg_all['relationships'])}")
        
        # 4. 保存年份元数据
        metadata = {
            'years_processed': list(all_records_by_year.keys()),
            'total_records': len(all_records),
            'records_by_year': {year: len(records) for year, records in all_records_by_year.items()},
            'output_files': {
                'all_years': str(output_file_all),
                'by_year': {year: str(self.output_dir / f"kg_{year}.json") for year in all_records_by_year.keys()}
            }
        }
        
        metadata_file = self.output_dir / "kg_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        print(f"\n元数据已保存: {metadata_file}")
        print("\n✅ 所有处理完成！")


if __name__ == "__main__":
    processor = MultiYearDataProcessor()
    processor.run()
