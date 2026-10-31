# 影之刃零 · AI 自动游玩（Phantom Blade Zero AI Agent）

> 这份文档是写给"另一个 AI 助手"的执行规格。读完之后，你应当能在一台 Windows 电脑上，
> 从零搭出一个"人走开、电脑自己打游戏"的闭环系统，并用 OBS 录成视频。

---

## 1. 目标（验收标准）

1. 启动脚本后，全程**不需要人手碰键鼠**，AI 能进游戏、跑图、战斗、死亡后重开/复活。
2. 每 0.8~1.5 秒做一次"战术级"决策（看你截的图 → 输出一条招式宏）。
3. 画面上有一个 OBS 可叠加的"HUD"，实时显示 AI 当前在想什么（做视频用）。
4. 全程录屏不卡（录屏与 AI 抢资源要有余量）。
5. 单次可连续运行 ≥ 60 分钟不崩。

**不追求**：打赢所有 Boss、无伤、像高手。要的是"能自己动、有逻辑、有节目效果"。
允许 AI 打得菜，但**不许卡死在原地不动**（这是最常见的失败模式）。

---

## 2. 架构（四层，务必按这个分层写，不要合并）

```
 ┌─────────────┐   30fps   ┌──────────────┐  1次/秒  ┌───────────────┐
 │ DXGI 抓屏   │ ────────► │ 帧缓冲(最新帧)│ ───────► │ 视觉决策模型  │
 │ dxcam       │           │ 只保留最新    │          │ UI-TARS/Qwen-VL│
 └─────────────┘           └──────────────┘          └──────┬────────┘
                                                            │ JSON: macro
                                                            ▼
 ┌─────────────┐   60Hz    ┌──────────────┐          ┌───────────────┐
 │ 游戏进程    │ ◄──────── │ 虚拟Xbox手柄 │ ◄─────── │ 宏队列播放器  │
 │ (XInput)    │           │ vgamepad     │          │ 独立线程      │
 └─────────────┘           └──────────────┘          └───────────────┘
```

**为什么必须分层**：视觉模型单步 0.5~3 秒，动作游戏弹反窗口只有 100~200ms。
所以模型永远**不直接按单键**，它只喊"向左闪避+反击"这种战术指令，
由本地脚本线程在一秒内把这套动作完整播完。**这是整个方案成立的核心。**

**为什么用手柄不用键鼠**：游戏原生支持 XInput，虚拟手柄是系统级设备，
不注入进程、不读写内存、不碰反作弊，也不受游戏窗口焦点影响（键鼠会）。
**但你的场景是云游戏网页**——那就再加一条：网页版优先测 `input.backend: cdp`，
用 CDP 给页面发键盘事件，见第 9 节。

---

## 3. 硬件 / 软件环境

| 项目 | 最低 | 推荐 |
|---|---|---|
| 系统 | Windows 10 21H2 | Windows 11 23H2 |
| 显卡 | RTX 3060 12G（跑本地 7B 视觉模型） | RTX 4070Ti+ |
| 或 | 不用本地模型，走云端 API | — |
| 内存 | 16G | 32G |
| 显示器 | 1080p | 1080p 就行，别上 4K（模型输入反正要缩） |

必须装：
- Python **3.11**（3.12 部分包轮子不稳，别用）
- **ViGEmBus 驱动**（虚拟手柄的内核驱动，装完必须重启）
- OBS Studio 30+（录屏 + 叠加 HUD）
- 游戏本体，**画面设置：窗口化无边框 1920x1080，垂直同步关，帧率不限**
  - ⚠️ 独占全屏会让 DXGI 抓屏黑屏或抓不到，这是第一大坑

---

