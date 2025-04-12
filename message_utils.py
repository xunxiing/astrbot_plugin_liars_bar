# liar_tavern/message_utils.py

# -*- coding: utf-8 -*-

import logging
from typing import List, Dict, Any, Optional

# Import framework components and models
import astrbot.api.message_components as Comp
from .exceptions import (
    GameError, NotPlayersTurnError, InvalidCardIndexError, PlayerNotInGameError,
    EmptyHandError, InvalidActionError, AIDecisionError
)
from .models import PlayerData, GameState, GameStatus, LastPlay, ChallengeResult, ShotResult, MIN_PLAYERS, JOKER

logger = logging.getLogger(__name__)

# --- Helper to create At or Plain based on ID ---
def _get_player_mention(player_id: str, player_name: str, is_ai: bool) -> List[Any]:
    """根据玩家 ID 和是否 AI 返回 Comp.At 或 Comp.Plain"""
    if not is_ai and player_id.isdigit():
        # 如果不是 AI 且 ID 是数字，尝试 @
        try:
            return [Comp.At(qq=int(player_id)), Comp.Plain(f"({player_name})")]
        except ValueError:
            # 如果 ID 是数字但转换失败（理论上不应发生），回退到 Plain
            logger.warning(f"玩家 ID '{player_id}' 是数字但无法转换为 int 用于 At。")
            return [Comp.Plain(f"{player_name}")]
    elif is_ai:
        # 如果是 AI，使用 Plain
        return [Comp.Plain(f"🤖 {player_name}")]
    else:
        # 其他情况（非 AI 但 ID 不是纯数字），使用 Plain
        return [Comp.Plain(f"{player_name}")]


# --- Formatting Helpers ---
def format_hand(hand: List[str], show_indices: bool = True) -> str:
    """格式化玩家手牌用于显示"""
    if not hand: return "无"
    if show_indices: return ' '.join([f"[{i+1}:{card}]" for i, card in enumerate(hand)])
    else: return ' '.join(hand)

def format_player_list(players: Dict[str, PlayerData], turn_order: List[str]) -> str:
    """格式化玩家列表，包含状态和 AI 标识"""
    if not turn_order: return "无玩家"
    display_list = []
    for pid in turn_order:
        pdata = players.get(pid)
        if pdata: status = " (淘汰)" if pdata.is_eliminated else ""; ai_tag = " [AI]" if pdata.is_ai else ""; display_list.append(f"{pdata.name}{ai_tag}{status}")
        else: display_list.append(f"[未知:{pid}]")
    return ", ".join(display_list)

# --- Result to Message Conversion ---

def build_join_message(player_id: str, player_name: str, player_count: int, is_ai: bool = False) -> List[Any]:
    """构建玩家加入/添加 AI 的消息"""
    action_text = "添加 AI" if is_ai else "加入"
    mention_comps = _get_player_mention(player_id, player_name, is_ai) # 获取提及组件
    prefix_comp = Comp.Plain(text="🤖 " if is_ai else "✅ ")
    suffix_comp = Comp.Plain(text=f" 已{action_text}！当前 {player_count} 人。")
    # 组合消息，注意 mention_comps 返回的是列表
    return [prefix_comp] + mention_comps[:-1] + [Comp.Plain(mention_comps[-1].text.replace('(','').replace(')',''))] + [suffix_comp] # 移除括号并组合

def build_start_game_message(result: Dict[str, Any]) -> List[Any]:
    """构建游戏开始的消息"""
    first_player_id = result['first_player_id']
    first_player_name = result['first_player_name']
    is_first_player_ai = result.get('first_player_is_ai', False)
    mention_comps = _get_player_mention(first_player_id, first_player_name, is_first_player_ai)

    components = [
        Comp.Plain(text=f"🎉 游戏开始！{len(result['turn_order_names'])} 人参与。\n"
                    f"👑 本轮主牌: 【{result['main_card']}】\n"
                    f"(初始手牌已尝试私信发送)\n"
                    f"📜 顺序: {', '.join(result['turn_order_names'])}\n\n"
                    f"👉 请第一位 ")
    ]
    components.extend(mention_comps) # 添加提及组件列表

    if is_first_player_ai:
        components.append(Comp.Plain(text=" 行动..."))
    else:
        components.append(Comp.Plain(text=" 出牌！\n(/出牌 编号 [编号...])"))
    return components

