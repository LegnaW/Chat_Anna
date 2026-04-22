"""
测试客户端 - 模拟 OneBot 客户端连接并测试 API
"""

import asyncio
import json
import websockets


async def test_client():
    """测试客户端"""
    uri = "ws://127.0.0.1:8000/"

    async with websockets.connect(uri) as websocket:
        print("✅ 已连接到 OneBot 服务")

        # 接收连接事件
        msg = await websocket.recv()
        print(f"收到: {msg}")

        # 测试 get_version_info API
        print("\n📋 测试 get_version_info API")
        await websocket.send(json.dumps({
            "action": "get_version_info",
            "echo": "test-1"
        }))
        response = await websocket.recv()
        print(f"响应: {response}")

        # 测试 get_status API
        print("\n📋 测试 get_status API")
        await websocket.send(json.dumps({
            "action": "get_status",
            "echo": "test-2"
        }))
        response = await websocket.recv()
        print(f"响应: {response}")

        # 测试 send_private_msg API
        print("\n📋 测试 send_private_msg API")
        await websocket.send(json.dumps({
            "action": "send_private_msg",
            "params": {
                "user_id": 123456,
                "message": "Hello from AnnaBot!"
            },
            "echo": "test-3"
        }))
        response = await websocket.recv()
        print(f"响应: {response}")

        print("\n✅ 所有测试完成！")


if __name__ == "__main__":
    asyncio.run(test_client())
