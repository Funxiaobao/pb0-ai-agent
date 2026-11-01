"""云游戏（网页版）输入后端：通过 Chrome DevTools Protocol 直接给页面发按键。

为什么不用键鼠注入：网页只认页面内的键盘事件，系统级 SendInput 要抢焦点，
而且指针锁定后坐标会乱。CDP 的 Input.dispatchKeyEvent 直接进渲染进程，
窗口被遮挡也能生效，最稳。

注意：Playwright 的 sync API 不是线程安全的，所以连接和按键全部在播放线程里建，
主线程只负责抓屏（dxcam），两边不共享 Playwright 对象。
"""
import queue
import threading
import time


def probe_video_region(cdp_url="http://127.0.0.1:9222", keyword=""):
    """只读探测云游戏视频区域，返回物理像素 [x1,y1,x2,y2]；无视频流返回 None。"""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        pages = []
        for c in browser.contexts:
            pages.extend(c.pages)
        if not pages:
            return None
        page = pages[-1]
        for p in pages:
            if keyword and keyword in (p.url or ""):
                page = p
                break
        return page.evaluate("""(() => {
            const v = document.querySelector('video');
            if (!v || v.videoWidth <= 0) return null;
            const r = v.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            return [Math.round(r.left * dpr), Math.round(r.top * dpr),
                    Math.round(r.right * dpr), Math.round(r.bottom * dpr)];
        })()""")


