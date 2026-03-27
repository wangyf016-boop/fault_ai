"""
LLM推理器
封装Ollama和OpenAI API，用于推理故障原因
"""

import requests
import json
from typing import List, Dict, Optional


class LLMReasoner:
    """LLM推理器，支持Ollama和OpenAI"""
    
    def __init__(self, provider: str = 'ollama', model: str = 'deepseek-r1', api_key: str = None):
        """
        初始化LLM推理器
        
        Args:
            provider: LLM提供商 ('ollama' 或 'openai')
            model: 模型名称
            api_key: API密钥（OpenAI需要）
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        
        # 配置API端点
        if self.provider == 'ollama':
            self.api_url = 'http://localhost:11434/api/generate'
        elif self.provider == 'openai':
            self.api_url = 'https://api.openai.com/v1/chat/completions'
        else:
            raise ValueError(f"不支持的provider: {provider}")
    
    def infer_cause(self, entities: List[str], phenomenon: str = None) -> Dict:
        """
        基于实体推理故障原因
        
        Args:
            entities: 从解决方案中提取的实体列表
            phenomenon: 故障现象描述（可选）
            
        Returns:
            {
                'cause': '推理的原因',
                'confidence': 0.85,
                'reasoning': '推理过程'
            }
        """
        # 构建prompt
        prompt = self._build_prompt(entities, phenomenon)
        
        # 调用LLM
        if self.provider == 'ollama':
            response = self._call_ollama(prompt)
        elif self.provider == 'openai':
            response = self._call_openai(prompt)
        else:
            raise ValueError(f"不支持的provider: {self.provider}")
        
        # 解析响应
        result = self._parse_response(response)
        
        return result
    
    def _build_prompt(self, entities: List[str], phenomenon: str = None) -> str:
        """构建LLM推理prompt"""
        entities_str = ', '.join(entities) if entities else '无'
        
        prompt = f"""你是一个设备故障诊断专家。基于以下信息推理故障原因：

解决方案中的关键操作/部件: {entities_str}
"""
        
        if phenomenon:
            prompt += f"故障现象: {phenomenon}\n"
        
        prompt += """
请推理出最可能的故障原因。要求：
1. 给出简洁的原因描述（10-30字）
2. 提供推理置信度（0-1之间的数字）
3. 简要说明推理逻辑

请以JSON格式返回：
{
  "cause": "故障原因",
  "confidence": 0.85,
  "reasoning": "推理逻辑"
}
"""
        return prompt
    
    def _call_ollama(self, prompt: str) -> str:
        """调用Ollama API"""
        try:
            payload = {
                'model': self.model,
                'prompt': prompt,
                'stream': False
            }
            
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return result.get('response', '')
        
        except Exception as e:
            print(f"Ollama API调用失败: {e}")
            return None
    
    def _call_openai(self, prompt: str) -> str:
        """调用OpenAI API"""
        try:
            headers = {
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json'
            }
            
            payload = {
                'model': self.model,
                'messages': [
                    {'role': 'user', 'content': prompt}
                ],
                'temperature': 0.7
            }
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            return result['choices'][0]['message']['content']
        
        except Exception as e:
            print(f"OpenAI API调用失败: {e}")
            return None
    
    def _parse_response(self, response: str) -> Dict:
        """解析LLM响应"""
        if not response:
            return {
                'cause': '未知原因',
                'confidence': 0.0,
                'reasoning': 'LLM调用失败'
            }
        
        try:
            # 尝试解析JSON响应
            # 可能需要清理响应文本（去除markdown标记等）
            clean_response = response.strip()
            if '```json' in clean_response:
                clean_response = clean_response.split('```json')[1].split('```')[0]
            elif '```' in clean_response:
                clean_response = clean_response.split('```')[1].split('```')[0]
            
            result = json.loads(clean_response)
            
            return {
                'cause': result.get('cause', '未知原因'),
                'confidence': float(result.get('confidence', 0.5)),
                'reasoning': result.get('reasoning', '')
            }
        
        except:
            # 如果解析失败，使用原始响应
            return {
                'cause': response[:100],  # 截取前100字符
                'confidence': 0.5,
                'reasoning': '响应解析失败'
            }


if __name__ == '__main__':
    # 测试代码
    reasoner = LLMReasoner(provider='ollama', model='deepseek-r1')
    
    entities = ['焊头', '传感器']
    phenomenon = '焊接不良'
    
    result = reasoner.infer_cause(entities, phenomenon)
    
    print(f"推理结果: {result}")
