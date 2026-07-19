"""crplayer 命令行入口。

    crplayer devices                     # 列出 adb 设备
    crplayer capture [-o out.png]        # 抓一帧存盘
    crplayer perceive <image>            # 对图片跑感知,打印 JSON 状态
    crplayer live [--fps 2]              # 从设备连续抓帧+感知,打印 JSON 流
    crplayer calibrate <image> [-o ...]  # 叠加 ROI/网格辅助校准 layout.yaml
"""

from __future__ import annotations

import time
from pathlib import Path

import typer
from loguru import logger

app = typer.Typer(add_completion=False, help="皇室战争感知层 CLI")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPTURES_DIR = _REPO_ROOT / "data" / "captures"


@app.command()
def devices() -> None:
    """列出已连接的 adb 设备。"""
    import adbutils

    lst = adbutils.adb.device_list()
    if not lst:
        typer.echo("未检测到设备。请连接安卓设备并开启 USB 调试。")
        raise typer.Exit(1)
    for d in lst:
        info = d.prop.model if hasattr(d, "prop") else ""
        typer.echo(f"{d.serial}\t{info}")


@app.command()
def capture(
    output: Path = typer.Option(None, "-o", "--output", help="输出路径(默认 data/captures/)"),
    serial: str = typer.Option(None, "--serial", help="设备 serial(多设备时必填)"),
    backend: str = typer.Option("adb", "--backend", help="采集后端: adb / scrcpy"),
) -> None:
    """从设备抓取一帧并保存。"""
    import cv2

    from crplayer.capture import open_capture

    with open_capture(backend, serial=serial) as cap:
        frame = cap.grab()

    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    out = output or (_CAPTURES_DIR / f"cap_{int(frame.timestamp)}.png")
    cv2.imwrite(str(out), frame.image)
    typer.echo(f"已保存 {out}  ({frame.width}x{frame.height})")


@app.command()
def perceive(
    image: Path = typer.Argument(..., help="输入截图路径"),
    model: Path = typer.Option(None, "--model", help="YOLO 权重路径(默认自动挑 models/*.pt)"),
    no_ocr: bool = typer.Option(False, "--no-ocr", help="禁用 OCR(计时器)"),
    compact: bool = typer.Option(False, "--compact", help="单行紧凑 JSON"),
) -> None:
    """对一张截图运行感知层,打印结构化 JSON 状态。"""
    import cv2

    from crplayer.perception import PerceptionPipeline

    img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if img is None:
        typer.echo(f"无法读取图片: {image}")
        raise typer.Exit(1)

    pipe = PerceptionPipeline(model_path=model, enable_ocr=not no_ocr)
    t0 = time.time()
    state = pipe.process_image(img, timestamp=time.time())
    dt = (time.time() - t0) * 1000
    logger.info(f"感知耗时 {dt:.0f} ms")
    typer.echo(state.to_json(indent=None if compact else 2))


@app.command()
def live(
    fps: float = typer.Option(2.0, "--fps", help="目标帧率"),
    serial: str = typer.Option(None, "--serial", help="设备 serial"),
    model: Path = typer.Option(None, "--model", help="YOLO 权重路径"),
    no_ocr: bool = typer.Option(True, "--no-ocr/--ocr", help="是否禁用 OCR(默认禁用以提速)"),
    backend: str = typer.Option("scrcpy", "--backend", help="采集后端: scrcpy(低延迟) / adb"),
) -> None:
    """从设备连续抓帧并输出 JSON 状态流(每行一个状态)。Ctrl-C 退出。"""
    from crplayer.capture import open_capture
    from crplayer.perception import PerceptionPipeline

    pipe = PerceptionPipeline(model_path=model, enable_ocr=not no_ocr)
    interval = 1.0 / max(fps, 0.1)
    frame_id = 0
    with open_capture(backend, serial=serial) as cap:
        try:
            while True:
                t0 = time.time()
                frame = cap.grab()
                state = pipe.process(frame, frame_id=frame_id)
                print(state.to_json(indent=None), flush=True)
                frame_id += 1
                sleep = interval - (time.time() - t0)
                if sleep > 0:
                    time.sleep(sleep)
        except KeyboardInterrupt:
            typer.echo("已停止。", err=True)


