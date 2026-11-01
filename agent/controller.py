"""虚拟 Xbox 手柄 + 宏队列播放器。

设计要点：
- 决策线程只往队列里丢字符串宏，立刻返回，绝不等待动作播完
- 播放线程以固定节奏执行，保证连招不断
- 任何异常都要 reset 手柄，否则会卡住某个键一直按着
"""
import queue
import threading
import time

try:
    import vgamepad as vg
    _BTN = {
        "A": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
        "B": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
        "X": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
        "Y": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        "LB": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER,
        "RB": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER,
        "BACK": vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK,
        "START": vg.XUSB_BUTTON.XUSB_GAMEPAD_START,
        "LS": vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB,
        "RS": vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB,
        "DPAD_UP": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
        "DPAD_DOWN": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN,
        "DPAD_LEFT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
        "DPAD_RIGHT": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
    }
    _TRIGGER = {"LT": "left_trigger", "RT": "right_trigger"}
except ImportError:  # cdp 后端不需要手柄
    vg = None
    _BTN = {}
    _TRIGGER = {}
_DIRS = {
    "forward": (0.0, 1.0),
    "back": (0.0, -1.0),
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "fl": (-0.7, 0.7),
    "fr": (0.7, 0.7),
    "bl": (-0.7, -0.7),
    "br": (0.7, -0.7),
}


class Gamepad:
    def __init__(self):
        if vg is None:
            raise RuntimeError("gamepad 后端需要 vgamepad+ViGEmBus；云游戏请用 input.backend: cdp")
        self.pad = vg.VX360Gamepad()
        self._lock = threading.Lock()

    def _send(self):
        with self._lock:
            self.pad.update()

    def press(self, name):
        with self._lock:
            if name in _BTN:
                self.pad.press_button(_BTN[name])
            elif name in _TRIGGER:
                self.pad.left_trigger(255) if name == "LT" else self.pad.right_trigger(255)
            self.pad.update()

    def release(self, name):
        with self._lock:
            if name in _BTN:
                self.pad.release_button(_BTN[name])
            elif name in _TRIGGER:
                self.pad.left_trigger(0) if name == "LT" else self.pad.right_trigger(0)
            self.pad.update()

    def tap(self, name, hold=0.06):
        self.press(name)
        time.sleep(hold)
        self.release(name)

    def stick(self, x, y):
        with self._lock:
            self.pad.left_joystick_float(float(x), float(y))
            self.pad.update()

    def reset(self):
        with self._lock:
            self.pad.reset()
            self.pad.update()


class MacroPlayer:
    """队列里永远只保留最新一条宏（旧的过期就丢掉，避免追尾）。"""

    def __init__(self, button_map, cfg=None):
        self.map = dict(button_map)
        self.cfg = cfg or {}
        self.tap_hold = float(self.cfg.get("tap_hold", 0.06))
        self.dodge_hold = float(self.cfg.get("dodge_hold", 0.35))
        self.gamepad = Gamepad()
        self.q = queue.Queue(maxsize=3)
        self._stop = threading.Event()
        self.current = ""
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()
        return self

    def submit(self, macro: str):
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

    def _btn(self, action, default):
        return self.map.get(action, default)

    # ---- 单个动作 ----
    def _do(self, name, arg1=None, arg2=None):
        if name in ("light", "heavy", "jump", "parry", "lock", "heal", "interact", "confirm"):
            self.gamepad.tap(self._btn(name, "X"), self.tap_hold)
            time.sleep(0.02)
        elif name == "attack":
            n = int(arg1 or 1)
            for _ in range(max(1, min(n, 5))):
                self.gamepad.tap(self._btn("light", "X"), self.tap_hold)
                time.sleep(0.10)
        elif name == "dodge":
            d = (arg1 or "back").lower()
            x, y = _DIRS.get(d, (0.0, -1.0))
            self.gamepad.stick(x, y)
            time.sleep(0.05)
            self.gamepad.tap(self._btn("dodge", "B"), self.tap_hold)
            time.sleep(self.dodge_hold)
            self.gamepad.stick(0.0, 0.0)
        elif name == "move":
            d = (arg1 or "forward").lower()
            secs = float(arg2 or 0.5)
            x, y = _DIRS.get(d, (0.0, 1.0))
            self.gamepad.stick(x, y)
            time.sleep(secs)
            self.gamepad.stick(0.0, 0.0)
        elif name == "guard":
            secs = float(arg1 or 1.0)
            self.gamepad.press(self._btn("parry", "RB"))
            time.sleep(secs)
            self.gamepad.release(self._btn("parry", "RB"))
        elif name == "wait":
            time.sleep(float(arg1 or 0.3))
        elif name == "ui_recover":
            for _ in range(2):
                self.gamepad.tap(self._btn("confirm", "A"), 0.1)
                time.sleep(0.2)
            self.gamepad.stick(1.0, 0.0)
            time.sleep(0.4)
            self.gamepad.stick(-1.0, 0.0)
            time.sleep(0.4)
            self.gamepad.stick(0.0, 0.0)
        else:
            # 未知动作：原地防御一下，别空转
            time.sleep(0.2)

    def play(self, macro: str):
        from .actions import parse_macro
        self.current = macro
        for step in parse_macro(macro):
            if self._stop.is_set():
                break
            try:
                self._do(*step)
            except Exception as e:
                print("[controller] 动作执行失败", step, e)
                self.gamepad.reset()

    def _run(self):
        while not self._stop.is_set():
            try:
                macro = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            self.play(macro)

    def stop(self):
        self._stop.set()
        try:
            self.gamepad.reset()
        except Exception:
            pass
