# liar_tavern/exceptions.py

# -*- coding: utf-8 -*-

class GameError(Exception):
    """游戏逻辑错误基类"""
    pass

class GameNotFoundError(GameError):
    """未找到游戏实例"""
    pass

class PlayerNotInGameError(GameError):
    """玩家不在游戏中"""
    pass

class PlayerAlreadyJoinedError(GameError):
    """玩家已加入"""
    pass

class GameNotWaitingError(GameError):
    """操作要求游戏状态为 WAITING"""
    pass

class GameNotPlayingError(GameError):
    """操作要求游戏状态为 PLAYING"""
    pass

class NotEnoughPlayersError(GameError):
    """玩家人数不足以开始游戏"""
    pass

class NotPlayersTurnError(GameError):
    """在非玩家回合尝试操作"""
    def __init__(self, message="在非玩家回合尝试操作", current_player_name=None):
        super().__init__(message)
        self.current_player_name = current_player_name # 可以携带当前轮到谁的名字

class InvalidActionError(GameError):
    """在当前上下文中不允许的操作 (例如，手牌非空时等待)"""
    pass

class InvalidCardIndexError(GameError):
    """提供的卡牌编号无效 (越界, 重复等)"""
    def __init__(self, message="提供的卡牌编号无效", invalid_indices=None, hand_size=None):
        super().__init__(message)
        self.invalid_indices = invalid_indices
        self.hand_size = hand_size

class InvalidPlayQuantityError(GameError):
    """尝试打出无效数量的牌"""
    pass

class NoChallengeTargetError(GameError):
    """尝试质疑时没有可质疑的出牌"""
    pass

class EmptyHandError(GameError):
     """尝试需要手牌的操作 (如出牌) 但手牌为空"""
     pass

# --- AI 相关异常 (已添加) ---
class AIDecisionError(GameError):
    """AI 决策时发生错误 (例如 LLM 调用失败或返回无效)"""
    pass

class AIParseError(AIDecisionError):
    """无法解析 AI (LLM) 的响应"""
    pass

class AIInvalidDecisionError(AIDecisionError):
    """AI (LLM) 的决策不符合游戏规则"""
    pass