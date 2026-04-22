# Chat Anna - OneBot 11 AI Bot

基于 **FastAPI** 和 **WebSocket** 实现的 OneBot 11 协议标准 AI 机器人程序。

**项目名称**: Chat Anna
**当前阶段**: Phase 2 - 批量决策调度器框架

## 功能特性

- ✅ **OneBot 11 协议标准**：完全遵循 OneBot 11 规范
- ✅ **正向 WebSocket**：支持正向 WebSocket 通信方式
- ✅ **核心 API 支持**：
  - `get_version_info` - 获取版本信息
  - `get_status` - 获取运行状态
  - `send_private_msg` - 发送私聊消息
  - `send_group_msg` - 发送群消息
  - 更多 API 持续添加中...
- ✅ **事件处理**：支持消息事件、元事件（心跳、生命周期）
- ✅ **异步支持**：基于 asyncio 的高并发处理

## 项目结构

```
Anna/
├── main.py                    # FastAPI 主程序（OneBot 服务端）
├── decision/                  # 决策模块（Phase 2 新增）
│   ├── __init__.py
│   ├── models.py              # 数据模型（DecisionContext, DecisionResult）
│   └── batch_scheduler.py     # 批量决策调度器核心逻辑
├── test_client.py             # 测试客户端
├── requirements.txt           # Python 依赖
├── config.example.yaml        # 配置示例
└── onebot-11-master/          # OneBot 11 协议文档
```

## 快速开始

### 1. 安装依赖

```bash
cd /d/CC/Anna
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
```

服务将在 `ws://0.0.0.0:8000/` 启动。

### 3. 测试连接

在另一个终端运行：

```bash
python test_client.py
```

或使用任何 OneBot 兼容的客户端（如 go-cqhttp）连接到 `ws://127.0.0.1:8000/`

## 与 go-cqhttp 配合使用

在 go-cqhttp 的配置文件中设置：

```yaml
servers:
  - ws-reverse:
      universal: ws://127.0.0.1:8000/
      reconnect-interval: 3000
```

## API 参考

### 已实现的 API

| API | 说明 | 参数 |
|-----|------|------|
| `get_version_info` | 获取版本信息 | 无 |
| `get_status` | 获取运行状态 | 无 |
| `send_private_msg` | 发送私聊消息 | `user_id`, `message`, `auto_escape` |
| `send_group_msg` | 发送群消息 | `group_id`, `message`, `auto_escape` |

### 事件格式

参考 `onebot-11-master/` 目录中的完整协议文档。

## 开发进度

### Phase 1：基础框架 ✅（已完成）
- [x] FastAPI WebSocket 端点
- [x] 基础消息接收循环
- [x] `/hello` 命令回复演示
- [x] 日志系统（logging）

### Phase 2：批量决策调度器 🔄（进行中）
- [x] 决策器数据模型（`DecisionContext`, `DecisionResult`）
- [x] 状态机实现（IDLE / WAITING_P / EXECUTING / WAITING_R）
- [x] 三个触发条件（数量 M、时间 N、提及 P）
- [x] 等待 R 秒冷却机制
- [x] 单线程串行保证（asyncio.Lock）
- [x] 集成到 WebSocket handler
- [ ] 真实决策逻辑（归属识别 + LLM 决策）⏳
- [ ] 动作执行器（发送消息、模式切换）

### Phase 3：状态管理（下一阶段）
- [ ] SQLite 会话存储
- [ ] 模式路由器框架（窥屏/话题分流）
- [ ] 基础配置系统（YAML 加载）

## 技术栈

- **Python 3.13+**
- **FastAPI** - Web 框架
- **WebSockets** - 双向通信
- **Pydantic** - 数据验证

## 协议标准

本项目遵循 [OneBot 11 标准](https://github.com/botuniverse/onebot-11)，由 botuniverse 社区维护。

## License

MIT License
