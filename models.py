# models.py - 骗子酒馆游戏数据模型和常量
from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum, auto

# 常量
class CardType:
    Q = "Q"
    K = "K"
    A = "A"
    JOKER = "Joker"

class GameState(Enum):
    WAITING = "waiting"
    PLAYING = "playing"
    ENDED = "ended"

class GameEvent(Enum):
    PLAYER_JOINED = auto()
    GAME_STARTED = auto()
    CARDS_DEALT = auto()
    CARDS_PLAYED = auto()
    CHALLENGE_MADE = auto()
    PLAYER_SHOT = auto()
    PLAYER_WAITED = auto()
    NEXT_TURN = auto()
    RESHUFFLED = auto()
    GAME_ENDED = auto()

@dataclass
class Player:
    """玩家数据模型"""
    id: str
    name: str
    hand: List[str] = field(default_factory=list)
    gun: List[str] = field(default_factory=list)
    gun_position: int = 0
    is_eliminated: bool = False

@dataclass
class GameConfig:
    """游戏配置"""
    CARD_TYPES: List[str] = field(default_factory=lambda: ["Q", "K", "A"])
    JOKER: str = "Joker"
    CARDS_PER_TYPE: int = 10
    HAND_SIZE: int = 5
    GUN_CHAMBERS: int = 6
    LIVE_BULLETS: int = 2
    MIN_PLAYERS: int = 2

