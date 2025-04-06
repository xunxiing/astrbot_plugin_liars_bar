# main.py - 左轮扑克 (骗子酒馆规则变体) - v2.1.9 文本优化 & Bug修复
import random
import re # 引入正则表达式库
from typing import Dict, List, Set, Any, Tuple
from collections import Counter

# --- 从 astrbot.api 导入所需组件 ---
from astrbot.api import logger  # <--- 直接导入 AstrBot 的 logger
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# --- 常量 ---
CARD_TYPES = ["Q", "K", "A"]
JOKER = "Joker"
VALID_CARDS = CARD_TYPES + [JOKER]
CARDS_PER_TYPE = 10 # <-- 增加目标牌数量 (原为 6)
# JOKER_COUNT 动态计算
HAND_SIZE = 5
GUN_CHAMBERS = 6
LIVE_BULLETS = 2 # <-- 调整实弹数量以降低空枪率 (原为 1) -> P(空)=2/6=66.7% P(实)=4/6=33.3%
MIN_PLAYERS = 2

# --- 插件注册 ---
@register("liar_tavern", "骗子酒馆助手", "左轮扑克 (骗子酒馆规则变体)", "2.2.0", "https://github.com/xunxiing/astrbot_plugin_liars_bar") # 更新版本号
class LiarsPokerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.games: Dict[str, Dict] = {}
        # 现在可以直接使用导入的 logger
        logger.info("LiarsPokerPlugin (左轮扑克) 初始化完成。")

    # --- 辅助函数 (使用导入的 logger) ---
    def _get_group_id(self, event: AstrMessageEvent) -> str | None:
        if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'group_id'):
            return str(event.message_obj.group_id)
        return None

    def _get_user_id(self, event: AstrMessageEvent) -> str | None:
        if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'sender') and hasattr(event.message_obj.sender, 'user_id'):
            return str(event.message_obj.sender.user_id)
        return None

    async def _get_bot_instance(self, event: AstrMessageEvent) -> Any:
        if hasattr(event, 'bot') and hasattr(event.bot, 'send_private_msg') and hasattr(event.bot, 'send_group_msg'):
             return event.bot
        logger.error("未能通过 event.bot 获取有效的 bot 实例")
        raise AttributeError("未能通过 event.bot 获取有效的 bot 实例")

    def _format_hand_for_display(self, hand: List[str]) -> str:
        if not hand: return "无"
        return ' '.join([f"[{i+1}:{card}]" for i, card in enumerate(hand)])

    def _convert_astr_comps_to_onebot(self, astr_message_list: List[Any]) -> List[Dict]:
        onebot_segments = []
        for comp in astr_message_list:
            if isinstance(comp, Comp.Plain):
                onebot_segments.append({"type": "text", "data": {"text": comp.text}})
            elif isinstance(comp, Comp.At):
                onebot_segments.append({"type": "at", "data": {"qq": str(comp.qq)}})
            else:
                logger.warning(f"未处理的 AstrBot 消息组件类型: {type(comp)}, 将尝试转为文本")
                try: text_repr = str(comp); onebot_segments.append({"type": "text", "data": {"text": text_repr}})
                except Exception: logger.error(f"无法将组件 {type(comp)} 转换为文本", exc_info=True)
        return onebot_segments

    async def _send_group_message_comp(self, event: AstrMessageEvent, group_id: str, astr_message_list: list):
        try:
            bot = await self._get_bot_instance(event)
            onebot_message = self._convert_astr_comps_to_onebot(astr_message_list)
            if not onebot_message: logger.warning(f"转换后的 OneBot 消息为空，取消向群 {group_id} 发送"); return
            logger.info(f"准备发送给 OneBot 的消息段 (群 {group_id}): {onebot_message}")
            await bot.send_group_msg(group_id=int(group_id), message=onebot_message)
            logger.info(f"尝试通过 bot.send_group_msg 向群 {group_id} 发送消息完成")
        except ValueError: logger.error(f"无法将 group_id '{group_id}' 转换为整数"); raise
        except AttributeError as e: logger.error(f"发送群消息失败: {e}"); raise
        except Exception as e: logger.error(f"通过 bot.send_group_msg 发送群聊给 {group_id} 失败: {e}", exc_info=True); raise

    async def _reply_text(self, event: AstrMessageEvent, text: str):
        """直接回复纯文本消息"""
        await self._reply_with_components(event, [Comp.Plain(text=text)])

    async def _reply_with_components(self, event: AstrMessageEvent, components: List[Any]):
        """使用指定的组件列表回复消息"""
        group_id = self._get_group_id(event)
        if group_id:
            try:
                await self._send_group_message_comp(event, group_id, components)
            except Exception as e:
                logger.error(f"回复群消息 (带组件) 时出错: {e}")
        else:
            user_id = self._get_user_id(event)
            if user_id:
                try:
                    plain_text = "".join(c.text for c in components if isinstance(c, Comp.Plain))
                    if plain_text: await self._send_private_message_text(event, user_id, plain_text)
                    else: logger.warning("无法将组件转换为纯文本以进行私聊回复")
                except Exception as e: logger.error(f"尝试回复私聊 (带组件) 失败: {e}")
            else: logger.error("无法获取群组ID或用户ID进行回复")

    async def _send_private_message_text(self, event: AstrMessageEvent, user_id: str, text: str):
        try:
            bot = await self._get_bot_instance(event)
            logger.info(f"准备通过 bot 实例向 {user_id} 发送私聊文本: {text}")
            await bot.send_private_msg(user_id=int(user_id), message=text)
            logger.info(f"尝试通过 bot.send_private_msg 向 {user_id} 发送私聊完成")
        except ValueError: logger.error(f"无法将 user_id '{user_id}' 转换为整数用于发送私聊"); raise
        except AttributeError as e: logger.error(f"发送私聊消息失败: {e}"); raise
        except Exception as e: logger.error(f"通过 bot.send_private_msg 发送私聊给 {user_id} 失败: {e}", exc_info=True); raise

    # --- 新增方法：发送玩家手牌更新 ---
    async def _send_hand_update(self, event: AstrMessageEvent, group_id: str, player_id: str, hand: List[str], main_card: str):
        """向玩家发送手牌更新的私信"""
        if not hand:
            pm_text = f"游戏骗子酒馆 (群: {group_id})\n✋ 手牌: 无\n👑 主牌: {main_card}\n👉 你已无手牌，轮到你时只能 /质疑 或 /等待"
        else:
            hand_display = self._format_hand_for_display(hand)
            pm_text = f"游戏骗子酒馆 (群: {group_id})\n✋ 手牌: {hand_display}\n👑 主牌: {main_card}\n👉 (出牌请用括号内编号)"
        
        try:
            await self._send_private_message_text(event, player_id, pm_text)
            logger.info(f"已向玩家 {player_id} 发送手牌更新私信")
            return True
        except Exception as e:
            logger.warning(f"向玩家 {player_id} 发送手牌更新私信失败: {e}")
            return False
    # --- (已有代码: _send_hand_update) ---
    # ... _send_hand_update 函数的代码 ...
        except Exception as e:
            logger.warning(f"向玩家 {player_id} 发送手牌更新私信失败: {e}")
            return False # _send_hand_update 的最后一行 (大约 L121)

    # --- 在这里添加新的辅助函数 (大约 L122) ---
    async def _reshuffle_and_redeal(self, event: AstrMessageEvent, group_id: str, game: Dict, reason: str, eliminated_player_id: str | None = None):
        """核心逻辑：收集所有牌，洗牌，重新发牌，确定新主牌和起始玩家"""
        logger.info(f"[群{group_id}] 触发重新洗牌发牌，原因: {reason}")
        await self._reply_text(event, f"{reason}！重新洗牌发牌...")

        active_player_ids = self._get_active_players(game)
        if not active_player_ids:
            logger.error(f"[群{group_id}] 重新洗牌时没有活跃玩家？游戏可能已意外结束。")
            await self._reply_text(event, "错误：重新洗牌时找不到活跃玩家！")
            # 尝试结束游戏
            if group_id in self.games:
                game["status"] = "ended"
                # 不立即删除，让 check_game_end 处理或由其他逻辑清理
            return

        # 1. 收集所有牌 (弃牌堆 + 所有活跃玩家手牌)
        new_deck = list(game.get("discard_pile", []))
        game["discard_pile"] = [] # 清空弃牌堆
        for p_id in active_player_ids: # 只收集活跃玩家的手牌
            player_hand = game["players"][p_id].get("hand", [])
            if player_hand:
                new_deck.extend(player_hand)
                game["players"][p_id]["hand"] = [] # 清空手牌
        logger.info(f"[群{group_id}] 回收了 {len(new_deck)} 张牌用于重新洗牌。")

        # 如果回收的牌太少，可能无法满足发牌，需要处理（例如，如果牌堆设计有问题或丢失）
        if len(new_deck) < len(active_player_ids) * HAND_SIZE:
            logger.warning(f"[群{group_id}] 警告：回收的牌数({len(new_deck)})不足以给所有活跃玩家({len(active_player_ids)})发满{HAND_SIZE}张牌！")
            # 这里可以根据需要添加补充牌的逻辑，或者接受发不全牌的情况

        # 2. 确定新主牌
        game["main_card"] = self._determine_main_card()

        # 3. 洗牌
        random.shuffle(new_deck)

        # 4. 重新发牌给活跃玩家
        pm_failed_players = []
        for p_id in active_player_ids:
            hand = []
            for _ in range(HAND_SIZE):
                if new_deck: # 确保牌堆里还有牌
                    hand.append(new_deck.pop())
                else:
                    logger.warning(f"[群{group_id}] 重新发牌时牌堆提前耗尽！玩家 {p_id} 可能未收到完整手牌。")
                    break # 牌发完了就停止给这个人发
            game["players"][p_id]["hand"] = hand
            logger.info(f"[群{group_id}] 重新发给玩家 {p_id} 的手牌: {hand}")
            # 发送私信
            if not await self._send_hand_update(event, group_id, p_id, hand, game["main_card"]):
                 pm_failed_players.append(game["players"][p_id]["name"])

        # 5. 确定新一轮的起始玩家
        start_player_id = None
        start_player_index = -1
        turn_order = game["turn_order"]
        num_players = len(turn_order)

        if eliminated_player_id:
            # 如果有人被淘汰，从被淘汰者的下一位开始找第一个仍然活跃的玩家
            try:
                eliminated_idx = turn_order.index(eliminated_player_id)
                current_check_idx = (eliminated_idx + 1) % num_players
                for _ in range(num_players): # 最多检查一圈
                    potential_starter_id = turn_order[current_check_idx]
                    if not game["players"][potential_starter_id].get("is_eliminated", False):
                        start_player_id = potential_starter_id
                        start_player_index = current_check_idx
                        break
                    current_check_idx = (current_check_idx + 1) % num_players
            except ValueError:
                logger.error(f"被淘汰的玩家 {eliminated_player_id} 不在 turn_order 中！将随机选择起始玩家。")
                # Fallback: 随机选一个活跃玩家开始
                if active_player_ids:
                    start_player_id = random.choice(active_player_ids)
                    try:
                        start_player_index = turn_order.index(start_player_id)
                    except ValueError:
                         logger.error(f"随机选出的活跃玩家 {start_player_id} 也不在 turn_order 中！严重错误。")
                         # 进一步的错误处理，比如结束游戏

        else: # 如果是所有手牌为空导致重洗
             # 从上一轮的当前玩家开始找第一个仍然活跃的（理论上他就是，因为他是导致检查的最后一个动作发出者）
             # 注意：这里的 game["current_player_index"] 应该是导致检查发生前的那个玩家索引
             current_check_idx = game["current_player_index"]
             for _ in range(num_players): # 最多检查一圈
                 potential_starter_id = turn_order[current_check_idx]
                 if not game["players"][potential_starter_id].get("is_eliminated", False):
                     start_player_id = potential_starter_id
                     start_player_index = current_check_idx
                     break
                 current_check_idx = (current_check_idx + 1) % num_players

        # 最后检查是否成功找到起始玩家
        if start_player_id is None:
             logger.error(f"[群{group_id}] 重新洗牌后无法确定起始玩家！可能是所有人都被淘汰了。")
             await self._reply_text(event, "错误：重新洗牌后无法确定起始玩家！游戏可能无法继续。")
             # 尝试结束游戏
             if group_id in self.games:
                 game["status"] = "ended"
                 # 可选：立即清理 self.games[group_id] 或依赖外部清理
             return # 无法继续，直接返回

        game["current_player_index"] = start_player_index # 更新当前玩家索引
        start_player_name = game["players"][start_player_id]["name"]

        # 6. 公告新一轮开始
        turn_order_display = []
        for p_id in turn_order: # 使用完整的 turn_order 来显示顺序和状态
             p_name = game['players'][p_id]['name']
             status = " (淘汰)" if game['players'][p_id].get('is_eliminated') else ""
             turn_order_display.append(f"{p_name}{status}")
        start_message_components = [
            Comp.Plain(text=f"🔄 新一轮开始 ({reason})！\n"
                  f"👑 新主牌: {game['main_card']}\n"
                  f"📜 顺序: {', '.join(turn_order_display)}\n"
                  f"(新手牌已私信发送)\n" # 修正并简化提示
                  f"👉 轮到 "),
            Comp.At(qq=start_player_id),
            Comp.Plain(text=f" ({start_player_name}) 出牌。")
        ]
        
        # 处理私信失败的提示
        if pm_failed_players:
             start_message_components.append(Comp.Plain(text=f"\n\n注意：未能成功向以下玩家发送手牌私信：{', '.join(pm_failed_players)}。请检查机器人好友状态或私聊设置。"))

        await self._reply_with_components(event, start_message_components)
        game["last_play"] = None # 新一轮开始时清除上一轮的出牌信息

    async def _check_and_handle_all_hands_empty(self, event: AstrMessageEvent, group_id: str, game: Dict) -> bool:
        """检查是否所有活跃玩家手牌都空了，如果是则触发重洗并返回True"""
        active_players = self._get_active_players(game)
        if not active_players:
             logger.info(f"[群{group_id}] 检查空手牌时发现没有活跃玩家，不执行重洗。")
             return False # 没有活跃玩家，游戏应该已经结束或即将结束

        # 检查所有活跃玩家的手牌是否都为空列表或None
        all_empty = all(not game["players"][pid].get("hand") for pid in active_players)

        if all_empty:
            logger.info(f"[群{group_id}] 检测到所有活跃玩家手牌已空，触发重新洗牌。")
            # 注意：这里调用重洗函数时，不传递 eliminated_player_id
            await self._reshuffle_and_redeal(event, group_id, game, "所有活跃玩家手牌已空")
            return True # 表示已经处理了重洗，外部调用者不需要再继续处理下一回合
        return False # 不需要重洗，外部调用者应继续正常流程

    # --- (已有代码: _initialize_gun 等) ---

    # --- 游戏设置函数 ---
    def _initialize_gun(self) -> Tuple[List[str], int]:
        # 使用更新后的 LIVE_BULLETS 常量
        live_count = LIVE_BULLETS
        empty_count = GUN_CHAMBERS - live_count
        if empty_count < 0: # 防止配置错误
             logger.error(f"实弹数({live_count}) 大于弹巢数({GUN_CHAMBERS})，重置为空弹数=1")
             empty_count = 1
             live_count = GUN_CHAMBERS - 1

        bullets = ["空弹"] * empty_count + ["实弹"] * live_count
        random.shuffle(bullets)
        logger.info(f"初始化枪械: {live_count}实弹, {empty_count}空弹")
        return bullets, 0

    def _build_deck(self, player_count: int) -> List[str]:
        deck = []
        # 使用更新后的 CARDS_PER_TYPE
        for card_type in CARD_TYPES: deck.extend([card_type] * CARDS_PER_TYPE)
        joker_count_dynamic = player_count // 2
        logger.info(f"根据玩家数量 {player_count} 计算小丑牌数量: {joker_count_dynamic}")
        deck.extend([JOKER] * joker_count_dynamic)
        return deck

    def _determine_main_card(self) -> str:
        return random.choice(CARD_TYPES)

    def _deal_cards(self, deck: List[str], player_ids: List[str], game_players: Dict[str, Dict]):
        current_deck = list(deck)
        random.shuffle(current_deck)
        total_cards_needed = len(player_ids) * HAND_SIZE
        if len(current_deck) < total_cards_needed:
             logger.warning(f"牌堆总数 ({len(current_deck)}) 可能不足以满足所有玩家 ({len(player_ids)}人 * {HAND_SIZE}张/人 = {total_cards_needed}张)")

        for player_id in player_ids:
            hand = []
            for _ in range(HAND_SIZE):
                if current_deck: hand.append(current_deck.pop())
                else: logger.warning("发牌时牌堆提前耗尽！"); break
            game_players[player_id]["hand"] = hand
            logger.info(f"发给玩家 {player_id} 的手牌: {hand}")

    # --- 游戏进程函数 ---
    def _get_active_players(self, game: Dict) -> List[str]:
        return [pid for pid, pdata in game["players"].items() if not pdata.get("is_eliminated", False)]

    def _get_next_player_index(self, game: Dict) -> int:
        current_index = game["current_player_index"]
        turn_order = game["turn_order"]
        num_players = len(turn_order)
        if num_players == 0: return -1

        next_index = (current_index + 1) % num_players
        active_player_found = False
        for _ in range(num_players):
             # 只找未被淘汰的玩家，手牌是否为空不影响其参与轮转（可以质疑/被射击）
             if not game["players"][turn_order[next_index]].get("is_eliminated", False):
                  active_player_found = True; break
             next_index = (next_index + 1) % num_players

        if not active_player_found: logger.error("无法找到下一个活跃玩家！所有人都被淘汰了？"); return -1
        return next_index

    def _check_challenge(self, actual_cards: List[str], main_card: str) -> bool:
        return all(card == main_card or card == JOKER for card in actual_cards)

    async def _check_game_end(self, event: AstrMessageEvent, group_id: str, game: Dict) -> bool:
        active_players = self._get_active_players(game)
        if len(active_players) <= 1:
            game["status"] = "ended"
            winner_id = active_players[0] if active_players else None
            winner_name = game["players"][winner_id]["name"] if winner_id else "无人"
            await self._reply_text(event, f"🎉 游戏结束！胜者: {winner_name}！")
            logger.info(f"[群{group_id}] 游戏结束，获胜者: {winner_name}({winner_id})")
            event.stop_event()
            return True
        return False

    async def take_shot(self, event: AstrMessageEvent, group_id: str, player_id: str):
        game = self.games[group_id]
        player_data = game["players"][player_id]
        player_name = player_data["name"]
        if player_data.get("is_eliminated", False): return # 如果已经被淘汰，直接返回

        gun = player_data["gun"]
        position = player_data["gun_position"]
        bullet = gun[position]
        player_data["gun_position"] = (position + 1) % len(gun) # 无论如何都旋转弹巢

        shot_result = ""
        eliminated_in_this_shot = False # 标记本次射击是否导致淘汰

        if bullet == "空弹":
            shot_result = f"{player_name} 扣动扳机... 咔嚓！是【空弹】！"
            logger.info(f"[群{group_id}] 玩家 {player_name}({player_id}) 开枪: 空弹")
            await self._reply_text(event, shot_result) # 先报告空弹结果
            # 空弹后，轮到下一个人（在 challenge_play 中处理）
            # 这里不需要 stop_event，因为 challenge_play 会处理后续流程

        else: # 实弹
            player_data["is_eliminated"] = True
            eliminated_in_this_shot = True # 标记发生了淘汰
            shot_result = f"{player_name} 扣动扳机... 砰！是【实弹】！{player_name} 被淘汰了！"
            logger.info(f"[群{group_id}] 玩家 {player_name}({player_id}) 开枪: 中弹淘汰")
            await self._reply_text(event, shot_result) # 先报告淘汰结果

            # --- 在这里添加检查和重洗逻辑 ---
            # 检查游戏是否因这次淘汰而结束
            if await self._check_game_end(event, group_id, game):
                # 如果游戏结束了，就不需要重洗了，check_game_end 内部会 stop_event
                return # 直接返回，游戏已结束

            # 如果游戏没有结束，因为有人淘汰，触发重新洗牌
            logger.info(f"[群{group_id}] 玩家 {player_name} 被淘汰，游戏未结束，触发重新洗牌。")
            await self._reshuffle_and_redeal(event, group_id, game, f"玩家 {player_name} 被淘汰", eliminated_player_id=player_id)
            # 重洗函数内部会处理后续流程（宣布新回合等），这里直接停止当前事件处理
            event.stop_event()
            return # 结束 take_shot 的执行

        # --- 原有的检查游戏结束逻辑（针对空弹情况或未来可能的其他情况）---
        # 注意：上面的实弹逻辑已经包含了结束检查和重洗，理论上不会执行到这里了
        # 但为了代码完整性，保留这里的检查可能更好，以防未来逻辑变动
        # if not await self._check_game_end(event, group_id, game):
        #     # 如果是空弹且游戏没结束，challenge_play 会继续处理
        #     # 如果是其他情况（目前没有），可能需要 stop_event
        #     pass # 由调用者 (challenge_play) 决定是否 stop_event

        # 对于 take_shot 本身，如果不是实弹淘汰导致的重洗，执行到这里时，
        # 应该让调用它的函数 (challenge_play) 来决定后续流程和是否 stop_event
        # 所以这里不需要 event.stop_event()

    # --- 命令处理函数 ---
    @filter.command("骗子酒馆")
    async def create_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id: await self._reply_text(event, "请在群聊中使用此命令"); event.stop_event(); return
        if group_id in self.games and self.games[group_id].get("status") != "ended":
             await self._reply_text(event, "本群已有一个骗子酒馆游戏正在进行中 (使用 /结束游戏 可强制结束)")
             event.stop_event(); return
        self.games[group_id] = {
            "status": "waiting", "players": {}, "deck": [], "main_card": None,
            "turn_order": [], "current_player_index": -1, "last_play": None, "discard_pile": [],
        }
        logger.info(f"[群{group_id}] 骗子酒馆 (左轮扑克模式) 游戏已创建")
        await self._reply_text(event, f"骗子酒馆开张了！\n➡️ 输入 /加入 参与 (至少 {MIN_PLAYERS} 人)。\n➡️ 发起者输入 /开始 启动游戏。\n\n📜 玩法: 轮流用 /出牌 编号 (1-3张) 声称是主牌，下家可 /质疑 或继续 /出牌。")
        event.stop_event(); return

    @filter.command("加入")
    async def join_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        user_name = event.get_sender_name()
        if not group_id or not user_id: await self._reply_text(event, "无法识别命令来源"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game: await self._reply_text(event, "本群当前没有进行中的游戏"); event.stop_event(); return
        if game["status"] != "waiting": await self._reply_text(event, "游戏已经开始或结束，无法加入"); event.stop_event(); return
        if user_id in game["players"]: await self._reply_text(event, f"{user_name} 已经加入了游戏"); event.stop_event(); return
        # 初始化枪械时使用更新后的常量
        gun, gun_pos = self._initialize_gun()
        game["players"][user_id] = {
            "name": user_name, "hand": [], "gun": gun,
            "gun_position": gun_pos, "is_eliminated": False
        }
        player_count = len(game['players'])
        logger.info(f"[群{group_id}] 玩家 {user_name}({user_id}) 加入游戏 ({player_count}人)")
        await self._reply_text(event, f"✅ {user_name} 已加入！当前 {player_count} 人。")
        event.stop_event(); return

    @filter.command("开始")
    async def start_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id: await self._reply_text(event, "请在群聊中使用此命令"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game: await self._reply_text(event, "本群当前没有进行中的游戏"); event.stop_event(); return
        if game["status"] != "waiting": await self._reply_text(event, "游戏已经开始或结束"); event.stop_event(); return
        player_ids = list(game["players"].keys())
        player_count = len(player_ids)
        if player_count < MIN_PLAYERS: await self._reply_text(event, f"至少需要 {MIN_PLAYERS} 名玩家才能开始游戏，当前只有 {player_count} 人"); event.stop_event(); return
        game["deck"] = self._build_deck(player_count)
        game["main_card"] = self._determine_main_card()
        self._deal_cards(game["deck"], player_ids, game["players"])
        game["turn_order"] = random.sample(player_ids, len(player_ids))
        game["current_player_index"] = 0
        game["status"] = "playing"
        game["last_play"] = None
        game["discard_pile"] = []
        logger.info(f"[群{group_id}] 游戏开始! 主牌: {game['main_card']}, 顺序: {[game['players'][pid]['name'] for pid in game['turn_order']]}, 动态小丑牌: {player_count // 2}, 实弹数: {LIVE_BULLETS}")

        pm_failed_players = []
        for player_id in player_ids:
            hand = game["players"][player_id].get("hand", [])
            if hand:
                hand_display = self._format_hand_for_display(hand)
                pm_text = f"游戏骗子酒馆 (群: {group_id})\n✋ 手牌: {hand_display}\n👑 主牌: {game['main_card']}\n👉 (出牌请用括号内编号)"
                try: await self._send_private_message_text(event, player_id, pm_text)
                except Exception as e:
                    logger.warning(f"向玩家 {player_id} 发送手牌私信失败: {e}"); pm_failed_players.append(game["players"][player_id]["name"])

        start_player_id = game["turn_order"][game["current_player_index"]]
        start_player_name = game["players"][start_player_id]["name"]
        start_message_components = [
            Comp.Plain(text=f"游戏开始！共有 {player_count} 名玩家。\n"
                          f"👑 主牌: {game['main_card']}\n"
                          f"已将发送给各位。\n"
                          f"📜 顺序: {', '.join([game['players'][pid]['name'] for pid in game['turn_order']])}\n"
                          f"👉 轮到 @{start_player_id} ({start_player_name}) 出牌\n"),
            Comp.At(qq=start_player_id),
            Comp.Plain(text=f" (/出牌 编号...)")
        ]
        if pm_failed_players: start_message_components.append(Comp.Plain(text=f"\n\n注意：未能成功向以下玩家发送手牌私信：{', '.join(pm_failed_players)}。请检查机器人好友状态或私聊设置。"))
        await self._reply_with_components(event, start_message_components)
        event.stop_event(); return

    @filter.command("出牌")
    async def play_cards(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        player_id = self._get_user_id(event)
        player_name = event.get_sender_name()
        if not group_id or not player_id: await self._reply_text(event, "无法识别命令来源"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game or game["status"] != "playing": await self._reply_text(event, "现在不是进行游戏的时间"); event.stop_event(); return
        current_player_id = game["turn_order"][game["current_player_index"]]
        if player_id != current_player_id: await self._reply_text(event, "还没轮到你"); event.stop_event(); return

        # --- 检查手牌是否为空 ---
        player_data = game["players"][player_id]
        current_hand = player_data["hand"]
        if not current_hand:
            await self._reply_text(event, "✋ 你手牌已空，无法出牌。轮到你时可 /质疑 或 /等待。")
            event.stop_event(); return

        # --- 解析参数 ---
        try:
            if not hasattr(event, 'message_str'):
                 logger.error("事件对象缺少 message_str 属性！")
                 await self._reply_text(event, "无法解析命令参数。")
                 event.stop_event(); return
            args_text = event.message_str.strip()
            logger.debug(f"收到的参数文本 (message_str): '{args_text}'")
            indices_1based_str = re.findall(r'\d+', args_text)
            logger.debug(f"提取到的编号参数: {indices_1based_str}")
            if not indices_1based_str: raise ValueError("❌ 命令错误: {e}\n👉 请用 /出牌 编号 [编号...] (例: /出牌 1 3)")
            if not (1 <= len(indices_1based_str) <= 3): raise ValueError("出牌数量必须是 1 到 3 张")
            indices_1based = []
            for idx_str in indices_1based_str: idx = int(idx_str); indices_1based.append(idx)
            if len(indices_1based) != len(set(indices_1based)): raise ValueError("出牌编号不能重复")
            indices_0based = [i - 1 for i in indices_1based]
        except ValueError as e:
            await self._reply_text(event, f"✋ 你手牌已空，无法出牌。轮到你时可 /质疑 或 /等待。")
            event.stop_event(); return
        except Exception as e:
             logger.error(f"解析出牌命令时出错: {e}", exc_info=True)
             await self._reply_text(event, "❌ 处理出牌命令时发生内部错误，请检查日志或联系管理员。")
             event.stop_event(); return

        # --- 验证编号和手牌 ---
        hand_size = len(current_hand)
        invalid_indices = [i + 1 for i in indices_0based if i < 0 or i >= hand_size]
        if invalid_indices:
            await self._reply_text(event, f"❌ 无效的编号: {', '.join(map(str, invalid_indices))}。你的手牌只有 {hand_size} 张 (编号 1 到 {hand_size})")
            event.stop_event(); return

        # --- 执行出牌 ---
        if game["last_play"]:
            accepted_cards = game["last_play"]["actual_cards"]
            game["discard_pile"].extend(accepted_cards)
            logger.info(f"[群{group_id}] 玩家 {player_name} 未质疑，上轮牌 {accepted_cards} 进入弃牌堆")
            game["last_play"] = None
        cards_to_play = [current_hand[i] for i in indices_0based]
        new_hand = []
        indices_played_set = set(indices_0based)
        for i, card in enumerate(current_hand):
            if i not in indices_played_set: new_hand.append(card)
        player_data["hand"] = new_hand # 更新手牌
        quantity_played = len(cards_to_play)
        game["last_play"] = {
            "player_id": player_id, "claimed_quantity": quantity_played, "actual_cards": cards_to_play
        }
        logger.info(f"[群{group_id}] 玩家 {player_name}({player_id}) 使用编号 {indices_1based} 打出了牌: {cards_to_play}. 剩余手牌: {len(player_data['hand'])}")
        
        # --- 【新增】向玩家发送手牌更新私信 ---
        await self._send_hand_update(event, group_id, player_id, player_data["hand"], game["main_card"])

        # --- 确定下一玩家并公告 ---
        next_player_index = self._get_next_player_index(game)
        if next_player_index == -1: await self._reply_text(event, "❌ 错误：无法确定下一位玩家！"); event.stop_event(); return
        game["current_player_index"] = next_player_index
        next_player_id = game["turn_order"][next_player_index]
        next_player_data = game["players"][next_player_id]
        next_player_name = next_player_data["name"]
        next_player_hand_empty = not next_player_data["hand"] # 检查下一位玩家手牌是否为空
          # --- 在这里添加检查所有手牌是否为空的逻辑 ---
        if await self._check_and_handle_all_hands_empty(event, group_id, game):
           event.stop_event() # 重洗函数已处理后续，停止当前事件
           return # 直接返回    
        # 构建提示消息
        announcement_components = []
        if not player_data["hand"]: # 如果当前玩家打完手牌
             announcement_components.append(Comp.Plain(text=f"{player_name} 打出了最后 {quantity_played} 张牌！声称是主牌【{game['main_card']}】。\n轮到 "))
        else:
             announcement_components.append(Comp.Plain(text=f"{player_name} 打出了 {quantity_played} 张牌，声称是主牌【{game['main_card']}】。\n轮到 "))
        announcement_components.append(Comp.At(qq=next_player_id))
        # 根据下一位玩家手牌情况调整提示
        if next_player_hand_empty:
             announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应 (手牌已空，只能 /质疑 或 /等待)")) # 确认提示包含等待
        else:
             announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应。请选择 /质疑 或 /出牌 <编号...>"))

        await self._reply_with_components(event, announcement_components)
        event.stop_event(); return

    @filter.command("质疑")
    async def challenge_play(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        challenger_id = self._get_user_id(event)
        challenger_name = event.get_sender_name()
        if not group_id or not challenger_id: await self._reply_text(event, "❌ 无法识别命令来源"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game or game["status"] != "playing": await self._reply_text(event, "现在不是进行游戏的时间"); event.stop_event(); return
        reacting_player_id = game["turn_order"][game["current_player_index"]]
        if challenger_id != reacting_player_id: await self._reply_text(event, "还没轮到你反应"); event.stop_event(); return
        last_play_info = game.get("last_play")
        if not last_play_info: await self._reply_text(event, "ℹ️ 当前没有可质疑的出牌"); event.stop_event(); return

        player_who_played_id = last_play_info["player_id"]
        player_who_played_name = game["players"][player_who_played_id]["name"]
        actual_cards = last_play_info["actual_cards"]
        claimed_quantity = last_play_info["claimed_quantity"]
        main_card = game["main_card"]

        await self._reply_text(event,
            f"🤔 {challenger_name} 质疑 {player_who_played_name} 打出的 {claimed_quantity} 张 👑{main_card}！\n亮牌: 【{' '.join(actual_cards)}】"
            f"亮牌结果: 【{' '.join(actual_cards)}】")
        is_claim_true = self._check_challenge(actual_cards, main_card)
        loser_id, loser_name = (challenger_id, challenger_name) if is_claim_true else (player_who_played_id, player_who_played_name)
        result_text = f"❌ 质疑失败！{player_who_played_name} 确实是主牌/鬼牌。{loser_name} 开枪！" if is_claim_true else f"质疑成功！{player_who_played_name} 没有完全打出 {claimed_quantity} 张主牌或鬼牌。 {loser_name} 需要开枪！"
        await self._reply_text(event, f"{result_text} {loser_name} 需要开枪！")
        game["discard_pile"].extend(actual_cards)
        game["last_play"] = None

        await self.take_shot(event, group_id, loser_id) # 开枪内部会处理 stop_event

        # 如果游戏没结束，确定下一轮出牌者并提示
        if game["status"] == "playing":
            next_player_to_play_id = None
            challenger_still_active = not game["players"][challenger_id].get("is_eliminated", False)
            if challenger_still_active:
                 next_player_to_play_id = challenger_id
                 try: game["current_player_index"] = game["turn_order"].index(challenger_id)
                 except ValueError:
                     logger.error(f"无法在 turn_order 中找到 challenger_id {challenger_id}"); event.stop_event(); return
            else:
                 next_active_index = self._get_next_player_index(game)
                 if next_active_index != -1:
                      game["current_player_index"] = next_active_index
                      next_player_to_play_id = game["turn_order"][next_active_index]
                 else:
                     logger.error("质疑后无法确定下一位玩家 (可能都淘汰了?)"); event.stop_event(); return

            if next_player_to_play_id:
                next_player_data = game["players"][next_player_to_play_id]
                next_player_name = next_player_data["name"]
                next_player_hand_empty = not next_player_data["hand"]
            if await self._check_and_handle_all_hands_empty(event, group_id, game):
                # challenge_play 在 take_shot 返回后可能已经 stop_event 了，但以防万一
               if not event.is_stopped(): event.stop_event()
               return # 重洗已处理，直接返回
                # 构建提示消息
            next_turn_components = [Comp.Plain(text="轮到 "), Comp.At(qq=next_player_to_play_id)]
            if next_player_hand_empty:
                 # 质疑结算后轮到空手牌玩家，他不能主动出牌，只能等待（因为质疑已经处理了上一轮的出牌）
                 next_turn_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌 (手牌已空，只能 /等待)"))
            else:
                 next_turn_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌。请使用 /出牌 <编号...>"))

            await self._reply_with_components(event, next_turn_components)
                
                # --- 【新增】向下一位玩家发送手牌更新私信 ---
            if not next_player_data.get("is_eliminated", False):
                    await self._send_hand_update(event, group_id, next_player_to_play_id, next_player_data["hand"], game["main_card"])
            

    # 无论游戏是否结束，质疑命令处理完成
        if not event.is_stopped(): event.stop_event(); return # 确保事件停止
        # 无论游戏是否结束，质疑命令处理完成
        event.stop_event(); return
    @filter.command("等待")
    async def wait_turn(self, event: AstrMessageEvent):
        """处理玩家选择等待的操作 (仅限手牌为空时)"""
        group_id = self._get_group_id(event)
        player_id = self._get_user_id(event)
        player_name = event.get_sender_name()

        # --- 基本检查 ---
        if not group_id or not player_id:
            await self._reply_text(event, "无法识别命令来源")
            event.stop_event(); return
        game = self.games.get(group_id)
        if not game or game["status"] != "playing":
            await self._reply_text(event, "现在不是进行游戏的时间")
            event.stop_event(); return
        current_player_id = game["turn_order"][game["current_player_index"]]
        if player_id != current_player_id:
            await self._reply_text(event, "还没轮到你")
            event.stop_event(); return

        # --- 核心逻辑：检查手牌是否为空 ---
        player_data = game["players"][player_id]
        if player_data["hand"]: # 如果手牌不为空
            await self._reply_text(event, "你还有手牌，不能选择等待！请使用 /出牌 或 /质疑。")
            event.stop_event(); return

        # --- 执行等待操作 ---
        logger.info(f"[群{group_id}] 玩家 {player_name}({player_id}) 手牌为空，选择等待。")

        # 如果上一个玩家出牌了，但当前玩家（手牌为空）选择等待，意味着上轮出牌被接受
        if game["last_play"]:
            accepted_cards = game["last_play"]["actual_cards"]
            last_player_name = game["players"][game["last_play"]["player_id"]]["name"]
            game["discard_pile"].extend(accepted_cards)
            logger.info(f"[群{group_id}] 玩家 {player_name} 等待，上轮 {last_player_name} 的牌 {accepted_cards} 进入弃牌堆")
            game["last_play"] = None # 清除上轮出牌信息

        # --- 确定下一玩家并公告 ---
        next_player_index = self._get_next_player_index(game)
        if next_player_index == -1:
            await self._reply_text(event, "错误：无法确定下一位玩家！")
            event.stop_event(); return

        game["current_player_index"] = next_player_index
        next_player_id = game["turn_order"][next_player_index]
        next_player_data = game["players"][next_player_id]
        next_player_name = next_player_data["name"]
        next_player_hand_empty = not next_player_data["hand"] # 检查下一位玩家手牌是否为空
        if await self._check_and_handle_all_hands_empty(event, group_id, game):
            event.stop_event() # 重洗函数已处理后续，停止当前事件
            return # 直接返回
        # 构建提示消息
        announcement_components = [
            Comp.Plain(text=f"{player_name} 手牌已空，选择等待。\n轮到 "),
            Comp.At(qq=next_player_id)
        ]
        # 根据下一位玩家手牌情况调整提示
        if next_player_hand_empty:
            # 如果下一位玩家手牌也为空
            if game["last_play"]: # 并且上一轮有人出牌了（即当前等待的玩家本可以质疑）
                 announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应 (手牌已空，只能 /质疑 或 /等待)"))
            else: # 上一轮没人出牌（比如质疑结算后轮到空手牌玩家）
                 announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌 (手牌已空，只能 /等待)")) # 空手牌不能主动出牌
        else:
            # 如果下一位玩家有手牌
            if game["last_play"]: # 并且上一轮有人出牌了
                 announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应。请选择 /质疑 或 /出牌 <编号...>"))
            else: # 上一轮没人出牌
                 announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌。请使用 /出牌 <编号...>"))

        await self._reply_with_components(event, announcement_components)

        # --- 【重要】向下一位玩家发送手牌更新私信 (如果他没被淘汰且有手牌) ---
        if not next_player_data.get("is_eliminated", False) and not next_player_hand_empty:
             await self._send_hand_update(event, group_id, next_player_id, next_player_data["hand"], game["main_card"])
        elif not next_player_data.get("is_eliminated", False) and next_player_hand_empty:
             # 如果下一位玩家手牌也空了，也发个提醒
             await self._send_hand_update(event, group_id, next_player_id, [], game["main_card"])


        event.stop_event(); return
        
    @filter.command("状态")
    async def game_status(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id: await self._reply_text(event, "请在群聊中使用此命令"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game or game["status"] == "ended": await self._reply_text(event, "本群当前没有进行中的骗子酒馆游戏"); event.stop_event(); return
        if game["status"] == "waiting":
            player_list = "\n".join([f"- {p['name']}" for p in game["players"].values()]) or "暂无玩家加入"
            await self._reply_text(event, f"⏳ 游戏状态: 等待中\n玩家 ({len(game['players'])}人):\n{player_list}\n\n➡️ 发起者输入 /开始 (至少 {MIN_PLAYERS} 人)")
            event.stop_event(); return

        main_card = game["main_card"]
        turn_order_names = [game['players'][pid]['name'] for pid in game['turn_order']]
        current_player_name = "未知"; current_player_at = None
        if 0 <= game["current_player_index"] < len(game["turn_order"]):
            current_player_id = game["turn_order"][game["current_player_index"]]
            current_player_name = game["players"][current_player_id]["name"]
            current_player_at = Comp.At(qq=current_player_id)
        else:
            logger.warning(f"状态查询时 current_player_index 无效: {game['current_player_index']}")
        player_statuses = [f"- {pdata['name']}: {'淘汰' if pdata.get('is_eliminated') else str(len(pdata.get('hand', []))) + '张牌'}" for pid, pdata in game["players"].items()]
        last_play_text = "无"
        if game["last_play"]:
             last_player_name = game["players"][game["last_play"]["player_id"]]["name"]
             claimed_quantity = game["last_play"]["claimed_quantity"]
             last_play_text = f"{last_player_name} 声称打出 {claimed_quantity} 张主牌【{main_card}】 (等待 {current_player_name} 反应)"

        status_components = [Comp.Plain(text=f"游戏状态：进行中\n主牌: 【{main_card}】\n出牌顺序: {', '.join(turn_order_names)}\n当前轮到: ")]
        if current_player_at: status_components.append(current_player_at); status_components.append(Comp.Plain(text=f" ({current_player_name})"))
        else: status_components.append(Comp.Plain(text=current_player_name))
        status_components.extend([
            Comp.Plain(text=f"\n--------------------\n玩家状态:\n" + "\n".join(player_statuses) + "\n"
                          f"--------------------\n等待处理的出牌: {last_play_text}\n"
                          f"弃牌堆: {len(game.get('discard_pile',[]))}张 | 牌堆剩余: 约{len(game.get('deck',[]))}张")
        ])
        user_id = self._get_user_id(event)
        if user_id and user_id in game["players"] and not game["players"][user_id].get("is_eliminated"):
             my_hand = game["players"][user_id].get("hand", [])
             my_hand_display = self._format_hand_for_display(my_hand)
             status_components.append(Comp.Plain(text=f"\n--------------------\n你的手牌: {my_hand_display}"))
        await self._reply_with_components(event, status_components)
        event.stop_event(); return

    @filter.command("我的手牌")
    async def show_my_hand(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        if not group_id or not user_id: await self._reply_text(event, "无法识别命令来源"); event.stop_event(); return
        game = self.games.get(group_id)
        if not game or game["status"] != "playing": await self._reply_text(event, "现在不是进行游戏的时间"); event.stop_event(); return
        player_data = game["players"].get(user_id)
        if not player_data or player_data.get("is_eliminated"): await self._reply_text(event, "你不在游戏中或已被淘汰。"); event.stop_event(); return
        my_hand = player_data.get("hand", [])
        my_hand_display = self._format_hand_for_display(my_hand)
        main_card = game["main_card"]
        
        # 使用新增的手牌更新方法
        success = await self._send_hand_update(event, group_id, user_id, my_hand, main_card)
        if success:
            await self._reply_text(event, "已通过私信将你的手牌发送给你，请查收。")
        else:
            # 如果私聊失败，则在群里回复（注意隐私风险）
            await self._reply_text(event, f"你的手牌: {my_hand_display}\n本轮主牌: 【{main_card}】\n(私信发送失败，已在群内显示)")
        
        event.stop_event(); return

    @filter.command("结束游戏")
    async def force_end_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id: await self._reply_text(event, "请在群聊中使用此命令"); event.stop_event(); return
        if group_id in self.games:
            del self.games[group_id]
            logger.info(f"[群{group_id}] 游戏被强制结束")
            await self._reply_text(event, "当前群聊的骗子酒馆游戏已被强制结束。")
        else: await self._reply_text(event, "本群当前没有进行中的骗子酒馆游戏。")
        event.stop_event(); return

    async def terminate(self):
        logger.info("骗子酒馆插件卸载/停用，清理所有游戏数据...")
        self.games = {}
        logger.info("所有游戏数据已清理")
