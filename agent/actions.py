"""宏语法：模型只能输出白名单内的动作，其他一律丢弃。

格式：分号分隔的步骤，冒号分隔参数，例如
    "dodge:left;attack:3;wait:0.2"
    "move:forward:0.8;light"
"""
import re

_SAFE = re.compile(r"^[a-z0-9_]+(:[a-z0-9_.\-,]+){0,2}$")
ALLOWED = {
    "light", "heavy", "attack", "jump", "parry", "dodge",
    "lock", "heal", "interact", "confirm", "move", "wait",
    "guard", "ui_recover", "sprint", "turn", "spam",
    "combo", "skill1", "skill2", "guard_attack", "surge", "qte", "stance",
    "parry_tap", "unblock",
}


def parse_macro(macro):
    """-> [(name, arg1, arg2), ...]，非法步骤直接跳过"""
    out = []
    if not isinstance(macro, str):
        return out
    for raw in macro.replace("；", ";").split(";"):
        s = raw.strip().lower()
        if not s or len(s) > 40:
            continue
        if not _SAFE.match(s):
            continue
        parts = s.split(":")
        name = parts[0]
        if name not in ALLOWED:
            continue
        arg1 = parts[1] if len(parts) > 1 else None
        arg2 = parts[2] if len(parts) > 2 else None
        out.append((name, arg1, arg2))
    return out[:6]  # 单条宏最多 6 步，防止模型发疯播 10 秒


def sanitize(macro, fallback="guard:1.0"):
    return macro if parse_macro(macro) else fallback
