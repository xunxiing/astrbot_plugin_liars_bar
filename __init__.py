# __init__.py - 包标识文件，导入核心类
from .game_logic import LiarsTavernGame
from .models import GameState, GameEvent, Player, GameConfig
from .exceptions import GameError, InvalidActionError, InvalidPlayerError

__all__ = [
    'LiarsTavernGame',
    'GameState',
    'GameEvent',
    'Player',
    'GameConfig',
    'GameError',
    'InvalidActionError',
    'InvalidPlayerError'
]

