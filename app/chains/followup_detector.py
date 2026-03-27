"""追问检测器 - 基于规则，无LLM调用"""
import re
from typing import List, Dict, Tuple


class FollowUpDetector:
    # 强指代词 - 明确指向上文
    STRONG_REFS = ["它", "这个", "那个", "这些", "那些", "该站", "该问题", "该故障", "此站", "此问题"]
    # 弱指代词 - 需要结合上下文
    WEAK_REFS = ["该", "此", "当日", "当天", "同一"]
    # 追问动作词
    FOLLOWUP_ACTIONS = ["还有", "另外", "其他", "更多", "详细", "具体", "继续", "除此之外"]
    # 引用历史关键词 - 明确引用之前的对话内容
    HISTORY_REFS = ["以上", "上面", "上述", "前面", "刚才", "之前"]
    # 总结类动作词 - 对历史内容进行操作
    SUMMARY_ACTIONS = ["总结", "归纳", "概括", "汇总", "整理", "分析一下", "对比一下"]
    
    def __init__(self):
        pass
    
    def is_followup(self, current_input: str, chat_history: List[Dict[str, str]] = None) -> Tuple[bool, float, str]:
        if not current_input or not current_input.strip():
            return False, 0.0, "空输入"
        if not chat_history:
            return False, 0.0, "首次提问"
        
        text = current_input.strip()
        reasons = []
        
        # 规则0: 总结类动作词 + 引用历史 = 强追问（如"总结以上记录"）
        has_summary = any(act in text for act in self.SUMMARY_ACTIONS)
        has_history_ref = any(ref in text for ref in self.HISTORY_REFS)
        
        if has_summary and has_history_ref:
            return True, 0.95, "总结类动作+引用历史"
        
        # 规则0.5: 单独的总结类动作词 + 有对话历史 = 追问（如"总结一下"）
        if has_summary and len(chat_history) >= 2:
            return True, 0.85, "总结类动作词+有对话历史"
        
        # 规则0.6: 引用历史关键词 = 追问（如"以上记录"、"上面的问题"）
        if has_history_ref:
            return True, 0.9, f"包含引用历史词"
        
        # 规则1: 强指代词直接判定为追问
        for ref in self.STRONG_REFS:
            if ref in text:
                return True, 0.9, f"包含强指代词'{ref}'"
        
        # 规则2: 弱指代词 + 追问动作词 = 追问
        has_weak_ref = any(ref in text for ref in self.WEAK_REFS)
        has_action = any(act in text for act in self.FOLLOWUP_ACTIONS)
        
        if has_weak_ref and has_action:
            return True, 0.8, "弱指代词+追问动作词"
        
        # 规则3: 单独的追问动作词（句首）
        for act in self.FOLLOWUP_ACTIONS:
            if text.startswith(act):
                return True, 0.7, f"以追问词'{act}'开头"
        
        # 规则4: 弱指代词 + 短句（<15字）= 可能追问
        if has_weak_ref and len(text) < 15:
            return True, 0.6, "弱指代词+短句"
        
        # 规则5: 单独弱指代词，有历史记录
        if has_weak_ref and len(chat_history) >= 2:
            return True, 0.5, "弱指代词+有对话历史"
        
        return False, 0.0, "无追问特征"
