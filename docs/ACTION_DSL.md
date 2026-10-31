# 宏语法（Action DSL）

模型唯一被允许输出的语言。解析器在 `agent/actions.py`，非法内容会被丢弃并替换成 `guard:1.0`。

| 宏 | 参数 | 说明 |
|---|---|---|
| `light` | — | 轻攻击一次 |
| `heavy` | — | 重攻击一次 |
| `attack:N` | N=1~5 | 连续轻击 N 下，间隔 0.1s |
| `jump` | — | 跳 |
| `parry` | — | 弹反（按下即走，不持续） |
| `dodge:dir` | dir | 朝 dir 闪避，含 0.35s 后摇 |
| `lock` | — | 锁定敌人 |
| `heal` | — | 吃药 |
| `interact` / `confirm` | — | 交互 / 确认 |
| `move:dir:secs` | dir, 秒 | 摇杆持续推某方向 |
| `wait:secs` | 秒 | 站着不动（要少用） |
| `guard:secs` | 秒 | 按住弹反/格挡键 |
| `ui_recover` | — | 菜单脱困：连点确认 + 左右摇杆 |

`dir` 取值：`forward back left right fl fr bl br`

一条宏最多 6 步，超过截断。示例：

```
dodge:left;attack:3
move:forward:0.8;lock;light
parry;attack:2;dodge:back
```

**调延时的小技巧**：如果 AI 总是在动作播完前就被打断，说明模型给的宏太长，
在 prompt 里加一句"最多 2 步"，比在代码里截断更自然。