def build_play_card_announcement(result: Dict[str, Any]) -> List[Any]:
    """构建出牌动作的群公告"""
    player_name = result['player_name']; player_id = result['player_id']; is_ai = result.get('player_is_ai', False)
    quantity = result['quantity_played']; main_card = result['main_card']
    next_player_id = result.get('next_player_id'); next_player_name = result.get('next_player_name')
    next_hand_empty = result.get('next_player_hand_empty', False); next_is_ai = result.get('next_player_is_ai', False)
    played_hand_empty = result['played_hand_empty']

    player_mention_comps = _get_player_mention(player_id, player_name, is_ai)
    components = []
    action_prefix = "✨ " if played_hand_empty else "➡️ "
    components.append(Comp.Plain(action_prefix))
    components.extend(player_mention_comps) # 添加出牌者提及
    components.append(Comp.Plain(text=f" 打出 {quantity} 张，声称主牌【{main_card}】。\n"))

    if next_player_id and next_player_name is not None:
        next_mention_comps = _get_player_mention(next_player_id, next_player_name, next_is_ai)
        components.append(Comp.Plain(text="轮到 "))
        components.extend(next_mention_comps) # 添加下一位玩家提及
        if next_is_ai:
            components.append(Comp.Plain(text=" 行动..."))
        else:
            if next_hand_empty: components.append(Comp.Plain(text=" 反应 (手牌空，请 /质疑 或 /等待)"))
            else: components.append(Comp.Plain(text=" 反应。\n请 /质疑 或 /出牌 <编号...>"))
    return components

