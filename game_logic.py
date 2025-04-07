import random
from typing import Dict, List, Set, Any, Tuple, Callable, Optional
from collections import Counter

from .models import Player, GameState, GameConfig, GameEvent, CardType
from .exceptions import GameError, InvalidActionError, InvalidPlayerError

class LiarsTavernGame:
    """骗子酒馆游戏核心逻辑类"""
    
    def __init__(self, game_id: str, config: GameConfig = None):
        """
        初始化一个新的游戏实例
        
        Args:
            game_id: 游戏唯一标识符（通常是群ID）
            config: 游戏配置，如果为None则使用默认配置
        """
        self.game_id = game_id
        self.config = config or GameConfig()
        self.state = GameState.WAITING
        self.players: Dict[str, Player] = {}
        self.turn_order: List[str] = []
        self.current_player_index: int = -1
        self.main_card: str = None
        self.last_play: Dict = None
        self.discard_pile: List[str] = []
        self.deck: List[str] = []
        
        # 事件回调函数
        self.event_callbacks: Dict[GameEvent, List[Callable]] = {event: [] for event in GameEvent}
    
    def register_callback(self, event: GameEvent, callback: Callable) -> None:
        """注册事件回调函数"""
        if event in self.event_callbacks:
            self.event_callbacks[event].append(callback)
    
    def _trigger_event(self, event: GameEvent, **kwargs) -> None:
        """触发事件，调用所有注册的回调函数"""
        for callback in self.event_callbacks.get(event, []):
            callback(self, **kwargs)
    
    def add_player(self, player_id: str, player_name: str) -> bool:
        """
        添加玩家到游戏
        
        Args:
            player_id: 玩家ID
            player_name: 玩家名称
            
        Returns:
            bool: 是否成功添加
            
        Raises:
            GameError: 如果游戏状态不是等待中
            InvalidPlayerError: 如果玩家已经在游戏中
        """
        if self.state != GameState.WAITING:
            raise GameError("游戏已经开始或结束，无法加入")
        
        if player_id in self.players:
            raise InvalidPlayerError(f"玩家 {player_name} 已经加入了游戏")
        
        # 初始化枪械
        gun, gun_pos = self._initialize_gun()
        
        # 创建玩家
        player = Player(
            id=player_id,
            name=player_name,
            hand=[],
            gun=gun,
            gun_position=gun_pos,
            is_eliminated=False
        )
        
        self.players[player_id] = player
        self._trigger_event(GameEvent.PLAYER_JOINED, player=player)
        return True
    
    def start_game(self) -> bool:
        """
        开始游戏
        
        Returns:
            bool: 是否成功开始游戏
            
        Raises:
            GameError: 如果游戏状态不是等待中或玩家数量不足
        """
        if self.state != GameState.WAITING:
            raise GameError("游戏已经开始或结束")
        
        player_ids = list(self.players.keys())
        player_count = len(player_ids)
        
        if player_count < self.config.MIN_PLAYERS:
            raise GameError(f"至少需要 {self.config.MIN_PLAYERS} 名玩家才能开始游戏，当前只有 {player_count} 人")
        
        # 构建牌堆
        self.deck = self._build_deck(player_count)
        self.main_card = self._determine_main_card()
        
        # 发牌
        self._deal_cards(self.deck, player_ids)
        
        # 确定玩家顺序
        self.turn_order = random.sample(player_ids, len(player_ids))
        self.current_player_index = 0
        self.state = GameState.PLAYING
        self.last_play = None
        self.discard_pile = []
        
        self._trigger_event(GameEvent.GAME_STARTED, 
                           main_card=self.main_card, 
                           turn_order=self.turn_order,
                           first_player_id=self.turn_order[0])
        return True
    
    def _initialize_gun(self) -> Tuple[List[str], int]:
        """初始化枪械，返回弹巢和初始位置"""
        live_count = self.config.LIVE_BULLETS
        empty_count = self.config.GUN_CHAMBERS - live_count
        
        if empty_count < 0:
            empty_count = 1
            live_count = self.config.GUN_CHAMBERS - 1
        
        bullets = ["空弹"] * empty_count + ["实弹"] * live_count
        random.shuffle(bullets)
        return bullets, 0
    
    def _build_deck(self, player_count: int) -> List[str]:
        """构建牌堆"""
        deck = []
        for card_type in self.config.CARD_TYPES:
            deck.extend([card_type] * self.config.CARDS_PER_TYPE)
        
        joker_count = player_count // 2
        deck.extend([self.config.JOKER] * joker_count)
        return deck
    
    def _determine_main_card(self) -> str:
        """确定主牌"""
        return random.choice(self.config.CARD_TYPES)
    
    def _deal_cards(self, deck: List[str], player_ids: List[str]) -> None:
        """发牌给玩家"""
        current_deck = list(deck)
        random.shuffle(current_deck)
        
        for player_id in player_ids:
            hand = []
            for _ in range(self.config.HAND_SIZE):
                if current_deck:
                    hand.append(current_deck.pop())
                else:
                    break
            self.players[player_id].hand = hand
            
            self._trigger_event(GameEvent.CARDS_DEALT, 
                               player_id=player_id, 
                               hand=hand, 
                               main_card=self.main_card)
    
    def get_current_player(self) -> Optional[Player]:
        """获取当前玩家"""
        if self.state != GameState.PLAYING:
            return None
        
        if 0 <= self.current_player_index < len(self.turn_order):
            current_player_id = self.turn_order[self.current_player_index]
            return self.players.get(current_player_id)
        
        return None
    
    def get_active_players(self) -> List[str]:
        """获取所有活跃（未被淘汰）的玩家ID"""
        return [pid for pid, player in self.players.items() 
                if not player.is_eliminated]
    
    def get_next_player_index(self) -> int:
        """获取下一个玩家的索引"""
        if self.state != GameState.PLAYING:
            return -1
        
        current_index = self.current_player_index
        turn_order = self.turn_order
        num_players = len(turn_order)
        
        if num_players == 0:
            return -1
        
        next_index = (current_index + 1) % num_players
        active_player_found = False
        
        for _ in range(num_players):
            if not self.players[turn_order[next_index]].is_eliminated:
                active_player_found = True
                break
            next_index = (next_index + 1) % num_players
        
        if not active_player_found:
            return -1
            
        return next_index
    
    def play_cards(self, player_id: str, card_indices: List[int]) -> bool:
        """
        玩家出牌
        
        Args:
            player_id: 玩家ID
            card_indices: 要出的牌的索引（基于1）
            
        Returns:
            bool: 是否成功出牌
            
        Raises:
            GameError: 如果游戏状态不是进行中
            InvalidPlayerError: 如果不是当前玩家的回合
            InvalidActionError: 如果出牌无效
        """
        if self.state != GameState.PLAYING:
            raise GameError("游戏未在进行中")
        
        current_player_id = self.turn_order[self.current_player_index]
        if player_id != current_player_id:
            raise InvalidPlayerError("还没轮到你")
        
        player = self.players[player_id]
        
        # 检查手牌是否为空
        if not player.hand:
            raise InvalidActionError("你手牌已空，无法出牌")
        
        # 验证索引
        indices_0based = [i - 1 for i in card_indices]
        hand_size = len(player.hand)
        
        invalid_indices = [i + 1 for i in indices_0based if i < 0 or i >= hand_size]
        if invalid_indices:
            raise InvalidActionError(f"无效的编号: {', '.join(map(str, invalid_indices))}。你的手牌只有 {hand_size} 张 (编号 1 到 {hand_size})")
        
        # 检查出牌数量
        if not (1 <= len(card_indices) <= 3):
            raise InvalidActionError("出牌数量必须是 1 到 3 张")
        
        # 检查是否有重复索引
        if len(indices_0based) != len(set(indices_0based)):
            raise InvalidActionError("出牌编号不能重复")
        
        # 处理上一轮出牌
        if self.last_play:
            accepted_cards = self.last_play["actual_cards"]
            self.discard_pile.extend(accepted_cards)
            self.last_play = None
        
        # 执行出牌
        cards_to_play = [player.hand[i] for i in indices_0based]
        new_hand = []
        indices_played_set = set(indices_0based)
        
        for i, card in enumerate(player.hand):
            if i not in indices_played_set:
                new_hand.append(card)
        
        player.hand = new_hand
        quantity_played = len(cards_to_play)
        
        self.last_play = {
            "player_id": player_id,
            "claimed_quantity": quantity_played,
            "actual_cards": cards_to_play
        }
        
        # 确定下一玩家
        next_player_index = self.get_next_player_index()
        if next_player_index == -1:
            raise GameError("无法确定下一位玩家")
        
        self.current_player_index = next_player_index
        next_player_id = self.turn_order[next_player_index]
        
        # 检查所有手牌是否为空
        if self._check_all_hands_empty():
            self._reshuffle_and_redeal("所有活跃玩家手牌已空")
            return True
        
        self._trigger_event(GameEvent.CARDS_PLAYED, 
                           player_id=player_id,
                           cards_played=cards_to_play,
                           quantity_played=quantity_played,
                           next_player_id=next_player_id,
                           player_hand_empty=(len(new_hand) == 0))
        
        return True
    
    def challenge(self, challenger_id: str) -> bool:
        """
        玩家质疑上一轮出牌
        
        Args:
            challenger_id: 质疑者ID
            
        Returns:
            bool: 是否成功质疑
            
        Raises:
            GameError: 如果游戏状态不是进行中
            InvalidPlayerError: 如果不是当前玩家的回合
            InvalidActionError: 如果没有可质疑的出牌
        """
        if self.state != GameState.PLAYING:
            raise GameError("游戏未在进行中")
        
        reacting_player_id = self.turn_order[self.current_player_index]
        if challenger_id != reacting_player_id:
            raise InvalidPlayerError("还没轮到你反应")
        
        if not self.last_play:
            raise InvalidActionError("当前没有可质疑的出牌")
        
        player_who_played_id = self.last_play["player_id"]
        actual_cards = self.last_play["actual_cards"]
        claimed_quantity = self.last_play["claimed_quantity"]
        
        # 检查质疑是否成功
        is_claim_true = self._check_challenge(actual_cards, self.main_card)
        loser_id = challenger_id if is_claim_true else player_who_played_id
        
        # 将牌放入弃牌堆
        self.discard_pile.extend(actual_cards)
        self.last_play = None
        
        # 触发质疑事件
        self._trigger_event(GameEvent.CHALLENGE_MADE, 
                           challenger_id=challenger_id,
                           challenged_id=player_who_played_id,
                           actual_cards=actual_cards,
                           is_claim_true=is_claim_true,
                           loser_id=loser_id)
        
        # 输家开枪
        shot_result = self.take_shot(loser_id)
        
        # 如果游戏结束，直接返回
        if self.state == GameState.ENDED:
            return True
        
        # 如果有人被淘汰，重新洗牌发牌
        if shot_result["is_eliminated"]:
            self._reshuffle_and_redeal(f"玩家 {self.players[loser_id].name} 被淘汰", eliminated_player_id=loser_id)
            return True
        
        # 确定下一轮出牌者
        challenger_still_active = not self.players[challenger_id].is_eliminated
        if challenger_still_active:
            self.current_player_index = self.turn_order.index(challenger_id)
            next_player_id = challenger_id
        else:
            next_active_index = self.get_next_player_index()
            if next_active_index != -1:
                self.current_player_index = next_active_index
                next_player_id = self.turn_order[next_active_index]
            else:
                raise GameError("质疑后无法确定下一位玩家")
        
        # 检查所有手牌是否为空
        if self._check_all_hands_empty():
            self._reshuffle_and_redeal("所有活跃玩家手牌已空")
            return True
        
        # 触发下一轮事件
        self._trigger_event(GameEvent.NEXT_TURN, 
                           player_id=next_player_id,
                           player_hand_empty=(not self.players[next_player_id].hand))
        
        return True
    
    def wait_turn(self, player_id: str) -> bool:
        """
        玩家选择等待（仅限手牌为空时）
        
        Args:
            player_id: 玩家ID
            
        Returns:
            bool: 是否成功等待
            
        Raises:
            GameError: 如果游戏状态不是进行中
            InvalidPlayerError: 如果不是当前玩家的回合
            InvalidActionError: 如果玩家手牌不为空
        """
        if self.state != GameState.PLAYING:
            raise GameError("游戏未在进行中")
        
        current_player_id = self.turn_order[self.current_player_index]
        if player_id != current_player_id:
            raise InvalidPlayerError("还没轮到你")
        
        player = self.players[player_id]
        
        # 检查手牌是否为空
        if player.hand:
            raise InvalidActionError("你还有手牌，不能选择等待")
        
        # 处理上一轮出牌
        if self.last_play:
            accepted_cards = self.last_play["actual_cards"]
            self.discard_pile.extend(accepted_cards)
            self.last_play = None
        
        # 确定下一玩家
        next_player_index = self.get_next_player_index()
        if next_player_index == -1:
            raise GameError("无法确定下一位玩家")
        
        self.current_player_index = next_player_index
        next_player_id = self.turn_order[next_player_index]
        
        # 检查所有手牌是否为空
        if self._check_all_hands_empty():
            self._reshuffle_and_redeal("所有活跃玩家手牌已空")
            return True
        
        self._trigger_event(GameEvent.PLAYER_WAITED, 
                           player_id=player_id,
                           next_player_id=next_player_id,
                           next_player_hand_empty=(not self.players[next_player_id].hand))
        
        return True
    
    def take_shot(self, player_id: str) -> Dict:
        """
        玩家开枪
        
        Args:
            player_id: 玩家ID
            
        Returns:
            Dict: 包含开枪结果的字典
        """
        player = self.players[player_id]
        
        if player.is_eliminated:
            return {"success": False, "message": "玩家已被淘汰"}
        
        gun = player.gun
        position = player.gun_position
        bullet = gun[position]
        player.gun_position = (position + 1) % len(gun)
        
        result = {
            "success": True,
            "player_id": player_id,
            "bullet": bullet,
            "is_eliminated": False
        }
        
        if bullet == "实弹":
            player.is_eliminated = True
            result["is_eliminated"] = True
            
            self._trigger_event(GameEvent.PLAYER_SHOT, 
                               player_id=player_id,
                               is_eliminated=True)
            
            # 检查游戏是否结束
            if self._check_game_end():
                return result
        else:
            self._trigger_event(GameEvent.PLAYER_SHOT, 
                               player_id=player_id,
                               is_eliminated=False)
        
        return result
    
    def _check_challenge(self, actual_cards: List[str], main_card: str) -> bool:
        """检查质疑是否成功（即出牌是否符合声明）"""
        return all(card == main_card or card == self.config.JOKER for card in actual_cards)
    
    def _check_game_end(self) -> bool:
        """检查游戏是否结束"""
        active_players = self.get_active_players()
        
        if len(active_players) <= 1:
            self.state = GameState.ENDED
            winner_id = active_players[0] if active_players else None
            
            self._trigger_event(GameEvent.GAME_ENDED, 
                               winner_id=winner_id,
                               winner_name=self.players[winner_id].name if winner_id else "无人")
            
            return True
        
        return False
    
    def _check_all_hands_empty(self) -> bool:
        """检查所有活跃玩家的手牌是否都为空"""
        active_players = self.get_active_players()
        
        if not active_players:
            return False
        
        return all(not self.players[pid].hand for pid in active_players)
    
    def _reshuffle_and_redeal(self, reason: str, eliminated_player_id: str = None) -> None:
        """
        重新洗牌并发牌
        
        Args:
            reason: 重洗的原因
            eliminated_player_id: 被淘汰的玩家ID（如果有）
        """
        active_player_ids = self.get_active_players()
        
        if not active_player_ids:
            self.state = GameState.ENDED
            self._trigger_event(GameEvent.GAME_ENDED, 
                               winner_id=None,
                               winner_name="无人")
            return
        
        # 收集所有牌
        new_deck = list(self.discard_pile)
        self.discard_pile = []
        
        for p_id in active_player_ids:
            player_hand = self.players[p_id].hand
            if player_hand:
                new_deck.extend(player_hand)
                self.players[p_id].hand = []
        
        # 确定新主牌
        self.main_card = self._determine_main_card()
        
        # 洗牌
        random.shuffle(new_deck)
        
        # 重新发牌
        for p_id in active_player_ids:
            hand = []
            for _ in range(self.config.HAND_SIZE):
                if new_deck:
                    hand.append(new_deck.pop())
                else:
                    break
            self.players[p_id].hand = hand
            
            self._trigger_event(GameEvent.CARDS_DEALT, 
                               player_id=p_id,
                               hand=hand,
                               main_card=self.main_card)
        
        # 确定新一轮的起始玩家
        start_player_id = None
        start_player_index = -1
        turn_order = self.turn_order
        num_players = len(turn_order)
        
        if eliminated_player_id:
            # 如果有人被淘汰，从被淘汰者的下一位开始找活跃玩家
            try:
                eliminated_idx = turn_order.index(eliminated_player_id)
                current_check_idx = (eliminated_idx + 1) % num_players
                
                for _ in range(num_players):
                    potential_starter_id = turn_order[current_check_idx]
                    if not self.players[potential_starter_id].is_eliminated:
                        start_player_id = potential_starter_id
                        start_player_index = current_check_idx
                        break
                    current_check_idx = (current_check_idx + 1) % num_players
            except ValueError:
                # Fallback: 随机选一个活跃玩家
                if active_player_ids:
                    start_player_id = random.choice(active_player_ids)
                    try:
                        start_player_index = turn_order.index(start_player_id)
                    except ValueError:
                        # 严重错误，可能需要结束游戏
                        self.state = GameState.ENDED
                        self._trigger_event(GameEvent.GAME_ENDED, 
                                           winner_id=None,
                                           winner_name="无人")
                        return
        else:
            # 从上一轮的当前玩家开始找活跃玩家
            current_check_idx = self.current_player_index
            
            for _ in range(num_players):
                potential_starter_id = turn_order[current_check_idx]
                if not self.players[potential_starter_id].is_eliminated:
                    start_player_id = potential_starter_id
                    start_player_index = current_check_idx
                    break
                current_check_idx = (current_check_idx + 1) % num_players
        
        # 检查是否找到起始玩家
        if start_player_id is None:
            self.state = GameState.ENDED
            self._trigger_event(GameEvent.GAME_ENDED, 
                               winner_id=None,
                               winner_name="无人")
            return
        
        self.current_player_index = start_player_index
        self.last_play = None
        
        # 触发重洗事件
        self._trigger_event(GameEvent.RESHUFFLED, 
                           reason=reason,
                           main_card=self.main_card,
                           start_player_id=start_player_id)
    
    def force_end(self) -> bool:
        """强制结束游戏"""
        if self.state == GameState.ENDED:
            return False
        
        self.state = GameState.ENDED
        self._trigger_event(GameEvent.GAME_ENDED, 
                           winner_id=None,
                           winner_name="无人",
                           forced=True)
        
        return True
    
    def get_game_status(self) -> Dict:
        """获取游戏状态信息"""
        status = {
            "game_id": self.game_id,
            "state": self.state.value,
            "player_count": len(self.players),
            "active_player_count": len(self.get_active_players()),
            "discard_pile_count": len(self.discard_pile),
            "deck_count": len(self.deck)
        }
        
        if self.state != GameState.WAITING:
            status.update({
                "main_card": self.main_card,
                "turn_order": [self.players[pid].name for pid in self.turn_order],
                "current_player_index": self.current_player_index
            })
            
            if 0 <= self.current_player_index < len(self.turn_order):
                current_player_id = self.turn_order[self.current_player_index]
                status["current_player"] = {
                    "id": current_player_id,
                    "name": self.players[current_player_id].name
                }
            
            if self.last_play:
                status["last_play"] = {
                    "player_id": self.last_play["player_id"],
                    "player_name": self.players[self.last_play["player_id"]].name,
                    "claimed_quantity": self.last_play["claimed_quantity"]
                }
        
        status["players"] = {}
        for pid, player in self.players.items():
            status["players"][pid] = {
                "name": player.name,
                "is_eliminated": player.is_eliminated,
                "hand_size": len(player.hand)
            }
        
        return status
