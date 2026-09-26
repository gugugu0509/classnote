"""
课堂笔记助手 - 后端入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from routers import audio, image, mindmap, wechat
import os

app = FastAPI(
    title="课堂笔记助手 API",
    description="录音转写 + 图片识别 + 思维导图生成",
    version="0.1.0",
)

# 跨域配置（允许手机App访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(audio.router)
app.include_router(image.router)
app.include_router(mindmap.router)
app.include_router(wechat.router)

# 静态文件（前端页面）
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/app", StaticFiles(directory=static_dir, html=True), name="static")


@app.get("/")
async def root():
    return RedirectResponse(url="/app/")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