def build_challenge_result_messages(result: Dict[str, Any]) -> List[List[Any]]:
    """构建质疑结果的多条群公告"""
    messages = []
    challenger_id = result['challenger_id']; challenger_name = result['challenger_name']; challenger_is_ai = result.get('challenger_is_ai', False)
    challenged_id = result['challenged_player_id']; challenged_name = result['challenged_player_name']; challenged_is_ai = result.get('challenged_player_is_ai', False)
    loser_id = result['loser_id']; loser_name = result['loser_name']; loser_is_ai = result.get('loser_is_ai', False)
    quantity = result['claimed_quantity']; main_card = result['main_card']
    actual_cards_str = format_hand(result['actual_cards'], show_indices=False)
    challenge_outcome = result['challenge_result']; shot_outcome = result['shot_outcome']

    challenger_mention = _get_player_mention(challenger_id, challenger_name, challenger_is_ai)
    challenged_mention = _get_player_mention(challenged_id, challenged_name, challenged_is_ai)
    loser_mention = _get_player_mention(loser_id, loser_name, loser_is_ai)

    # 1. 宣布质疑和亮牌
    reveal_comps = [Comp.Plain("🤔 ")] + challenger_mention + [Comp.Plain(" 质疑 ")] + challenged_mention + [Comp.Plain(f" 的 {quantity} 张 👑{main_card}！\n亮牌: 【{actual_cards_str}】")]
    messages.append(reveal_comps)

    # 2. 宣布质疑结果和开枪者
    outcome_text = f"✅ 质疑失败！{challenged_mention[0].text if challenged_is_ai else challenged_name} 确实是主牌/{JOKER}。" if challenge_outcome == ChallengeResult.FAILURE else f"❌ 质疑成功！{challenged_mention[0].text if challenged_is_ai else challenged_name} 没有完全打出主牌/{JOKER}。"
    shot_trigger_comps = [Comp.Plain(f"{outcome_text}\n轮到 ")] + loser_mention + [Comp.Plain(" 开枪！")]
    messages.append(shot_trigger_comps)

    # 3. 宣布开枪结果
    shot_result_text = "";
    if shot_outcome == ShotResult.SAFE: shot_result_text = f"💥 {loser_mention[0].text if loser_is_ai else loser_name} 扣动扳机... 咔嚓！【空弹】！安全！"
    elif shot_outcome == ShotResult.HIT: shot_result_text = f"💥 {loser_mention[0].text if loser_is_ai else loser_name} 扣动扳机... 砰！【实弹】！{loser_name} 被淘汰！"
    elif shot_outcome == ShotResult.ALREADY_ELIMINATED: shot_result_text = f"ℹ️ {loser_mention[0].text if loser_is_ai else loser_name} 已被淘汰。"
    elif shot_outcome == ShotResult.GUN_ERROR: shot_result_text = f"❌ 内部错误：{loser_mention[0].text if loser_is_ai else loser_name} 枪支错误！"
    if shot_result_text: messages.append([Comp.Plain(shot_result_text)])

    # 4. 宣布下一轮
    if not result.get("game_ended") and not result.get("reshuffled"):
        next_player_id = result.get("next_player_id"); next_player_name = result.get("next_player_name")
        next_hand_empty = result.get("next_player_hand_empty"); next_is_ai = result.get('next_player_is_ai', False)
        if next_player_id and next_player_name is not None:
            next_mention = _get_player_mention(next_player_id, next_player_name, next_is_ai)
            next_turn_comps = [Comp.Plain(text="下一轮，轮到 ")] + next_mention
            if next_is_ai: next_turn_comps.append(Comp.Plain(" 行动..."))
            else:
                 if next_hand_empty: next_turn_comps.append(Comp.Plain("。\n(手牌空，请 /质疑 或 /等待)"))
                 else: next_turn_comps.append(Comp.Plain(" 出牌。\n请使用 `/出牌 <编号...>`"))
            messages.append(next_turn_comps)
        else: messages.append([Comp.Plain("错误：无法确定下一位玩家。")])
    return messages

def build_wait_announcement(result: Dict[str, Any]) -> List[Any]:
    """构建等待动作的群公告"""
    player_id = result['player_id']; player_name = result['player_name']; is_ai = result.get('player_is_ai', False)
    next_player_id = result.get('next_player_id'); next_player_name = result.get('next_player_name')
    next_hand_empty = result.get('next_player_hand_empty', False); next_is_ai = result.get('next_player_is_ai', False)

    player_mention = _get_player_mention(player_id, player_name, is_ai)
    components = [Comp.Plain("😑 ")] + player_mention + [Comp.Plain(" (空手牌) 选择等待。\n")]

    if next_player_id and next_player_name is not None:
        next_mention = _get_player_mention(next_player_id, next_player_name, next_is_ai)
        components.append(Comp.Plain(text="轮到 "))
        components.extend(next_mention)
        if next_is_ai: components.append(Comp.Plain(" 行动..."))
        else:
             if next_hand_empty: components.append(Comp.Plain("。\n(手牌空，请 /质疑 或 /等待)"))
             else: components.append(Comp.Plain(" 出牌。\n请使用 `/出牌 <编号...>`"))
    return components

