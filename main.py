# liar_tavern/main.py

# -*- coding: utf-8 -*-

import logging
import re
import json
import asyncio
import random
import collections
from typing import List, Dict, Optional, Any, Tuple

# --- AstrBot API Imports ---
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.event.filter import EventMessageType # 确认导入路径
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from astrbot.api.event import MessageChain # 确认导入路径

from astrbot.api import AstrBotConfig
from aiocqhttp.exceptions import ActionFailed

# --- Local Imports ---
from .exceptions import (
    GameError, NotPlayersTurnError, InvalidActionError, InvalidCardIndexError,
    NotEnoughPlayersError,
    AIDecisionError, AIParseError, AIInvalidDecisionError
)
from .game_logic import LiarDiceGame
from .models import (
    GameStatus, MIN_PLAYERS, GameState, MAX_PLAY_CARDS, HAND_SIZE,
    CARD_TYPES_BASE, JOKER, AI_MAX_RETRIES, PlayerData
)
from .message_utils import (
    format_hand, build_join_message, build_start_game_message,
    build_play_card_announcement, build_challenge_result_messages,
    build_wait_announcement, build_reshuffle_announcement,
    build_game_status_message, build_game_end_message,
    build_error_message
)

# --- Logger Setup ---
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# --- Plugin Registration ---
@register(
    "骗子酒馆", "YourName_AI", "一个结合了吹牛和左轮扑克的多人卡牌游戏 (含AI玩家和聊天互动)。",
    "1.3.6", # <-- 版本号再微调
    "your_repo_url"
)
class LiarDicePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.context = context
        self.config = config
        self.games: Dict[str, LiarDiceGame] = {}
        self.active_ai_tasks: Dict[str, asyncio.Task] = {}
        self.group_chat_history: Dict[str, collections.deque] = {}
        logger.info("骗子酒馆插件 (含AI) v1.3.6 已加载并初始化")
        logger.debug(f"加载的插件配置: {self.config}")

    # --- 监听群聊消息以记录历史 ---
    @filter.event_message_type(EventMessageType.GROUP_MESSAGE, priority=10)
    async def _record_group_chat(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        if not group_id or not user_id:
            return

        user_name = event.get_sender_name() or f"用户{user_id[:4]}"
        message_text = event.message_str.strip()

        game_instance = self.games.get(group_id) # 先获取实例
        if game_instance and game_instance.state.status == GameStatus.PLAYING and message_text:
            history_len = self.config.get("recent_chat_history_length", 10)
            if group_id not in self.group_chat_history or self.group_chat_history[group_id].maxlen != history_len:
                 old_history = list(self.group_chat_history.get(group_id, []))
                 self.group_chat_history[group_id] = collections.deque(old_history, maxlen=history_len)

            self.group_chat_history[group_id].append({"sender": user_name, "text": message_text})
            logger.debug(f"记录群聊 {group_id} 消息: {user_name}: {message_text}")

    # --- AstrBot Interaction Helpers ---
    def _get_group_id(self, event: AstrMessageEvent) -> Optional[str]:
        group_id = event.get_group_id()
        return str(group_id) if group_id else None
    def _get_user_id(self, event: AstrMessageEvent) -> Optional[str]:
        sender_id = event.get_sender_id()
        return str(sender_id) if sender_id else None
    async def _get_bot_instance(self, event: AstrMessageEvent) -> Optional[Any]:
        if hasattr(event, 'bot') and hasattr(event.bot, 'send_group_msg'):
             return event.bot
        logger.warning("无法从事件中可靠地获取 bot 实例。")
        return None
    async def _send_private_message_text(self, event: AstrMessageEvent, user_id: str, text: str) -> bool:
        bot = await self._get_bot_instance(event)
        if not bot or not hasattr(bot, 'send_private_msg'):
             logger.error(f"无法发送私信给 {user_id}: 无效 bot 实例。")
             return False
        try:
             await bot.send_private_msg(user_id=int(user_id), message=text)
             return True
        except ValueError:
             logger.error(f"无效用户 ID '{user_id}' 用于私信。")
             return False
        except ActionFailed as e:
             logger.error(f"发送私信给 {user_id} 失败 (ActionFailed): {e}")
             return False
        except Exception as e:
             logger.error(f"发送私信给 {user_id} 失败: {type(e).__name__}", exc_info=False)
             return False
    async def _send_hand_update(self, event: AstrMessageEvent, group_id: str, player_id: str, hand: List[str], main_card: Optional[str]) -> bool:
        game_instance = self.games.get(group_id)
        if not game_instance:
             return False
        player_data = game_instance.state.players.get(player_id)
        if not player_data:
             logger.warning(f"尝试发送手牌给不存在的玩家 {player_id}")
             return False
        if player_data.is_eliminated or player_data.is_ai:
             return True
        main_card_display = main_card or "未定"
        hand_display = format_hand(hand)
        if not hand:
             pm_text = f"游戏: 骗子酒馆 (群: {group_id})\n✋ 手牌: 无\n👑 主牌: 【{main_card_display}】\n👉 无手牌时只能 /质疑 或 /等待"
        else:
             pm_text = f"游戏: 骗子酒馆 (群: {group_id})\n✋ 手牌: {hand_display}\n👑 主牌: 【{main_card_display}】\n👉 (出牌请用括号内编号)"
        success = await self._send_private_message_text(event, player_id, pm_text)
        if not success:
             logger.warning(f"向玩家 {player_data.name}({player_id}) 发送手牌私信失败")
        return success

    # --- 消息转换与发送 (使用直接 API) ---
    def _components_to_onebot(self, components: List[Any], group_id: Optional[str]=None) -> List[Dict]:
        onebot_segments = []
        game_instance = self.games.get(group_id) if group_id else None
        for comp in components:
            segment = None
            if isinstance(comp, Comp.Plain):
                 segment = {"type": "text", "data": {"text": comp.text}}
            elif isinstance(comp, Comp.At):
                qq_str = str(comp.qq)
                if qq_str.isdigit():
                     segment = {"type": "at", "data": {"qq": qq_str}}
                else:
                    player_name="未知用户"
                    if game_instance:
                         pdata = game_instance.state.players.get(qq_str)
                         player_name=pdata.name if pdata else player_name
                    segment = {"type": "text", "data": {"text": f"@{player_name} "}}
            elif isinstance(comp, Comp.Image):
                 file_data = getattr(comp, 'file', None) or getattr(comp, 'url', None)
                 if file_data and isinstance(file_data, str):
                      if not re.match(r"^(https?|file|base64)://", file_data):
                           logger.warning(f"图片路径可能需处理: {file_data}")
                      segment = {"type": "image", "data": {"file": file_data}}
                 else:
                      logger.warning(f"图片组件缺少有效文件/URL: {comp}")
            # ... 其他组件转换 ...
            else:
                 logger.warning(f"未处理组件类型: {type(comp).__name__}")
            if segment:
                 onebot_segments.append(segment)
        return onebot_segments
    async def _broadcast_message(self, event: AstrMessageEvent, message_components: List[Any]):
        if not isinstance(event, AstrMessageEvent):
             logger.error(f"_broadcast_message 需要 AstrMessageEvent 对象")
             return
        if not message_components:
             return
        group_id = self._get_group_id(event)
        bot = await self._get_bot_instance(event)
        if not group_id or not bot:
             logger.error("广播消息缺少 group_id 或 bot 实例")
             return
        try:
             group_id_int = int(group_id)
        except ValueError:
             logger.error(f"无法将群 ID '{group_id}' 转为整数。")
             return
        try:
             onebot_message = self._components_to_onebot(message_components, group_id=group_id)
        except Exception as e:
             logger.error(f"组件转 OneBot 格式出错: {e}", exc_info=True)
             return
        if not onebot_message:
             logger.warning("转换后 OneBot 消息为空")
             return
        try:
             await bot.send_group_msg(group_id=group_id_int, message=onebot_message)
             logger.debug("直接发送 GroupMsg 成功。")
        except ActionFailed as e:
             logger.error(f"直接发送群消息失败 (ActionFailed): group_id={group_id_int}, retcode={e.retcode}, msg='{e.message}', wording='{e.wording}'")
        except Exception as e:
             logger.error(f"直接发送群消息未知错误: group_id={group_id_int}, error={e}", exc_info=True)

    # --- AI Task Done Callback ---
    def _ai_task_done_callback(self, task: asyncio.Task, group_id: str):
        self.active_ai_tasks.pop(group_id, None)
        try:
            task.result() # 检查异常
        except asyncio.CancelledError:
            logger.debug(f"AI task for group {group_id} was cancelled.")
        except Exception as e:
            logger.error(f"AI task for group {group_id} finished with error: {e}", exc_info=True)

    # --- AI Turn Logic ---
    def _format_chat_history(self, group_id: str) -> str:
        history_deque = self.group_chat_history.get(group_id)
        if not history_deque:
            return "（暂无相关聊天记录）"
        return "\n".join([f"{item['sender']}: {item['text']}" for item in history_deque])
    def _build_llm_prompt(self, game_state: GameState, ai_player_id: str, include_chat: bool, task_type: str = "action") -> str:
        ai_player=game_state.players[ai_player_id]; ai_hand=ai_player.hand; main_card=game_state.main_card or "未定"; turn_order=game_state.turn_order; last_play=game_state.last_play
        prompt = f"你是卡牌游戏“骗子酒馆” AI {ai_player.name}。\n目标：赢。\n\n规则:\n- 主牌【{main_card}】({JOKER}万能)。\n- 打1-{MAX_PLAY_CARDS}张牌，声称主牌/鬼牌。\n- 可【质疑】上家(假则他开枪，真则你开枪)。\n- 可【出牌】跟进。\n- 手牌空只能【质疑】或【等待】。\n- 中弹淘汰。\n\n状态:\n- 主牌:【{main_card}】\n- 你手牌:{format_hand(ai_hand)}\n- 玩家状态:\n"
        player_statuses=[f"  - {p.name}{'[AI]' if p.is_ai else ''}{' (淘汰)' if p.is_eliminated else ''}:{len(p.hand) if not p.is_eliminated else 0}张" for pid,p in game_state.players.items() if pid in turn_order]; prompt+="\n".join(player_statuses)+"\n"
        prompt+=f"- 当前轮到你。\n";
        if last_play: last_pdata=game_state.players.get(last_play.player_id); last_tag="[AI] " if last_pdata and last_pdata.is_ai else ""; prompt+=f"- 上家:{last_tag}{last_play.player_name} 声称打出 {last_play.claimed_quantity} 张主牌。\n"
        else: prompt+="- 上家: 无。\n"
        group_id = None;
        # !! 更健壮地获取 group_id !!
        for pid, pdata in game_state.players.items():
             # 假设群ID嵌入在AI ID中或所有玩家都在一个群
             # 这是一个临时的获取方式，需要根据实际情况调整
             if pid.startswith("ai_"): parts = pid.split('_'); group_id = parts[1] if len(parts) >= 2 and parts[1].isdigit() else None; break
             # 如果能从 game_state 或 context 获取 group_id 会更好

        if group_id and include_chat:
             chat_history_str=self._format_chat_history(group_id)
             prompt+=f"\n最近聊天:\n---\n{chat_history_str}\n---\n"
        if task_type == "trash_talk":
             style_prompt=self.config.get("trash_talk_style_prompt","简短、幽默、挑衅。")
             prompt+=f"\n任务:\n说句垃圾话。风格:'{style_prompt}'。\n结合游戏和聊天。**只输出一句垃圾话文本。**"
        elif task_type == "action":
             prompt+=f"\n可用行动分析:\n...\n任务:\n分析局势选最佳动作(play,challenge,wait)。\n格式:\n1.<thinking>思考</thinking>\n2.下一行**仅**输出JSON决策:\n   play:{{\"action\":\"play\",\"indices\":[编号]}}\n   challenge:{{\"action\":\"challenge\"}}\n   wait:{{\"action\":\"wait\"}}\n确保编号有效(1-{len(ai_hand)})。"
        else:
             prompt+="\n任务:未知。"
        return prompt
    def _parse_llm_response(self, response_text: str, game_state: GameState, ai_player_id: str) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        reasoning_text=None; decision_dict=None; error_message=None; logger.debug(f"解析 LLM: ```{response_text}```")
        think_match=re.search(r"<thinking>(.*?)</thinking>", response_text, re.DOTALL|re.IGNORECASE); response_after_think=response_text[think_match.end():].strip() if think_match else response_text.strip();
        if think_match: reasoning_text=think_match.group(1).strip();
        json_str=None; json_match=re.search(r'(\{.*\})', response_after_think, re.DOTALL); json_str=json_match.group(1) if json_match else response_after_think;
        if json_str:
            try: decision_dict=json.loads(json_str)
            except json.JSONDecodeError as e: error_message=f"JSON解析失败:{e}"; return reasoning_text, None, error_message
        else: error_message="未找到JSON"; return reasoning_text, None, error_message
        if not isinstance(decision_dict,dict) or "action" not in decision_dict: error_message="JSON格式错误"; return reasoning_text, None, error_message
        action=decision_dict.get("action"); ai_player=game_state.players[ai_player_id]; hand_size=len(ai_player.hand); last_play_exists=game_state.last_play is not None
        if action=="play":
            if not ai_player.hand: error_message="手牌空不能play"; return reasoning_text,None,error_message
            if "indices" not in decision_dict or not isinstance(decision_dict["indices"],list): error_message="'play'缺indices"; return reasoning_text,None,error_message
            indices=decision_dict["indices"]; count=len(indices)
            if not(1<=count<=MAX_PLAY_CARDS): error_message=f"play数量({count})无效"; return reasoning_text,None,error_message
            if count>hand_size: error_message="打超手牌数"; return reasoning_text,None,error_message
            invalid=[]; valid_0=set(); all_valid=True
            for idx in indices:
                try: i=int(idx)
                except(ValueError,TypeError): invalid.append(idx);all_valid=False;continue
                if not(1<=i<=hand_size): invalid.append(i);all_valid=False
                else: i0=i-1;
                if i0 in valid_0: error_message=f"编号{i}重复";all_valid=False;break;
                valid_0.add(i0)
            if not all_valid and not error_message: error_message=f"含无效编号{invalid}"; return reasoning_text,None,error_message
            if error_message: return reasoning_text,None,error_message
            decision_dict['indices']=[int(i) for i in indices]
        elif action=="challenge":
            if not last_play_exists: error_message="无法challenge"; return reasoning_text,None,error_message
        elif action=="wait":
            if ai_player.hand: error_message="手牌非空不能wait"; return reasoning_text,None,error_message
        else: error_message=f"未知action:{action}"; return reasoning_text,None,error_message
        return reasoning_text, decision_dict, None
    async def _get_ai_fallback_decision(self, game_state: GameState, ai_player_id: str) -> Dict[str, Any]:
        logger.warning(f"AI ({ai_player_id}) 启用备用逻辑。"); ai_player = game_state.players[ai_player_id]; hand_size = len(ai_player.hand); last_play_exists = game_state.last_play is not None
        if not ai_player.hand: return {"action": "wait"} if not last_play_exists else ({"action": "challenge"} if random.random() < 0.5 else {"action": "wait"})
        else:
            if last_play_exists: return {"action": "challenge"} if random.random() < 0.4 else {"action": "play", "indices": [random.randint(1, hand_size)]}
            else: return {"action": "play", "indices": [random.randint(1, hand_size)]}
    async def _handle_ai_turn(self, original_event: AstrMessageEvent, group_id: str, ai_player_id: str):
        logger.info(f"AI Task Started for player {ai_player_id} in group {group_id}")
        game_instance = self.games.get(group_id);
        if not game_instance: logger.warning(f"AI 回合: 游戏 {group_id} 不存在。Task exiting."); return
        ai_player_data = game_instance.state.players.get(ai_player_id)
        if not ai_player_data or ai_player_data.is_eliminated: logger.warning(f"AI 回合: 玩家 {ai_player_id} 无效或淘汰。Task exiting."); await self._trigger_next_turn_safe(original_event, group_id); return
        current_player_check = game_instance.get_current_player_id();
        if current_player_check != ai_player_id: logger.warning(f"AI 回合: 非 {ai_player_id} 回合 ({current_player_check})。Task exiting."); return

        logger.info(f"[群{group_id}] AI {ai_player_data.name} ({ai_player_id}) 回合开始处理。")
        provider = self.context.get_using_provider()

        # --- 1. 垃圾话 ---
        if self.config.get("enable_trash_talk", True) and provider:
            await self._broadcast_message(original_event, [Comp.Plain(f"轮到 🤖 {ai_player_data.name} 了，它正在想 P 话...")])
            await asyncio.sleep(random.uniform(0.5, 1.5))
            trash_talk_text = None
            try: trash_talk_prompt = self._build_llm_prompt(game_instance.state, ai_player_id, include_chat=True, task_type="trash_talk"); logger.debug(f"AI ({ai_player_id}) 请求垃圾话..."); response = await provider.text_chat(prompt=trash_talk_prompt, session_id=None, contexts=[], temperature=0.7); trash_talk_text = response.completion_text.strip(); trash_talk_text = re.sub(r'<[^>]+>', '', trash_talk_text).strip(); logger.info(f"AI ({ai_player_id}) 生成垃圾话: {trash_talk_text}")
            except Exception as e: logger.error(f"AI ({ai_player_id}) 生成垃圾话失败: {e}", exc_info=False)
            if trash_talk_text: trash_talk_message=[Comp.Plain(f"🤖 {ai_player_data.name}: {trash_talk_text}")]; await self._broadcast_message(original_event, trash_talk_message); await asyncio.sleep(random.uniform(1.0, 2.5))

        # --- 2. 游戏动作 ---
        await self._broadcast_message(original_event, [Comp.Plain(f"🤖 {ai_player_data.name} 开始操作...")])
        await asyncio.sleep(random.uniform(1.0, 2.0))
        final_decision_dict = None; reasoning_text = None; error_details = None; include_chat_in_action = self.config.get("include_chat_in_action_prompt", True)

        if provider:
            action_prompt = self._build_llm_prompt(game_instance.state, ai_player_id, include_chat=include_chat_in_action, task_type="action")
            for attempt in range(AI_MAX_RETRIES):
                 current_player_check_loop = game_instance.get_current_player_id();
                 if group_id not in self.games or game_instance.state.status != GameStatus.PLAYING or current_player_check_loop != ai_player_id: logger.warning(f"AI({ai_player_id}) LLM 循环中状态变更/非本人回合({current_player_check_loop})，退出。"); break
                 logger.info(f"AI ({ai_player_id}) 决策 LLM 调用 {attempt + 1}/{AI_MAX_RETRIES}...")
                 # !! 修正 Try...Except 块结构 !!
                 try:
                     llm_response = await provider.text_chat(prompt=action_prompt, session_id=None, contexts=[])
                     reasoning, decision, error_msg = self._parse_llm_response(llm_response.completion_text, game_instance.state, ai_player_id)
                     reasoning_text = reasoning or reasoning_text
                     error_details = error_msg
                     if decision:
                         final_decision_dict = decision
                         logger.info(f"AI ({ai_player_id}) 第 {attempt + 1} 次尝试成功获得有效决策。")
                         break # 成功，跳出
                     else:
                         logger.warning(f"AI ({ai_player_id}) 第 {attempt + 1} 次尝试失败: {error_msg}")
                         if attempt < AI_MAX_RETRIES - 1:
                             await asyncio.sleep(random.uniform(0.5, 1.0))
                 except Exception as llm_err:
                     # 将异常处理放在 except 块内
                     error_details = f"LLM 调用异常: {type(llm_err).__name__}"
                     logger.error(f"AI ({ai_player_id}) 第 {attempt + 1} 次调用 LLM 时发生异常: {llm_err}", exc_info=False)
                     if attempt < AI_MAX_RETRIES - 1:
                         await asyncio.sleep(random.uniform(0.5, 1.0))
            # 检查是否因状态变更退出循环
            if final_decision_dict is None and (group_id not in self.games or game_instance.state.status != GameStatus.PLAYING or game_instance.get_current_player_id() != ai_player_id): logger.warning(f"AI({ai_player_id}) LLM 循环结束后状态改变，取消回合处理。"); return
        else: error_details = "无 LLM Provider。"; logger.error(error_details)

        if final_decision_dict is None: final_decision_dict = await self._get_ai_fallback_decision(game_instance.state, ai_player_id); reasoning_text = reasoning_text or "(备用决策)"
        if reasoning_text: logger.info(f"AI ({ai_player_data.name}) Decision Reasoning: {reasoning_text.strip()}")
        logger.info(f"AI ({ai_player_data.name}) Chosen Action: {final_decision_dict} (Fallback reason: {error_details})")

        result = None
        try:
            if game_instance.get_current_player_id() != ai_player_id: logger.warning(f"AI({ai_player_id})执行前回合变更，取消。"); return
            action = final_decision_dict['action']
            if action == 'play': result = game_instance.process_play_card(ai_player_id, final_decision_dict['indices'])
            elif action == 'challenge': result = game_instance.process_challenge(ai_player_id)
            elif action == 'wait': result = game_instance.process_wait(ai_player_id)
            else: raise ValueError(f"AI无效动作:{action}")
        except GameError as e: logger.error(f"AI({ai_player_id})执行动作{final_decision_dict}游戏错误:{e}"); error_comps=[Comp.Plain(f"🤖 AI({ai_player_data.name})操作({final_decision_dict.get('action')})出错:{build_error_message(e, game_instance, ai_player_id)}")] ; await self._broadcast_message(original_event, error_comps); await self._trigger_next_turn_safe(original_event, group_id); return # 传递 event
        except Exception as unexpected_err: logger.error(f"AI({ai_player_id})执行意外错误:{unexpected_err}", exc_info=True); error_comps=[Comp.Plain(f"❌处理AI({ai_player_data.name})回合内部错误。")]; await self._broadcast_message(original_event, error_comps); await self._trigger_next_turn_safe(original_event, group_id); return # 传递 event

        if result and isinstance(result, dict):
            result['player_is_ai'] = True; pids_to_check = ['challenger_id', 'challenged_player_id', 'loser_id', 'next_player_id', 'trigger_player_id', 'eliminated_player_id']
            for key in pids_to_check: pid_res = result.get(key); result[key.replace('_id', '_is_ai')] = game_instance.state.players.get(pid_res, PlayerData("","",is_ai=False)).is_ai if pid_res else False
        await self._process_and_broadcast_result(original_event, group_id, result, ai_player_id) # 传递 event
        if group_id in self.games and not result.get("game_ended", False):
            next_pid = result.get("next_player_id"); next_pname = result.get("next_player_name")
            if next_pid and next_pname is not None: await asyncio.sleep(random.uniform(0.3,0.8)); await self._trigger_next_turn(original_event, group_id, next_pid, next_pname) # 传递 event
            else: logger.error(f"AI({ai_player_id})回合后结果缺下一玩家，尝试安全推进。"); await self._trigger_next_turn_safe(original_event, group_id) # 传递 event

    # --- Process Result & Trigger Next Turn Helpers ---
    async def _process_and_broadcast_result(self, event: AstrMessageEvent, group_id: str, result: Dict[str, Any], acting_player_id: Optional[str] = None): # ... (保持不变) ...
        game_instance = self.games.get(group_id);
        if not game_instance: return
        messages_to_send = []; pm_failures = []
        if not result or not result.get("success"): error_msg = result.get("error","未知错误"); messages_to_send.append([Comp.Plain(f"❗处理逻辑出错:{error_msg}")]); logger.warning(f"处理结果逻辑错误:{error_msg}"); [await self._broadcast_message(event, mc) for mc in messages_to_send]; return # 传递 event
        action = result.get("action"); current_main_card = result.get("new_main_card") or game_instance.state.main_card or "未知"
        hands_to_update = result.get("new_hands", {});
        if action == "play" and "hand_after_play" in result and acting_player_id: hands_to_update[acting_player_id] = result["hand_after_play"]
        if hands_to_update:
            logger.debug(f"准备发送手牌更新私信给: {list(hands_to_update.keys())}")
            for p_id, hand in hands_to_update.items():
                 player_data = game_instance.state.players.get(p_id)
                 if player_data and not player_data.is_eliminated and not player_data.is_ai:
                      if not await self._send_hand_update(event, group_id, p_id, hand, current_main_card): # 传递 event
                           pm_failures.append(player_data.name)
        primary_messages = []; acting_player_data = game_instance.state.players.get(acting_player_id) if acting_player_id else None
        if acting_player_data: result['player_is_ai'] = acting_player_data.is_ai
        if action == "play": primary_messages.append(build_play_card_announcement(result))
        elif action == "challenge": primary_messages.extend(build_challenge_result_messages(result))
        elif action == "wait": primary_messages.append(build_wait_announcement(result))
        if action == "challenge": messages_to_send.extend(primary_messages)
        elif primary_messages: messages_to_send.append(primary_messages[0])
        game_ended_flag = result.get("game_ended", False); reshuffled_flag = result.get("reshuffled", False)
        if reshuffled_flag and not game_ended_flag:
            elim_id = result.get("eliminated_player_id"); trigger_set = False
            if elim_id: elim_pd = game_instance.state.players.get(elim_id); result['trigger_action'] = "elimination"; result['trigger_player_id'] = elim_id; result['trigger_player_name'] = elim_pd.name if elim_pd else "??"; result['trigger_player_is_ai'] = elim_pd.is_ai if elim_pd else False; trigger_set = True
            if not trigger_set and acting_player_data: result['trigger_action'] = action; result['trigger_player_id'] = acting_player_id; result['trigger_player_name'] = acting_player_data.name; result['trigger_player_is_ai'] = acting_player_data.is_ai
            next_pid = result.get("next_player_id"); result['next_player_is_ai'] = game_instance.state.players.get(next_pid, PlayerData("","",is_ai=False)).is_ai if next_pid else False
            messages_to_send.append(build_reshuffle_announcement(result))
        if game_ended_flag:
            winner_id = result.get("winner_id"); winner_name = result.get("winner_name"); is_winner_ai = False
            if winner_id and winner_id in game_instance.state.players: is_winner_ai = game_instance.state.players[winner_id].is_ai
            end_comps = build_game_end_message(winner_id, winner_name); messages_to_send.append(end_comps); logger.info(f"游戏结束，胜者:{winner_name}")
            if group_id in self.games: del self.games[group_id]
            if group_id in self.active_ai_tasks: task = self.active_ai_tasks.pop(group_id); task.cancel()
        for msg_comps in messages_to_send: await self._broadcast_message(event, msg_comps); await asyncio.sleep(0.2) # 传递 event
        if pm_failures: await self._broadcast_message(event, [Comp.Plain(f"⚠️未能向{','.join(pm_failures)}发送手牌私信。")]) # 传递 event
    async def _trigger_next_turn(self, event: AstrMessageEvent, group_id: str, next_player_id: str, next_player_name: str): # ... (保持不变) ...
        logger.debug(f"调用 _trigger_next_turn: group={group_id}, next_player={next_player_name}({next_player_id})")
        if group_id not in self.games: logger.warning(f"_trigger_next_turn: 游戏 {group_id} 不存在。"); return
        game_instance = self.games[group_id]; next_player_data = game_instance.state.players.get(next_player_id)
        if not next_player_data or next_player_data.is_eliminated: logger.warning(f"_trigger_next_turn: 玩家 {next_player_id} 无效或已淘汰，尝试安全推进。"); await self._trigger_next_turn_safe(event, group_id); return # 传递 event
        if group_id in self.active_ai_tasks: logger.warning(f"触发新回合时，群 {group_id} 仍有活动的 AI 任务，尝试取消旧任务。"); old_task = self.active_ai_tasks.pop(group_id); old_task.cancel()
        if next_player_data.is_ai:
            logger.info(f"触发 AI {next_player_name} 回合任务。")
            ai_task = asyncio.create_task(self._handle_ai_turn(event, group_id, next_player_id)) # !! 传递 event !!
            self.active_ai_tasks[group_id] = ai_task
            ai_task.add_done_callback(lambda t: self._ai_task_done_callback(t, group_id))
        else: # 人类玩家
            logger.info(f"轮到人类 {next_player_name}。")
            next_hand_empty = not next_player_data.hand; msg_comps = [Comp.Plain("轮到你了, "), Comp.At(qq=next_player_id), Comp.Plain(f" ({next_player_name}) ")]
            can_challenge = game_instance.state.last_play is not None
            if next_hand_empty: msg_comps.append(Comp.Plain(".\n✋手牌空，请 "+("/质疑` 或 `"if can_challenge else "")+"/等待`。"))
            else: msg_comps.append(Comp.Plain(".\n请 "+("/质疑` 或 `"if can_challenge else "")+"/出牌 <编号...>`。"))
            await self._broadcast_message(event, msg_comps) # 传递 event
    async def _trigger_next_turn_safe(self, event: AstrMessageEvent, group_id: str): # ... (保持不变) ...
         logger.debug(f"安全推进回合...")
         if group_id not in self.games: return
         game_instance = self.games[group_id]; next_player_id, next_player_name = game_instance._advance_turn()
         if next_player_id and next_player_name is not None: await self._trigger_next_turn(event, group_id, next_player_id, next_player_name) # 传递 event
         else:
              if game_instance._check_game_end_internal():
                   if game_instance.state.status != GameStatus.ENDED: game_instance.state.status = GameStatus.ENDED
                   winner_id=game_instance._get_winner_id(); winner_name=game_instance.state.players[winner_id].name if winner_id else None; end_msg = build_game_end_message(winner_id, winner_name)
                   await self._broadcast_message(event, end_msg); # 传递 event
                   if group_id in self.games: del self.games[group_id]
                   if group_id in self.active_ai_tasks: task = self.active_ai_tasks.pop(group_id); task.cancel()
              else: logger.error(f"游戏状态异常！"); await self._broadcast_message(event, [Comp.Plain("❌游戏状态异常，请/结束游戏")]) # 传递 event

    # --- Command Handlers ---
    # ... (保持不变) ...
    @filter.command("骗子酒馆", alias={'pzjg', 'liardice'})
    async def create_game(self, event: AstrMessageEvent): # ... (代码同上) ...
        logger.info(f"接收到 create_game 命令，来源: {event.get_sender_id()}，群组: {event.get_group_id()}")
        group_id = self._get_group_id(event);
        if not group_id: user_id = self._get_user_id(event); await self._send_private_message_text(event, user_id, "请在群聊中使用此命令创建游戏。") if user_id else logger.warning("群外无法获取用户ID"); event.stop_event(); return
        if group_id in self.games:
            game_instance=self.games.get(group_id); current_status=game_instance.state.status if game_instance else GameStatus.ENDED
            if current_status!=GameStatus.ENDED: yield event.plain_result(f"⏳ 本群已有游戏 ({current_status.name})。\n➡️ /结束游戏 可强制结束。"); event.stop_event(); return
            else: del self.games[group_id]; self.active_ai_tasks.pop(group_id, None); logger.info(f"清理已结束游戏 {group_id}。")
        creator_id = self._get_user_id(event); self.games[group_id] = LiarDiceGame(creator_id=creator_id); logger.info(f"[群{group_id}] 由 {creator_id} 创建新游戏。")
        announcement = (f"🍻 骗子酒馆开张！(AI版 v1.3.6)\n➡️ /加入 参与 (需{MIN_PLAYERS}人)。\n➡️ /添加AI [数量] 加AI。\n➡️ 发起者({event.get_sender_name()}) /开始 启动。\n\n📜 玩法:\n1. 轮流用 `/出牌 编号 [...]` (1-{MAX_PLAY_CARDS}张) 声称主牌/鬼牌。\n2. 下家可 `/质疑` 或 `/出牌`。\n3. 质疑失败或声称不实者开枪！(中弹淘汰)\n4. 手牌空只能 `/质疑` 或 `/等待`。\n5. 活到最后！")
        yield event.plain_result(announcement)
        if not event.is_stopped(): event.stop_event(); return
    @filter.command("加入")
    async def join_game(self, event: AstrMessageEvent): # ... (代码同上) ...
        group_id = self._get_group_id(event); user_id = self._get_user_id(event); user_name = event.get_sender_name() or f"用户{user_id[:4]}"
        if not group_id or not user_id: yield event.plain_result("❌无法识别来源"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️无等待中游戏"); event.stop_event(); return
        game_instance = self.games[group_id]
        try: game_instance.add_player(user_id, user_name); player_count = len(game_instance.state.players); yield event.chain_result(build_join_message(user_id, user_name, player_count, is_ai=False))
        except GameError as e: yield event.plain_result(f"⚠️加入失败:{e}")
        except Exception as e: logger.error(f"加入错误:{e}", exc_info=True); yield event.plain_result("❌加入内部错误")
        if not event.is_stopped(): event.stop_event(); return
    @filter.command("添加AI", alias={'addai', '加AI'})
    async def add_ai_player(self, event: AstrMessageEvent, count: int = 1): # ... (代码同上) ...
        group_id = self._get_group_id(event)
        if not group_id: yield event.plain_result("❌群聊命令"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️无等待中游戏"); event.stop_event(); return
        game_instance = self.games[group_id]
        if game_instance.state.status != GameStatus.WAITING: yield event.plain_result("⚠️游戏非等待状态"); event.stop_event(); return
        requested_count = count # 保存原始请求数量
        if count <= 0: yield event.plain_result("⚠️数量需>0"); event.stop_event(); return
        added_count = 0; max_players = 8; current_players = len(game_instance.state.players)
        adjusted_count = count # 调整后的数量
        if current_players + count > max_players:
             adjusted_count = max_players - current_players
             if adjusted_count <= 0: yield event.plain_result(f"⚠️人数已达上限({max_players})"); event.stop_event(); return
             if adjusted_count != requested_count: yield event.plain_result(f"⚠️ 最多只能再加 {adjusted_count} 个 AI。")
        ai_names = [f"AI-{i}" for i in range(1,10)]; used_names = {p.name for p in game_instance.state.players.values()}; messages = []
        for i in range(adjusted_count): # 使用调整后的数量
            ai_id = f"ai_{group_id}_{random.randint(10000,99999)}_{i}"; ai_name = f"AI牌手{i+1}"; # 在ID中包含group_id可能有助于调试
            for name in ai_names:
                 if name not in used_names: ai_name=name; break
            try: game_instance.add_player(ai_id, ai_name); game_instance.state.players[ai_id].is_ai = True; used_names.add(ai_name); added_count += 1; player_count = len(game_instance.state.players); messages.append(build_join_message(ai_id, ai_name, player_count, is_ai=True))
            except GameError as e: yield event.plain_result(f"⚠️添加第{i+1}个AI失败:{e}"); break
            except Exception as e: logger.error(f"添加AI错误:{e}",exc_info=True); yield event.plain_result(f"❌添加第{i+1}个AI内部错误"); break
        if messages: combined = []; [combined.extend(m + [Comp.Plain("\n")]) for m in messages]; yield event.chain_result(combined[:-1]) # 合并消息
        if not event.is_stopped(): event.stop_event(); return
    @filter.command("开始", alias={'start'})
    async def start_game_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        group_id = self._get_group_id(event); user_id = self._get_user_id(event)
        if not group_id: yield event.plain_result("❌群聊命令"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️无游戏"); event.stop_event(); return
        game_instance = self.games[group_id]
        if game_instance.state.status != GameStatus.WAITING: yield event.plain_result(f"⚠️非等待状态"); event.stop_event(); return
        if len(game_instance.state.players) < MIN_PLAYERS: yield event.plain_result(f"❌至少需{MIN_PLAYERS}人"); event.stop_event(); return
        pm_failures = []
        try:
            start_result = game_instance.start_game()
            if not start_result or not start_result.get("success"): yield event.plain_result(f"❌启动失败:{start_result.get('error','未知')}"); event.stop_event(); return
            hands = start_result.get("initial_hands",{}); card = start_result.get("main_card"); first_pid = start_result.get("first_player_id"); first_is_ai = False
            if first_pid and first_pid in game_instance.state.players: first_is_ai = game_instance.state.players[first_pid].is_ai; start_result['first_player_is_ai'] = first_is_ai
            logger.info(f"游戏 {group_id} 开始。主牌:{card}")
            for pid, hand in hands.items():
                 player_data = game_instance.state.players.get(pid)
                 if player_data and not player_data.is_ai:
                      if not await self._send_hand_update(event, group_id, pid, hand, card):
                           pm_failures.append({'id': pid, 'name': player_data.name})
            start_comps = build_start_game_message(start_result); yield event.chain_result(start_comps)
            if pm_failures: failed_mentions = []; [failed_mentions.extend([Comp.At(qq=detail['id']), Comp.Plain(f"({detail['name']})"), Comp.Plain(", ")]) for detail in pm_failures]; yield event.chain_result([Comp.Plain("⚠️未能向 ")] + failed_mentions[:-1] + [Comp.Plain(" 发送私信。")])
            if first_is_ai and first_pid: logger.info(f"首位AI({start_result.get('first_player_name')})行动"); await asyncio.sleep(1.0); await self._trigger_next_turn(event, group_id, first_pid, start_result.get('first_player_name','AI')) # !! 传递 event !!
        except GameError as e: yield event.plain_result(f"⚠️启动失败:{e}")
        except Exception as e: logger.error(f"开始游戏错误:{e}",exc_info=True); yield event.plain_result("❌开始内部错误")
        if not event.is_stopped(): event.stop_event(); return
    async def _handle_human_action(self, event: AstrMessageEvent, action_type: str, params: Optional[Any] = None): # ... (代码同上) ...
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id or not player_id: yield event.plain_result("❌无法识别来源"); event.stop_event(); return
        game_instance = self.games.get(group_id)
        if not game_instance: yield event.plain_result("ℹ️无游戏"); event.stop_event(); return
        player_data = game_instance.state.players.get(player_id)
        if player_data and player_data.is_ai: yield event.plain_result("🤖AI请勿用命令"); event.stop_event(); return
        # !! event 对象将传递下去 !!
        result = None
        try:
            if action_type == "play": result = game_instance.process_play_card(player_id, params)
            elif action_type == "challenge": result = game_instance.process_challenge(player_id)
            elif action_type == "wait": result = game_instance.process_wait(player_id)
            else: raise ValueError(f"未知动作:{action_type}")
        except GameError as e: error_string = build_error_message(e, game_instance, player_id); yield event.plain_result(error_string); event.stop_event(); return
        except Exception as e: logger.error(f"处理玩家{player_id}动作'{action_type}'错误:{e}",exc_info=True); error_string=build_error_message(e); yield event.plain_result(error_string); event.stop_event(); return
        if result:
            await self._process_and_broadcast_result(event, group_id, result, player_id) # !! 传递 event !!
            if group_id not in self.games: event.stop_event(); return
            if not result.get("game_ended", False):
                 next_pid = result.get("next_player_id"); next_pname = result.get("next_player_name")
                 if next_pid and next_pname is not None: await asyncio.sleep(0.1); await self._trigger_next_turn(event, group_id, next_pid, next_pname) # !! 传递 event !!
                 else: await self._trigger_next_turn_safe(event, group_id) # !! 传递 event !!
        if not event.is_stopped(): event.stop_event()
    @filter.command("出牌", alias={'play', '打出'})
    async def play_cards_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        card_indices_1based = []; parse_error = None
        try:
            full_msg = event.message_str.strip(); match = re.match(r'^\S+\s+(.*)', full_msg)
            param_part = match.group(1).strip() if match else ""
            if not param_part:
                 command_name = getattr(event, 'command_name', ''); prefix = getattr(self.context.get_config(), 'command_prefix', '/'); full_command = prefix + command_name if command_name else ""
                 if full_msg == full_command or (command_name and full_msg.startswith(command_name)): parse_error = f"请提供1-{MAX_PLAY_CARDS}个编号。"
                 else: parse_error = "未找到有效数字编号。"
            else:
                indices_str = re.findall(r'\d+', param_part)
                if not indices_str: parse_error = "未找到有效数字编号。"
                else: card_indices_1based = [int(s) for s in indices_str]; assert card_indices_1based
        except (ValueError, AssertionError): parse_error = "编号必须是数字。"
        except Exception as e: parse_error = f"解析错误:{e}"
        if parse_error: yield event.plain_result(f"❌命令错误:{parse_error}"); event.stop_event(); return
        async for _ in self._handle_human_action(event, "play", card_indices_1based): yield _
    @filter.command("质疑", alias={'challenge', '抓'})
    async def challenge_play_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        async for _ in self._handle_human_action(event, "challenge"): yield _
    @filter.command("等待", alias={'wait', 'pass', '过'})
    async def wait_turn_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        async for _ in self._handle_human_action(event, "wait"): yield _
    @filter.command("状态", alias={'status', '游戏状态'})
    async def game_status_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        group_id = self._get_group_id(event); player_id = self._get_user_id(event)
        if not group_id: yield event.plain_result("群聊命令"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️无游戏"); event.stop_event(); return
        game_instance = self.games[group_id]
        try: yield event.chain_result(build_game_status_message(game_instance.state, player_id))
        except Exception as e: logger.error(f"获取状态错误:{e}"); yield event.plain_result("❌获取状态内部错误")
        if not event.is_stopped(): event.stop_event(); return
    @filter.command("我的手牌", alias={'hand', '手牌'})
    async def show_my_hand_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        group_id = self._get_group_id(event); user_id = self._get_user_id(event)
        if not group_id or not user_id: yield event.plain_result("❌无法识别来源"); event.stop_event(); return
        if group_id not in self.games: yield event.plain_result("ℹ️无游戏"); event.stop_event(); return
        game_instance = self.games[group_id]; player_data = game_instance.state.players.get(user_id)
        if not player_data: yield event.plain_result("ℹ️未参与"); event.stop_event(); return
        if player_data.is_ai: yield event.plain_result("🤖AI无需查牌"); event.stop_event(); return
        if player_data.is_eliminated: yield event.plain_result("☠️已淘汰"); event.stop_event(); return
        success = await self._send_hand_update(event, group_id, user_id, player_data.hand, game_instance.state.main_card)
        if success: yield event.plain_result("🤫已私信")
        else: yield event.chain_result([ Comp.At(qq=user_id), Comp.Plain(text="，私信失败，请检查好友或设置。") ])
        if not event.is_stopped(): event.stop_event(); return
    @filter.command("结束游戏", alias={'endgame', '强制结束'})
    async def force_end_game_cmd(self, event: AstrMessageEvent): # ... (代码同上) ...
        group_id = self._get_group_id(event); user_id = self._get_user_id(event); user_name = event.get_sender_name() or "未知用户"
        if not group_id: yield event.plain_result("群聊命令"); event.stop_event(); return
        if group_id in self.games:
            if group_id in self.active_ai_tasks: task = self.active_ai_tasks.pop(group_id); task.cancel()
            game_instance = self.games.pop(group_id); game_status = game_instance.state.status.name if game_instance else '未知'
            logger.info(f"[群{group_id}]游戏被{user_name}({user_id})强制结束(原状态:{game_status})")
            yield event.plain_result("🛑游戏已被强制结束。")
        else: yield event.plain_result("ℹ️无游戏")
        if not event.is_stopped(): event.stop_event(); return

    # --- Plugin Lifecycle ---
    async def terminate(self): # ... (保持不变) ...
        logger.info("骗子酒馆插件卸载/停用，清理...")
        active_tasks = list(self.active_ai_tasks.values())
        if active_tasks: logger.info(f"取消{len(active_tasks)}个AI任务..."); [t.cancel() for t in active_tasks if not t.done()]; self.active_ai_tasks.clear(); logger.info("AI任务已取消。")
        if self.games: logger.info(f"清理{len(self.games)}个游戏实例..."); self.games.clear(); logger.info("游戏实例数据已清理。")
        logger.info("清理完成。")

# --- End of LiarDicePlugin Class ---