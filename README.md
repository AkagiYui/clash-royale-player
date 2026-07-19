# clash-royale-player

感知与决策解耦的皇室战争(Clash Royale)自动游玩 AI。参考路线接近 AlphaStar/OpenAI Five,
**不走 VLA 端到端**:感知层输出干净的结构化状态,决策层完全不碰像素。

完整架构见 [`皇室战争自动玩AI-架构规划.md`](皇室战争自动玩AI-架构规划.md)。

> 当前实现范围:**采集链路 + 感知层(战场信息识别)**,输出结构化 JSON 状态。
> 决策层与动作执行(MaaTouch)为后续阶段。

## 环境

- macOS(主)/ Linux(辅);游戏跑在安卓手机上,电脑只做 CV 与决策。
- Python 3.11–3.12(用 `uv` 管理,已锁定 `.python-version=3.12`)。
- 系统工具:`adb`(必需)、`scrcpy` + `ffmpeg`(低延迟采集后端需要)。

```bash
brew install scrcpy ffmpeg          # 系统依赖
uv sync                             # Python 依赖(拉入 torch/ultralytics,首次较慢)
uv sync --extra ocr                 # 可选:OCR(计时器/比分)
```

MaaTouch 二进制放在 `bin/maatouch`(不入库;从
[MaaTouch releases](https://github.com/MaaAssistantArknights/MaaTouch/releases) 下载)。

## 目录结构

```
config/           # 可插拔配置:layout.yaml(ROI 比例)、cards.yaml(卡牌数值)
src/crplayer/
  capture/        # 采集层:adb screencap / scrcpy 视频流(scrcpy-server + ffmpeg 自实现)
  perception/     # 感知层:归一化 / 圣水 / 手牌 / 塔血 / 单位检测(YOLO) / 计时器 / 阶段
  control/        # 触控执行:MaaTouch(常驻 socket,最贴近真实物理触控)
  ui/             # UI 层级守卫:uiautomator2(检测游戏退出 / 弹窗)
  state/          # 结构化状态数据模型(schema.py)
  cli.py          # 命令行入口
bin/maatouch      # MaaTouch 二进制(不入库)
models/           # YOLO 权重(*.pt,不入库)
data/             # 采集/数据集/卡牌模板(不入库)
tests/
```

三条通道相互独立:**scrcpy 采集(视频) · MaaTouch 执行(触控) · uiautomator2(UI 状态)**。

## 使用

```bash
# 列出 adb 设备
uv run crplayer devices

# 抓一帧存盘(data/captures/)
uv run crplayer capture -o shot.png

# 对截图跑感知,打印 JSON 状态
uv run crplayer perceive shot.png

# 校准:叠加 ROI 框 + 战场网格,人工核对 layout.yaml
uv run crplayer calibrate shot.png

# 从设备连续抓帧 + 感知,输出 JSON 流(默认 scrcpy 低延迟采集)
uv run crplayer live --fps 2

# 用 scrcpy 后端抓一帧
uv run crplayer capture --backend scrcpy -o shot.png

# UI 状态(前台包 / 是否在游戏 / 弹窗),检测游戏退出或弹窗
uv run crplayer uistate

# 触控注入(设备像素坐标)。默认后端 adb —— 本机(Android 16 国服)唯一稳定派发到
# 游戏窗口的注入路径;MaaTouch 注入不派发到游戏窗口(见 control/adb_input.py 说明)。
uv run crplayer tap 1200 1700
uv run crplayer swipe 1200 2400 1200 1600 --duration 300
uv run crplayer tap 1200 1700 --touch maatouch   # 显式换后端(adb / maatouch / scrcpy)

# 场景识别(传统 CV,不用大模型):main_menu / matchmaking / in_battle / battle_end
uv run crplayer scene                       # 打印当前场景
uv run crplayer scene --goto matchmaking    # 主菜单点"对战"进入匹配
```

## 触控后端

`control/` 有三条独立注入通道,经 `open_touch(backend)` 选择,默认 **adb**:

| 后端 | 机制 | 本机(OPPO / Android 16) |
|------|------|--------------------------|
| `adb` | `adb shell input`(InputManager,带正确 displayId) | ✅ 稳定 |
| `maatouch` | 常驻 app_process,反射 injectInputEvent | ❌ 事件不派发到游戏窗口(见下) |
| `scrcpy` | scrcpy 控制 socket(注入前 setDisplayId) | ❌ 当前实现未注入(P:0/1),待调试 |

> **MaaTouch 不通根因(已对照官方源码求证,与反外挂无关、别的设备没有):**
> MaaTouch 的 `Controller.java` 构造 MotionEvent 时**从不调用 `setDisplayId`**,又用
> `INJECT_MODE_ASYNC` 静默注入;Android 12+ 的 InputDispatcher 会丢弃无有效目标显示的
> 注入事件(logcat `no touched window on display`),但指针叠层仍能看到 → "叠层有、
> 游戏无反应"。scrcpy 早已用反射 `InputEvent.setDisplayId(displayId)` 解决同类问题
> ([scrcpy#3186](https://github.com/Genymobile/scrcpy/issues/3186)),MaaTouch 至今未跟进;
> MAA 主项目对多显示器仅在 screencap 层用 `-d` 指定,与注入无关。`adb`/`scrcpy` 后端都带
> 有效 displayId 故可用。evdev 直写因 SELinux 不可用(需 root)。详见
> `src/crplayer/control/adb_input.py` 顶部说明。

## 感知层输出(GameState)

每帧输出一个 JSON:圣水、手牌(4+下一张)、六座塔血量比例、场上单位
(含阵营/动作/护盾/地空等状态维度)、计时器、游戏阶段,以及采集时间戳
(供后续延迟补偿使用)。

## 待办 / 后续阶段

- **单位检测需要皇室战争专用 YOLO 权重**:放入 `models/*.pt` 即自动生效
  (未提供时检测返回空,其余链路照常)。数据/标注参考 KataCR 方案。
- 手牌识别当前为模板匹配:把卡牌模板 PNG 放入 `data/card_templates/<name>.png`
  即可启用;后续可替换为小型 CNN。
- `layout.yaml` 的 ROI 比例为经验初值,接入真机后用 `crplayer calibrate` 校准。
- 跨帧跟踪(SORT/ByteTrack)、延迟补偿、决策层、MaaTouch 动作执行:后续阶段。