## 4. 依赖清单

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` 内容：
```
dxcam>=0.0.5          # DXGI 抓屏，240fps 级别，几乎不吃 CPU
vgamepad>=0.1.0       # 虚拟 Xbox360 手柄（依赖 ViGEmBus）
pynput>=1.7.6         # 全局热键急停
opencv-python>=4.9    # 缩放 / JPEG 编码
numpy>=1.26
requests>=2.31
pyyaml>=6.0
```

**外部下载（需人工点一次，脚本代替不了）**：
1. ViGEmBus：https://github.com/ViGEm/ViGEmBus/releases → 装 `ViGEmBus_*_x64.msi` → **重启**
2. OBS：https://obsproject.com/
3. 视觉模型，二选一：
   - **本地**：`vllm serve ByteDance-Seed/UI-TARS-1.5-7B --port 8000`（7B 约需 16G 显存，fp16）
     或 `ollama run qwen2.5vl:7b`（Ollama 的 OpenAI 兼容口在 `http://127.0.0.1:11434/v1`）
   - **云端**：阿里云百炼 `qwen-vl-plus` / 智谱 `glm-4.5v` / 任意 OpenAI 兼容视觉接口
     （注意：DeepSeek 官方 API 目前没有视觉输入，不能直接看图，别在这上面浪费时间；
      如果一定要用 DeepSeek，只能让它当"高层军师"，看文字战报不出招，另说。）

---

## 5. 文件说明

```
pb0-ai-agent/
├─ README.md               ← 本文件（规格）
├─ CHECKLIST.md            ← 照着一步步做的执行清单，先做这个
├─ requirements.txt
├─ config.example.yaml     ← 复制成 config.yaml 改
├─ agent/
│  ├─ capture.py           DXGI 抓屏，只留最新帧
│  ├─ policy.py            调视觉模型，解析 JSON
│  ├─ controller.py        虚拟手柄 + 宏队列播放器（核心）
│  ├─ browser_input.py     云游戏网页输入：CDP 键盘事件播放器
│  ├─ actions.py           宏语法解析
│  └─ main.py              主循环 + 日志 + 急停
├─ docs/
│  ├─ ACTION_DSL.md        宏语法白名单（模型只能输出这些）
│  └─ PROMPT.md            给视觉模型的 system prompt（可直接用）
├─ overlay/
│  └─ index.html           OBS 浏览器源，显示 AI 实时想法
└─ tools/
   ├─ selftest_capture.py  验证抓屏（存一张 png）
   ├─ selftest_controller.py 验证手柄（按 A，看游戏有没有反应）
   └─ attach_browser.py    验证 CDP：列页面 + 往网页发一个键（云游戏用）
```

---

## 6. 运行

```bash
# 1) 先跑自检，两个都通过再往下
python tools/selftest_capture.py
python tools/selftest_controller.py

# 2) 起模型（本地示例）
vllm serve ByteDance-Seed/UI-TARS-1.5-7B --port 8000

# 3) 起主程序（游戏已经在跑、且在前台）
copy config.example.yaml config.yaml
python -m agent.main config.yaml

# 4) OBS 加"浏览器源"→ 勾选"本地文件"→ overlay/index.html
#    再开录屏。急停按 F12。
```

**云游戏（网易云游戏网页）版本**，多一步：先把 Chrome 用调试端口起好、登录进游戏，
再跑主程序（`input.backend` 设成 `cdp`）：

```bat
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\cdp-profile ^
  --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
python tools/attach_browser.py --test
python -m agent.main config.yaml
```

日志落在 `logs/episode_YYYYmmdd_HHMMSS.jsonl`，每行一条
`{ts, frame_id, thought, macro, latency_ms}`，剪视频时按这个挑高光片段。

---

## 7. 调参（决定成败的三个旋钮）

| 旋钮 | 默认 | 说明 |
|---|---|---|
| `capture.model_every` | 1.0s | 多久问一次模型。调到 0.6 更跟手但更吃算力；>2s 会看起来像发呆 |
| 宏内单步时长 | 0.06~0.4s | 太短模型来不及反应，太长会被打断。闪避后摇统一给 0.35s |
| `policy.timeout` | 8s | 超时就播"后退+防御"保命宏，**绝对不能让主循环卡住** |

