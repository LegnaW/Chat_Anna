"""
批量决策调度器 - 核心逻辑实现
不包含具体的决策逻辑（如 LLM 调用），只管理触发时机、状态流转、消息队列
"""

import asyncio
import logging
import time
from typing import List, Optional, Callable
from .models import (
    MessageEvent,
    DecisionResult,
    DecisionContext,
    DecisionState,
    DecisionAction,
    DecisionFunction,
    EnterTalkModeAction,
    ExitTalkModeAction
)

logger = logging.getLogger(__name__)


# 动作执行器类型别名
# 输入：事件、动作、上下文
# 输出：None（执行可能失败，但通过异常或日志处理）
ActionExecutor = Callable[[MessageEvent, DecisionAction, DecisionContext], None]


class BatchDecisionScheduler:
    """
    批量决策调度器

    核心职责：
    1. 管理每个群的 DecisionContext（状态、队列、时间）
    2. 根据三个触发条件（数量、时间、提及）决定是否触发决策
    3. 维护状态机（IDLE → WAITING_P/EXECUTING → WAITING_R → IDLE）
    4. 保证单线程串行（一个会话同时只执行一个决策）
    5. 调用外部决策函数（占位符），获取决策结果
    6. 执行动作（通过 action_executor 回调）

    使用方式：
        scheduler = BatchDecisionScheduler(make_decision, execute_action)
        # 在 WebSocket handler 中：
        await scheduler.on_message(event, group_id, current_mode)
    """

    def __init__(
        self,
        make_decision_fn: DecisionFunction,
        action_executor: Optional[ActionExecutor] = None,
        default_config: Optional[dict] = None
    ):
        """
        初始化调度器

        Args:
            make_decision_fn: 决策函数，签名为：
                async def make_decision(messages: List[MessageEvent], ctx: DecisionContext)
                -> List[DecisionResult]
                这个函数由外部实现，包含归属识别 + LLM 决策等具体逻辑

            action_executor: 动作执行器，签名为：
                async def execute_action(event, action, ctx)
                根据 DecisionAction 的类型执行实际操作（发送消息、切换模式等）
                如果为 None，则只打印日志不执行

            default_config: 默认配置字典，包含 M, N, m, n, P, R, bot_name
        """
        self.make_decision = make_decision_fn
        self.action_executor = action_executor
        self.contexts: dict[int, DecisionContext] = {}  # group_id -> context
        self.default_config = default_config or {}

        # 全局配置默认值
        self.default_M = self.default_config.get("M", 10)
        self.default_N = self.default_config.get("N", 40)
        self.default_m = self.default_config.get("m", 3)
        self.default_n = self.default_config.get("n", 10)
        self.default_P = self.default_config.get("P", 3)
        self.default_R = self.default_config.get("R", 2)
        self.default_bot_name = self.default_config.get("bot_name", "Anna")

    def get_context(self, group_id: int) -> DecisionContext:
        """获取或创建群的决策上下文"""
        if group_id not in self.contexts:
            self.contexts[group_id] = DecisionContext(
                group_id=group_id,
                M=self.default_M,
                N=self.default_N,
                m=self.default_m,
                n=self.default_n,
                P=self.default_P,
                R=self.default_R,
                bot_name=self.default_bot_name
            )
        return self.contexts[group_id]

    async def on_message(self, event: MessageEvent, group_id: int, current_mode: str = "peek") -> None:
        """
        消息到达入口（从 WebSocket handler 调用）

        流程：
        1. 获取/创建该群的 DecisionContext
        2. 更新 context.current_mode（用于阈值选择）
        3. 根据当前状态进行分流处理
        4. 可能触发决策，也可能只是入队
        """
        ctx = self.get_context(group_id)
        ctx.current_mode = current_mode  # 更新当前模式（影响阈值选择）

        # 使用锁保护状态检查和修改
        async with ctx.lock:
            current_state = ctx.state

            # === 状态分支处理 ===

            if current_state == DecisionState.EXECUTING:
                # 决策执行中：消息入队，不触发
                ctx.pending_messages.append(event)
                return

            if current_state == DecisionState.WAITING_R:
                # 等待R秒冷却期：消息入队，不触发
                ctx.pending_messages.append(event)
                return

            if current_state == DecisionState.WAITING_P:
                # 提及等待期（P秒倒计时）
                ctx.pending_messages.append(event)
                if self._is_mention(event, ctx):
                    # 再次提及，刷新倒计时
                    await self._reset_mention_timer(ctx)
                return

            if current_state == DecisionState.IDLE:
                # 空闲状态：检查触发条件
                ctx.pending_messages.append(event)

                # 条件3：提及触发（优先级最高）
                if self._is_mention(event, ctx):
                    await self._schedule_mention_trigger(ctx)
                    return

                # 条件1/2：数量或时间触发
                if self._should_trigger_by_count(ctx) or self._should_trigger_by_time(ctx):
                    await self._enter_executing(ctx)
                    return

                # 无触发，保持 IDLE
                return

    def _is_mention(self, event: MessageEvent, ctx: DecisionContext) -> bool:
        """
        检查消息是否提及机器人
        支持：@机器人QQ号、@机器人名字、直接包含昵称
        """
        msg = event.message

        # 检查 @机器人QQ号（简单实现，实际需要从配置读取 self_id）
        # if f"@{ctx.bot_qq}" in msg:
        #     return True

        # 检查 @机器人名字
        if f"@{ctx.bot_name}" in msg:
            return True

        # 检查直接包含昵称（需注意误触发，如"anna"出现在其他词中）
        # 简单实现：用正则 \b 边界
        # import re
        # pattern = rf'\b{re.escape(ctx.bot_name)}\b'
        # if re.search(pattern, msg, re.IGNORECASE):
        #     return True

        return False

    def _should_trigger_by_count(self, ctx: DecisionContext) -> bool:
        """条件1/2：检查消息数量是否达到阈值"""
        # 根据当前模式选择阈值
        if ctx.current_mode == "talk":
            threshold = ctx.m
        else:  # peek mode
            threshold = ctx.M
        return len(ctx.pending_messages) > threshold

    def _should_trigger_by_time(self, ctx: DecisionContext) -> bool:
        """条件2：检查时间间隔是否达到阈值"""
        now = time.time()
        time_diff = now - ctx.last_decision_time

        # 首次决策（last_decision_time=0）特殊处理
        if ctx.last_decision_time == 0:
            return False  # 首次不触发（除非数量达到）

        # 根据当前模式选择时间阈值
        if ctx.current_mode == "talk":
            threshold = ctx.n
        else:  # peek mode
            threshold = ctx.N

        return time_diff >= threshold and len(ctx.pending_messages) > 0

    async def _schedule_mention_trigger(self, ctx: DecisionContext) -> None:
        """
        条件3：安排提及触发（P秒后）

        流程：
        1. 设置状态为 WAITING_P
        2. 记录提及时间
        3. 启动 asyncio 定时器，P秒后执行 _trigger_by_mention()
        4. 如果期间再次提及，会重置定时器
        """
        ctx.state = DecisionState.WAITING_P
        ctx.mention_time = time.time()

        # 取消旧任务（如果有）
        if ctx.mention_timer_task and not ctx.mention_timer_task.done():
            ctx.mention_timer_task.cancel()

        async def delayed_trigger():
            """P秒后执行的逻辑"""
            await asyncio.sleep(ctx.P)

            async with ctx.lock:
                # 双重检查：可能已被取消或状态变更
                if ctx.state == DecisionState.WAITING_P:
                    # 清除等待状态，进入执行
                    ctx.state = DecisionState.EXECUTING
                    ctx.mention_timer_task = None
                    await self._execute_decision(ctx)

        ctx.mention_timer_task = asyncio.create_task(delayed_trigger())

    async def _reset_mention_timer(self, ctx: DecisionContext) -> None:
        """刷新提及倒计时（取消旧任务，新建任务）"""
        if ctx.mention_timer_task and not ctx.mention_timer_task.done():
            ctx.mention_timer_task.cancel()
        # 重新安排
        await self._schedule_mention_trigger(ctx)

    async def _enter_executing(self, ctx: DecisionContext) -> None:
        """
        进入执行状态（条件1/2触发）
        要求调用方已经持有 ctx.lock
        """
        if ctx.state != DecisionState.IDLE:
            return  # 已经在执行中，跳过
        ctx.state = DecisionState.EXECUTING
        # 创建异步任务，不阻塞当前调用者
        asyncio.create_task(self._execute_decision(ctx))

    async def _execute_decision(self, ctx: DecisionContext) -> None:
        """
        执行批量决策（核心逻辑）

        步骤：
        1. 取出所有 pending_messages（清空队列）
        2. 调用外部决策函数 make_decision(messages, ctx)
        3. 遍历结果，通过 action_executor 执行动作
        4. 根据动作更新上下文模式（如 enter_talk_mode）
        5. 更新 last_decision_time
        6. 进入等待R秒状态
        7. 等待结束后回到 IDLE，并检查队列是否需要立即触发
        """
        try:
            # 1. 取出消息
            messages = ctx.pending_messages.copy()
            ctx.pending_messages.clear()

            # 2. 调用决策函数（外部实现）
            results: List[DecisionResult] = await self.make_decision(messages, ctx)

            # 3. 执行动作（通过回调）
            for msg, result in zip(messages, results):
                action = result.action

                # 打印日志
                if action.action_type == "reply":
                    logger.info(f"[决策] 回复用户 {msg.user_id}: {action.reply_text}")
                elif action.action_type == "no_reply":
                    logger.debug(f"[决策] 不回复用户 {msg.user_id}")
                elif action.action_type == "enter_talk_mode":
                    logger.info(f"[决策] 进入话题模式（群 {msg.group_id}）")
                elif action.action_type == "exit_talk_mode":
                    logger.info(f"[决策] 退出话题模式（群 {msg.group_id}）")

                # 调用执行器（如果提供了）
                if self.action_executor:
                    try:
                        await self.action_executor(msg, action, ctx)
                    except Exception as e:
                        logger.error(f"动作执行失败: {e}")

                # 4. 根据动作更新上下文模式（同步模式状态）
                # 注意：如果 action_executor 已经更新了 state_manager，这里也要同步 ctx.current_mode
                if action.action_type == "enter_talk_mode":
                    ctx.current_mode = "talk"
                elif action.action_type == "exit_talk_mode":
                    ctx.current_mode = "peek"

            # 5. 更新时间戳
            ctx.last_decision_time = time.time()

            # 6. 进入等待R秒状态
            ctx.state = DecisionState.WAITING_R

            # 7. 安排R秒后回到 IDLE
            await self._schedule_back_to_idle(ctx)

        except Exception as e:
            # 异常处理：记录日志，重置状态，避免死锁
            logger.exception(f"决策执行异常: {e}")
            ctx.state = DecisionState.IDLE
            ctx.pending_messages.clear()  # 清空队列，避免重复处理

    async def _schedule_back_to_idle(self, ctx: DecisionContext) -> None:
        """
        安排R秒后回到 IDLE 状态，并检查队列
        """
        async def delayed_reset():
            await asyncio.sleep(ctx.R)

            async with ctx.lock:
                if ctx.state == DecisionState.WAITING_R:
                    ctx.state = DecisionState.IDLE
                    ctx.waiting_r_task = None

                    # 检查队列中是否有消息，可能立即触发下一轮
                    if len(ctx.pending_messages) > 0:
                        # 重新检查触发条件
                        if self._should_trigger_by_count(ctx) or self._should_trigger_by_time(ctx):
                            await self._enter_executing(ctx)
                        # 如果条件不满足，保持 IDLE，消息留在队列等待下一条

        ctx.waiting_r_task = asyncio.create_task(delayed_reset())

    def cancel_all_tasks(self, group_id: int) -> None:
        """
        取消该群的所有待办任务（如提及定时器、R秒定时器）
        用于模式切换或清理资源
        """
        ctx = self.contexts.get(group_id)
        if not ctx:
            return

        if ctx.mention_timer_task and not ctx.mention_timer_task.done():
            ctx.mention_timer_task.cancel()
        if ctx.waiting_r_task and not ctx.waiting_r_task.done():
            ctx.waiting_r_task.cancel()

    def clear_context(self, group_id: int) -> None:
        """
        清空指定群的上下文（退出话题模式时调用）
        """
        self.cancel_all_tasks(group_id)
        if group_id in self.contexts:
            self.contexts[group_id].reset()
