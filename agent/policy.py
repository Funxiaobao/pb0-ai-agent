"""视觉决策：截图 -> 模型 -> JSON {thought, macro}。"""
import base64
import json
import re
import time

import cv2
import requests

from .actions import sanitize

SYSTEM_PROMPT = """你是一个正在实际操纵游戏《影之刃零》的玩家。你只能看到当前这一帧画面。
你的输出会被直接翻译成手柄操作，所以你只能使用下面白名单里的动作，不要解释。

动作白名单（用分号分隔，最多3步）：
light / heavy / attack:N / jump / parry / dodge:方向 / lock / heal / interact / confirm /
move:方向:秒数 / wait:秒数 / guard:秒数 / ui_recover
方向可选：forward back left right fl fr bl br

规则：
1. 优先保持移动和进攻，不要连续输出 wait。
2. 看到敌人举武器/白光 → parry；看到红色范围或敌人冲刺 → dodge:back 或 dodge:left。
3. 血量明显偏低 → heal 后 move:back:0.8。
4. 画面是菜单/黑屏/载入 → ui_recover。
5. 只输出 JSON，不要 markdown，不要多余文字。

输出格式：
{"thought": "一句话说明你在干什么", "macro": "动作宏"}
"""


class Policy:
    def __init__(self, cfg):
        self.cfg = cfg
        self.base = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.key = cfg.get("api_key", "EMPTY")
        self.timeout = float(cfg.get("timeout", 8))
        self.max_tokens = int(cfg.get("max_tokens", 220))
        self.temp = float(cfg.get("temperature", 0.2))
        self.history_turns = int(cfg.get("history_turns", 4))
        self.max_w = int(cfg.get("max_width", 960)) if "max_width" in cfg else 960
        self.history = []

    def _img(self, frame):
        h, w = frame.shape[:2]
        if w > self.max_w:
            frame = cv2.resize(frame, (self.max_w, int(h * self.max_w / w)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            raise RuntimeError("JPEG 编码失败")
        return "data:image/jpeg;base64," + base64.b64encode(buf).decode()

    def decide(self, frame):
        t0 = time.time()
        user_text = "这是当前游戏画面。给出你的下一步动作。"
        if self.history:
            user_text += "\n你最近做过：" + " | ".join(self.history[-self.history_turns:])
        payload = {
            "model": self.model,
            "temperature": self.temp,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": self._img(frame)}},
                ]},
            ],
        }
        r = requests.post(
            self.base + "/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.key}"},
            timeout=self.timeout,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        thought, macro = self._parse(text)
        self.history.append(macro)
        return {
            "thought": thought,
            "macro": macro,
            "raw": text[:500],
            "latency_ms": int((time.time() - t0) * 1000),
        }

    @staticmethod
    def _parse(text):
        thought, macro = "（模型返回无法解析）", "guard:1.0"
        if not isinstance(text, str):
            return thought, macro
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                thought = str(d.get("thought", thought))[:120]
                macro = str(d.get("macro", macro))
            except Exception:
                pass
        return thought, sanitize(macro)
