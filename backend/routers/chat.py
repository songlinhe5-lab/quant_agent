import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter()

# --- 1. 定义 Pydantic 数据模型 ---
class ChatAttachment(BaseModel):
    name: str
    url: str    # 包含 Base64 数据，如 "data:image/jpeg;base64,/9j/4AAQ..."
    type: str   # MIME 类型，如 "image/jpeg" 或 "application/pdf"

class ChatMessage(BaseModel):
    role: str
    content: str
    attachments: Optional[List[ChatAttachment]] = None

# 对应前端发送的 Request Body
class ChatRequest(BaseModel):
    session_id: str
    messages: List[ChatMessage]

# --- 2. FastAPI 路由与多模态解析逻辑 ---
@router.post("/chat")
async def chat_endpoint(request: ChatRequest):
    try:
        # 1. 提取当前用户的最新消息
        user_message = request.messages[-1]

        # 2. 组装发给大模型（如 GPT-4o / Claude 3 / DeepSeek-VL）的多模态格式
        llm_content = []

        # 加入文本提问
        if user_message.content.strip():
            llm_content.append({
                "type": "text",
                "text": user_message.content
            })

        # 加入图片/文件附件
        if user_message.attachments:
            for att in user_message.attachments:
                if att.type.startswith("image/"):
                    # 视觉大模型通常原生支持带有 Data URL 协议的 Base64 字符串
                    llm_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": att.url
                        }
                    })
                elif att.type == "application/pdf":
                    # PDF 解析降级逻辑：在后端分离 base64 数据头，后续可接入 pdfplumber 提取纯文本  # noqa: E501
                    if "," in att.url:
                        header, base64_data = att.url.split(",", 1)
                    else:
                        base64_data = att.url

                    # 💡 防御 Prompt 注入：净化用户控制的文件名，防止恶意闭合符伪造系统级别的核心指令  # noqa: E501
                    safe_name = att.name.replace("[", "【").replace("]", "】").replace("\n", " ")  # noqa: E501

                    llm_content.append({
                        "type": "text",
                        "text": f"[系统提示：用户上传了 PDF 文件 {safe_name}，Base64 数据长度: {len(base64_data)} 字节]"  # noqa: E501
                    })

        # 构建最终发给 LLM SDK 的 messages

        # 3. 发起调用与流式返回 (StreamingResponse)
        async def generate_response():
            # 💡 模拟底层 Agent 执行 Tool 时的思考与纠错过程
            thoughts = [
                "调用 get_broker_market_data 获取实时行情...",
                "⚠️ 发现参数偏离设定，正在自动纠错重试 (第 1 次)...\n拦截原因: 不支持该维度或周期 [filters->0->field]",  # noqa: E501
                "纠错成功，已获取到标准格式的 JSON 数据，准备生成最终分析。"
            ]
            for thought in thoughts:
                yield json.dumps({"type": "thought_chunk", "content": thought}) + "\n"
                await asyncio.sleep(0.5) # 模拟思考耗时

            # 💡 思考完毕后，开始输出给用户的正式回复
            reply_text = "已收到指令。经过分析，为您筛选出以下结果..."
            for char in reply_text:
                yield json.dumps({"type": "text_chunk", "content": char}) + "\n"
                await asyncio.sleep(0.03) # 模拟文字吐出延迟

        return StreamingResponse(generate_response(), media_type="application/x-ndjson")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
