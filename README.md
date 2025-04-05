## AstrBot 插件：骗子酒馆助手 (liar_tavern) - 开发维护文档

**版本:** 2.1.9 (与 `main.py` 和 `metadata.yaml` 中的版本对应)
**作者:** xunxi (请根据实际情况修改)
**仓库:** [https://github.com/xunxiing/astrbot_plugin_liars_bar](https://github.com/xunxiing/astrbot_plugin_liars_bar) (请根据实际情况修改)

### 1. 插件概述

本插件实现了一个基于 AstrBot 框架的群聊游戏，名为“骗子酒馆”。其核心玩法融合了“骗子骰”的吹牛机制和“俄罗斯轮盘”的惩罚机制：

*   **核心机制**: 玩家轮流打出手牌（扑克牌 Q, K, A, Joker），并声称打出的是指定数量的“主牌”（每轮随机指定 Q, K, A 中的一种）。
*   **质疑**: 下家可以选择相信并继续出牌，或者选择“质疑”上家的出牌。
*   **惩罚**: 如果质疑失败（上家确实打出了主牌或鬼牌），质疑者需要“开枪”（模拟左轮手枪，内含配置数量的实弹和空弹）；如果质疑成功（上家撒谎），则上家开枪。
*   **淘汰**: 被“实弹”击中的玩家被淘汰。
*   **胜利**: 游戏持续进行，直到只剩下一名玩家存活。
*   **特殊情况**: 玩家手牌为空时，轮到他时只能选择“质疑”或“等待”。所有活跃玩家手牌都为空，或有玩家被淘汰时，会触发重新洗牌和发牌。

### 2. 项目结构

插件主要包含以下文件：

```
liar_tavern/
├── main.py             # 插件核心逻辑，包含 Star 类和所有游戏处理函数
├── _conf_schema.json   # 定义插件配置项的 Schema，供 AstrBot WebUI 生成配置界面
├── metadata.yaml       # 插件元数据 (名称, 作者, 版本, 描述等)，供 AstrBot 识别和市场展示
└── requirements.txt    # (可选) 插件的 Python 依赖库列表
```

### 3. 安装与设置

1.  **放置插件**: 将整个 `liar_tavern` 文件夹放置于 AstrBot 安装目录下的 `data/plugins/` 文件夹内。
2.  **安装依赖**: (如果 `requirements.txt` 文件存在且包含内容) 在 AstrBot 环境下执行 `pip install -r data/plugins/liar_tavern/requirements.txt`。
3.  **重启 AstrBot**: 完全停止并重新启动 AstrBot 服务以加载插件。
4.  **配置插件**:
    *   访问 AstrBot Web 管理面板。
    *   导航到“插件管理”部分。
    *   找到“骗子酒馆助手”插件，点击“管理”。
    *   根据界面提示配置“左轮手枪中的空弹数量”。

### 4. 配置说明 (`_conf_schema.json`)

本插件通过 `_conf_schema.json` 文件定义配置项，允许用户通过 WebUI 自定义。

```json
{
  "empty_bullet_count": {
    "type": "int",
    "description": "左轮手枪中的空弹数量",
    "default": 4,
    "hint": "请输入 0 到 5 之间的整数。弹巢总数为 6，插件会确保至少有1发实弹。"
  }
}
```

*   **`empty_bullet_count`**:
    *   **类型 (`type`)**: `int` (整数)
    *   **描述 (`description`)**: 在 WebUI 中显示的配置项名称/标签。
    *   **默认值 (`default`)**: `4` (如果用户未配置，则使用此值)。
    *   **提示 (`hint`)**: 在 WebUI 中显示的额外说明信息。

**在代码中访问配置**:

AstrBot 框架在初始化插件类 `LiarsPokerPlugin` 时，会将包含用户配置（或默认值）的 `AstrBotConfig` 对象传入 `__init__` 方法。代码通过 `self.config.get("empty_bullet_count", fallback_default)` 来获取配置值。

```python
# main.py
from astrbot.api import AstrBotConfig

class LiarsPokerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config # 保存配置对象
        # ...

    def _initialize_gun(self):
        try:
            # 从 self.config 获取配置值
            config_empty_bullets = int(self.config.get("empty_bullet_count", 4))
            # ... 后续处理 ...
        except Exception as e:
            # ... 错误处理 ...
```

### 5. 核心代码逻辑 (`main.py`)

`main.py` 文件包含了 `LiarsPokerPlugin` 类，继承自 `astrbot.api.star.Star`。

**5.1. 主要数据结构**

*   **`self.games: Dict[str, Dict]`**: 存储当前所有正在进行的游戏。
    *   **键**: 群组 ID (`group_id`)。
    *   **值**: 一个字典，包含该群组的游戏状态和数据：
        *   `status`: 游戏状态 (`"waiting"`, `"playing"`, `"ended"`)。
        *   `players`: 存储玩家数据的字典 (键: `user_id`, 值: 玩家信息字典)。
            *   `name`: 玩家昵称。
            *   `hand`: 玩家当前手牌 (List[str])。
            *   `gun`: 玩家的左轮手枪弹巢 (List["实弹" | "空弹"])。
            *   `gun_position`: 当前待击发的弹巢位置 (int)。
            *   `is_eliminated`: 玩家是否已被淘汰 (bool)。
        *   `deck`: 当前牌堆 (List[str]) - **注意：实际游戏中牌是分散在玩家手中和弃牌堆的，此字段可能用处不大或在重洗时临时使用**。
        *   `main_card`: 当前回合的主牌 (`"Q"`, `"K"`, or `"A"`).
        *   `turn_order`: 玩家出牌顺序 (List[`user_id`])。
        *   `current_player_index`: 当前轮到出牌/反应的玩家在 `turn_order` 中的索引 (int)。
        *   `last_play`: 上一个玩家的出牌信息 (Dict)，用于质疑。包含 `player_id`, `claimed_quantity`, `actual_cards`。
        *   `discard_pile`: 弃牌堆 (List[str])。

**5.2. 关键方法**

*   **`__init__(self, context: Context, config: AstrBotConfig)`**: 初始化插件，加载配置，初始化 `self.games`。
*   **`_initialize_gun(self)`**: 根据 `self.config` 中的 `empty_bullet_count` 创建并随机化弹巢内容，确保至少有一发实弹。
*   **`_build_deck(self, player_count: int)`**: 根据玩家数量创建初始牌堆（包含 QKA 和动态数量的 Joker）。
*   **`_determine_main_card(self)`**: 随机选择 Q, K, A 中的一种作为主牌。
*   **`_deal_cards(self, deck, player_ids, game_players)`**: 洗牌并发牌给所有玩家。
*   **`create_game(self, event)`**: (`/骗子酒馆`) 命令处理函数，创建新游戏。
*   **`join_game(self, event)`**: (`/加入`) 命令处理函数，玩家加入等待中的游戏，并初始化该玩家的枪。
*   **`start_game(self, event)`**: (`/开始`) 命令处理函数，开始游戏，确定主牌、顺序，发牌，并通知玩家。
*   **`play_cards(self, event)`**: (`/出牌`) 命令处理函数，处理玩家出牌逻辑，验证手牌，更新状态，通知下一位玩家。
*   **`challenge_play(self, event)`**: (`/质疑`) 命令处理函数，处理质疑逻辑，亮牌，判断输赢，调用 `take_shot`。
*   **`wait_turn(self, event)`**: (`/等待`) 命令处理函数，处理玩家手牌为空时选择等待的操作。
*   **`take_shot(self, event, group_id, player_id)`**: 处理开枪逻辑，判断子弹类型，更新玩家状态（可能淘汰），检查游戏是否结束，如果有人淘汰且游戏未结束则调用 `_reshuffle_and_redeal`。
*   **`_check_challenge(self, actual_cards, main_card)`**: 判断上家打出的牌是否符合声称（全是主牌或 Joker）。
*   **`_check_game_end(self, event, group_id, game)`**: 检查活跃玩家数量，判断游戏是否结束，并宣布胜利者。
*   **`_reshuffle_and_redeal(self, event, group_id, game, reason, eliminated_player_id=None)`**: 核心重置逻辑，在玩家淘汰或所有活跃玩家手牌为空时触发。收集所有牌（手牌+弃牌堆），重新洗牌，重新发牌，确定新主牌和下一轮的起始玩家。
*   **`_check_and_handle_all_hands_empty(self, event, group_id, game)`**: 检查是否所有活跃玩家手牌都为空，如果是则触发重洗。
*   **`game_status(self, event)`**: (`/状态`) 命令处理函数，显示当前游戏状态。
*   **`show_my_hand(self, event)`**: (`/我的手牌`) 命令处理函数，私信发送玩家手牌。
*   **`force_end_game(self, event)`**: (`/结束游戏`) 命令处理函数，强制结束当前群组的游戏。
*   **`terminate(self)`**: 插件卸载或停用时调用，清理 `self.games`。
*   **辅助函数**: 如 `_get_group_id`, `_get_user_id`, `_reply_text`, `_reply_with_components`, `_send_private_message_text`, `_send_hand_update` 等，用于简化代码和与 AstrBot API 交互。

### 6. 如何维护和扩展

*   **修改游戏规则**:
    *   调整牌的数量/类型: 修改 `CARD_TYPES`, `CARDS_PER_TYPE`, `JOKER` 相关逻辑（主要在 `_build_deck`）。
    *   调整手牌数量/弹巢大小: 修改 `HAND_SIZE`, `GUN_CHAMBERS` 常量。
    *   修改获胜/失败条件: 修改 `_check_game_end`, `take_shot`。
    *   修改质疑逻辑: 修改 `_check_challenge`, `challenge_play`。
*   **添加新的配置项**:
    1.  在 `_conf_schema.json` 中添加新的配置项定义。
    2.  在 `main.py` 中需要使用该配置的地方，通过 `self.config.get("new_config_name", default_value)` 获取。
    3.  确保在相关逻辑（如 `_initialize_gun`, `start_game` 日志等）中使用新的配置值。
*   **添加新指令**:
    1.  在 `LiarsPokerPlugin` 类中定义一个新的 `async def` 方法。
    2.  使用 `@filter.command("新指令名")` 装饰器注册该方法。
    3.  在新方法中实现指令逻辑，使用 `event` 对象获取信息，并通过 `_reply_text` 或 `_reply_with_components` 回复用户。
    4.  记得在方法结束时调用 `event.stop_event()` (如果不想让事件继续传递)。
*   **修改回复文本**: 查找并修改调用 `_reply_text`, `_reply_with_components`, `_send_private_message_text` 的地方，以及 `_send_hand_update` 中的消息文本。
*   **调试**:
    *   查看 AstrBot 控制台或日志文件中的 `logger.info`, `logger.warning`, `logger.error` 输出。
    *   在关键位置添加 `logger.debug(...)` 或 `print()` 语句进行调试。
    *   修改代码后，在 AstrBot WebUI 中“重载插件”通常可以生效，但修改 `_conf_schema.json` 或 `metadata.yaml` 后**必须完全重启 AstrBot**。

### 7. 注意事项

*   **文件编码**: 所有 `.py`, `.json`, `.yaml` 文件必须保存为 **UTF-8 (无 BOM)** 编码，否则可能导致加载失败或乱码。
*   **AstrBot 版本**: 当前配置系统 (`_conf_schema.json`) 依赖 AstrBot v3.4.15 或更高版本。
*   **异步编程**: 插件中的大部分 IO 操作（如发送消息）都是异步的，需要使用 `async` 和 `await`。
*   **错误处理**: 代码中已包含一些基本的 `try...except` 块，但可能需要根据实际运行情况补充更健壮的错误处理。
*   **状态管理**: 游戏状态完全存储在内存中的 `self.games` 字典里。如果 AstrBot 重启，所有进行中的游戏都会丢失。如果需要持久化，需要引入数据库或其他存储机制。
