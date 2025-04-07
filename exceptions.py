# exceptions.py - 自定义游戏异常
class GameError(Exception):
    """游戏逻辑错误的基类"""
    pass

class InvalidActionError(GameError):
    """无效的游戏动作"""
    pass

class InvalidPlayerError(GameError):
    """无效的玩家操作"""
    pass

