# 请将这段代码完整粘贴到 message_utils.py 文件中

# liar_tavern/message_utils.py

# -*- coding: utf-8 -*-

import logging
from typing import List, Dict, Any, Optional

# Import framework components and models
import astrbot.api.message_components as Comp
# --- MODIFICATION: Import GameError and specific exceptions directly for isinstance checks ---
from .exceptions import (
    GameError, NotPlayersTurnError, InvalidCardIndexError, PlayerNotInGameError,
    EmptyHandError, InvalidActionError # Add other relevant exceptions if needed
)
# --- MODIFICATION: Import LiarDiceGame type hint if needed, but maybe not necessary now ---
# from .game_logic import LiarDiceGame
from .models import PlayerData, GameState, GameStatus, LastPlay, ChallengeResult, ShotResult, MIN_PLAYERS # Import MIN_PLAYERS here

logger = logging.getLogger(__name__)

# --- Formatting Helpers ---

def format_hand(hand: List[str]) -> str:
    """Formats a player's hand for display."""
    if not hand:
        return "无"
    return ' '.join([f"[{i+1}:{card}]" for i, card in enumerate(hand)])

def format_player_list(players: Dict[str, PlayerData], turn_order: List[str]) -> str:
    """Formats the player list, possibly with status."""
    if not turn_order: return "无玩家"
    display_list = []
    for pid in turn_order:
        pdata = players.get(pid)
        if pdata:
            status = " (淘汰)" if pdata.is_eliminated else ""
            display_list.append(f"{pdata.name}{status}")
        else:
            display_list.append(f"[未知:{pid}]")
    return ", ".join(display_list)

# --- Result to Message Conversion (Keep existing build_* functions that return List[Any]) ---
# build_join_message, build_start_game_message, etc. remain unchanged

def build_join_message(player_id: str, player_name: str, player_count: int) -> List[Any]:
    return [ Comp.Plain(text="✅ "), Comp.At(qq=player_id), Comp.Plain(text=f" ({player_name}) 已加入！当前 {player_count} 人。") ]

def build_start_game_message(result: Dict[str, Any], failed_pms: List[str]) -> List[Any]:
    components = [
        Comp.Plain(text=f"🎉 游戏开始！{len(result['turn_order_names'])} 人参与。\n"
                    f"👑 本轮主牌: 【{result['main_card']}】\n"
                    f"(初始手牌已尝试私信发送)\n"
                    f"📜 顺序: {', '.join(result['turn_order_names'])}\n\n"
                    f"👉 请第一位 "),
        Comp.At(qq=result['first_player_id']),
        Comp.Plain(text=f" ({result['first_player_name']}) 出牌！\n"
                    f"(/出牌 编号 [编号...])")
    ]
    if failed_pms:
        failed_str = ', '.join(failed_pms)
        components.append(Comp.Plain(text=f"\n\n⚠️ 未能向以下玩家发送私信：{failed_str}"))
    return components

def build_play_card_announcement(result: Dict[str, Any]) -> List[Any]:
    player_name = result['player_name']
    quantity = result['quantity_played']
    main_card = result['main_card']
    next_player_id = result['next_player_id']
    next_player_name = result['next_player_name']
    next_hand_empty = result['next_player_hand_empty']
    played_hand_empty = result['played_hand_empty']
    components = []
    accepted_info = result.get("accepted_play_info")
    # if accepted_info: # Optional: Announce implicit accept
    #    components.append(Comp.Plain(text=f"({player_name} 未质疑，{accepted_info['player_name']} 的牌被接受)\n"))

    if played_hand_empty:
        components.append(Comp.Plain(text=f"✨ {player_name} 打出最后 {quantity} 张！声称主牌【{main_card}】。\n"))
    else:
        components.append(Comp.Plain(text=f"➡️ {player_name} 打出 {quantity} 张，声称主牌【{main_card}】。\n"))

    components.append(Comp.Plain(text="轮到 "))
    components.append(Comp.At(qq=next_player_id))
    components.append(Comp.Plain(text=f" ({next_player_name}) "))

    if next_hand_empty:
        components.append(Comp.Plain(text="反应 (手牌已空，只能 /质疑 或 /等待)"))
    else:
        components.append(Comp.Plain(text="反应。\n请 /质疑 或 /出牌 <编号...>"))
    return components

