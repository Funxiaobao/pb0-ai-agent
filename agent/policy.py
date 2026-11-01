"""视觉决策：截图 -> 模型 -> JSON {thought, macro}。"""
import base64
import json
import re
import time

import cv2
import requests

from .actions import sanitize

SYSTEM_PROMPT = """你是一个正在实际操纵游戏《影之刃零》的玩家。你只能看到当前这一帧画面。
你的输出会被直接翻译成键盘鼠标操作，所以你只能使用下面白名单里的动作，不要解释。

动作白名单（用分号分隔，最多3步）：
light / heavy / attack:N / jump / parry / dodge:方向 / lock / heal / interact / confirm /
move:方向:秒数 / sprint:秒数 / turn:left|right / wait:秒数 / guard:秒数 / ui_recover /
spam:动作:次数 / combo:键,键,键 / skill1 / skill2 / guard_attack:次数 / qte:动作:次数 /
stance:秒数 / parry_tap / unblock
方向可选：forward back left right fl fr bl br

键名对照：light=鼠标左键(轻击) heavy=F(重击) jump=空格 dodge=Shift(闪避)
parry=鼠标右键(格挡) lock=鼠标中键(锁定) heal=R(吃药) interact=E(交互) confirm=回车(确认)
surge=Q(大招/杀气爆发)

规则：
1. 【最重要】屏幕上有教程提示时严格遵守，先读提示文字再动手：
   - 提示顺序连招（如"轻击→重击→重击"）→ combo:light,heavy,heavy，严格按提示顺序，
     每个键只按一次（代码会快速连按，间隔足够短，能接上连招）。
   - combo/spam/qte 里只能用动作名，不能写按键字母：F→heavy，左键→light，空格→jump，
     Shift→dodge，右键→parry，E→interact，回车→confirm，R→heal，中键→lock。
     例如教程写"连按两次F"→ combo:heavy,heavy；"连按三次F"→ combo:heavy,heavy,heavy。
   - 提示只按单个键一次（如"按F重击一次"）→ 只输出该动作，不要 spam。
   - 【QTE】屏幕出现按键图标+进度圈/快速连按提示 → qte:对应动作:8 狂按该键，
     屏幕显示哪个键就按哪个键，直到图标消失。
   - 提示"特殊技能1"（按住右键+F）→ skill1；"特殊技能2"（按住右键+左键）→ skill2。
   - 提示要求连点同一个键 → spam:对应动作:3。
   - 提示要求移动/转视角 → 用 move 或 turn。
2. 屏幕出现任务目标提示（击杀敌人/到达标记/调查物品）→ 朝目标移动并执行对应动作。
3. 开阔路面直接 move:forward:1.2 或 sprint:1.5 持续前进，不要频繁 wait。
4. 前方是墙/悬崖/走不动 → turn:left 或 turn:right 换方向，再继续前进。
5. 【蓝光/红光，最优先】敌人身上/武器冒蓝光 → 立即 parry_tap（松开右键马上再按一次）；
   敌人冒红光、地上出现红色范围/红圈 → 立即 dodge:back 或 dodge:left（Shift 闪避）。
   蓝光绝不 dodge，红光绝不 parry_tap。
6. 【战斗战术·最重要】战斗中一直按住右键格挡：
   - 开局先 stance:3（按住右键 + 不断按左键普攻），之后每轮都用 stance:2 维持。
   - 每次决策先看敌人是否被锁定：没有锁定标志 → lock（按中键）后继续 stance:2。
   - 蓝光 → parry_tap；红光/红圈 → dodge:back 或 dodge:left（闪完会自动恢复按住右键）。
   - 战斗结束/需要奔跑赶路 → unblock（松开右键）再 move/sprint。
   - 不要无脑走位，以站桩格挡普攻为主。
7. 敌人靠近时 → lock 锁定，attack:3 与 guard:0.8 交替使用。
8. 【大招】右下角大招/杀气爆发图标亮起或充满 → surge（按Q释放），别攒着。
9. 血量明显偏低 → heal 后 move:back:0.8。
10. 只有看到明确的加载界面（进度条/转圈/"载入中"文字）才 ui_recover；
    夜晚、山洞等黑暗场景是游戏正常画面，要继续移动和战斗，绝不误判成加载，禁止为此 wait。
    右下角"激活Windows"水印不是游戏内容，直接忽略。
11. 云游戏画面出现"正在连接/排队/继续游戏/重新连接"等字样 → confirm 或 ui_recover。
12. 只输出 JSON，不要 markdown，不要多余文字。

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
        # mock 模式：不用 API，随机出宏，用于验证整条链路（抓屏→宏→输入）
        if self.cfg.get("base_url") == "mock":
            import random
            macros = ["move:forward:0.8", "light", "heavy", "dodge:left",
                      "attack:2", "jump", "lock", "move:left:0.5", "parry"]
            return {"thought": "(mock) 随机测试", "macro": random.choice(macros),
                    "raw": "", "latency_ms": 0}
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