**失败模式与对策**：
- 原地发呆/绕圈 → prompt 里加"禁止连续两次 wait"，并且代码层做重复宏惩罚
- 一直被打死 → 提高 dodge / parry 在 prompt 里的优先级，血量低于 30% 强制 `heal`
- 卡在门/菜单 → 单独写一个 `ui_recover` 宏（按确认键 + 摇杆乱转 1.5s），连续 3 次同画面触发
- 模型输出乱码 → 解析失败直接播 `guard:1.5`，不要抛异常

---

## 9. 适配：网易云游戏网页版（重要）

游戏不是本地进程，而是浏览器里的一条 WebRTC 视频流。这一条改变四件事：

### 9.1 输入：先测浏览器认不认手柄
云游戏平台大多支持手柄，但走的是浏览器 **Gamepad API**，ViGEmBus 虚拟手柄在
Chrome 里通常是能识别的（要先在页面上按一次键"唤醒"）。测法：

1. 起 Chrome → 进网易云游戏 → 进影之刃零 → 设置成**手柄模式**
2. 跑 `python tools/selftest_controller.py`，看角色动不动
3. 动 → `input.backend: gamepad`，最省事，相机用右摇杆，别折腾鼠标
4. 不动 → `input.backend: cdp`，走网页键盘注入

**CDP 模式前置**（必须新开一个 Chrome 实例，不能用正在跑的）：
```bat
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\cdp-profile ^
  --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
```
然后在**这个窗口里**登录云游戏、进游戏、设置键盘键位，把键位抄进 `config.yaml` 的 `input.key_map`。
验证：`python tools/attach_browser.py --test`，看角色有没有反应。

> 直接 `SendInput`/pyautogui 千万别用：云游戏页面在指针锁定状态下会把系统鼠标
> 变成"隐藏光标 + 相对位移"，自动化库算出来的坐标全是错的，人肉调试能耗一晚上。

### 9.2 抓屏：抓浏览器内容区，不是全屏
`capture.region` 填浏览器里视频区域的坐标 `[x1, y1, x2, y2]`。
先跑一次 `tools/selftest_capture.py`，看存下来的图是不是游戏画面：
- 抓到地址栏/收藏夹 → region 往下移
- 画面是黑底加一行"正在连接" → 视频还没解码完，等到进游戏再抓
- 浏览器开 F11 全屏最省事，region 直接 `[0,0,1920,1080]`

### 9.3 延迟预算：比本地多 40~80ms，模型侧要多让
本地：抓屏 5ms + 模型 800ms。
云游戏：**再加网络往返 20~50ms + 解码 16ms**，而且画面本身晚 1~2 帧。
所以 `capture.model_every` 从 1.0 放宽到 **1.2~1.5**，宏里单步时长整体 +30%，
宁可看起来"慢半拍"，也不要在动作播一半时被下一个宏打断。

### 9.4 云游戏特有的坑（比本地多三种）
1. **排队 / 免费时长 / 掉线**：出现"继续游戏""重新连接""排队中"画面时，
   模型是看不懂的。让 `ui_recover` 覆盖这些关键词，并在主循环里加一条规则：
   画面长时间静止 → 先点确认，再连点 A/Enter 两次。
2. **掉帧和码率抖动**：网络差时画面糊成马赛克，模型会乱出招，这是视频本身的问题不是模型问题。
   录视频时最好插网线，并且把平台画质固定，不要"自适应"。
3. **平台规则**：串流自己买的单机游戏、自己操控，一般不违反条款；但别用平台账号做多开/挂机刷时长，
   发视频前把账号 ID 糊掉。

### 9.5 出片视角（云游戏反而更好拍）
云游戏本身就是"一台电脑在跑"，你只要在画面角落再叠一个小窗口显示 `overlay/index.html`，
再加一句字幕"本机无人在操作"，比本地游戏更有说服力。片头可以拍你把鼠标键盘推到桌子另一头。

---

## 8. 合规与发布

- 单机游戏、无联机、无交易，用虚拟手柄/网页按键不算作弊工具，可以放心发。
- 视频里最好保留"HUD 显示 AI 思考"+"偶尔被小怪打死"的真实感，这比全胜更好看。
- 标题党可以，但别写"AI 通关"如果没通关，评论区会抓这个。
