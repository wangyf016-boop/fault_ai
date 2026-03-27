"""
BERT实体提取器
使用训练好的BERT-CRF模型从文本中提取实体
"""

from transformers import AutoTokenizer, AutoModelForTokenClassification
import torch
from pathlib import Path


class BERTEntityExtractor:
    """BERT-CRF实体提取器"""
    
    def __init__(self, model_path: str = None):
        """
        初始化BERT实体提取器
        
        Args:
            model_path: 模型路径，默认使用models/saved/model_output/solution/
        """
        if model_path is None:
            project_root = Path(__file__).parent.parent
            # 使用正确的模型路径
            model_path = project_root / 'models' / 'saved' / 'model_output' / 'solution'
        
        # 转换为 Path 对象以便检查和操作
        model_path = Path(model_path)
        
        if not model_path.exists():
            raise FileNotFoundError(f"模型路径不存在: {model_path}")
        
        self.model_path = str(model_path.absolute())
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # transformers的from_pretrained期望相对于项目根目录的相对路径
        # 所以我们使用绝对路径，并让transformers自己处理
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, local_files_only=True)
            self.model = AutoModelForTokenClassification.from_pretrained(self.model_path, local_files_only=True)
        except Exception as e:
            # 如果transformers无法加载，尝试直接加载config和weights
            import json
            config_path = model_path / 'config.json'
            if config_path.exists():
                from transformers import BertConfig
                config = BertConfig.from_json_file(str(config_path))
                self.model = AutoModelForTokenClassification.from_config(config)
                
                # 加载权重
                weights_path = model_path / 'pytorch_model.bin'
                if weights_path.exists():
                    state_dict = torch.load(str(weights_path), map_location=self.device)
                    self.model.load_state_dict(state_dict)
                
                # 加载tokenizer配置
                tokenizer_config_path = model_path / 'tokenizer_config.json'
                vocab_path = model_path / 'vocab.txt'
                if tokenizer_config_path.exists() and vocab_path.exists():
                    from transformers import BertTokenizer
                    self.tokenizer = BertTokenizer.from_pretrained(str(model_path), local_files_only=True)
                else:
                    raise e
            else:
                raise e
        
        self.model.to(self.device)
        self.model.eval()
    
    def extract(self, text: str) -> list:
        """
        从文本中提取实体
        
        Args:
            text: 输入文本
            
        Returns:
            提取的实体列表 [(entity_text, label), ...]
        """
        # Tokenize
        inputs = self.tokenizer(
            text,
            return_tensors='pt',
            padding=True,
            truncation=True,
            max_length=512
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        # 预测
        with torch.no_grad():
            outputs = self.model(**inputs)
            predictions = torch.argmax(outputs.logits, dim=-1)
        
        # 解码实体
        entities = self._decode_entities(
            text,
            predictions[0].cpu().numpy(),
            inputs['input_ids'][0].cpu().numpy()
        )
        
        return entities
    
    def _decode_entities(self, text: str, predictions: list, input_ids: list) -> list:
        """
        从预测标签中解码实体
        
        Args:
            text: 原始文本
            predictions: 预测的标签ID
            input_ids: tokenizer的input_ids
            
        Returns:
            实体列表 [(entity_text, label), ...]
        """
        # 从模型配置获取id2label映射
        if hasattr(self.model.config, 'id2label'):
            id2label = self.model.config.id2label
        else:
            # 备选：从模型权重获取
            id2label = {i: f"LABEL_{i}" for i in range(len(set(predictions)))}
        
        # 转换token IDs到tokens
        tokens = self.tokenizer.convert_ids_to_tokens(input_ids)
        
        entities = []
        current_entity_tokens = []
        current_label = None
        
        for token, pred_id in zip(tokens, predictions):
            # 转换预测ID到标签
            if isinstance(pred_id, int):
                pred_label = id2label.get(pred_id, "O")
            else:
                pred_label = id2label.get(int(pred_id), "O")
            
            # 跳过特殊标记
            if token in ['[CLS]', '[SEP]', '[PAD]']:
                # 如果遇到特殊标记且有当前实体，保存它
                if current_entity_tokens and current_label and current_label != 'O':
                    entity_text = ''.join(current_entity_tokens).replace('##', '')
                    if entity_text.strip():
                        # 移除B-/I-前缀，只保留标签名
                        clean_label = current_label.replace('B-', '').replace('I-', '')
                        entities.append((entity_text, clean_label))
                current_entity_tokens = []
                current_label = None
                continue
            
            # 处理[UNK]
            if token == '[UNK]':
                if current_entity_tokens and current_label and current_label != 'O':
                    entity_text = ''.join(current_entity_tokens).replace('##', '')
                    if entity_text.strip():
                        clean_label = current_label.replace('B-', '').replace('I-', '')
                        entities.append((entity_text, clean_label))
                current_entity_tokens = []
                current_label = None
                continue
            
            # BIO标签处理
            if pred_label.startswith('B-'):
                # 遇到B-标签，保存前一个实体（如果有）
                if current_entity_tokens and current_label and current_label != 'O':
                    entity_text = ''.join(current_entity_tokens).replace('##', '')
                    if entity_text.strip():
                        clean_label = current_label.replace('B-', '').replace('I-', '')
                        entities.append((entity_text, clean_label))
                # 开始新实体
                current_entity_tokens = [token]
                current_label = pred_label
            elif pred_label.startswith('I-'):
                # 继续当前实体
                if current_label and current_label.startswith('B-'):
                    # 检查I-标签和B-标签是否匹配（同一实体类型）
                    if pred_label[2:] == current_label[2:]:  # 比较去掉B-/I-后的部分
                        current_entity_tokens.append(token)
                    else:
                        # 标签不匹配，保存前一个实体，开始新的
                        if current_entity_tokens:
                            entity_text = ''.join(current_entity_tokens).replace('##', '')
                            if entity_text.strip():
                                clean_label = current_label.replace('B-', '').replace('I-', '')
                                entities.append((entity_text, clean_label))
                        current_entity_tokens = [token]
                        current_label = pred_label
                elif not current_label or current_label == 'O':
                    # I-标签在没有B-的情况下，作为B-处理
                    current_entity_tokens = [token]
                    current_label = 'B-' + pred_label[2:]
            else:
                # O标签，结束当前实体
                if current_entity_tokens and current_label and current_label != 'O':
                    entity_text = ''.join(current_entity_tokens).replace('##', '')
                    if entity_text.strip():
                        clean_label = current_label.replace('B-', '').replace('I-', '')
                        entities.append((entity_text, clean_label))
                current_entity_tokens = []
                current_label = None
        
        # 处理文本末尾的实体
        if current_entity_tokens and current_label and current_label != 'O':
            entity_text = ''.join(current_entity_tokens).replace('##', '')
            if entity_text.strip():
                clean_label = current_label.replace('B-', '').replace('I-', '')
                entities.append((entity_text, clean_label))
        
        return entities


if __name__ == '__main__':
    # 测试代码
    extractor = BERTEntityExtractor()
    
    test_text = "更换焊头，清洁传感器"
    entities = extractor.extract(test_text)
    
    print(f"提取的实体: {entities}")
