# 影之刃零 · AI 自动游玩（云游戏实战打磨版）

> 让 AI 自己玩《影之刃零》：抓屏 → 视觉模型看图出招 → 宏队列 → CDP 键鼠注入云游戏网页。
> 本仓库经过一次完整的实战调教，**AI 已独立战胜序章 Boss「左殇」**。
> 技术验证与踩坑经验见文末 [实战经验](#实战经验)。

---

## 架构（四层，别合并）

```
┌──────────┐   30fps    ┌────────────┐   1次/1.2s   ┌──────────────┐
│ mss 抓屏 │ ─────────► │ 帧缓冲      │ ──────────► │ 视觉决策模型   │
│ (云游戏视频区自动探测)│ (只留最新帧) │              │ glm-4v-flash  │
└──────────┘            └────────────┘              └──────┬───────┘
                                                           │ JSON 宏
                                                           ▼
┌────────────┐           ┌─────────────────┐          ┌──────────┐
│ 网易云游戏   │ ◄──────── │ 宏队列播放器线程   │ ◄──────── │ 动作白名单 │
│ (Chrome)   │  CDP 键鼠 │ (招式中断/让位机制)│          │ actions.py│
└────────────┘           └─────────────────┘          └──────────┘
```

**为什么分层**：视觉模型单步 1~3 秒，动作游戏弹反窗口只有零点几秒。
模型永远不直接按单键——它只输出"站桩格挡 2 秒""蓝光重按右键"这类战术宏，
由播放器线程在亚秒级节奏内把整套动作播完。这是整个方案成立的核心。

**为什么用 CDP 而不是系统级键鼠注入**：CDP 的 `Input.dispatchKeyEvent` 直接进渲染进程，
事件是可信的，窗口被遮挡、失焦都能生效；云游戏页面在指针锁定下坐标会乱，
SendInput 类方案会踩坑。

---

## 快速开始

### 0) 环境

- Windows 10/11，Python 3.11/3.12（3.12 已验证）
- Chrome（用调试端口另起一个实例，见下）
- 网易云游戏网页版里的《影之刃零》

### 1) 安装依赖

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

> 国内网络直连 PyPI 慢/断，用阿里云镜像；清华镜像曾返回 403。

### 2) 起带调试端口的 Chrome

```bat
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\cdp-profile ^
  --disable-backgrounding-occluded-windows --disable-renderer-backgrounding
```

在这个窗口登录网易云游戏并进游戏（登录态存在 profile 里，之后不用重登）。

### 3) 视觉模型 API（二选一）

| 方案 | 说明 |
|---|---|
| **智谱 GLM-4V-Flash（免费，实测在用）** | [open.bigmodel.cn](https://open.bigmodel.cn) 手机号注册 → API 密钥。`base_url: https://open.bigmodel.cn/api/paas/v4`，`model: glm-4v-flash` |
| 硅基流动 Qwen3-VL-8B | [cloud.siliconflow.cn](https://cloud.siliconflow.cn)，注意：新户赠额耗尽后所有视觉模型 402，需充值 |

把 key 填进 `config.yaml`（从 `config.example.yaml` 复制）。**config.yaml 含密钥，已被 .gitignore 排除，勿提交。**

### 4) 自检（都过了再跑主程序）

```powershell
python tools/selftest_capture.py config.yaml    # 存 logs\selftest.png，应是游戏画面
python tools/selftest_policy.py config.yaml     # 模型应回 JSON {thought, macro}
python tools/list_pages.py                      # 确认 CDP 能看到云游戏页面
python tools/input_test.py                      # 发一次点击+跳跃，测帧差验证输入
```

### 5) 开跑

```bat
run_agent.bat      # 或 .venv\Scripts\python -m agent.main config.yaml
```

- **F12 随时全局急停**（不需要窗口焦点）
- 决策日志：`logs\episode_YYYYmmdd_HHMMSS.jsonl`，每行 `{ts, frame, thought, macro, latency_ms}`
- OBS 录屏叠加 AI 内心戏：浏览器源 → 本地文件 → `overlay/index.html`（读 `overlay/state.json`）

---

## 动作 DSL（模型唯一允许输出的语言）

宏 = 分号分隔的步骤，冒号分隔参数。白名单在 `agent/actions.py`，非法内容被丢弃并替换为 `guard:1.0`。

| 宏 | 参数 | 说明 |
|---|---|---|
| `light` / `heavy` / `jump` / `heal` / `interact` / `confirm` / `lock` / `surge` | — | 单按一次（左键/F/空格/R/E/回车/中键/Q） |
| `attack:N` | N=1~5 | 连续轻击 N 下 |
| `dodge:方向` | forward/back/left/right/fl/fr/bl/br | Shift 闪避（含后摇；格挡中会自动松开右键、闪完恢复） |
| `move:方向:秒数` | 默认 1.1s | 按住方向键走，期间新宏到来立即让位 |
| `sprint:秒数` | 默认 1.2s | 按住 W+Shift 奔跑 |
| `turn:left|right` | — | 鼠标相对位移转视角 |
| `wait:秒数` | 上限 2s | 站桩 |
| `guard:秒数` | — | 按住右键格挡 |
| `parry_tap` | — | 蓝光反应：松开右键立刻再按一次（重新格挡判定） |
| `stance:秒数` | 默认 2s | **站桩格挡流核心**：按住右键不放 + 连按左键普攻，新宏立即让位 |
| `unblock` | — | 松开右键（战斗结束/赶路） |
| `combo:键,键,键` | 键名见下 | **快速顺序连招**（0.05s 按下/0.07s 间隔，慢了接不上） |
| `skill1` / `skill2` | — | 特殊技能：按住右键+F / 按住右键+左键 |
| `guard_attack:次数` | 默认 3 | 按住右键的同时连按左键 |
| `spam:动作:次数` | ≤6 | 连点同一键 |
| `qte:动作:次数` | 默认 8, ≤10 | QTE 狂按（0.04s/0.06s 极快节奏），屏幕提示哪个键按哪个 |
| `ui_recover` | — | 脱困：连点确认 + 左右移动 |

**键名对照**：`light`=鼠标左键(轻击) `heavy`=F(重击) `jump`=空格 `dodge`=Shift `parry`=鼠标右键(格挡) `lock`=鼠标中键 `heal`=R `interact`=E `confirm`=回车 `surge`=Q。
模型偶尔直接输出按键字母（F/左键/空格/重击…），`browser_input._norm()` 会做别名归一化。

---

## 战斗心法（实战调出来的规则，已写入 policy 提示词）

1. **一直按住右键格挡**：开局 `stance:3`（按住右键+不断左键普攻），之后每轮 `stance:2` 维持；右键由播放器线程保持按住，不会松。
2. **蓝光 → `parry_tap`**：敌人冒蓝光时松开右键马上再按一次（重新格挡判定）；蓝光绝不闪避。
3. **红光/红圈 → `dodge`**：Shift 闪避；红光挡不住，绝不格挡；闪完自动恢复按住右键。
4. **没锁定 → `lock`**：每次决策先看敌人身上有没有锁定标志，没有就按中键锁定再继续 stance。
5. **连招按屏幕提示**：教程写什么顺序就 `combo:` 什么顺序，每键只按一次、代码快速连按；QTE 用 `qte:` 狂按。
6. **大招亮了按 Q**：右下角杀气爆发图标充满 → `surge`。
7. **攻守平衡**：以 stance 站桩格挡普攻为主，不无脑走位，也不要纯防守僵住。
8. **战斗结束/赶路 → `unblock`** 再 move/sprint。

---

## 实战经验（每一坑都踩过）

1. **Python 3.12 没有 dxcam 轮子** → 抓屏换 `mss`（BitBlt，30fps 足够），接口保持一致。
2. **vgamepad 无 3.12 轮子且需要 ViGEmBus 驱动** → `controller.py` 改为惰性导入；云游戏走 cdp 后端完全用不到手柄。
3. **受限环境下 playwright 报 `EPERM mkdtemp`**（TEMP 目录不可写）→ 启动前把 `TMP`/`TEMP` 重定向到项目内 `tmp\`（`run_agent.bat` 已内置）。
4. **抓屏区域别写死** → 启动时用 CDP 在页面里 `video.getBoundingClientRect()` 自动探测视频区（`capture.region: auto`），窗口布局怎么变都跟得住。
5. **模型会把悬浮窗口当游戏画面**（曾把聊天窗、OBS 界面当成游戏提示来"阅读"）→ 录屏/悬浮窗放游戏画面外或最小化；抓屏只取视频区。
6. **暗场景被误判"加载中"** → 提示词明确：只有进度条/转圈/"载入中"文字才算加载；夜晚山洞是正常画面，禁止为此 wait。右下角"激活Windows"水印让模型忽略。
7. **连招接不上** → 单键间隔要 ≤0.07s（0.05s 按下/0.07s 间隔）；QTE 要 0.04s/0.06s 的连打速度。
8. **模型把聊天记录当教程**（见第 5 条）与**模型输出按键字母**（F→heavy）都要在输入层做归一化。
9. **模型免费额度耗尽 402** → 换智谱免费 GLM-4V-Flash；DeepSeek 官方 API 无视觉输入，不能看图出招。
10. **决策延迟与宏的衔接** → `move/sprint/stance` 在播放期间轮询队列，新宏一来立即让位，避免"播完 2 秒旧动作才反应"。

---

## 目录

```
├─ agent/           主循环 / 抓屏 / 决策 / 输入后端 / 宏解析
├─ tools/           自检脚本（抓屏、策略、CDP 列表、输入注入、只读链路演练）
├─ docs/            宏语法 + 给模型的提示词
├─ overlay/         OBS 浏览器源 HUD
├─ config.example.yaml   模板（复制成 config.yaml 填 key）
├─ run_agent.bat    一键启动（含 TMP 重定向 + F12 急停提示）
└─ 使用说明.md       小白版操作手册
```

## 合规

单机游戏、自己操控自己账号的云游戏、不读内存不开挂、只像人一样看屏幕按键。发视频前把账号 ID 糊掉。