@app.command()
def calibrate(
    image: Path = typer.Argument(..., help="输入截图路径"),
    output: Path = typer.Option(None, "-o", "--output", help="标注输出(默认 <image>.calib.png)"),
) -> None:
    """在截图上叠加各 ROI 框与战场网格,便于人工核对/微调 layout.yaml。"""
    import cv2

    from crplayer.perception.layout import Layout
    from crplayer.perception.normalize import to_canvas

    img = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if img is None:
        typer.echo(f"无法读取图片: {image}")
        raise typer.Exit(1)

    layout = Layout.load()
    canvas = to_canvas(img, layout.canvas_wh)
    h, w = canvas.shape[:2]

    def draw_roi(keys, color, label):
        roi = layout.roi(*keys)
        x1, y1, x2, y2 = roi.to_pixels(w, h)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        cv2.putText(canvas, label, (x1, max(y1 - 4, 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    draw_roi(("elixir", "roi"), (255, 0, 255), "elixir")
    draw_roi(("hand", "slots_roi"), (0, 255, 255), "hand")
    draw_roi(("hand", "next_roi"), (0, 200, 255), "next")
    draw_roi(("timer", "roi"), (0, 255, 0), "timer")
    draw_roi(("arena", "roi"), (255, 128, 0), "arena")

    # 战场网格
    arena = layout.roi("arena", "roi")
    ax1, ay1, ax2, ay2 = arena.to_pixels(w, h)
    cols = int(layout.get("arena", "grid_cols", default=18))
    rows = int(layout.get("arena", "grid_rows", default=32))
    for c in range(cols + 1):
        x = int(ax1 + (ax2 - ax1) * c / cols)
        cv2.line(canvas, (x, ay1), (x, ay2), (80, 80, 80), 1)
    for r in range(rows + 1):
        y = int(ay1 + (ay2 - ay1) * r / rows)
        cv2.line(canvas, (ax1, y), (ax2, y), (80, 80, 80), 1)

    # 塔锚点
    towers = layout.get("towers", default={}) or {}
    for key, anchor in towers.items():
        if key == "hp_bar" or not isinstance(anchor, list):
            continue
        px, py = int(anchor[0] * w), int(anchor[1] * h)
        cv2.circle(canvas, (px, py), 5, (0, 0, 255), -1)

    out = output or image.with_suffix(".calib.png")
    cv2.imwrite(str(out), canvas)
    typer.echo(f"已保存标注图 {out}")


@app.command()
def uistate(
    serial: str = typer.Option(None, "--serial", help="设备 serial"),
) -> None:
    """打印 uiautomator2 采集的 UI 状态(前台包 / 是否在游戏 / 弹窗文本)。"""
    from crplayer.ui import UiGuard

    st = UiGuard(serial=serial).status()
    typer.echo(f"package : {st.package}")
    typer.echo(f"activity: {st.activity}")
    typer.echo(f"in_game : {st.in_game}   likely_popup: {st.likely_popup}")
    if st.clickable_texts:
        typer.echo(f"可点击控件(疑似弹窗按钮): {st.clickable_texts}")
    if st.texts:
        typer.echo(f"屏幕文本: {st.texts[:20]}")
    elif st.in_game:
        typer.echo("(游戏为自绘画面,无 Android 视图文本——属正常)")


@app.command()
def scene(
    serial: str = typer.Option(None, "--serial", help="设备 serial"),
    backend: str = typer.Option("scrcpy", "--backend", help="采集后端"),
    touch: str = typer.Option("adb", "--touch", help="触控后端: adb / maatouch / scrcpy"),
    goto: str = typer.Option(None, "--goto", help="导航到目标场景(如 in_battle)"),
) -> None:
    """场景调度:识别当前场景(传统 CV),或用 --goto 沿导航图跳转。"""
    from crplayer.scene import SceneController

    with SceneController(serial=serial, backend=backend, touch_backend=touch) as sc:
        cur = sc.current_scene()
        typer.echo(f"当前场景: {cur}")
        if goto:
            ok = sc.goto(goto)
            typer.echo(f"导航到 {goto}: {'成功' if ok else '失败'}")


@app.command()
def tap(
    x: int = typer.Argument(..., help="设备像素 X"),
    y: int = typer.Argument(..., help="设备像素 Y"),
    serial: str = typer.Option(None, "--serial", help="设备 serial"),
    touch: str = typer.Option("adb", "--touch", help="触控后端: adb / maatouch / scrcpy"),
) -> None:
    """在设备像素坐标点击(测试触控注入)。默认 adb(本机唯一稳定派发到游戏窗口的路径)。"""
    from crplayer.control import open_touch

    with open_touch(touch, serial=serial) as c:
        c.tap(x, y)
    typer.echo(f"已点击 ({x}, {y}) via {touch}")


@app.command()
def swipe(
    x1: int = typer.Argument(...),
    y1: int = typer.Argument(...),
    x2: int = typer.Argument(...),
    y2: int = typer.Argument(...),
    duration: int = typer.Option(300, "--duration", help="拖拽时长 ms"),
    serial: str = typer.Option(None, "--serial", help="设备 serial"),
    touch: str = typer.Option("adb", "--touch", help="触控后端: adb / maatouch / scrcpy"),
) -> None:
    """拖拽(测试)。默认 adb。"""
    from crplayer.control import open_touch

    with open_touch(touch, serial=serial) as c:
        c.swipe(x1, y1, x2, y2, duration_ms=duration)
    typer.echo(f"已拖拽 ({x1},{y1}) -> ({x2},{y2}) via {touch}")


if __name__ == "__main__":
    app()
