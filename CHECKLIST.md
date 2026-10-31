# 执行清单（给 AI 助手：按顺序做，每步都要验证通过再下一步）

## 阶段 0.5：云游戏确认（网页版必须先做）
- [ ] 确认游戏跑在浏览器里，且是**无边框/窗口化**能正常显示（云游戏本身就是窗口，OK）
- [ ] 进游戏 → 设置 → 看是"手柄模式"还是"键鼠模式"
- [ ] **先测手柄**：`python tools/selftest_controller.py`，角色有反应 → `input.backend: gamepad`，跳过 CDP
- [ ] 手柄没反应 → 关掉游戏内手柄模式，改用键盘，进入下一步
- [ ] 用带调试端口的 Chrome 重新登录云游戏（命令见 README 9.1）
- [ ] `python tools/attach_browser.py` 能看到云游戏那个标签页
- [ ] `python tools/attach_browser.py --test`，角色有反应 → CDP 通路成立
- [ ] 把云游戏里的键位抄进 `config.yaml` 的 `input.key_map` / `move_keys`

## 阶段 0：环境
- [ ] 确认系统是 Windows 10/11 x64，`python --version` 是 3.11.x
- [ ] 安装 ViGEmBus 驱动，**重启电脑**
- [ ] `python -m venv .venv` → `.venv\Scripts\activate`
- [ ] `pip install -r requirements.txt`
- [ ] 验证：`python -c "import dxcam, vgamepad, cv2; print('ok')"` 输出 ok

## 阶段 1：抓屏可用
- [ ] 游戏启动，画面设置改成 **窗口化无边框 1920x1080**，关垂直同步
- [ ] `python tools/selftest_capture.py`
- [ ] 打开生成的 `logs/selftest.png`，必须是清晰的游戏画面
  - 全黑 → 游戏还是独占全屏 / 抓屏区域坐标不对 / 显卡驱动太旧
  - 半黑 → region 参数没设对，先用 None 全屏

## 阶段 2：手柄可用（关键一步）
- [ ] `python tools/selftest_controller.py`
- [ ] 观察：游戏角色是否做出了"跳跃/攻击"动作
- [ ] 打开"设置 → 蓝牙和其他设备 → 设备和打印机"，应看到 **XBOX 360 Controller for Windows**
- [ ] 若游戏无反应：先用手柄图标右键"游戏控制器设置"确认能读到；再检查游戏内是否切到了键鼠模式（动一下真鼠标再切回）

## 阶段 3：按键映射
- [ ] 在游戏设置里查看每个动作绑定的键，记下来
- [ ] 填进 `config.yaml` 的 `controller.button_map`：
      jump / light / heavy / dodge / parry / lock / heal / interact / confirm
- [ ] 每个动作单独跑一次 `tools/selftest_controller.py --action light` 验证

## 阶段 4：模型可用
- [ ] 起模型服务，`curl http://127.0.0.1:8000/v1/models` 能返回模型名
- [ ] 填 `config.yaml` 的 `policy.base_url / model / api_key`
- [ ] `python tools/selftest_policy.py` → 应打印一段 JSON：`{"thought":..., "macro":"..."}`
- [ ] 若模型不认识画面：换 UI-TARS-1.5，它专门为 GUI/游戏截图训练；Qwen2.5-VL 也行但要在 prompt 里给更多描述

## 阶段 5：闭环
- [ ] 游戏在前台，`python -m agent.main config.yaml`
- [ ] 前 60 秒只观察，不改参数：记录三条指标 —— 决策延迟、是否有连续 3 次相同宏、是否卡在同画面
- [ ] 按 `capture.model_every` 从 1.5s 往 0.8s 逐步收紧，直到动作衔接自然
- [ ] 连续跑 10 分钟不崩，进入下一阶段

## 阶段 6：出片
- [ ] OBS 添加"浏览器源"→ 本地文件 → `overlay/index.html`，尺寸 900x160，放左下角
- [ ] 主画面 + HUD + 摄像头位（可选），录 60fps，码率 8000kbps
- [ ] 录 30~40 分钟素材，按 `logs/*.jsonl` 找 thought 有趣的片段剪
- [ ] 片头必须 3 秒内出现"人不在电脑前"的镜头（空椅子/走开的背影），这是点击率关键

## 常见坑速查
1. 抓屏全黑 → 独占全屏，改无边框
2. 手柄没反应 → ViGEmBus 没重启 / 游戏用键鼠模式 / Steam 输入干扰（关掉 Steam 输入）
3. AI 疯狂转圈 → prompt 缺"目标"，补一行"当前目标：向前推进，找到敌人并击杀"
4. 模型返回带 markdown ```json → 解析器要容错，先正则提 `{...}`
5. 主循环卡死 → 所有网络调用必须有 timeout，播放器线程与决策线程分离
6. 显存不够 → 用 4bit 量化 7B，或直接走云端 API
