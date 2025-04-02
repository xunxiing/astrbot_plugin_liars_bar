*开发文档 (基于 v2.1.7 代码)**


# 骗子酒馆 (左轮扑克模式) AstrBot 插件 - 开发文档

**版本:** 2.1.7

## 1. 简介

本插件是为 AstrBot 框架开发的游戏插件，实现了一个骗子酒馆。

**核心玩法:**

*   玩家轮流出牌（1-3张），并声称这些牌是当前回合的“主牌”。
*   下一位玩家可以选择“质疑”上一家的出牌，或者继续出牌。
*   质疑时，亮出实际牌面：
    *   若上一家确实出的都是主牌或鬼牌 (Joker)，则质疑者输，需“开枪”。
    *   若上一家“吹牛”了（出的牌不全是主牌或鬼牌），则上一家输，需“开枪”。
*   “开枪”：从一个装有少量实弹（默认为1发）和若干空弹的左轮手枪中随机抽取一发。抽中实弹者淘汰。
*   游戏持续进行，直到只剩下一名玩家存活。

**技术栈:**

*   Python 3
*   AstrBot 框架
*   OneBot v11 协议 (通过 AstrBot 的适配器，如 aiocqhttp)

## 2. 文件结构

主要代码逻辑均包含在 `main.py` 文件中。

*   `main.py`: 包含插件主类、所有游戏逻辑、命令处理函数和辅助函数。
*   `metadata.yaml` (可选但推荐): 定义插件的元数据，如名称、作者、描述、版本等，用于插件市场展示。
*   `requirements.txt` (如果需要): 列出插件依赖的第三方 Python 库。

## 3. 核心概念

### 3.1. 插件类 `LiarsPokerPlugin(Star)`

*   继承自 `astrbot.api.star.Star`。
*   通过 `@register(...)` 装饰器向 AstrBot 注册插件信息。
*   `__init__(self, context: Context)`: 初始化插件，最重要的是创建用于存储游戏状态的字典 `self.games`。`context` 对象可用于访问 AstrBot 的其他组件（本插件未使用）。
*   `async def terminate(self)`: (可选) 定义插件卸载或停用时执行的清理操作，例如清空 `self.games`。

### 3.2. 游戏状态管理 (`self.games`)

*   `self.games` 是一个字典，用于存储不同群聊的游戏实例。
*   键 (Key): 群聊 ID (字符串格式)。
*   值 (Value): 另一个字典，表示该群聊当前的游戏状态。

**单个游戏状态字典结构:**

```python
{
    "status": str,  # 游戏当前状态: "waiting", "playing", "ended"
    "players": Dict[str, Dict], # 参与玩家的信息字典 (键: 玩家QQ ID字符串)
    "deck": List[str], # 当前牌堆剩余的牌
    "main_card": str | None, # 本轮游戏的主牌 ("Q", "K", "A")
    "turn_order": List[str], # 玩家出牌顺序 (QQ ID 列表)
    "current_player_index": int, # 当前轮到行动的玩家在 turn_order 中的索引
    "last_play": Dict | None, # 上一次出牌的信息，用于质疑
    "discard_pile": List[str] # 弃牌堆
}
```

**玩家信息字典结构 (`game["players"][player_id]`)**

```python
{
    "name": str, # 玩家昵称
    "hand": List[str], # 玩家当前手牌
    "gun": List[str], # 玩家的左轮手枪弹膛状态 ("实弹", "空弹" 列表)
    "gun_position": int, # 当前子弹在弹膛中的位置索引
    "is_eliminated": bool # 玩家是否已被淘汰
}
```

### 3.3. 事件处理与命令

*   使用 `@filter.command("命令名称")` 装饰器注册命令处理函数。
*   处理函数必须是 `async def`，并且通常接受 `self` 和 `event: AstrMessageEvent` 两个参数。
*   `event` 对象包含了触发事件的所有信息（发送者、群组、消息内容等）。
*   **事件传播控制:** 为了防止插件处理完命令后，事件继续传递给 LLM 导致意外回复，本插件在所有命令处理函数中，凡是进行了回复 (调用 `_reply_text` 或 `_reply_with_components`) 的地方，都显式调用了 `event.stop_event()` 并 `return`。

### 3.4. 消息发送

*   **`_reply_text(self, event, text)`:** 发送纯文本回复。
*   **`_reply_with_components(self, event, components)`:** 发送包含 AstrBot 消息组件（如 `Comp.Plain`, `Comp.At`）的回复。
*   **`_send_group_message_comp(self, event, group_id, components)`:** 底层函数，将 AstrBot 组件列表转换为 OneBot v11 格式并发送。
*   **`_convert_astr_comps_to_onebot(self, components)`:** 将 AstrBot 组件列表转换为 OneBot v11 消息段列表。
*   **`_send_private_message_text(self, event, user_id, text)`:** 发送私聊消息。

## 4. 主要函数说明

### 4.1. 命令处理函数

*   `create_game(event)`: 处理 `/骗子酒馆`，创建新游戏。
*   `join_game(event)`: 处理 `/加入`，玩家加入等待中的游戏。
*   `start_game(event)`: 处理 `/开始`，初始化牌堆（动态小丑牌）、发牌、确定顺序、发送开始消息并 `@` 第一个玩家。
*   `play_cards(event)`: 处理 `/出牌 <编号...>`，解析参数、验证手牌、执行出牌、更新状态、发送提示并 `@` 下一个玩家。
*   `challenge_play(event)`: 处理 `/质疑`，验证质疑、亮牌、判断输赢、调用 `take_shot`、更新状态、发送提示并 `@` 下一个玩家。
*   `game_status(event)`: 处理 `/状态`，查询并回复当前游戏详细状态，包括 `@` 当前玩家。
*   `show_my_hand(event)`: 处理 `/我的手牌`，回复玩家当前手牌（带编号）。
*   `force_end_game(event)`: 处理 `/结束游戏`，强制删除当前群的游戏状态。