def build_reshuffle_announcement(result: Dict[str, Any]) -> List[Any]:
    """构建洗牌后的群公告"""
    reason = result['reason']; new_main_card = result['new_main_card']
    turn_order_display = result.get('turn_order_names', ["未知顺序"]) # 列表
    next_player_id = result['next_player_id']; next_player_name = result['next_player_name']; next_is_ai = result.get('next_player_is_ai', False)

    components = []
    # 添加触发原因前缀
    trigger_action = result.get("trigger_action"); trigger_player_name = result.get("trigger_player_name"); trigger_player_is_ai = result.get("trigger_player_is_ai", False)
    trigger_mention_text = f"{'🤖 ' if trigger_player_is_ai else ''}{trigger_player_name}" if trigger_player_name else "某人"
    prefix_text = ""
    if trigger_action == "play" and trigger_player_name:
        prefix_text = f"✨ {trigger_mention_text} 打出最后 {result.get('played_quantity','?')} 张！\n" if result.get("played_hand_empty") else f"➡️ {trigger_mention_text} 打出 {result.get('played_quantity','?')} 张。\n"
    elif trigger_action == "wait" and trigger_player_name: prefix_text = f"😑 {trigger_mention_text} (空手牌) 等待。\n"
    elif trigger_action == "elimination" and trigger_player_name: prefix_text = f"☠️ {trigger_mention_text} 被淘汰！\n"
    if prefix_text: components.append(Comp.Plain(prefix_text))

    # 添加洗牌核心信息
    components.append(Comp.Plain(text=f"🔄 {reason}！重新洗牌发牌！\n"
                    f"👑 新主牌: 【{new_main_card}】\n"
                    f"📜 顺序: {', '.join(turn_order_display)}\n" # 已包含 AI 标记
                    f"(新手牌已尝试私信发送)\n👉 轮到 "))

    # 添加下一位玩家信息
    next_mention = _get_player_mention(next_player_id, next_player_name, next_is_ai)
    components.extend(next_mention)
    if next_is_ai: components.append(Comp.Plain(" 行动..."))
    else: components.append(Comp.Plain(" 出牌。"))

    return components


def build_game_status_message(game: GameState, requesting_player_id: Optional[str]) -> List[Any]:
    """构建游戏状态查询的回复消息"""
    status_text = f"🎲 骗子酒馆状态\n状态: {game.status.name}\n"
    if game.status == GameStatus.WAITING:
        player_list = [f"- {pdata.name}{' [AI]' if pdata.is_ai else ''}" for pdata in game.players.values()]
        status_text += f"玩家 ({len(player_list)}人):\n" + ('\n'.join(player_list) if player_list else "暂无")
        status_text += f"\n\n➡️ /加入 参与 (需 {MIN_PLAYERS} 人)\n➡️ /添加AI [数量]\n➡️ 发起者可 /开始"
        return [Comp.Plain(status_text)]

    main_card = game.main_card or "未定"; turn_order_display = format_player_list(game.players, game.turn_order)
    status_text += f"👑 主牌: 【{main_card}】\n📜 顺序: {turn_order_display}\n"
    status_components = [Comp.Plain(status_text)]

    current_player_id = game.turn_order[game.current_player_index] if 0 <= game.current_player_index < len(game.turn_order) else None
    current_player_data = game.players.get(current_player_id) if current_player_id else None
    if current_player_data:
        current_player_name = current_player_data.name; current_is_ai = current_player_data.is_ai
        current_mention = _get_player_mention(current_player_id, current_player_name, current_is_ai)
        status_components.append(Comp.Plain("当前轮到: "))
        status_components.extend(current_mention)
    else: status_components.append(Comp.Plain("当前轮到: 未知"))

    player_statuses = []
    for pid in game.turn_order:
        pdata = game.players.get(pid)
        if pdata: status_icon = "☠️" if pdata.is_eliminated else ("🤖" if pdata.is_ai else "😀"); hand_count = len(pdata.hand) if not pdata.is_eliminated else 0; hand_text = f"{hand_count}张" if not pdata.is_eliminated else "淘汰"; player_statuses.append(f"{status_icon} {pdata.name}: {hand_text}")
    status_components.append(Comp.Plain("\n--------------------\n玩家状态:\n" + "\n".join(player_statuses)))

    last_play_text = "无"
    if game.last_play:
        lp = game.last_play; lp_pdata = game.players.get(lp.player_id); lp_mention = _get_player_mention(lp.player_id, lp.player_name, lp_pdata.is_ai if lp_pdata else False)
        current_mention_text = current_player_data.name if current_player_data else "未知"
        last_play_text = f"{lp_mention[0].text if lp_pdata and lp_pdata.is_ai else lp.player_name} 声称打出 {lp.claimed_quantity} 张【{main_card}】 (等待 {current_mention_text} 反应)"
    status_components.append(Comp.Plain(f"\n--------------------\n等待处理: {last_play_text}\n弃牌堆: {len(game.discard_pile)}张 | 牌堆余: {len(game.deck)}张"))

    requesting_pdata = game.players.get(requesting_player_id) if requesting_player_id else None
    if requesting_pdata and not requesting_pdata.is_eliminated and not requesting_pdata.is_ai:
        my_hand_display = format_hand(requesting_pdata.hand)
        status_components.append(Comp.Plain(f"\n--------------------\n你的手牌: {my_hand_display}"))
    return status_components

