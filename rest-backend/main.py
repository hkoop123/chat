from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from typing import Dict
from datetime import datetime
import uvicorn
import base64
import json
from datetime import datetime, timedelta, timezone
import openai
from openai import AsyncOpenAI
import os
import asyncio


openai_client = AsyncOpenAI(api_key=)

app = FastAPI()

origins = ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

mongo_client = MongoClient("mongodb://localhost:27017")
db = mongo_client.chat_db
messages_collection = db.messages


#from fastapi import Request
#from fastapi.responses import JSONResponse
#
#@app.get("/messages")
#async def get_messages():
#    messages = list(messages_collection.find({}, {"_id": 0}))
#    return messages  # 배열 형태 반환
#
#@app.post("/messages")
#async def post_message(request: Request):
#    data = await request.json()
#    message = {
#        "username": data["username"],
#        "content": data["content"],
#        "timestamp": datetime.utcnow()
#    }
#messages_collection.insert_one(message)
#    return JSONResponse(content={"message": "Message stored"})


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        
    async def connect(self, websocket: WebSocket, nickname: str):
        await websocket.accept()
        self.active_connections[nickname] = websocket 
    
    def disconnect(self, nickname: str):
        self.active_connections.pop(nickname, None)
        
    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)    
                
manager = ConnectionManager()


async def ask_chatgpt(prompt: str) -> str:
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "당신은 친절한 상담봇입니다."},
                {"role": "user", "content":prompt}
            ]
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[GPT 오류] {e}"

@app.websocket("/ws/{nickname}")
async def websocket_endpoint(websocket: WebSocket, nickname: str):
    await manager.connect(websocket, nickname)
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                print("Invalid JSON:", raw_data)
                continue
            
            timestamp = datetime.utcnow()
            data["timestamp"] = timestamp.isoformat()
            
            messages_collection.insert_one({
                "nickname": data.get("nickname", nickname),
                "message": data.get("message", ""),
                "timestamp": timestamp
            })                  

            msg_type = data.get("type")
            if msg_type == "text":
                await manager.broadcast(data)
                
                if data["message"].startswith("@chatbot"):
                    user_msg = data["message"].replace("@chatbot", "").strip()
                    gpt_reply = await ask_chatgpt(user_msg)
                    print("📡 GPT 응답 내용:", gpt_reply)
                    gpt_msg = {
                        "nickname": "chatbot",
                        "text": gpt_reply,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                
                    await manager.broadcast(gpt_msg)
                    messages_collection.insert_one(gpt_msg) 
                    
    except WebSocketDisconnect:
            manager.disconnect(nickname)
            await manager.broadcast({
                "nickname": "system",
                "text": f"{nickname}님이 나갔습니다.",
                "timestamp": datetime.utcnow().isoformat()
            })

