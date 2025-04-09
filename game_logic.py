# 请将这段代码完整粘贴到 game_logic.py 文件中 (已添加更多日志用于调试)

# liar_tavern/game_logic.py

# -*- coding: utf-8 -*-

import random
import logging
from typing import List, Dict, Optional, Tuple, Any
import math

# Import models and exceptions
from .models import (
    GameState, PlayerData, GameStatus, LastPlay, ShotResult, ChallengeResult,
    HAND_SIZE, CARD_TYPES_BASE, JOKER, MAX_PLAY_CARDS, MIN_PLAYERS,
    initialize_gun
)
from .exceptions import (
    GameError, PlayerNotInGameError, NotPlayersTurnError, InvalidCardIndexError,
    InvalidPlayQuantityError, NoChallengeTargetError, EmptyHandError, InvalidActionError,
    PlayerAlreadyJoinedError, GameNotWaitingError, GameNotPlayingError,
    NotEnoughPlayersError
)

logger = logging.getLogger(__name__)

class LiarDiceGame:
    """Encapsulates the state and logic for a single game instance."""

    def __init__(self, creator_id: Optional[str] = None):
        self.state = GameState(status=GameStatus.WAITING, creator_id=creator_id)
        logger.debug("New LiarDiceGame instance created.")

    def add_player(self, player_id: str, player_name: str) -> None:
        """Adds a player to the game during the WAITING phase."""
        if self.state.status != GameStatus.WAITING:
             raise GameNotWaitingError(f"游戏正在进行({self.state.status.name})，无法加入。")
        if player_id in self.state.players:
            logger.warning(f"Player {player_name}({player_id}) attempted to join again (ignored).")
            return
        gun_bullets, gun_pos = initialize_gun()
        self.state.players[player_id] = PlayerData(id=player_id, name=player_name, gun=gun_bullets, gun_position=gun_pos)
        logger.info(f"Player {player_name}({player_id}) added. Total players: {len(self.state.players)}")

    def start_game(self) -> Dict[str, Any]:
        """Starts the game, deals cards, determines turn order."""
        if self.state.status != GameStatus.WAITING: raise InvalidActionError("游戏未处于等待状态。")
        if len(self.state.players) < MIN_PLAYERS: raise NotEnoughPlayersError(f"至少需要 {MIN_PLAYERS} 人才能开始。")

        player_ids = list(self.state.players.keys()); player_count = len(player_ids)
        self.state.main_card = random.choice(CARD_TYPES_BASE); logger.info(f"Game starting. Main card: {self.state.main_card}")
        self.state.deck = self._build_deck(player_count)
        logger.debug(f"Built deck ({len(self.state.deck)} cards)")
        try: self._deal_cards_new_rule()
        except ValueError as e: logger.error(f"Dealing failed: {e}"); raise GameError(f"发牌失败: {e}")
        except IndexError as e: logger.error(f"Dealing failed with IndexError: {e}", exc_info=True); raise GameError(f"发牌失败: 内部索引错误，请检查逻辑。")

        self.state.turn_order = random.sample(player_ids, player_count)
        self.state.current_player_index = 0; self.state.status = GameStatus.PLAYING; self.state.last_play = None; self.state.discard_pile = []; self.state.round_start_reason = "游戏开始"
        logger.info(f"Game started. Order: {[self.state.players[pid].name for pid in self.state.turn_order]}")

        initial_hands = {pid: pdata.hand for pid, pdata in self.state.players.items()}
        current_player_id = self.get_current_player_id(); current_player_name = self.get_current_player_name()
        return {"success": True, "main_card": self.state.main_card, "turn_order_names": [self.state.players[pid].name for pid in self.state.turn_order], "initial_hands": initial_hands, "first_player_id": current_player_id, "first_player_name": current_player_name }

    def process_play_card(self, player_id: str, card_indices_1based: List[int]) -> Dict[str, Any]:
        """Processes a player's card play action with validation."""
        self._check_is_playing(); self._check_player_turn(player_id)
        player_data = self.state.players[player_id]; hand_size = len(player_data.hand)
        if not hand_size > 0: raise EmptyHandError("手牌为空，无法出牌。")

        num_indices_provided = len(card_indices_1based)
        if not (1 <= num_indices_provided <= MAX_PLAY_CARDS): raise InvalidPlayQuantityError(f"每次出牌需提供 1 到 {MAX_PLAY_CARDS} 个有效编号，您提供了 {num_indices_provided} 个。")
        if len(card_indices_1based) != len(set(card_indices_1based)): raise InvalidCardIndexError("出牌编号不能重复。")

        indices_0based = [i - 1 for i in card_indices_1based]
        invalid_indices = [i + 1 for i in indices_0based if i < 0 or i >= hand_size]
        if invalid_indices: invalid_str = ', '.join(map(str, invalid_indices)); raise InvalidCardIndexError(f"无效编号: {invalid_str} (你只有编号 1 到 {hand_size} 的牌)。")

        num_unique_cards_to_play = len(indices_0based)
        if num_unique_cards_to_play > hand_size: logger.error(f"Logic Error? Play {num_unique_cards_to_play} > hand {hand_size}. P:{player_id}, I:{card_indices_1based}"); raise InvalidPlayQuantityError(f"逻辑错误：试图打出比手牌 ({hand_size}) 更多的牌 ({num_unique_cards_to_play})。")

        logger.debug(f"P:{player_id} validated play idx {card_indices_1based} (0based: {indices_0based}) hand size {hand_size}.")
        accepted_play_info = None
        if self.state.last_play: accepted_cards = self.state.last_play.actual_cards; self.state.discard_pile.extend(accepted_cards); accepted_play_info = { "player_id": self.state.last_play.player_id, "player_name": self.state.last_play.player_name, "cards": accepted_cards }; logger.info(f"{player_data.name} accepts {self.state.last_play.player_name}'s cards."); self.state.last_play = None

        cards_to_play = [player_data.hand[i] for i in indices_0based]
        indices_played_set = set(indices_0based); new_hand = [card for i, card in enumerate(player_data.hand) if i not in indices_played_set]; player_data.hand = new_hand
        quantity_played = len(cards_to_play)
        self.state.last_play = LastPlay(player_id, player_data.name, quantity_played, cards_to_play)
        logger.info(f"{player_data.name} played {quantity_played} (Actual: {cards_to_play}). Hand size now: {len(new_hand)}")

        reshuffle_result = self._check_and_handle_all_hands_empty_internal("玩家出牌后")
        if reshuffle_result["reshuffled"]:
             reshuffle_result.update({"accepted_play_info": accepted_play_info, "player_who_played_id": player_id, "player_who_played_name": player_data.name, "played_quantity": quantity_played, "played_cards": cards_to_play, "played_hand_empty": not new_hand, "action": "play"}); logger.info(f"{player_data.name} play triggered reshuffle."); return reshuffle_result

        next_player_id, next_player_name = self._advance_turn()
        if next_player_id is None:
             logger.error("Play card: Could not advance turn, game ending."); self.state.status = GameStatus.ENDED
             winner_id = self._get_winner_id(); winner_name = self.state.players[winner_id].name if winner_id else "无人"
             return { "success": True, "action": "play", "player_id": player_id, "player_name": player_data.name, "quantity_played": quantity_played, "actual_cards": cards_to_play, "main_card": self.state.main_card, "hand_after_play": new_hand, "played_hand_empty": not new_hand, "accepted_play_info": accepted_play_info, "game_ended": True, "winner_id": winner_id, "winner_name": winner_name }

        next_player_data = self.state.players.get(next_player_id); next_hand_empty_flag = (not next_player_data.hand) if next_player_data else True
        return { "success": True, "action": "play", "player_id": player_id, "player_name": player_data.name, "quantity_played": quantity_played, "actual_cards": cards_to_play, "main_card": self.state.main_card, "hand_after_play": new_hand, "played_hand_empty": not new_hand, "next_player_id": next_player_id, "next_player_name": next_player_name, "next_player_hand_empty": next_hand_empty_flag, "accepted_play_info": accepted_play_info, "reshuffled": False, "game_ended": False }

    def process_challenge(self, challenger_id: str) -> Dict[str, Any]:
        """Processes a player's challenge action."""
        self._check_is_playing(); self._check_player_turn(challenger_id)
        if not self.state.last_play: raise NoChallengeTargetError("当前没有可以质疑的出牌。")

        challenger_name = self.state.players[challenger_id].name; last_play = self.state.last_play
        challenged_player_id = last_play.player_id; challenged_player_name = last_play.player_name
        actual_cards = last_play.actual_cards; claimed_quantity = last_play.claimed_quantity
        logger.info(f"{challenger_name} challenges {challenged_player_name}'s {claimed_quantity} cards (Actual: {actual_cards})")

        is_claim_true = all(card == self.state.main_card or card == JOKER for card in actual_cards)
        challenge_result = ChallengeResult.FAILURE if is_claim_true else ChallengeResult.SUCCESS
        loser_id = challenger_id if challenge_result == ChallengeResult.FAILURE else challenged_player_id
        loser_name = self.state.players[loser_id].name
        logger.info(f"Challenge result: {challenge_result}. Loser: {loser_name}")

        self.state.discard_pile.extend(actual_cards); self.state.last_play = None
        shot_outcome = self._determine_shot_outcome(loser_id)
        shot_applied_result = self._apply_shot_consequences(loser_id, shot_outcome)

        result_base = { "success": True, "action": "challenge", "challenger_id": challenger_id, "challenger_name": challenger_name, "challenged_player_id": challenged_player_id, "challenged_player_name": challenged_player_name, "claimed_quantity": claimed_quantity, "actual_cards": actual_cards, "main_card": self.state.main_card, "challenge_result": challenge_result, "loser_id": loser_id, "loser_name": loser_name, "shot_outcome": shot_outcome }
        result_base.update(shot_applied_result)

        if not result_base.get("game_ended") and not result_base.get("reshuffled"):
            next_player_id = None
            challenger_still_active = challenger_id in self.state.players and not self.state.players[challenger_id].is_eliminated
            if challenger_still_active:
                next_player_id = challenger_id
                try: self.state.current_player_index = self.state.turn_order.index(challenger_id)
                except ValueError: logger.warning(f"Challenger {challenger_id} not in turn order?"); next_player_id, _ = self._advance_turn()
            else: next_player_id, _ = self._advance_turn()

            if next_player_id:
                 next_player_data = self.state.players.get(next_player_id)
                 result_base["next_player_id"] = next_player_id; result_base["next_player_name"] = next_player_data.name if next_player_data else "错误"; result_base["next_player_hand_empty"] = (not next_player_data.hand) if next_player_data else True
            else: logger.error("Challenge: Could not advance turn, game ending."); self.state.status = GameStatus.ENDED; result_base["game_ended"] = True; winner_id = self._get_winner_id(); result_base["winner_id"] = winner_id; result_base["winner_name"] = self.state.players[winner_id].name if winner_id else "无人"

            if not result_base.get("game_ended"):
                reshuffle_check = self._check_and_handle_all_hands_empty_internal("质疑结算后");
                if reshuffle_check["reshuffled"]: result_base.update(reshuffle_check); result_base["reshuffled"] = True
        return result_base

    def _apply_shot_consequences(self, player_id: str, shot_outcome: ShotResult) -> Dict[str, Any]:
         """Applies state changes for shot outcome. Returns dict with game_ended/reshuffled flags."""
         update_result = {"game_ended": False, "reshuffled": False}
         player_data = self.state.players.get(player_id)
         if not player_data: logger.error(f"Player {player_id} not found for shot."); return {"error": "Player not found."}

         gun = player_data.gun; position = player_data.gun_position; gun_chambers = len(gun)
         # Advance pointer AFTER shot outcome is determined based on CURRENT position
         if gun and position is not None and gun_chambers > 0:
              logger.debug(f"Advancing gun pointer for {player_data.name} from {position}...")
              player_data.gun_position = (position + 1) % gun_chambers
              logger.debug(f"  New gun pointer: {player_data.gun_position}")
         else: logger.error(f"Cannot update gun position for {player_data.name}.")

         if shot_outcome == ShotResult.HIT:
             if not player_data.is_eliminated:
                 player_data.is_eliminated = True; logger.info(f"{player_data.name} is eliminated.")
                 if self._check_game_end_internal():
                      update_result["game_ended"] = True; self.state.status = GameStatus.ENDED
                      winner_id = self._get_winner_id(); update_result["winner_id"] = winner_id; update_result["winner_name"] = self.state.players[winner_id].name if winner_id else "无人"; logger.info("Game ended due to elimination.")
                 else:
                      logger.info("Elimination triggering reshuffle.")
                      reshuffle_internal_result = self._reshuffle_internal(f"玩家 {player_data.name} 被淘汰", eliminated_player_id=player_id); update_result.update(reshuffle_internal_result); update_result["reshuffled"] = True
         elif shot_outcome == ShotResult.SAFE: logger.info(f"{player_data.name} was safe.")
         elif shot_outcome == ShotResult.ALREADY_ELIMINATED: logger.warning(f"Shot consequence on already eliminated {player_data.name}.")
         elif shot_outcome == ShotResult.GUN_ERROR: logger.error(f"Gun error for {player_data.name}."); update_result["error"] = "枪支错误"
         return update_result

    def process_wait(self, player_id: str) -> Dict[str, Any]:
        """Processes a player's 'wait' action (only if hand is empty)."""
        self._check_is_playing(); self._check_player_turn(player_id)
        player_data = self.state.players[player_id]
        if player_data.hand: raise InvalidActionError("手牌不为空，不能选择等待。")

        logger.info(f"{player_data.name} waits (empty hand).")
        accepted_play_info = None
        if self.state.last_play:
            accepted_cards = self.state.last_play.actual_cards; self.state.discard_pile.extend(accepted_cards); accepted_play_info = { "player_id": self.state.last_play.player_id, "player_name": self.state.last_play.player_name, "cards": accepted_cards }; logger.info(f"{player_data.name} accepts {self.state.last_play.player_name}'s cards by waiting."); self.state.last_play = None

        reshuffle_result = self._check_and_handle_all_hands_empty_internal("玩家等待后")
        if reshuffle_result["reshuffled"]: reshuffle_result.update({"accepted_play_info": accepted_play_info, "player_who_waited_id": player_id, "player_who_waited_name": player_data.name, "action": "wait"}); return reshuffle_result

        next_player_id, next_player_name = self._advance_turn()
        if next_player_id is None: logger.error("Wait: Could not advance turn, game ending."); self.state.status = GameStatus.ENDED; winner_id = self._get_winner_id(); winner_name = self.state.players[winner_id].name if winner_id else "无人"; return {"success": True, "action": "wait", "player_id": player_id, "player_name": player_data.name, "accepted_play_info": accepted_play_info, "game_ended": True, "winner_id": winner_id, "winner_name": winner_name}

        next_player_data = self.state.players.get(next_player_id); next_hand_empty_flag = (not next_player_data.hand) if next_player_data else True
        return { "success": True, "action": "wait", "player_id": player_id, "player_name": player_data.name, "next_player_id": next_player_id, "next_player_name": next_player_name, "next_player_hand_empty": next_hand_empty_flag, "accepted_play_info": accepted_play_info, "reshuffled": False, "game_ended": False }

    # --- Internal Helper Methods ---
    def _check_is_playing(self):
        if self.state.status != GameStatus.PLAYING: raise GameNotPlayingError(f"游戏需要为 PLAYING 状态 (当前: {self.state.status.name})。")
    def _check_player_turn(self, player_id: str):
        current_player_id = self.get_current_player_id();
        if current_player_id != player_id: current_name = self.get_current_player_name() or "未知"; raise NotPlayersTurnError(f"还没轮到你，当前轮到 {current_name}。", current_player_name=current_name)
        player_data = self.state.players.get(player_id);
        if not player_data: raise PlayerNotInGameError(f"玩家 {player_id} 不在本局。")
        if player_data.is_eliminated: raise InvalidActionError(f"你 ({player_data.name}) 已被淘汰。")
    def get_current_player_id(self) -> Optional[str]:
        if self.state.status != GameStatus.PLAYING or not self.state.turn_order or not (0 <= self.state.current_player_index < len(self.state.turn_order)): return None
        try: return self.state.turn_order[self.state.current_player_index]
        except IndexError: logger.error(f"IndexError get current player at {self.state.current_player_index}"); return None
    def get_current_player_name(self) -> Optional[str]:
        player_id = self.get_current_player_id(); player_data = self.state.players.get(player_id) if player_id else None; return player_data.name if player_data else None
    def get_player_hand(self, player_id: str) -> Optional[List[str]]:
         player = self.state.players.get(player_id); return list(player.hand) if player else None
    def get_player_status_info(self) -> List[Dict[str, Any]]:
         status_list = [];
         for pid in self.state.turn_order:
              pdata = self.state.players.get(pid);
              if pdata: status_list.append({"id": pid, "name": pdata.name, "is_eliminated": pdata.is_eliminated, "hand_count": len(pdata.hand) if not pdata.is_eliminated else 0})
              else: logger.warning(f"Player {pid} in order but not dict."); status_list.append({"id": pid, "name": f"[未知:{pid}]", "is_eliminated": True, "hand_count": 0})
         return status_list
    def _build_deck(self, player_count: int) -> List[str]:
        """Builds a deck with sufficient cards dynamically based on player count."""
        if player_count <= 0: return []
        hand_size = HAND_SIZE; num_base_types = len(CARD_TYPES_BASE); min_base_cards_per_type = max(5, MAX_PLAY_CARDS * 2)
        total_cards_needed = player_count * hand_size; joker_count = math.ceil(player_count / 2)
        total_base_cards_needed = total_cards_needed - joker_count
        base_per_type_calc = math.ceil(max(0, total_base_cards_needed) / num_base_types)
        base_per_type = max(base_per_type_calc, min_base_cards_per_type)
        deck = [];
        for card_type in CARD_TYPES_BASE: deck.extend([card_type] * base_per_type)
        deck.extend([JOKER] * joker_count)
        logger.info(f"动态构建牌堆 ({player_count}名玩家): {num_base_types}种基础牌各 {base_per_type} 张, {joker_count} 张 Joker. 总牌数: {len(deck)} (需求: {total_cards_needed}).")
        return deck

    # --- MODIFIED _deal_cards_new_rule with detailed logging ---
    def _deal_cards_new_rule(self):
        """Deals cards from self.state.deck to active players based on main card rule."""
        main_card = self.state.main_card; active_player_ids = self._get_active_player_ids();
        if not main_card: raise GameError("Deal fail: Main card not set.");
        if not active_player_ids: logger.warning("Deal: No active players."); return

        deck = list(self.state.deck); random.shuffle(deck)
        required_main_or_joker = len(active_player_ids) * 2; available_main = deck.count(main_card); available_joker = deck.count(JOKER)
        if available_main + available_joker < required_main_or_joker: raise ValueError(f"牌堆主牌({main_card})/Joker不足 ({available_main}+{available_joker}), 无法满足每人至少需要 {required_main_or_joker // len(active_player_ids)} 张的需求")
        if len(deck) < len(active_player_ids) * HAND_SIZE: logger.warning(f"Deck size ({len(deck)}) insufficient for {len(active_player_ids)}*{HAND_SIZE} cards.")

        deck_after_min_deal = list(deck); temp_hands = {pid: [] for pid in active_player_ids}; main_cards_dealt_total = 0; jokers_used_for_main_total = 0
        logger.debug(f"开始发保底牌 (主牌 {main_card})...")
        for p_id in active_player_ids:
            dealt_main = 0; dealt_joker = 0; needed = 2
            logger.debug(f"  为 {p_id} 发保底牌:")
            # 1. 发主牌
            indices_to_remove_main = [i for i, card in enumerate(deck_after_min_deal) if card == main_card]
            logger.debug(f"    找到 {len(indices_to_remove_main)} 个主牌索引: {indices_to_remove_main}")
            for index in sorted(indices_to_remove_main, reverse=True):
                if dealt_main < needed:
                    try: card_popped = deck_after_min_deal.pop(index); temp_hands[p_id].append(card_popped); dealt_main += 1; main_cards_dealt_total += 1; # logger.debug(f"      -> 发了主牌 {card_popped} (来自索引 {index})") # Verbose
                    except IndexError: logger.error(f"IndexError popping main card at {index} for {p_id}"); break
                else: break
            logger.debug(f"    发完主牌后，需要 {needed - dealt_main} 张 Joker。")
            # 2. 补 Joker (Fixed Logic)
            needed -= dealt_main
            if needed > 0:
                all_joker_indices = [i for i, card in enumerate(deck_after_min_deal) if card == JOKER]
                logger.debug(f"    找到 {len(all_joker_indices)} 个 Joker 索引: {all_joker_indices}")
                jokers_popped_count = 0
                for index in sorted(all_joker_indices, reverse=True):
                    if dealt_joker < needed: # Check *inside* the loop
                        try: card_popped = deck_after_min_deal.pop(index); temp_hands[p_id].append(card_popped); dealt_joker += 1; jokers_used_for_main_total += 1; jokers_popped_count += 1; # logger.debug(f"      -> 发了 Joker {card_popped} (来自索引 {index})") # Verbose
                        except IndexError: logger.error(f"IndexError popping joker at {index} for {p_id}"); break
                    else: break # Stop when enough jokers are dealt for this player
                logger.debug(f"    实际补发 {jokers_popped_count} 张 Joker。")
            logger.debug(f"    保底牌完成: {dealt_main} 主牌, {dealt_joker} Joker。当前手牌: {temp_hands[p_id]}")
            if dealt_main + dealt_joker < 2: logger.error(f"Logic error: Failed dealing min 2 main/joker to {p_id}! Got {dealt_main}+{dealt_joker}."); raise GameError(f"内部错误：无法为玩家 {self.state.players[p_id].name} 发放足够的保底牌。")

        logger.info(f"保底牌发放统计: {main_cards_dealt_total} 张 {main_card}, {jokers_used_for_main_total} 张 Jokers。剩余牌: {len(deck_after_min_deal)}")
        # 3. 补齐剩余牌
        deck_remaining = deck_after_min_deal
        logger.debug("开始补齐剩余手牌...")
        for p_id in active_player_ids:
            current_hand_size = len(temp_hands[p_id]); fill_needed = HAND_SIZE - current_hand_size
            # --- ADDED LOGGING ---
            logger.debug(f"  为 {p_id} (当前 {current_hand_size} 张) 补齐 {fill_needed} 张。")
            logger.debug(f"    牌堆补牌前状态 (剩余 {len(deck_remaining)} 张): {deck_remaining[:10]}...") # 显示前10张牌
            # --- END LOGGING ---
            if fill_needed > 0:
                 if len(deck_remaining) < fill_needed: logger.warning(f"牌堆不足以为 {p_id} 补齐剩余 {fill_needed} 张牌 (只有 {len(deck_remaining)} 张)。"); fill_needed = len(deck_remaining)
                 cards_added_this_round = 0
                 for i in range(fill_needed):
                      if not deck_remaining: logger.warning(f"补牌给 {p_id} 时牌堆提前耗尽 (已补 {i} 张)。"); break
                      card_to_add = deck_remaining.pop(0); temp_hands[p_id].append(card_to_add); cards_added_this_round += 1
                      # logger.debug(f"      -> 添加 {card_to_add} (手牌增至 {len(temp_hands[p_id])})") # Optional verbose log
                 logger.debug(f"    实际为 {p_id} 补发 {cards_added_this_round} 张。")

            random.shuffle(temp_hands[p_id]); self.state.players[p_id].hand = temp_hands[p_id]
            # --- Changed Log Level ---
            logger.info(f"玩家 {self.state.players[p_id].name} ({p_id}) 的最终手牌数量: {len(self.state.players[p_id].hand)}")

        self.state.deck = []; logger.info("发牌流程完成。")
    # --- End of MODIFIED _deal_cards_new_rule ---

    def _get_active_player_ids(self) -> List[str]: return [pid for pid, pdata in self.state.players.items() if not pdata.is_eliminated]
    def _get_ordered_active_player_ids(self) -> List[str]: active = self._get_active_player_ids(); return [pid for pid in self.state.turn_order if pid in active]
    def _advance_turn(self) -> Tuple[Optional[str], Optional[str]]:
        if not self.state.turn_order or self.state.status != GameStatus.PLAYING: logger.error("Cannot advance turn."); return None, None
        num_players = len(self.state.turn_order); current_idx = self.state.current_player_index
        for i in range(num_players):
            next_idx = (current_idx + 1 + i) % num_players
            next_player_id = self.state.turn_order[next_idx]; player_data = self.state.players.get(next_player_id)
            if player_data and not player_data.is_eliminated: self.state.current_player_index = next_idx; logger.info(f"Turn advanced to {player_data.name}({next_player_id})"); return next_player_id, player_data.name
        logger.error("Could not find next active player!"); return None, None

    # --- MODIFIED _determine_shot_outcome with logging ---
    def _determine_shot_outcome(self, player_id: str) -> ShotResult:
         player_data = self.state.players.get(player_id);
         if not player_data: return ShotResult.GUN_ERROR;
         if player_data.is_eliminated: return ShotResult.ALREADY_ELIMINATED;
         gun = player_data.gun; position = player_data.gun_position; gun_chambers = len(gun);
         if not gun or position is None or not (0 <= position < gun_chambers): logger.error(f"Invalid gun info for {player_data.name}"); return ShotResult.GUN_ERROR;

         # --- ADDED LOGGING ---
         logger.debug(f"开枪判定 for {player_data.name} ({player_id}):")
         logger.debug(f"  Gun State: {gun}")
         logger.debug(f"  Current Position: {position}")
         # --- END LOGGING ---

         bullet = gun[position]; # Check the bullet at the current position
         logger.info(f"  玩家 {player_data.name} 在位置 {position} 开枪，子弹是: '{bullet}'") # Use INFO level
         return ShotResult.HIT if bullet == "实弹" else ShotResult.SAFE
    # --- End of MODIFIED _determine_shot_outcome ---

    def _check_game_end_internal(self) -> bool: return len(self._get_active_player_ids()) <= 1
    def _get_winner_id(self) -> Optional[str]: active = self._get_active_player_ids(); return active[0] if len(active) == 1 else None
    def _check_and_handle_all_hands_empty_internal(self, trigger_reason: str) -> Dict[str, Any]:
         active_players = self._get_ordered_active_player_ids();
         if not active_players: logger.debug("No active players, skip empty check."); return {"reshuffled": False}
         all_empty = all(not self.state.players[pid].hand for pid in active_players);
         if all_empty: logger.info(f"All hands empty ({trigger_reason}). Triggering reshuffle."); return self._reshuffle_internal(f"所有活跃玩家手牌已空 ({trigger_reason})")
         else: return {"reshuffled": False}
    def _reshuffle_internal(self, reason: str, eliminated_player_id: Optional[str] = None) -> Dict[str, Any]:
         logger.info(f"开始内部洗牌。原因: {reason}"); self.state.round_start_reason = reason
         active_player_ids = self._get_ordered_active_player_ids(); player_count = len(active_player_ids)
         if not active_player_ids: logger.error("Reshuffle: No active players!"); self.state.status = GameStatus.ENDED; return {"reshuffled": True, "game_ended": True, "error": "洗牌时无活跃玩家。"}
         self.state.discard_pile = [];
         for p_id in active_player_ids:
             if p_id in self.state.players: self.state.players[p_id].hand = []
         logger.info("Cleared discard pile and active hands.")
         self.state.main_card = random.choice(CARD_TYPES_BASE); logger.info(f"Reshuffle new main card: {self.state.main_card}")
         self.state.deck = self._build_deck(player_count); logger.info(f"Rebuilt dynamic deck ({len(self.state.deck)} cards) for {player_count} active players.")
         try: self._deal_cards_new_rule()
         except (ValueError, IndexError) as e: logger.error(f"Reshuffle dealing failed: {e}", exc_info=True); self.state.status = GameStatus.ENDED; return { "reshuffled": True, "game_ended": True, "error": f"洗牌后重新发牌失败: {e}", "new_main_card": self.state.main_card, }
         start_player_id = self._determine_next_starter_after_reshuffle(eliminated_player_id)
         if not start_player_id: logger.error("Reshuffle cannot determine starter!"); self.state.status = GameStatus.ENDED; return { "reshuffled": True, "game_ended": True, "error": "无法确定起始玩家。", "new_main_card": self.state.main_card }
         try: self.state.current_player_index = self.state.turn_order.index(start_player_id)
         except ValueError: logger.error(f"Starter {start_player_id} not in turn order!"); self.state.status = GameStatus.ENDED; return { "reshuffled": True, "game_ended": True, "error": "无法设置回合索引。" }
         self.state.last_play = None; logger.info(f"Reshuffle complete. Next turn: {self.state.players[start_player_id].name}")
         return { "reshuffled": True, "game_ended": False, "reason": reason, "new_main_card": self.state.main_card, "new_hands": {pid: self.state.players[pid].hand for pid in active_player_ids}, "next_player_id": start_player_id, "next_player_name": self.state.players[start_player_id].name, "turn_order_names": [pdata.name + (" (淘汰)" if pdata.is_eliminated else "") for pid, pdata in sorted(self.state.players.items(), key=lambda item: self.state.turn_order.index(item[0]) if item[0] in self.state.turn_order else float('inf'))], }
    def _determine_next_starter_after_reshuffle(self, eliminated_player_id: Optional[str]) -> Optional[str]:
         active_ids_ordered = self._get_ordered_active_player_ids();
         if not active_ids_ordered: logger.warning("No active players for next starter."); return None
         start_checking_id = None
         if eliminated_player_id and eliminated_player_id in self.state.turn_order:
              try: elim_idx = self.state.turn_order.index(eliminated_player_id); start_checking_id = self.state.turn_order[(elim_idx + 1) % len(self.state.turn_order)]
              except ValueError: pass
         if not start_checking_id and 0 <= self.state.current_player_index < len(self.state.turn_order): start_checking_id = self.state.turn_order[(self.state.current_player_index + 1) % len(self.state.turn_order)]
         if not start_checking_id and self.state.turn_order: start_checking_id = self.state.turn_order[0]
         if not start_checking_id: return active_ids_ordered[0]
         try: start_idx = self.state.turn_order.index(start_checking_id)
         except ValueError: start_idx = 0
         for i in range(len(self.state.turn_order)):
              check_id = self.state.turn_order[(start_idx + i) % len(self.state.turn_order)];
              if check_id in active_ids_ordered: return check_id
         return active_ids_ordered[0]