### 4.2. 核心逻辑函数

*   `_build_deck(player_count)`: 根据玩家数量动态计算小丑牌数量 (player_count // 2)，并构建牌堆。
*   `_deal_cards(deck, player_ids, game_players)`: 洗牌并发牌给所有玩家。
*   `take_shot(event, group_id, player_id)`: 执行“开枪”逻辑，判断是否命中实弹，更新玩家状态，回复结果，并检查游戏是否结束。
*   `_check_challenge(actual_cards, main_card)`: 判断一次出牌相对主牌是否“诚实”（全是主牌或鬼牌）。
*   `_check_game_end(event, group_id, game)`: 检查当前活跃玩家数量，判断游戏是否结束，如果结束则发送结束消息并停止事件。
*   `_get_next_player_index(game)`: 根据当前玩家索引和淘汰状态，找到下一个应该行动的玩家的索引。

### 4.3. 辅助函数

*   `_get_group_id(event)` / `_get_user_id(event)` / `_get_bot_instance(event)`: 从事件中获取必要信息。
*   `_format_hand_for_display(hand)`: 将手牌列表格式化为带编号的字符串，如 `[1:Q] [2:K]`。

## 5. 游戏逻辑流程

1.  **创建:** 玩家 A 发送 `/骗子酒馆` -> `create_game` -> 初始化游戏状态 `status="waiting"` -> 回复创建成功信息 -> `stop_event()`。
2.  **加入:** 玩家 B, C 发送 `/加入` -> `join_game` -> 验证状态 -> 将玩家加入 `game["players"]` -> 回复加入成功信息 -> `stop_event()`。
3.  **开始:** 任意玩家发送 `/开始` -> `start_game` -> 验证人数 -> 调用 `_build_deck(人数)` -> 调用 `_deal_cards` -> 发私信手牌 -> 确定顺序 `turn_order` -> 设置 `status="playing"` -> 回复开始信息并 `@` 第一个玩家 -> `stop_event()`。
4.  **出牌:** 轮到的玩家发送 `/出牌 <编号...>` -> `play_cards` -> 验证轮次 -> 解析编号 -> 验证手牌 -> 移除手牌 -> 更新 `game["last_play"]` -> 调用 `_get_next_player_index` 更新 `current_player_index` -> 回复出牌信息并 `@` 下一个玩家 -> `stop_event()`。
5.  **质疑:** 轮到的玩家发送 `/质疑` -> `challenge_play` -> 验证轮次 -> 获取 `game["last_play"]` -> 调用 `_check_challenge` 判断真伪 -> 回复亮牌结果和质疑结果 -> 确定输家 -> 调用 `take_shot(输家)` -> 如果游戏未结束，确定下一个出牌者（质疑者或其后继）并 `@` 提示 -> `stop_event()`。
6.  **不质疑 (跟牌):** 轮到的玩家直接发送 `/出牌 <编号...>` -> `play_cards` -> (同步骤4，但在执行出牌前会将 `game["last_play"]` 中的牌加入弃牌堆)。
7.  **开枪:** `take_shot` 被调用 -> 判断弹膛 -> 回复开枪结果 (`空弹` 或 `实弹+淘汰`) -> 如果淘汰，调用 `_check_game_end`。
8.  **游戏结束检查:** `_check_game_end` 被调用 -> 计算活跃玩家数 -> 如果 <= 1，设置 `status="ended"`，回复获胜者信息 -> `stop_event()`。
9.  **重复 4-8** 直到游戏结束。

## 6. 维护与扩展

*   **调试:** 主要依靠 `logging` 模块输出日志进行调试。可以在关键函数入口、分支、发送消息前等位置添加 `logger.info()` 或 `logger.debug()`。
*   **常见问题:**
    *   **LLM 干扰:** 确保所有命令处理函数在回复后都调用 `event.stop_event()`。
    *   **`@` 不生效:** 检查 OneBot 实现的日志和配置，确认发送的消息段格式是否正确。
    *   **API 变更:** AstrBot 或 OneBot API 更新可能导致函数或属性失效，需要根据错误日志和官方文档进行调整。
*   **扩展方向:**
    *   **更灵活的命令:** 使用 `@filter.startswith` 或正则表达式支持 `出牌 1` 等无斜杠命令（需注意潜在冲突）。
    *   **不同游戏模式:** 调整牌堆构成、手牌数量、开枪规则等。
    *   **计分系统:** 记录玩家胜负或积分。
    *   **更丰富的交互:** 使用图片或更复杂的 UI（如果平台和适配器支持）。
    *   **国际化/本地化:** 将提示文本提取为可配置项。

## 7. 常量说明

*   `CARD_TYPES`: 定义了基础牌面。
*   `JOKER`: 定义了鬼牌的名称。
*   `VALID_CARDS`: 所有有效牌面名称列表，用于验证。
*   `CARDS_PER_TYPE`: 每种基础牌的数量。
*   `HAND_SIZE`: 初始手牌数量。
*   `GUN_CHAMBERS`: 左轮弹膛数量。
*   `LIVE_BULLETS`: 实弹数量。
*   `MIN_PLAYERS`: 开始游戏所需的最少玩家数。
```

希望这份开发文档能帮助你或其他维护者理解和修改这个插件！
