# message_utils.py - 消息格式化和发送相关的辅助函数
from typing import List, Dict, Any

class MessageFormatter:
    """消息格式化工具类"""
    
    def format_hand_for_display(self, hand: List[str]) -> str:
        """格式化手牌用于显示"""
        if not hand:
            return "无"
        return ' '.join([f"[{i+1}:{card}]" for i, card in enumerate(hand)])
    
    def format_hand_update(self, group_id: str, hand: List[str], main_card: str) -> str:
        """格式化手牌更新私信"""
        if not hand:
            return (f"游戏骗子酒馆 (群: {group_id})\n"
                   f"✋ 手牌: 无\n"
                   f"👑 主牌: {main_card}\n"
                   f"👉 你已无手牌，轮到你时只能 /质疑 或 /等待")
        else:
            hand_display = self.format_hand_for_display(hand)
            return (f"游戏骗子酒馆 (群: {group_id})\n"
                   f"✋ 手牌: {hand_display}\n"
                   f"👑 主牌: {main_card}\n"
                   f"👉 (出牌请用括号内编号)")