def build_challenge_result_messages(result: Dict[str, Any]) -> List[List[Any]]:
    messages = []
    challenger = result['challenger_name']
    challenged = result['challenged_player_name']
    quantity = result['claimed_quantity']
    main_card = result['main_card']
    actual_cards_str = ' '.join(result['actual_cards'])
    challenge_outcome = result['challenge_result'] # SUCCESS or FAILURE
    loser_name = result['loser_name']
    shot_outcome = result['shot_outcome'] # SAFE, HIT, etc.

    reveal_comps = [Comp.Plain(
        f"🤔 {challenger} 质疑 {challenged} 的 {quantity} 张 👑{main_card}！\n"
        f"亮牌: 【{actual_cards_str}】"
    )]
    messages.append(reveal_comps)

    outcome_text = ""
    if challenge_outcome == ChallengeResult.FAILURE: outcome_text = f"✅ 质疑失败！{challenged} 确实是主牌/鬼牌。"
    else: outcome_text = f"❌ 质疑成功！{challenged} 没有完全打出主牌/鬼牌。"

    shot_trigger_text = f"{outcome_text} 轮到 {loser_name} 开枪！"
    messages.append([Comp.Plain(shot_trigger_text)])

    shot_result_text = ""
    if shot_outcome == ShotResult.SAFE: shot_result_text = f"💥 {loser_name} 扣动扳机... 咔嚓！是【空弹】！安全！"
    elif shot_outcome == ShotResult.HIT: shot_result_text = f"💥 {loser_name} 扣动扳机... 砰！是【实弹】！{loser_name} 被淘汰了！"
    elif shot_outcome == ShotResult.ALREADY_ELIMINATED: shot_result_text = f"ℹ️ {loser_name} 已被淘汰，无需开枪。"
    elif shot_outcome == ShotResult.GUN_ERROR: shot_result_text = f"❌ 内部错误：{loser_name} 枪支信息丢失！"
    if shot_result_text: messages.append([Comp.Plain(shot_result_text)])

    if not result.get("game_ended") and not result.get("reshuffled"):
        next_player_id = result.get("next_player_id")
        next_player_name = result.get("next_player_name")
        next_hand_empty = result.get("next_player_hand_empty")
        if next_player_id and next_player_name is not None:
            next_turn_comps = [Comp.Plain(text="下一轮，轮到 "), Comp.At(qq=next_player_id)]
            if next_hand_empty: next_turn_comps.append(Comp.Plain(text=f" ({next_player_name})。\n(手牌已空，只能 /等待)"))
            else: next_turn_comps.append(Comp.Plain(text=f" ({next_player_name}) 出牌。\n请使用 `/出牌 <编号...>`"))
            messages.append(next_turn_comps)
        else:
            logger.error("Challenge result missing next player info when expected.")
            messages.append([Comp.Plain("错误：无法确定下一位玩家。")])
    return messages

def build_wait_announcement(result: Dict[str, Any]) -> List[Any]:
    player_name = result['player_name']
    next_player_id = result['next_player_id']
    next_player_name = result['next_player_name']
    next_hand_empty = result['next_player_hand_empty']
    components = []
    accepted_info = result.get("accepted_play_info")
    # if accepted_info:
    #    components.append(Comp.Plain(text=f"({player_name} 等待，接受了 {accepted_info['player_name']} 的牌)\n"))

    components.append(Comp.Plain(text=f"😑 {player_name} (空手牌) 选择等待。\n轮到 "))
    components.append(Comp.At(qq=next_player_id))

    if next_hand_empty: components.append(Comp.Plain(text=f" ({next_player_name})。\n(手牌已空，只能 /等待)"))
    else: components.append(Comp.Plain(text=f" ({next_player_name}) 出牌。\n请使用 `/出牌 <编号...>`"))
    return components

def build_reshuffle_announcement(result: Dict[str, Any]) -> List[Any]:
    reason = result['reason']
    new_main_card = result['new_main_card']
    turn_order_display = result['turn_order_names'] # Expect pre-formatted list w/ status
    next_player_id = result['next_player_id']
    next_player_name = result['next_player_name']
    components = [
        Comp.Plain(text=f"🔄 {reason}！重新洗牌发牌！\n"
                    f"👑 新主牌: {new_main_card}\n"
                    f"📜 顺序: {', '.join(turn_order_display)}\n"
                    f"(新手牌已尝试私信发送)\n"
                    f"👉 轮到 "),
        Comp.At(qq=next_player_id),
        Comp.Plain(text=f" ({next_player_name}) 出牌。")
    ]
    # Prepend initiator action info if reshuffle was triggered by play/wait
    action_player_name = result.get("player_who_played_name") or result.get("player_who_waited_name")
    if result.get("action") == "play" and action_player_name:
        played_quantity = result.get("played_quantity", "?")
        if result.get("played_hand_empty"):
            components.insert(0, Comp.Plain(f"✨ {action_player_name} 打出了最后 {played_quantity} 张牌！\n"))
        else:
            components.insert(0, Comp.Plain(f"➡️ {action_player_name} 打出了 {played_quantity} 张牌。\n"))
    elif result.get("action") == "wait" and action_player_name:
         components.insert(0, Comp.Plain(f"😑 {action_player_name} (空手牌) 选择等待。\n"))

    return components


