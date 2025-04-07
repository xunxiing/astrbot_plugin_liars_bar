# main.py - 骗子酒馆插件入口 (瘦身版)
# 处理 AstrBot 事件，调用游戏逻辑

from typing import Dict, Any, List, Optional
import re

# --- 从 astrbot.api 导入所需组件 ---
from astrbot.api import logger
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

# --- 导入游戏逻辑和模型（使用相对导入）---
from .game_logic import LiarsTavernGame
from .models import GameEvent, GameConfig, GameState
from .message_utils import MessageFormatter
from .exceptions import GameError, InvalidActionError, InvalidPlayerError

# --- 插件注册 ---
@register("liar_tavern", "骗子酒馆助手", "左轮扑克 (骗子酒馆规则变体)", "3.0.0", "https://github.com/xunxiing/astrbot_plugin_liars_bar")
class LiarsPokerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.games: Dict[str, LiarsTavernGame] = {}
        self.message_formatter = MessageFormatter()
        logger.info("LiarsPokerPlugin (左轮扑克) 初始化完成。")

    # --- 辅助函数 ---
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
                    if plain_text: 
                        await self._send_private_message_text(event, user_id, plain_text)
                    else: 
                        logger.warning("无法将组件转换为纯文本以进行私聊回复")
                except Exception as e: 
                    logger.error(f"尝试回复私聊 (带组件) 失败: {e}")
            else: 
                logger.error("无法获取群组ID或用户ID进行回复")

    async def _send_group_message_comp(self, event: AstrMessageEvent, group_id: str, astr_message_list: list):
        try:
            bot = await self._get_bot_instance(event)
            onebot_message = self._convert_astr_comps_to_onebot(astr_message_list)
            if not onebot_message: 
                logger.warning(f"转换后的 OneBot 消息为空，取消向群 {group_id} 发送")
                return
            logger.info(f"准备发送给 OneBot 的消息段 (群 {group_id}): {onebot_message}")
            await bot.send_group_msg(group_id=int(group_id), message=onebot_message)
            logger.info(f"尝试通过 bot.send_group_msg 向群 {group_id} 发送消息完成")
        except ValueError: 
            logger.error(f"无法将 group_id '{group_id}' 转换为整数")
            raise
        except AttributeError as e: 
            logger.error(f"发送群消息失败: {e}")
            raise
        except Exception as e: 
            logger.error(f"通过 bot.send_group_msg 发送群聊给 {group_id} 失败: {e}", exc_info=True)
            raise

    def _convert_astr_comps_to_onebot(self, astr_message_list: List[Any]) -> List[Dict]:
        onebot_segments = []
        for comp in astr_message_list:
            if isinstance(comp, Comp.Plain):
                onebot_segments.append({"type": "text", "data": {"text": comp.text}})
            elif isinstance(comp, Comp.At):
                onebot_segments.append({"type": "at", "data": {"qq": str(comp.qq)}})
            else:
                logger.warning(f"未处理的 AstrBot 消息组件类型: {type(comp)}, 将尝试转为文本")
                try: 
                    text_repr = str(comp)
                    onebot_segments.append({"type": "text", "data": {"text": text_repr}})
                except Exception: 
                    logger.error(f"无法将组件 {type(comp)} 转换为文本", exc_info=True)
        return onebot_segments

    async def _send_private_message_text(self, event: AstrMessageEvent, user_id: str, text: str):
        try:
            bot = await self._get_bot_instance(event)
            logger.info(f"准备通过 bot 实例向 {user_id} 发送私聊文本: {text}")
            await bot.send_private_msg(user_id=int(user_id), message=text)
            logger.info(f"尝试通过 bot.send_private_msg 向 {user_id} 发送私聊完成")
        except ValueError: 
            logger.error(f"无法将 user_id '{user_id}' 转换为整数用于发送私聊")
            raise
        except AttributeError as e: 
            logger.error(f"发送私聊消息失败: {e}")
            raise
        except Exception as e: 
            logger.error(f"通过 bot.send_private_msg 发送私聊给 {user_id} 失败: {e}", exc_info=True)
            raise

    async def _send_hand_update(self, event: AstrMessageEvent, group_id: str, player_id: str, hand: List[str], main_card: str):
        """向玩家发送手牌更新的私信"""
        message = self.message_formatter.format_hand_update(group_id, hand, main_card)
        
        try:
            await self._send_private_message_text(event, player_id, message)
            logger.info(f"已向玩家 {player_id} 发送手牌更新私信")
            return True
        except Exception as e:
            logger.warning(f"向玩家 {player_id} 发送手牌更新私信失败: {e}")
            return False

    # --- 游戏事件回调处理 ---
    def _register_game_callbacks(self, game: LiarsTavernGame, event: AstrMessageEvent):
        """为游戏注册事件回调"""
        
        async def on_player_joined(game_instance, **kwargs):
            player = kwargs.get('player')
            await self._reply_text(event, f"✅ {player.name} 已加入！当前 {len(game_instance.players)} 人。")
        
        async def on_game_started(game_instance, **kwargs):
            main_card = kwargs.get('main_card')
            turn_order = kwargs.get('turn_order')
            first_player_id = kwargs.get('first_player_id')
            
            # 发送手牌给所有玩家
            pm_failed_players = []
            for player_id, player in game_instance.players.items():
                if not await self._send_hand_update(event, game_instance.game_id, player_id, player.hand, main_card):
                    pm_failed_players.append(player.name)
            
            # 构建游戏开始消息
            start_message_components = [
                Comp.Plain(text=f"游戏开始！共有 {len(game_instance.players)} 名玩家。\n"
                          f"👑 主牌: {main_card}\n"
                          f"已将手牌发送给各位。\n"
                          f"📜 顺序: {', '.join([game_instance.players[pid].name for pid in turn_order])}\n"
                          f"👉 轮到 "),
                Comp.At(qq=first_player_id),
                Comp.Plain(text=f" ({game_instance.players[first_player_id].name}) 出牌 (/出牌 编号...)")
            ]
            
            if pm_failed_players:
                start_message_components.append(Comp.Plain(text=f"\n\n注意：未能成功向以下玩家发送手牌私信：{', '.join(pm_failed_players)}。请检查机器人好友状态或私聊设置。"))
            
            await self._reply_with_components(event, start_message_components)
        
        async def on_cards_played(game_instance, **kwargs):
            player_id = kwargs.get('player_id')
            cards_played = kwargs.get('cards_played')
            quantity_played = kwargs.get('quantity_played')
            next_player_id = kwargs.get('next_player_id')
            player_hand_empty = kwargs.get('player_hand_empty')
            
            player_name = game_instance.players[player_id].name
            next_player_name = game_instance.players[next_player_id].name
            next_player_hand_empty = not game_instance.players[next_player_id].hand
            
            # 构建出牌消息
            announcement_components = []
            if player_hand_empty:
                announcement_components.append(Comp.Plain(text=f"{player_name} 打出了最后 {quantity_played} 张牌！声称是主牌【{game_instance.main_card}】。\n轮到 "))
            else:
                announcement_components.append(Comp.Plain(text=f"{player_name} 打出了 {quantity_played} 张牌，声称是主牌【{game_instance.main_card}】。\n轮到 "))
            
            announcement_components.append(Comp.At(qq=next_player_id))
            
            if next_player_hand_empty:
                announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应 (手牌已空，只能 /质疑 或 /等待)"))
            else:
                announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应。请选择 /质疑 或 /出牌 <编号...>"))
            
            await self._reply_with_components(event, announcement_components)
            
            # 向出牌玩家发送手牌更新
            await self._send_hand_update(event, game_instance.game_id, player_id, game_instance.players[player_id].hand, game_instance.main_card)
            
            # 向下一位玩家发送手牌更新
            if not game_instance.players[next_player_id].is_eliminated:
                await self._send_hand_update(event, game_instance.game_id, next_player_id, game_instance.players[next_player_id].hand, game_instance.main_card)
        
        async def on_challenge_made(game_instance, **kwargs):
            challenger_id = kwargs.get('challenger_id')
            challenged_id = kwargs.get('challenged_id')
            actual_cards = kwargs.get('actual_cards')
            is_claim_true = kwargs.get('is_claim_true')
            loser_id = kwargs.get('loser_id')
            
            challenger_name = game_instance.players[challenger_id].name
            challenged_name = game_instance.players[challenged_id].name
            loser_name = game_instance.players[loser_id].name
            
            # 构建质疑消息
            challenge_message = (
                f"🤔 {challenger_name} 质疑 {challenged_name} 打出的牌是主牌【{game_instance.main_card}】！\n"
                f"亮牌结果: 【{' '.join(actual_cards)}】\n"
            )
            
            if is_claim_true:
                challenge_message += f"❌ 质疑失败！{challenged_name} 确实出的是主牌/鬼牌。{loser_name} 需要开枪！"
            else:
                challenge_message += f"✅ 质疑成功！{challenged_name} 没有完全打出主牌或鬼牌。{loser_name} 需要开枪！"
            
            await self._reply_text(event, challenge_message)
        
        async def on_player_shot(game_instance, **kwargs):
            player_id = kwargs.get('player_id')
            is_eliminated = kwargs.get('is_eliminated')
            
            player_name = game_instance.players[player_id].name
            
            if is_eliminated:
                await self._reply_text(event, f"{player_name} 扣动扳机... 砰！是【实弹】！{player_name} 被淘汰了！")
            else:
                await self._reply_text(event, f"{player_name} 扣动扳机... 咔嚓！是【空弹】！")
        
        async def on_player_waited(game_instance, **kwargs):
            player_id = kwargs.get('player_id')
            next_player_id = kwargs.get('next_player_id')
            next_player_hand_empty = kwargs.get('next_player_hand_empty')
            
            player_name = game_instance.players[player_id].name
            next_player_name = game_instance.players[next_player_id].name
            
            # 构建等待消息
            announcement_components = [
                Comp.Plain(text=f"{player_name} 手牌已空，选择等待。\n轮到 "),
                Comp.At(qq=next_player_id)
            ]
            
            # 根据下一位玩家手牌情况调整提示
            if next_player_hand_empty:
                if game_instance.last_play:
                    announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应 (手牌已空，只能 /质疑 或 /等待)"))
                else:
                    announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌 (手牌已空，只能 /等待)"))
            else:
                if game_instance.last_play:
                    announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 反应。请选择 /质疑 或 /出牌 <编号...>"))
                else:
                    announcement_components.append(Comp.Plain(text=f" ({next_player_name}) 出牌。请使用 /出牌 <编号...>"))
            
            await self._reply_with_components(event, announcement_components)
            
            # 向下一位玩家发送手牌更新
            if not game_instance.players[next_player_id].is_eliminated:
                await self._send_hand_update(event, game_instance.game_id, next_player_id, game_instance.players[next_player_id].hand, game_instance.main_card)
        
        async def on_next_turn(game_instance, **kwargs):
            player_id = kwargs.get('player_id')
            player_hand_empty = kwargs.get('player_hand_empty')
            
            player_name = game_instance.players[player_id].name
            
            # 构建下一轮消息
            next_turn_components = [
                Comp.Plain(text="轮到 "),
                Comp.At(qq=player_id)
            ]
            
            if player_hand_empty:
                if game_instance.last_play:
                    next_turn_components.append(Comp.Plain(text=f" ({player_name}) 反应 (手牌已空，只能 /质疑 或 /等待)"))
                else:
                    next_turn_components.append(Comp.Plain(text=f" ({player_name}) 出牌 (手牌已空，只能 /等待)"))
            else:
                if game_instance.last_play:
                    next_turn_components.append(Comp.Plain(text=f" ({player_name}) 反应。请选择 /质疑 或 /出牌 <编号...>"))
                else:
                    next_turn_components.append(Comp.Plain(text=f" ({player_name}) 出牌。请使用 /出牌 <编号...>"))
            
            await self._reply_with_components(event, next_turn_components)
            
            # 向玩家发送手牌更新
            if not game_instance.players[player_id].is_eliminated:
                await self._send_hand_update(event, game_instance.game_id, player_id, game_instance.players[player_id].hand, game_instance.main_card)
        
        async def on_reshuffled(game_instance, **kwargs):
            reason = kwargs.get('reason')
            main_card = kwargs.get('main_card')
            start_player_id = kwargs.get('start_player_id')
            
            # 发送手牌给所有活跃玩家
            pm_failed_players = []
            for player_id in game_instance.get_active_players():
                if not await self._send_hand_update(event, game_instance.game_id, player_id, game_instance.players[player_id].hand, main_card):
                    pm_failed_players.append(game_instance.players[player_id].name)
            
            # 构建重洗消息
            turn_order_display = []
            for p_id in game_instance.turn_order:
                p_name = game_instance.players[p_id].name
                status = " (淘汰)" if game_instance.players[p_id].is_eliminated else ""
                turn_order_display.append(f"{p_name}{status}")
            
            start_player_name = game_instance.players[start_player_id].name
            
            start_message_components = [
                Comp.Plain(text=f"🔄 新一轮开始 ({reason})！\n"
                          f"👑 新主牌: {main_card}\n"
                          f"📜 顺序: {', '.join(turn_order_display)}\n"
                          f"(新手牌已私信发送)\n"
                          f"👉 轮到 "),
                Comp.At(qq=start_player_id),
                Comp.Plain(text=f" ({start_player_name}) 出牌。")
            ]
            
            if pm_failed_players:
                start_message_components.append(Comp.Plain(text=f"\n\n注意：未能成功向以下玩家发送手牌私信：{', '.join(pm_failed_players)}。请检查机器人好友状态或私聊设置。"))
            
            await self._reply_with_components(event, start_message_components)
        
        async def on_game_ended(game_instance, **kwargs):
            winner_id = kwargs.get('winner_id')
            winner_name = kwargs.get('winner_name')
            forced = kwargs.get('forced', False)
            
            if forced:
                await self._reply_text(event, "当前群聊的骗子酒馆游戏已被强制结束。")
            else:
                await self._reply_text(event, f"🎉 游戏结束！胜者: {winner_name}！")
        
        # 注册所有回调
        game.register_callback(GameEvent.PLAYER_JOINED, on_player_joined)
        game.register_callback(GameEvent.GAME_STARTED, on_game_started)
        game.register_callback(GameEvent.CARDS_PLAYED, on_cards_played)
        game.register_callback(GameEvent.CHALLENGE_MADE, on_challenge_made)
        game.register_callback(GameEvent.PLAYER_SHOT, on_player_shot)
        game.register_callback(GameEvent.PLAYER_WAITED, on_player_waited)
        game.register_callback(GameEvent.NEXT_TURN, on_next_turn)
        game.register_callback(GameEvent.RESHUFFLED, on_reshuffled)
        game.register_callback(GameEvent.GAME_ENDED, on_game_ended)

    # --- 命令处理函数 ---
    @filter.command("骗子酒馆")
    async def create_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            await self._reply_text(event, "请在群聊中使用此命令")
            event.stop_event()
            return
        
        if group_id in self.games and self.games[group_id].state != GameState.ENDED:
            await self._reply_text(event, "本群已有一个骗子酒馆游戏正在进行中 (使用 /结束游戏 可强制结束)")
            event.stop_event()
            return
        
        # 创建新游戏实例
        game = LiarsTavernGame(group_id)
        self.games[group_id] = game
        
        # 注册事件回调
        self._register_game_callbacks(game, event)
        
        logger.info(f"[群{group_id}] 骗子酒馆 (左轮扑克模式) 游戏已创建")
        await self._reply_text(event, f"骗子酒馆开张了！\n➡️ 输入 /加入 参与 (至少 {game.config.MIN_PLAYERS} 人)。\n➡️ 发起者输入 /开始 启动游戏。\n\n📜 玩法: 轮流用 /出牌 编号 (1-3张) 声称是主牌，下家可 /质疑 或继续 /出牌。")
        event.stop_event()
        return

    @filter.command("加入")
    async def join_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        user_name = event.get_sender_name()
        
        if not group_id or not user_id:
            await self._reply_text(event, "无法识别命令来源")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game:
            await self._reply_text(event, "本群当前没有进行中的游戏")
            event.stop_event()
            return
        
        try:
            game.add_player(user_id, user_name)
            # 注意：加入成功的消息由事件回调处理
        except GameError as e:
            await self._reply_text(event, str(e))
        except InvalidPlayerError as e:
            await self._reply_text(event, str(e))
        except Exception as e:
            logger.error(f"加入游戏时发生错误: {e}", exc_info=True)
            await self._reply_text(event, f"加入游戏时发生错误: {e}")
        
        event.stop_event()
        return

    @filter.command("开始")
    async def start_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        if not group_id:
            await self._reply_text(event, "请在群聊中使用此命令")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game:
            await self._reply_text(event, "本群当前没有进行中的游戏")
            event.stop_event()
            return
        
        try:
            game.start_game()
            # 注意：游戏开始的消息由事件回调处理
        except GameError as e:
            await self._reply_text(event, str(e))
        except Exception as e:
            logger.error(f"开始游戏时发生错误: {e}", exc_info=True)
            await self._reply_text(event, f"开始游戏时发生错误: {e}")
        
        event.stop_event()
        return

    @filter.command("出牌")
    async def play_cards(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        player_id = self._get_user_id(event)
        
        if not group_id or not player_id:
            await self._reply_text(event, "无法识别命令来源")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game or game.state != GameState.PLAYING:
            await self._reply_text(event, "现在不是进行游戏的时间")
            event.stop_event()
            return
        
        # 解析参数
        try:
            if not hasattr(event, 'message_str'):
                logger.error("事件对象缺少 message_str 属性！")
                await self._reply_text(event, "无法解析命令参数。")
                event.stop_event()
                return
            
            args_text = event.message_str.strip()
            indices_1based_str = re.findall(r'\d+', args_text)
            
            if not indices_1based_str:
                raise ValueError("请用 /出牌 编号 [编号...] (例: /出牌 1 3)")
            
            indices_1based = [int(idx_str) for idx_str in indices_1based_str]
            
            # 执行出牌
            game.play_cards(player_id, indices_1based)
            # 注意：出牌结果的消息由事件回调处理
            
        except ValueError as e:
            await self._reply_text(event, f"❌ 命令错误: {e}\n👉 请用 /出牌 编号 [编号...] (例: /出牌 1 3)")
        except InvalidPlayerError as e:
            await self._reply_text(event, f"❌ {e}")
        except InvalidActionError as e:
            await self._reply_text(event, f"❌ {e}")
        except GameError as e:
            await self._reply_text(event, f"❌ {e}")
        except Exception as e:
            logger.error(f"处理出牌命令时发生错误: {e}", exc_info=True)
            await self._reply_text(event, f"❌ 处理出牌命令时发生内部错误，请检查日志或联系管理员。")
        
        event.stop_event()
        return

    @filter.command("质疑")
    async def challenge_play(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        challenger_id = self._get_user_id(event)
        
        if not group_id or not challenger_id:
            await self._reply_text(event, "❌ 无法识别命令来源")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game or game.state != GameState.PLAYING:
            await self._reply_text(event, "现在不是进行游戏的时间")
            event.stop_event()
            return
        
        try:
            game.challenge(challenger_id)
            # 注意：质疑结果的消息由事件回调处理
        except InvalidPlayerError as e:
            await self._reply_text(event, f"❌ {e}")
        except InvalidActionError as e:
            await self._reply_text(event, f"❌ {e}")
        except GameError as e:
            await self._reply_text(event, f"❌ {e}")
        except Exception as e:
            logger.error(f"处理质疑命令时发生错误: {e}", exc_info=True)
            await self._reply_text(event, f"❌ 处理质疑命令时发生内部错误，请检查日志或联系管理员。")
        
        event.stop_event()
        return

    @filter.command("等待")
    async def wait_turn(self, event: AstrMessageEvent):
        """处理玩家选择等待的操作 (仅限手牌为空时)"""
        group_id = self._get_group_id(event)
        player_id = self._get_user_id(event)
        
        if not group_id or not player_id:
            await self._reply_text(event, "无法识别命令来源")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game or game.state != GameState.PLAYING:
            await self._reply_text(event, "现在不是进行游戏的时间")
            event.stop_event()
            return
        
        try:
            game.wait_turn(player_id)
            # 注意：等待结果的消息由事件回调处理
        except InvalidPlayerError as e:
            await self._reply_text(event, f"❌ {e}")
        except InvalidActionError as e:
            await self._reply_text(event, f"❌ {e}")
        except GameError as e:
            await self._reply_text(event, f"❌ {e}")
        except Exception as e:
            logger.error(f"处理等待命令时发生错误: {e}", exc_info=True)
            await self._reply_text(event, f"❌ 处理等待命令时发生内部错误，请检查日志或联系管理员。")
        
        event.stop_event()
        return

    @filter.command("状态")
    async def game_status(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        
        if not group_id:
            await self._reply_text(event, "请在群聊中使用此命令")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game or game.state == GameState.ENDED:
            await self._reply_text(event, "本群当前没有进行中的骗子酒馆游戏")
            event.stop_event()
            return
        
        if game.state == GameState.WAITING:
            player_list = "\n".join([f"- {player.name}" for player in game.players.values()]) or "暂无玩家加入"
            await self._reply_text(event, f"⏳ 游戏状态: 等待中\n玩家 ({len(game.players)}人):\n{player_list}\n\n➡️ 发起者输入 /开始 (至少 {game.config.MIN_PLAYERS} 人)")
            event.stop_event()
            return
        
        # 获取游戏状态信息
        status = game.get_game_status()
        
        # 构建状态消息
        status_components = [
            Comp.Plain(text=f"游戏状态：进行中\n主牌: 【{game.main_card}】\n出牌顺序: {', '.join([game.players[pid].name for pid in game.turn_order])}\n当前轮到: ")
        ]
        
        if 'current_player' in status:
            status_components.append(Comp.At(qq=status['current_player']['id']))
            status_components.append(Comp.Plain(text=f" ({status['current_player']['name']})"))
        else:
            status_components.append(Comp.Plain(text="未知"))
        
        # 玩家状态
        player_statuses = []
        for pid, pdata in status['players'].items():
            player_statuses.append(f"- {pdata['name']}: {'淘汰' if pdata['is_eliminated'] else str(pdata['hand_size']) + '张牌'}")
        
        # 上一轮出牌信息
        last_play_text = "无"
        if 'last_play' in status:
            last_player_name = status['last_play']['player_name']
            claimed_quantity = status['last_play']['claimed_quantity']
            last_play_text = f"{last_player_name} 声称打出 {claimed_quantity} 张主牌【{game.main_card}】"
            if 'current_player' in status:
                last_play_text += f" (等待 {status['current_player']['name']} 反应)"
        
        status_components.extend([
            Comp.Plain(text=f"\n--------------------\n玩家状态:\n" + "\n".join(player_statuses) + "\n"
                          f"--------------------\n等待处理的出牌: {last_play_text}\n"
                          f"弃牌堆: {len(game.discard_pile)}张 | 牌堆剩余: 约{len(game.deck)}张")
        ])
        
        # 如果是当前玩家查询，显示手牌
        if user_id and user_id in game.players and not game.players[user_id].is_eliminated:
            my_hand = game.players[user_id].hand
            my_hand_display = self.message_formatter.format_hand_for_display(my_hand)
            status_components.append(Comp.Plain(text=f"\n--------------------\n你的手牌: {my_hand_display}"))
        
        await self._reply_with_components(event, status_components)
        event.stop_event()
        return

    @filter.command("我的手牌")
    async def show_my_hand(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        user_id = self._get_user_id(event)
        
        if not group_id or not user_id:
            await self._reply_text(event, "无法识别命令来源")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if not game or game.state != GameState.PLAYING:
            await self._reply_text(event, "现在不是进行游戏的时间")
            event.stop_event()
            return
        
        if user_id not in game.players or game.players[user_id].is_eliminated:
            await self._reply_text(event, "你不在游戏中或已被淘汰。")
            event.stop_event()
            return
        
        my_hand = game.players[user_id].hand
        main_card = game.main_card
        
        # 使用手牌更新方法
        success = await self._send_hand_update(event, group_id, user_id, my_hand, main_card)
        if success:
            await self._reply_text(event, "已通过私信将你的手牌发送给你，请查收。")
        else:
            # 如果私聊失败，则在群里回复（注意隐私风险）
            my_hand_display = self.message_formatter.format_hand_for_display(my_hand)
            await self._reply_text(event, f"你的手牌: {my_hand_display}\n本轮主牌: 【{main_card}】\n(私信发送失败，已在群内显示)")
        
        event.stop_event()
        return

    @filter.command("结束游戏")
    async def force_end_game(self, event: AstrMessageEvent):
        group_id = self._get_group_id(event)
        
        if not group_id:
            await self._reply_text(event, "请在群聊中使用此命令")
            event.stop_event()
            return
        
        game = self.games.get(group_id)
        if game:
            game.force_end()
            # 游戏结束的消息由事件回调处理
            
            # 清理游戏实例
            if game.state == GameState.ENDED:
                del self.games[group_id]
        else:
            await self._reply_text(event, "本群当前没有进行中的骗子酒馆游戏。")
        
        event.stop_event()
        return

    async def terminate(self):
        logger.info("骗子酒馆插件卸载/停用，清理所有游戏数据...")
        
        # 强制结束所有游戏
        for group_id, game in list(self.games.items()):
            game.force_end()
        
        self.games = {}
        logger.info("所有游戏数据已清理")
