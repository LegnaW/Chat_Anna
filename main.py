"""
极简 OneBot 11 WebSocket 实现
集成批量决策调度器框架（不含具体决策逻辑）

阶段：Phase 2 - 决策器框架集成
"""

import asyncio
import json
import logging
import time
from typing import List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from decision import BatchDecisionScheduler, MessageEvent, DecisionResult, NoReplyAction

# ============== 日志配置 ==============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI()


# ============== 决策器配置 ==============
DECISION_CONFIG = {
    "M": 10,   # 窥屏模式：消息数量阈值
    "N": 40,   # 窥屏模式：时间阈值（秒）
    "m": 3,    # 话题模式：消息数量阈值
    "n": 10,   # 话题模式：时间阈值（秒）
    "P": 3,    # 提及等待时间（秒）
    "R": 2,    # 决策后等待时间（秒）
    "bot_name": "Anna"
}


# ============== 导入决策器组件 ==============
from decision import (
    BatchDecisionScheduler,
    MessageEvent,
    DecisionResult,
    DecisionContext,
    ReplyAction,
    NoReplyAction,
    EnterTalkModeAction,
    ExitTalkModeAction
)


# ============== Mock 决策函数 ==============
async def mock_make_decision(
    messages: List[MessageEvent],
    ctx: DecisionContext
) -> List[DecisionResult]:
    """
    Mock 决策函数：暂时只实现一个简单规则

    逻辑：如果消息内容以 "/" 开头，则回复 "ok"
    否则不回复

    这个函数后续会被真实的决策逻辑替换
    """
    results = []
    for msg in messages:
        content = msg.message.strip()
        if content.startswith("/"):
            action = ReplyAction(reply_text="ok")
            result = DecisionResult(action=action)
        else:
            action = NoReplyAction()
            result = DecisionResult(action=action)

        results.append(result)

    return results


# ============== 状态管理器（简化版）==============
class SimpleStateManager:
    """
    简化的状态管理器
    管理每个群的模式（peek / talk）
    实际项目中会持久化到 SQLite
    """

    def __init__(self):
        self.modes: dict[int, str] = {}  # group_id -> mode
        self._lock = asyncio.Lock()

    async def get_mode(self, group_id: int) -> str:
        """获取群当前模式"""
        async with self._lock:
            return self.modes.get(group_id, "peek")

    async def set_mode(self, group_id: int, mode: str) -> None:
        """设置群模式"""
        async with self._lock:
            self.modes[group_id] = mode
            logger.info(f"群 {group_id} 模式切换为: {mode}")

    async def enter_talk_mode(self, group_id: int) -> None:
        """进入话题模式"""
        await self.set_mode(group_id, "talk")

    async def exit_talk_mode(self, group_id: int) -> None:
        """退出话题模式（回到窥屏）"""
        await self.set_mode(group_id, "peek")


# ============== 初始化组件 ==============
state_manager = SimpleStateManager()
scheduler = BatchDecisionScheduler(
    make_decision_fn=mock_make_decision,
    action_executor=execute_action,  # 传入动作执行器
    default_config=DECISION_CONFIG
)


# ============== 消息发送器（占位符）==============
async def send_private_msg(user_id: int, message: str):
    """
    发送私聊消息（通过 OneBot API）
    这里只是占位符，实际会调用 OneBot 的 send_private_msg API
    """
    logger.info(f"[发送私聊] user_id={user_id}, message={message!r}")
    # TODO: 实际实现
    # await onebot_client.send_private_msg(user_id=user_id, message=message)


async def send_group_msg(group_id: int, message: str):
    """
    发送群消息（通过 OneBot API）
    """
    logger.info(f"[发送群聊] group_id={group_id}, message={message!r}")
    # TODO: 实际实现


# ============== 动作执行器 ===============
async def execute_action(event: MessageEvent, action, ctx: DecisionContext) -> None:
    """
    执行决策器返回的动作

    Args:
        event: 原始消息事件
        action: DecisionAction 实例
        ctx: 决策上下文（用于同步模式状态）
    """
    action_type = action.action_type

    if action_type == "reply":
        # 根据消息类型决定发私聊还是群聊
        if event.group_id:
            await send_group_msg(event.group_id, action.reply_text)
        else:
            await send_private_msg(event.user_id, action.reply_text)

    elif action_type == "enter_talk_mode":
        # 进入话题模式（更新状态管理器 + 同步上下文）
        if event.group_id:
            await state_manager.enter_talk_mode(event.group_id)
            ctx.current_mode = "talk"  # 同步更新上下文模式

    elif action_type == "exit_talk_mode":
        if event.group_id:
            await state_manager.exit_talk_mode(event.group_id)
            ctx.current_mode = "peek"  # 同步更新上下文模式

    # 其他动作类型（如 send_like 等）未来扩展
    else:
        logger.debug(f"未知动作类型: {action_type}")


# ============== WebSocket 端点 ===============
@app.websocket("/")
async def ws(websocket: WebSocket):
    await websocket.accept()
    logger.info("客户端已连接")

    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            logger.debug(f"收到原始消息: {raw}")

            # 只处理消息事件
            if msg.get("post_type") != "message":
                continue

            # 提取关键字段
            message_type = msg.get("message_type")
            user_id = msg.get("user_id")
            group_id = msg.get("group_id")  # 群聊时有，私聊时为 None
            message_text = msg.get("message", "").strip()
            message_id = msg.get("message_id", int(time.time()))

            # 构造简化版 MessageEvent
            event = MessageEvent(
                group_id=group_id or 0,  # 私聊 group_id=0
                user_id=user_id,
                message=message_text,
                message_id=message_id,
                time=msg.get("time", time.time())
            )

            # 根据消息类型分流
            if message_type == "private":
                # 私聊：暂时不经过批量决策器，直接决策并回复
                # 后续可以单独实现私聊决策逻辑
                logger.debug(f"私聊消息来自 user_id={user_id}: {message_text}")
                # TODO: 私聊决策
                if message_text == "/hello":
                    await send_private_msg(user_id, "ok")

            elif message_type == "group":
                # 群聊：获取当前模式并提交给决策器
                mode = await state_manager.get_mode(event.group_id)
                logger.debug(f"群 {event.group_id} 消息，模式: {mode}, 内容: {message_text}")

                ctx = scheduler.get_context(event.group_id)
                ctx.current_mode = mode  # 设置当前模式（用于阈值选择）
                await scheduler.on_message(event, event.group_id)

            else:
                logger.debug(f"忽略未知消息类型: {message_type}")

    except WebSocketDisconnect:
        logger.info("客户端断开")
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}")
    except Exception as e:
        logger.exception(f"WebSocket 异常: {e}")


@app.get("/")
async def root():
    logger.info("健康检查访问")
    return {"status": "ok", "protocol": "onebot-11", "project": "Chat Anna"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ============== 调试端点 ==============
@app.get("/debug/scheduler/{group_id}")
async def debug_scheduler(group_id: int):
    """调试端点：查看指定群的调度器状态"""
    ctx = scheduler.get_context(group_id)
    return {
        "group_id": group_id,
        "state": ctx.state,
        "pending_count": len(ctx.pending_messages),
        "last_decision_time": ctx.last_decision_time,
        "mode": await state_manager.get_mode(group_id)
    }


if __name__ == "__main__":
    import uvicorn
    logger.info("启动 Chat Anna 服务: ws://0.0.0.0:8000/")
    uvicorn.run(app, host="0.0.0.0", port=8000)