def build_game_end_message(winner_id: Optional[str], winner_name: Optional[str])-> List[Any]:
    """构建游戏结束的消息"""
    announcement = f"🎉 游戏结束！"
    if winner_id and winner_name:
        # 无法在此处直接访问 game_instance 来判断 is_ai, 需要调用者提供信息或修改接口
        # 假设 winner_name 中已包含 AI 标记 (如果需要)
        # 或者依赖 _get_player_mention (但需要 winner_id 和 is_ai 标志)
        # 简化处理：直接显示名字
        # winner_mention = _get_player_mention(winner_id, winner_name, is_winner_ai) # is_winner_ai 需要传入
        announcement += f"最后的胜者是: {winner_name}！"
        # 检查 winner_id 是否是数字来决定是否 @
        if winner_id.isdigit():
             return [Comp.Plain(announcement + "\n恭喜 "), Comp.At(qq=int(winner_id)), Comp.Plain(" !")]
        else: # 如果是 AI 或其他非数字 ID
             return [Comp.Plain(announcement)]
    else:
        announcement += "没有玩家幸存..."
        return [Comp.Plain(announcement)]

def build_error_message(
    error: Exception,
    game_instance: Optional[Any] = None,
    player_id: Optional[str] = None
) -> str:
    """生成用户友好的错误消息字符串"""
    # ... (保持不变) ...
    error_prefix = "⚠️ 操作失败: "; error_details = ""
    player_name = None; is_ai = False
    if player_id and game_instance and player_id in game_instance.state.players:
        pdata = game_instance.state.players[player_id]; player_name = pdata.name; is_ai = pdata.is_ai
        if is_ai: error_prefix = "🤖 AI 操作失败: "
    if isinstance(error, NotPlayersTurnError):
        error_prefix = "⏳ "; current_player_name = error.current_player_name or (game_instance.get_current_player_name() if game_instance else "未知")
        error_details = f"还没轮到你！当前轮到 {current_player_name}。"
    elif isinstance(error, InvalidCardIndexError):
        hand_size = error.hand_size or (len(game_instance.state.players[player_id].hand) if game_instance and player_id and player_id in game_instance.state.players else None)
        invalid_str = ', '.join(map(str, error.invalid_indices)) if error.invalid_indices else "未知"; error_details = f"无效的出牌编号: {invalid_str}。"
        if hand_size is not None: error_details += f" (你只有编号 1 到 {hand_size} 的牌)"
    elif isinstance(error, EmptyHandError): error_details = "你的手牌是空的，无法执行此操作。"
    elif isinstance(error, InvalidActionError): error_details = str(error)
    elif isinstance(error, AIDecisionError): error_prefix = "🤖 AI 决策错误: "; error_details = str(error)
    elif isinstance(error, GameError): error_details = str(error)
    else: error_prefix = "❌ 内部错误: "; error_details = f"处理时遇到意外问题。请联系管理员。错误类型: {type(error).__name__}"; logger.error(f"Unexpected error: {error}", exc_info=True)
    return error_prefix + error_details