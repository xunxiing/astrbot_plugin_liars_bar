# 请将这段代码完整粘贴到 main.py 文件中 (已修复 Pylance 报错的两行)

# -*- coding: utf-8 -*-

import logging
import re
from typing import List, Dict, Optional, Any

# --- AstrBot API Imports ---
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp

# --- Local Imports ---
from .exceptions import GameError, NotPlayersTurnError, InvalidActionError
from .game_logic import LiarDiceGame
from .models import GameStatus, MIN_PLAYERS, GameState, MAX_PLAY_CARDS
from .exceptions import GameError, NotEnoughPlayersError
from .message_utils import (
    format_hand, build_join_message, build_start_game_message,
    build_play_card_announcement, build_challenge_result_messages,
    build_wait_announcement, build_reshuffle_announcement,
    build_game_status_message, build_game_end_message,
    build_error_message
)

# --- Logger Setup ---
logger = logging.getLogger(__name__)

# --- Plugin Registration ---
@register(
    "骗子酒馆", "YourName", "一个结合了吹牛和左轮扑克的多人卡牌游戏 (重构版)。",
    "1.1.2", # <-- 版本号再微调
    "your_repo_url"
)
class LiarDicePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.context = context
        self.games: Dict[str, LiarDiceGame] = {}
        logger.info("骗子酒馆插件 (重构版) 已加载并初始化")

    # --- AstrBot Interaction Helpers ---
    def _get_group_id(self, event: AstrMessageEvent) -> Optional[str]:
        group_id = event.get_group_id(); return str(group_id) if group_id else None
    def _get_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        sender_id = event.get_sender_id(); return str(sender_id) if sender_id else None
    async def _get_bot_instance(self, event: AstrMessageEvent) -> Optional[Any]:
        if hasattr(event, 'bot') and (hasattr(event.bot, 'send_private_msg') or hasattr(event.bot, 'send_group_msg')): return event.bot
        logger.warning("Could not reliably get bot instance from event."); return None
    async def _send_private_message_text(self, event: AstrMessageEvent, user_id: str, text: str) -> bool:
        bot = await self._get_bot_instance(event)
        if not bot or not hasattr(bot, 'send_private_msg'): logger.error(f"Cannot send PM to {user_id}: No valid bot instance."); return False
        try: await bot.send_private_msg(user_id=int(user_id), message=text); logger.debug(f"Direct PM to {user_id} sent."); return True
        except ValueError: logger.error(f"Invalid user_id '{user_id}' for PM."); return False
        except Exception as e: logger.error(f"Direct PM to {user_id} failed: {e}", exc_info=False); return False
    async def _send_hand_update(self, event: AstrMessageEvent, group_id: str, player_id: str, hand: List[str], main_card: Optional[str]) -> bool:
        if main_card is None: main_card = "未定"
        if not hand: pm_text = f"游戏骗子酒馆 (群: {group_id})\n✋ 手牌: 无\n👑 主牌: 【{main_card}】\n👉 你已无手牌，轮到你时只能 /质疑 或 /等待"
        else: hand_display = format_hand(hand); pm_text = f"游戏骗子酒馆 (群: {group_id})\n✋ 手牌: {hand_display}\n👑 主牌: 【{main_card}】\n👉 (出牌请用括号内编号)"
        success = await self._send_private_message_text(event, player_id, pm_text)
        if not success: logger.warning(f"向玩家 {player_id} 发送手牌更新私信失败 (群 {group_id})")
        return success
    async def _handle_game_result(self, event: AstrMessageEvent, group_id: str, result: Dict[str, Any]) -> List[List[Any]]:
        messages_to_yield = []; pm_failures = []
        if not result or not result.get("success"): error_msg = result.get("error", "未知游戏逻辑错误") if result else "未知游戏逻辑错误"; logger.warning(f"[群{group_id}] Game logic error: {error_msg}"); messages_to_yield.append([Comp.Plain(f"❗ 操作失败: {error_msg}")]); return messages_to_yield
        action = result.get("action"); current_main_card = result.get("new_main_card") or (self.games.get(group_id, None) and self.games[group_id].state.main_card) or "未知"
        hands_to_update = result.get("new_hands", {})
        if action == "play" and not hands_to_update and "hand_after_play" in result: hands_to_update[result["player_id"]] = result["hand_after_play"]
        if group_id in self.games:
            for p_id, hand in hands_to_update.items():
                if not await self._send_hand_update(event, group_id, p_id, hand, current_main_card):
                    player_data_for_name = self.games[group_id].state.players.get(p_id); failed_player_name = player_data_for_name.name if player_data_for_name else p_id; pm_failures.append(failed_player_name)
        else: logger.warning(f"[群{group_id}] Game ended before PMs could be sent.")
        primary_messages = []
        if action == "play": primary_messages.append(build_play_card_announcement(result))
        elif action == "challenge": primary_messages.extend(build_challenge_result_messages(result))
        elif action == "wait": primary_messages.append(build_wait_announcement(result))
        messages_to_yield.extend(primary_messages)
        game_ended_flag = result.get("game_ended", False); reshuffled_flag = result.get("reshuffled", False)
        if reshuffled_flag and not game_ended_flag: messages_to_yield.append(build_reshuffle_announcement(result))
        if game_ended_flag: winner_id = result.get("winner_id"); winner_name = result.get("winner_name"); messages_to_yield.append(build_game_end_message(winner_id, winner_name)); del self.games[group_id]; logger.info(f"[群{group_id}] Game ended.")
        if pm_failures: messages_to_yield.append([Comp.Plain(f"⚠️ 注意：未能成功向 {', '.join(pm_failures)} 发送手牌私信。")])
        return messages_to_yield

    # --- Command Handlers ---

    @filter.command("骗子酒馆", alias={'pzjg', 'liardice'})
    async def create_game(self, event: AstrMessageEvent):
        '''创建一局新的骗子酒馆游戏'''
        group_id = self._get_group_id(event)
        if not group_id:
            user_id = self._get_user_id(event)
            if user_id: await self._send_private_message_text(event, user_id, "请在群聊中使用此命令创建游戏。")
            else: logger.warning("Command used outside group, no user ID.")
            if not event.is_stopped(): event.stop_event()
            return
        if group_id in self.games:
            game_instance = self.games.get(group_id); current_status = game_instance.state.status if game_instance else GameStatus.ENDED
            if current_status != GameStatus.ENDED: status_name = current_status.name; yield event.plain_result(f"⏳ 本群已有一局游戏 ({status_name})。\n➡️ /结束游戏 可强制结束。"); event.stop_event(); return
            else: del self.games[group_id]; logger.info(f"[群{group_id}] Removed ended game before creating new.")
        creator_id = self._get_user_id(event); self.games[group_id] = LiarDiceGame(creator_id=creator_id); logger.info(f"[群{group_id}] New game created by {creator_id}.")
        announcement = (f"🍻 骗子酒馆开张了！(左轮扑克版 v1.1)\n➡️ 输入 /加入 参与 (至少需 {MIN_PLAYERS} 人)。\n➡️ 发起者 ({event.get_sender_name()}) 输入 /开始 启动游戏。\n\n📜 玩法:\n1. 轮流用 `/出牌 编号 [编号...]` (1-{MAX_PLAY_CARDS}张) 声称打出【主牌】。\n2. 下家可 `/质疑` 或继续 `/出牌`。\n3. 质疑失败或声称不实，都要开枪！\n4. 手牌为空时，只能 `/质疑` 或 `/等待`。\n5. 活到最后即胜！(淘汰或全员空手牌时会重洗)"); yield event.plain_result(announcement); event.stop_event(); return

    @filter.command("加入")
    async def join_game(self, event: AstrMessageEvent):
        '''加入等待中的骗子酒馆游戏'''
        group_id = self._get_group_id(event); user_id = self._get_user_id(event); user_name = event.get_sender_name()
        if not group_id or not user_id: yield event.plain_result("❌ 无法识别命令来源。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有游戏。输入 /骗子酒馆 创建。"); event.stop_event(); return
        game_instance = self.games[group_id]
        try: game_instance.add_player(user_id, user_name); player_count = len(game_instance.state.players); yield event.chain_result(build_join_message(user_id, user_name, player_count))
        except GameError as e: yield event.plain_result(f"⚠️ 加入失败: {e}")
        except Exception as e: logger.error(f"[群{group_id}] Join error: {e}", exc_info=True); yield event.plain_result("❌ 处理加入命令时发生内部错误。")
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("开始")
    async def start_game(self, event: AstrMessageEvent):
        '''开始一局骗子酒馆游戏 (需要足够玩家)'''
        group_id = self._get_group_id(event); user_id = self._get_user_id(event)
        if not group_id: yield event.plain_result("❌ 请在群聊中开始游戏。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        # if game_instance.state.creator_id and user_id != game_instance.state.creator_id: yield event.plain_result("❌ 只有游戏发起者才能开始。"); event.stop_event(); return
        if len(game_instance.state.players) < MIN_PLAYERS: yield event.plain_result(f"❌ 至少需要 {MIN_PLAYERS} 人开始，当前 {len(game_instance.state.players)} 人。"); event.stop_event(); return
        pm_failures_details = []
        try:
            start_result = game_instance.start_game()
            if not start_result or not start_result.get("success"): error_msg = start_result.get("error", "未知错误"); yield event.plain_result(f"❌ 启动失败: {error_msg}"); event.stop_event(); return
            initial_hands = start_result.get("initial_hands", {}); main_card = start_result.get("main_card")
            for p_id, hand in initial_hands.items():
                if not await self._send_hand_update(event, group_id, p_id, hand, main_card):
                    player_data = game_instance.state.players.get(p_id); failed_name = player_data.name if player_data else p_id; pm_failures_details.append({'id': p_id, 'name': failed_name})
            yield event.chain_result(build_start_game_message(start_result, []))
            if pm_failures_details:
                failed_mentions = []
                # --- MODIFICATION START: Fixed semicolon and multiline logic ---
                for i, detail in enumerate(pm_failures_details):
                    failed_mentions.extend([Comp.At(qq=detail['id']), Comp.Plain(text=f"({detail['name']})")])
                    # 在名字后面加上逗号，除了最后一个
                    if i < len(pm_failures_details) - 1:
                        failed_mentions.append(Comp.Plain(text=", "))
                # --- MODIFICATION END ---
                yield event.chain_result([Comp.Plain("⚠️ 未能向 ")] + failed_mentions + [Comp.Plain(" 发送初始手牌私信。")])
        except GameError as e: yield event.plain_result(f"⚠️ 启动失败: {e}")
        except Exception as e: logger.error(f"[群{group_id}] Start game error: {e}", exc_info=True); yield event.plain_result("❌ 处理开始命令时发生内部错误。")
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("出牌", alias={'play', '打出'})
    async def play_cards(self, event: AstrMessageEvent):
        '''打出手牌 (1-3张)，声称是主牌。用法: /出牌 编号 [编号...]'''
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id or not player_id: yield event.plain_result("❌ 无法识别命令来源。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        card_indices_1based = []; parse_error = None
        try:
            full_message = event.message_str.strip(); match = re.match(r'^\S+\s+(.*)', full_message); param_part = match.group(1) if match else ""
            if not param_part: parse_error = f"请提供编号 (1-{MAX_PLAY_CARDS}个)。用法: /出牌 编号 [...]" if re.match(r'^\S+$', full_message) else "未提供有效编号。"
            # --- MODIFICATION START: Fixed semicolon and multiline logic ---
            else:
                indices_str = re.findall(r'\d+', param_part)
                card_indices_1based = [int(s) for s in indices_str] if indices_str else []
                # 检查解析后是否真的得到了编号
                if not card_indices_1based:
                    parse_error = "未在指令后找到有效的数字编号。"
            # --- MODIFICATION END ---
        except Exception as parse_ex: logger.error(f"[群{group_id}] Parse play param error: {parse_ex}"); parse_error = "解析参数出错。"
        if parse_error: yield event.plain_result(f"❌ 命令错误: {parse_error}"); event.stop_event(); return

        yielded_something = False
        handler_name = "play_cards"
        try:
            result = game_instance.process_play_card(player_id, card_indices_1based)
            message_lists_to_yield = await self._handle_game_result(event, group_id, result)
            if message_lists_to_yield:
                for msg_comps in message_lists_to_yield:
                    if msg_comps: yield event.chain_result(msg_comps); yielded_something = True
        except GameError as e:
            error_string = build_error_message(e, game_instance, player_id)
            yield event.plain_result(error_string); yielded_something = True
        except Exception as e:
            logger.error(f"[群{group_id}] Process play error: {e}", exc_info=True); error_string = build_error_message(e); yield event.plain_result(error_string); yielded_something = True
        finally:
            if not yielded_something: logger.debug(f"Handler '{handler_name}' completed without yielding."); yield event.make_result()
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("质疑", alias={'challenge', '抓'})
    async def challenge_play(self, event: AstrMessageEvent):
        '''质疑上一个玩家打出的牌是否符合声称'''
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id or not player_id: yield event.plain_result("❌ 无法识别命令来源。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        yielded_something = False
        handler_name = "challenge_play"
        try:
            result = game_instance.process_challenge(player_id)
            message_lists_to_yield = await self._handle_game_result(event, group_id, result)
            if message_lists_to_yield:
                for msg_comps in message_lists_to_yield:
                    if msg_comps: yield event.chain_result(msg_comps); yielded_something = True
        except GameError as e:
            error_string = build_error_message(e, game_instance, player_id)
            yield event.plain_result(error_string); yielded_something = True
        except Exception as e:
            logger.error(f"[群{group_id}] Process challenge error: {e}", exc_info=True); error_string = build_error_message(e); yield event.plain_result(error_string); yielded_something = True
        finally:
             if not yielded_something: logger.debug(f"Handler '{handler_name}' completed without yielding."); yield event.make_result()
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("等待", alias={'wait', 'pass', '过'})
    async def wait_turn(self, event: AstrMessageEvent):
        '''手牌为空时选择等待，跳过自己的回合'''
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id or not player_id: yield event.plain_result("❌ 无法识别命令来源。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        yielded_something = False
        handler_name = "wait_turn"
        try:
            result = game_instance.process_wait(player_id)
            message_lists_to_yield = await self._handle_game_result(event, group_id, result)
            if message_lists_to_yield:
                for msg_comps in message_lists_to_yield:
                    if msg_comps: yield event.chain_result(msg_comps); yielded_something = True
        except GameError as e:
            error_string = build_error_message(e, game_instance, player_id)
            yield event.plain_result(error_string); yielded_something = True
        except Exception as e:
            logger.error(f"[群{group_id}] Process wait error: {e}", exc_info=True); error_string = build_error_message(e); yield event.plain_result(error_string); yielded_something = True
        finally:
             if not yielded_something: logger.debug(f"Handler '{handler_name}' completed without yielding."); yield event.make_result()
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("状态", alias={'status', '游戏状态'})
    async def game_status(self, event: AstrMessageEvent):
        '''查看当前游戏状态和玩家信息'''
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id: yield event.plain_result("请在群聊中使用此命令。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有进行中的游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        try: yield event.chain_result(build_game_status_message(game_instance.state, player_id))
        except Exception as e: logger.error(f"[群{group_id}] Get status error: {e}", exc_info=True); yield event.plain_result("❌ 获取状态时发生内部错误。")
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("我的手牌", alias={'hand', '手牌'})
    async def show_my_hand(self, event: AstrMessageEvent):
        '''私信查看你当前的手牌'''
        group_id = self._get_group_id(event); user_id = self._get_user_id(event)
        if not group_id or not user_id: yield event.plain_result("❌ 无法识别命令来源。"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️ 本群当前没有进行中的游戏。"); event.stop_event(); return
        game_instance = self.games[group_id]
        player_data = game_instance.state.players.get(user_id)
        if not player_data: yield event.plain_result("ℹ️ 你似乎未参与本局游戏。"); event.stop_event(); return
        if player_data.is_eliminated: yield event.plain_result("☠️ 你已被淘汰，没有手牌了。"); event.stop_event(); return
        my_hand = player_data.hand; main_card = game_instance.state.main_card
        success = await self._send_hand_update(event, group_id, user_id, my_hand, main_card)
        if success: yield event.plain_result("🤫 已私信发送你的最新手牌，请查收。")
        else: my_hand_display = format_hand(my_hand); yield event.chain_result([ Comp.At(qq=user_id), Comp.Plain(text=f"，私信发送失败！\n你的手牌: {my_hand_display}\n👑 主牌: 【{main_card or '未定'}】") ])
        if not event.is_stopped(): event.stop_event(); return

    @filter.command("结束游戏", alias={'endgame', '强制结束'})
    async def force_end_game(self, event: AstrMessageEvent):
        '''强制结束当前群聊的游戏'''
        group_id = self._get_group_id(event); user_id = self._get_user_id(event); user_name = event.get_sender_name()
        if not group_id: yield event.plain_result("请在群聊中使用此命令。"); event.stop_event(); return
        if group_id in self.games:
            game_instance = self.games.pop(group_id); game_status = game_instance.state.status.name if game_instance else '未知'
            logger.info(f"[群{group_id}] Game force ended by {user_name}({user_id}) (was {game_status})")
            yield event.plain_result("🛑 当前群聊的骗子酒馆游戏已被强制结束。")
        else: yield event.plain_result("ℹ️ 本群当前没有进行中的游戏。")
        if not event.is_stopped(): event.stop_event(); return

    # --- Plugin Lifecycle ---
    async def terminate(self):
        logger.info("骗子酒馆插件 (重构版) 卸载/停用，清理所有游戏数据...")
        self.games.clear(); logger.info("所有游戏数据已清理")
