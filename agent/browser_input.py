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
                        self.page.keyboard.up(k)
                    except Exception:
                        pass
        except Exception:
            pass

    # ---- 内部 ----
    def _key(self, action, default):
        return self.km.get(action, default)

    def _tap(self, k, hold=None):
        h = self.tap_hold if hold is None else hold
        self.page.keyboard.down(k)
        time.sleep(h)
        self.page.keyboard.up(k)

    def _do(self, name, a1=None, a2=None):
        if name in ("light", "heavy", "jump", "parry", "lock", "heal", "interact", "confirm"):
            self._tap(self._key(name, "j"))
            time.sleep(0.02)
        elif name == "attack":
            for _ in range(max(1, min(int(a1 or 1), 5))):
                self._tap(self._key("light", "j"))
                time.sleep(0.10)
        elif name == "dodge":
            d = (a1 or "back").lower()
            k = self.mv.get(d)
            if k:
                self.page.keyboard.down(k)
                time.sleep(0.04)
            self._tap(self._key("dodge", "Shift"))
            time.sleep(self.dodge_hold)
            if k:
                self.page.keyboard.up(k)
        elif name == "move":
            d = (a1 or "forward").lower()
            secs = float(a2 or 0.5)
            k = self.mv.get(d)
            if k:
                self.page.keyboard.down(k)
                time.sleep(secs)
                self.page.keyboard.up(k)
        elif name == "guard":
            k = self._key("parry", "k")
            self.page.keyboard.down(k)
            time.sleep(float(a1 or 1.0))
            self.page.keyboard.up(k)
        elif name == "wait":
            time.sleep(float(a1 or 0.3))
        elif name == "ui_recover":
            for _ in range(2):
                self._tap(self._key("confirm", "Enter"), 0.1)
                time.sleep(0.25)
            self.page.keyboard.down(self.mv.get("right", "d"))
            time.sleep(0.4)
            self.page.keyboard.up(self.mv.get("right", "d"))
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
