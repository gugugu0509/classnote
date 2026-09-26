"""
微信消息路由
"""
from fastapi import APIRouter, Request, Query
from fastapi.responses import PlainTextResponse, Response
from services.wechat_service import verify_signature, parse_message, handle_message

router = APIRouter(prefix="/api/wechat", tags=["微信"])


@router.get("")
async def wechat_verify(
    signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
):
    """微信服务器验证"""
    if verify_signature(signature, timestamp, nonce):
        return PlainTextResponse(echostr)
    return PlainTextResponse("fail", status_code=403)


@router.post("")
async def wechat_message(request: Request):
    """接收微信消息"""
    body = await request.body()
    xml_str = body.decode("utf-8")

    msg = parse_message(xml_str)
    if not msg:
        return PlainTextResponse("success")

    try:
        reply_xml = await handle_message(msg)
        return Response(content=reply_xml, media_type="application/xml")
    except Exception as e:
        print(f"微信消息处理异常: {e}")
        return PlainTextResponse("success")