class KeyMacroPlayer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.cdp_url = cfg.get("cdp_url", "http://127.0.0.1:9222")
        self.keyword = cfg.get("page_keyword", "")
        self.km = cfg.get("key_map", {})
        self.mv = cfg.get("move_keys", {"forward": "w", "back": "s", "left": "a", "right": "d"})
        self.tap_hold = float(cfg.get("tap_hold", 0.06))
        self.dodge_hold = float(cfg.get("dodge_hold", 0.35))
        self.q = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self.current = ""
        self._guard_held = False  # 是否一直按着右键格挡
        self.page = None
        self._t = threading.Thread(target=self._run, daemon=True)

    # ---- 对外接口与手柄后端保持一致 ----
    def start(self):
        self._t.start()
        return self

    def submit(self, macro):
        if not macro:
            return
        try:
            self.q.put_nowait(macro)
        except queue.Full:
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(macro)
            except queue.Full:
                pass

    def stop(self):
        self._stop.set()
        try:
            if self.page:
                for k in set(list(self.mv.values()) + list(self.km.values())):
                    try:
                        self._up(k)
                    except Exception:
                        pass
        except Exception:
            pass

    # ---- 内部 ----
    def _key(self, action, default):
        return self.km.get(action, default)

    # 模型可能直接输出按键字母/中文，统一翻译成逻辑动作名
    _ALIASES = {
        "f": "heavy", "heavy": "heavy", "重击": "heavy",
        "left": "light", "lmb": "light", "light": "light",
        "左键": "light", "轻击": "light", "鼠标左键": "light",
        "space": "jump", "jump": "jump", "空格": "jump",
        "shift": "dodge", "dodge": "dodge", "闪避": "dodge",
        "right": "parry", "rmb": "parry", "parry": "parry",
        "右键": "parry", "格挡": "parry",
        "e": "interact", "interact": "interact", "交互": "interact",
        "enter": "confirm", "confirm": "confirm", "回车": "confirm",
        "r": "heal", "heal": "heal",
        "middle": "lock", "lock": "lock", "中键": "lock",
    }

    def _norm(self, act):
        return self._ALIASES.get(act.strip().lower(), act.strip().lower())

    @staticmethod
    def _split(k):
        if isinstance(k, str) and k.startswith("mouse:"):
            return "mouse", k.split(":", 1)[1]
        return "key", k

    def _down(self, k):
        kind, v = self._split(k)
        if kind == "mouse":
            self.page.mouse.down(button=v)
        else:
            self.page.keyboard.down(k)

    def _up(self, k):
        kind, v = self._split(k)
        if kind == "mouse":
            self.page.mouse.up(button=v)
        else:
            self.page.keyboard.up(k)

    def _tap(self, k, hold=None):
        h = self.tap_hold if hold is None else hold
        self._down(k)
        time.sleep(h)
        self._up(k)

    def _do(self, name, a1=None, a2=None):
        if name in ("light", "heavy", "jump", "parry", "lock", "heal", "interact", "confirm", "surge"):
            self._tap(self._key(name, "j"))
            time.sleep(0.02)
        elif name == "attack":
            for _ in range(max(1, min(int(a1 or 1), 5))):
                self._tap(self._key("light", "j"))
                time.sleep(0.10)
        elif name == "dodge":
            pk = self._key("parry", "mouse:right")
            released = False
            if self._guard_held:
                self._up(pk)  # 闪避瞬间松开右键，闪完自动恢复
                released = True
                time.sleep(0.03)
            d = (a1 or "back").lower()
            k = self.mv.get(d)
            if k:
                self._down(k)
                time.sleep(0.04)
            self._tap(self._key("dodge", "Shift"))
            time.sleep(self.dodge_hold)
            if k:
                self._up(k)
            if released:
                self._down(pk)
        elif name == "move":
            d = (a1 or "forward").lower()
            secs = min(float(a2 or 1.1), 3.0)
            k = self.mv.get(d)
            if k:
                self._down(k)
                deadline = time.time() + secs
                while time.time() < deadline and self.q.empty():
                    time.sleep(0.05)  # 期间来了新宏就立刻让位
                self._up(k)
        elif name == "sprint":
            secs = min(float(a1 or 1.2) if a1 else 1.2, 3.0)
            fw = self.mv.get("forward", "w")
            sk = self._key("dodge", "Shift")
            self._down(fw)
            self._down(sk)
            deadline = time.time() + secs
            while time.time() < deadline and self.q.empty():
                time.sleep(0.05)
            self._up(sk)
            self._up(fw)
        elif name == "turn":
            d = (a1 or "right").lower()
            dx = -260 if d == "left" else 260  # 鼠标相对位移转视角
            self.page.mouse.move(640, 400)
            time.sleep(0.02)
            self.page.mouse.move(640 + dx, 400, steps=4)
            time.sleep(0.06)
            self.page.mouse.move(640, 400)
        elif name == "guard":
            k = self._key("parry", "k")
            self._down(k)
            time.sleep(float(a1 or 1.0))
            self._up(k)
        elif name == "wait":
            time.sleep(min(float(a1 or 0.3), 2.0))
        elif name == "spam":
            act = self._norm(a1 or "light")
            n = min(int(a2 or 3), 6)  # 连点同一按键 N 次(教程提示常用)
            k = self._key(act, "j")
            for _ in range(max(1, n)):
                self._tap(k, 0.08)
                time.sleep(0.12)
        elif name == "combo":
            # 快速按顺序连招：combo:light,heavy,heavy -> 左键,F,F (间隔 0.07s 才接得上连招)
            seq = (a1 or "light").lower().split(",")
            for act in seq[:6]:
                k = self._key(self._norm(act.strip()), "j")
                self._tap(k, 0.05)
                time.sleep(0.07)
        elif name == "skill1":
            pk = self._key("parry", "mouse:right")  # 特殊技能1 = 按住右键 + F
            self._down(pk)
            time.sleep(0.03)
            self._tap(self._key("heavy", "f"), 0.06)
            self._up(pk)
        elif name in ("skill2", "guard_attack"):
            # 格挡普攻：按住右键 + 连按左键 N 次（a1 次数, 默认 3）
            n = min(int(a1 or 3), 6) if a1 else 3
            pk = self._key("parry", "mouse:right")
            lk = self._key("light", "mouse:left")
            self._down(pk)
            time.sleep(0.03)
            for _ in range(n):
                self._tap(lk, 0.05)
                time.sleep(0.08)
            self._up(pk)
        elif name == "qte":
            # QTE 狂按：屏幕提示哪个键就连打哪个键(极快)，直到提示消失
            act = self._norm(a1 or "light")
            n = min(int(a2 or 8), 10)
            k = self._key(act, "j")
            for _ in range(n):
                self._tap(k, 0.04)
                time.sleep(0.06)
        elif name == "stance":
            # 站桩格挡流：按住右键格挡(保持不放) + 不断按左键普攻，新宏到来立即让位
            secs = min(float(a1 or 2.0), 4.0)
            pk = self._key("parry", "mouse:right")
            lk = self._key("light", "mouse:left")
            if not self._guard_held:
                self._down(pk)
                self._guard_held = True
            deadline = time.time() + secs
            next_tap = time.time()
            while time.time() < deadline and self.q.empty():
                if time.time() >= next_tap:
                    self._tap(lk, 0.05)
                    next_tap = time.time() + 0.10
                time.sleep(0.03)
            # 右键继续保持按住（一直格挡）
        elif name == "parry_tap":
            # 蓝光：松开右键马上再按一次(重新格挡判定)，结束后继续保持按住
            pk = self._key("parry", "mouse:right")
            if self._guard_held:
                self._up(pk)
                time.sleep(0.04)
                self._down(pk)
            else:
                self._tap(pk, 0.06)
                self._guard_held = True
        elif name == "unblock":
            # 战斗结束/要跑路：松开右键
            if self._guard_held:
                self._up(self._key("parry", "mouse:right"))
                self._guard_held = False
        elif name == "ui_recover":
            for _ in range(3):
                self._tap(self._key("confirm", "Enter"), 0.1)
                time.sleep(0.25)
            self._down(self.mv.get("right", "d"))
            time.sleep(0.4)
            self._up(self.mv.get("right", "d"))
        else:
            time.sleep(0.2)

    def play(self, macro):
        from .actions import parse_macro
        self.current = macro
        for step in parse_macro(macro):
            if self._stop.is_set():
                break
            try:
                self._do(*step)
            except Exception as e:
                print("[browser] 动作失败", step, e)
                time.sleep(0.2)

    def _pick_page(self, browser):
        pages = []
        for c in browser.contexts:
            pages.extend(c.pages)
        if not pages:
            raise RuntimeError("CDP 连上了但没有任何页面，Chrome 是不是带 --remote-debugging-port 启动的？")
        for p in pages:
            if self.keyword and self.keyword in (p.url or ""):
                return p
        return pages[-1]

    def _run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print("[browser] 没装 playwright：pip install playwright")
            return
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(self.cdp_url)
            page = self._pick_page(browser)
            page.bring_to_front()
            print(f"[browser] 已连接：{page.title()} | {page.url[:80]}")
            try:
                page.mouse.click(640, 400)  # 先点一下，保证页面拿到焦点/进入指针锁定
                time.sleep(0.5)
            except Exception:
                pass
            self.page = page
            while not self._stop.is_set():
                try:
                    macro = self.q.get(timeout=0.2)
                except queue.Empty:
                    continue
                self.play(macro)
