# liar_tavern/models.py

# -*- coding: utf-8 -*-

import random # 确保导入 random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Dict, Optional, Tuple
import math # 导入 math 用于四舍五入
import logging
logger = logging.getLogger(__name__)
# --- Game Constants (保持更新!) ---
MIN_PLAYERS = 2
HAND_SIZE = 5 # 每人手牌总数
GUN_CHAMBERS = 6
LIVE_BULLETS = 3

# 更新卡牌类型和主牌候选
CARD_TYPES_BASE = ["A", "K", "Q"] # 基础牌型，主牌从中选
JOKER = "Joker" # 万能牌

MAX_PLAY_CARDS = 3
AI_MAX_RETRIES = 3 # AI 调用 LLM 的最大重试次数

# --- Enums (保持不变) ---
class GameStatus(Enum):
    WAITING = auto()
    PLAYING = auto()
    ENDED = auto()

class ShotResult(Enum):
    SAFE = auto()
    HIT = auto()
    ALREADY_ELIMINATED = auto()
    GUN_ERROR = auto()

class ChallengeResult(Enum):
    SUCCESS = auto() # 质疑成功 (出牌者撒谎)
    FAILURE = auto() # 质疑失败 (出牌者诚实)

# --- Data Classes (修改 PlayerData) ---
@dataclass
class PlayerData:
    id: str
    name: str
    hand: List[str] = field(default_factory=list)
    gun: List[str] = field(default_factory=list) # 弹膛顺序
    gun_position: int = 0 # 当前指针
    is_eliminated: bool = False
    is_ai: bool = False # 新增字段，标记是否为 AI 玩家

@dataclass
class LastPlay:
    player_id: str
    player_name: str
    claimed_quantity: int
    actual_cards: List[str]

@dataclass
class GameState:
    status: GameStatus = GameStatus.WAITING
    players: Dict[str, PlayerData] = field(default_factory=dict)
    deck: List[str] = field(default_factory=list) # 游戏开始时构建的完整牌堆
    main_card: Optional[str] = None # A, K, or Q
    turn_order: List[str] = field(default_factory=list)
    current_player_index: int = -1
    last_play: Optional[LastPlay] = None
    discard_pile: List[str] = field(default_factory=list)
    creator_id: Optional[str] = None
    round_start_reason: str = "游戏开始"

# --- Helper for Gun Initialization (保持不变) ---
def initialize_gun() -> Tuple[List[str], int]:
    """Initializes gun chamber and pointer."""
    live_count = LIVE_BULLETS
    empty_count = GUN_CHAMBERS - live_count
    if empty_count < 0:
         empty_count = 1
         live_count = GUN_CHAMBERS - 1
    elif empty_count == 0 and live_count == GUN_CHAMBERS:
         empty_count = 1
         live_count = GUN_CHAMBERS - 1

    bullets = ["空弹"] * empty_count + ["实弹"] * live_count
    random.shuffle(bullets)
    position = random.randint(0, GUN_CHAMBERS - 1)
    logger.debug(f"Initialized gun: Bullets={bullets}, StartPosition={position}")
    return bullets, position