def build_game_status_message(game: GameState, requesting_player_id: Optional[str]) -> List[Any]:
    status_text = f"🎲 骗子酒馆状态\n状态: {game.status.name}\n" # WAITING, PLAYING, ENDED

    if game.status == GameStatus.WAITING:
        player_list = [f"- {pdata.name}" for pdata in game.players.values()]
        status_text += f"玩家 ({len(player_list)}人):\n" + ('\n'.join(player_list) if player_list else "暂无")
        status_text += f"\n\n➡️ /加入 参与 (需 {MIN_PLAYERS} 人)" # Use imported constant
        if game.creator_id and game.creator_id in game.players:
            creator_name = game.players[game.creator_id].name
            status_text += f"\n➡️ 发起者 ({creator_name}) 可用 /开始"
        return [Comp.Plain(status_text)]

    # Playing State
    main_card = game.main_card or "未定"
    turn_order_display = format_player_list(game.players, game.turn_order)
    status_text += f"👑 主牌: 【{main_card}】\n"
    status_text += f"📜 顺序: {turn_order_display}\n"

    current_player_id = game.turn_order[game.current_player_index] if 0 <= game.current_player_index < len(game.turn_order) else None
    current_player_name = game.players[current_player_id].name if current_player_id else "未知"
    current_player_at = Comp.At(qq=current_player_id) if current_player_id else None

    status_components = [Comp.Plain(text=status_text + "当前轮到: ")]
    if current_player_at:
        status_components.append(current_player_at)
        status_components.append(Comp.Plain(text=f" ({current_player_name})"))
    else:
        status_components.append(Comp.Plain(text=current_player_name))

    player_statuses = []
    for pid in game.turn_order:
        pdata = game.players.get(pid)
        if pdata:
            status_icon = "☠️" if pdata.is_eliminated else "😀"
            hand_count = len(pdata.hand) if not pdata.is_eliminated else 0
            hand_text = f"{hand_count}张" if not pdata.is_eliminated else "淘汰"
            player_statuses.append(f"{status_icon} {pdata.name}: {hand_text}")

    status_components.append(Comp.Plain(text="\n--------------------\n玩家状态:\n" + "\n".join(player_statuses)))

    last_play_text = "无"
    if game.last_play:
        lp = game.last_play
        last_play_text = f"{lp.player_name} 声称打出 {lp.claimed_quantity} 张【{main_card}】 (等待 {current_player_name} 反应)"

    status_components.append(Comp.Plain(text=f"\n--------------------\n等待处理: {last_play_text}\n"
                                        f"弃牌堆: {len(game.discard_pile)}张 | "
                                        f"牌堆余: {len(game.deck)}张")) # Note: Deck might be 0 after initial deal

    if requesting_player_id and requesting_player_id in game.players and not game.players[requesting_player_id].is_eliminated:
        my_hand_display = format_hand(game.players[requesting_player_id].hand)
        status_components.append(Comp.Plain(text=f"\n--------------------\n你的手牌: {my_hand_display}"))

    return status_components

def build_game_end_message(winner_id: Optional[str], winner_name: Optional[str])-> List[Any]:
    announcement = f"🎉 游戏结束！"
    if winner_id and winner_name: # Check both exist
        announcement += f"最后的胜者是: {winner_name}！"
        return [Comp.Plain(text=announcement + "\n恭喜 "), Comp.At(qq=winner_id), Comp.Plain(text=" !")]
    else:
        announcement += "没有玩家幸存..." # Or "平局！" if applicable
        return [Comp.Plain(text=announcement)]

# --- MODIFICATION START: build_error_message returns string ---
def build_error_message(
    error: Exception,
    game_instance: Optional[Any] = None, # Keep Any to avoid potential import cycle
    player_id: Optional[str] = None
) -> str: # Changed return type hint to str
    """Generates a user-friendly error message string based on the caught exception."""

    error_prefix = "⚠️ 操作失败: "
    error_details = ""

    if isinstance(error, NotPlayersTurnError):
        error_prefix = "⏳ "
        error_details = str(error)

    elif isinstance(error, InvalidCardIndexError):
        error_details = str(error)
        # Consider adding hand info back here if LiarDiceGame can be imported safely
        # Or pass hand info explicitly if needed

    elif isinstance(error, EmptyHandError):
        error_details = str(error)

    elif isinstance(error, InvalidActionError):
        error_details = str(error)
        # Consider adding hand info back here if needed

    elif isinstance(error, GameError): # Catch other specific GameErrors
        error_details = str(error)

    else: # Fallback for unexpected exceptions
        error_prefix = "❌ 内部错误: "
        error_details = f"处理时遇到意外问题。请联系管理员。错误类型: {type(error).__name__}"
        logger.error(f"Unexpected error caught in build_error_message: {error}", exc_info=True)

    return error_prefix + error_details # Return formatted string
# --- MODIFICATION END ---
