"""
会话持久化 —— 把微信会话（用户累积的语音转写、图片知识点、文字笔记）落到磁盘。

解决的问题：原先会话只存在内存字典里，服务一重启，用户还没点「生成」的笔记就全丢了。
现在改为每次消息处理结束后原子写盘，重启后自动恢复；超过有效期的会话自动清理。
"""
from __future__ import annotations

import json
import os
import tempfile
import time

from config import DATA_DIR

# 会话有效期：超过这么多秒没有新消息就丢弃（避免文件无限增长）
EXPIRE_SECONDS = int(os.getenv("CLASSNOTE_SESSION_TTL", str(7 * 24 * 3600)))  # 默认 7 天

STORE_PATH = os.getenv("CLASSNOTE_SESSION_FILE", os.path.join(DATA_DIR, "wechat_sessions.json"))


def _empty_session() -> dict:
    return {"texts": [], "images": [], "last_active": time.time()}


class SessionStore:
    """带落盘的会话表。接口与原内存字典保持一致：get(openid) -> dict（可直接改）。"""

    def __init__(self, path: str = STORE_PATH, expire_seconds: int = EXPIRE_SECONDS):
        self.path = path
        self.expire_seconds = expire_seconds
        self._sessions: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------ 读
    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            self._sessions = {}
            return
        except Exception as e:  # 文件损坏/权限问题：不能让服务起不来
            print(f"会话文件读取失败，按空会话启动: {e}")
            self._sessions = {}
            return

        now = time.time()
        kept, dropped = {}, 0
        for openid, sess in (raw.items() if isinstance(raw, dict) else []):
            if not isinstance(sess, dict):
                continue
            try:
                last = float(sess.get("last_active", 0))
            except (TypeError, ValueError):
                last = 0
            if now - last > self.expire_seconds:
                dropped += 1
                continue
            sess["texts"] = list(sess.get("texts") or [])
            sess["images"] = list(sess.get("images") or [])
            kept[openid] = sess
        self._sessions = kept
        if kept or dropped:
            print(f"会话已恢复: {len(kept)} 个用户" + (f"，清理过期 {dropped} 个" if dropped else ""))

    def get(self, openid: str) -> dict:
        """取（或新建）某用户会话；返回的是内部对象，调用方可直接就地修改。"""
        sess = self._sessions.get(openid)
        if not isinstance(sess, dict):
            sess = _empty_session()
            self._sessions[openid] = sess
        sess.setdefault("texts", [])
        sess.setdefault("images", [])
        sess["last_active"] = time.time()
        return sess

    # ------------------------------------------------------------------ 写
    def save(self) -> None:
        """原子写盘：先写临时文件再 os.replace，避免写一半被中断导致文件损坏。"""
        directory = os.path.dirname(self.path) or "."
        try:
            os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".sessions-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._sessions, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception:
                # 失败时清掉临时文件，不留垃圾
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception as e:
            print(f"会话保存失败（不影响本次回复）: {e}")

    def clear(self, openid: str) -> dict:
        """清空某用户的累积内容（对应「清空 / 重置」指令）。"""
        sess = self.get(openid)
        sess["texts"] = []
        sess["images"] = []
        self.save()
        return sess

    def stats(self) -> dict:
        """调试用：当前会话数量与内容总量。"""
        return {
            "users": len(self._sessions),
            "texts": sum(len(s.get("texts", [])) for s in self._sessions.values()),
            "images": sum(len(s.get("images", [])) for s in self._sessions.values()),
            "path": self.path,
        }
