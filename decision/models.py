"""
决策器数据模型
"""

from dataclasses import dataclass, field
from typing import List, Optional, Callable, Any
from enum import Enum
import time


class DecisionState(str, Enum):
    """决策器状态枚举"""
    IDLE = "idle"           # 空闲，等待触发
    WAITING_P = "waiting_p" # 提及等待期（P秒倒计时）
    EXECUTING = "executing" # 决策执行中
    WAITING_R = "waiting_r" # 决策完成，等待R秒冷却


@dataclass
class MessageEvent:
    """消息事件（简化版，与 OneBot 事件对应）"""
    group_id: int
    user_id: int
    message: str
    message_id: int
    time: float = field(default_factory=time.time)
    # 可以扩展其他字段


@dataclass
class DecisionAction:
    """
    决策动作
    决策器应该返回此类或其子类的实例，表示要执行的动作
    """
    action_type: str  # "reply" | "no_reply" | "enter_talk_mode" | "exit_talk_mode" ...


@dataclass
class ReplyAction(DecisionAction):
    """回复动作"""
    action_type: str = "reply"
    reply_text: str = ""
    at_user: bool = False  # 是否要 @ 用户


@dataclass
class NoReplyAction(DecisionAction):
    """不回复动作"""
    action_type: str = "no_reply"


@dataclass
class EnterTalkModeAction(DecisionAction):
    """进入话题模式动作"""
    action_type: str = "enter_talk_mode"


@dataclass
class ExitTalkModeAction(DecisionAction):
    """退出话题模式动作"""
    action_type: str = "exit_talk_mode"


@dataclass
class DecisionResult:
    """
    单条消息的决策结果
    包含：动作类型 + 附加信息
    """
    action: DecisionAction
    # 可以扩展：reason（决策原因，用于调试）


@dataclass
class DecisionContext:
    """
    单个聊天会话的决策上下文
    每个群（或私聊）独立一个 DecisionContext
    """
    group_id: int

    # 消息队列
    pending_messages: List[MessageEvent] = field(default_factory=list)

    # 时间跟踪
    last_decision_time: float = 0          # 上次决策完成时间戳
    mention_time: float = 0                 # 最后一次提及时间戳
    state: DecisionState = DecisionState.IDLE

    # 异步控制
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    mention_timer_task: Optional[asyncio.Task] = None
    waiting_r_task: Optional[asyncio.Task] = None

    # 当前模式（peek 或 talk），由外部在 on_message 时设置
    current_mode: str = "peek"

    # 配置参数（会在初始化时从全局配置填充）
    M: int = 10    # 窥屏模式：消息数量阈值
    N: int = 40    # 窥屏模式：时间阈值（秒）
    m: int = 3     # 话题模式：消息数量阈值
    n: int = 10    # 话题模式：时间阈值（秒）
    P: int = 3     # 提及等待时间（秒）
    R: int = 2     # 决策后等待时间（秒）
    bot_name: str = "Anna"  # 机器人名字（用于提及检测）

    def reset(self):
        """重置上下文（用于模式切换或清理）"""
        self.pending_messages.clear()
        self.last_decision_time = 0
        self.mention_time = 0
        self.state = DecisionState.IDLE
        if self.mention_timer_task:
            self.mention_timer_task.cancel()
            self.mention_timer_task = None
        if self.waiting_r_task:
            self.waiting_r_task.cancel()
            self.waiting_r_task = None


# 类型别名：决策函数
# 输入：消息列表 + 上下文
# 输出：每条消息对应的 DecisionResult 列表
DecisionFunction = Callable[[List[MessageEvent], DecisionContext], Any]
