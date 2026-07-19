"""场景调度器:采集 -> 传统 CV 判定场景 -> MaaTouch 点击导航。

职责边界:本层只做"我在哪个界面、点哪、怎么在界面间跳转",用模板匹配(不碰大模型),
省资源。对战内的实时感知/决策是另一条链路(perception/decision)。

用法:
    with SceneController() as sc:
        sc.wait_scene("main_menu")
        sc.goto("in_battle")     # 自动点击"对战"进入一局
"""

from __future__ import annotations

import time
from collections import deque

from loguru import logger

from crplayer.scene.registry import EDGES, SCENES, TEMPLATES
from crplayer.scene.template import (
    REF_HEIGHT,
    REF_WIDTH,
    MatchResult,
    to_reference,
)


class SceneController:
    def __init__(
        self,
        serial: str | None = None,
        backend: str = "scrcpy",
        touch_backend: str = "adb",
    ):
        self.serial = serial
        self.backend = backend
        # 触控后端:默认 adb —— 本机(Android 16 国服)上 MaaTouch 注入不派发到游戏窗口,
        # 唯 adb input(带正确 displayId)稳定生效。详见 control/adb_input.py。
        self.touch_backend = touch_backend
        self._cap = None
        self._touch = None

    # —— 资源 ——
    def open(self) -> None:
        from crplayer.capture import open_capture
        from crplayer.control import open_touch

        self._cap = open_capture(self.backend, serial=self.serial)
        self._cap.open()
        self._touch = open_touch(self.touch_backend, serial=self.serial)
        self._touch.open()

    def close(self) -> None:
        if self._cap:
            self._cap.close()
            self._cap = None
        if self._touch:
            self._touch.close()
            self._touch = None

    def __enter__(self) -> SceneController:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # —— 采集 ——
    def grab_ref(self):
        """抓一帧并归一化到参考画布。"""
        frame = self._cap.grab()
        return to_reference(frame.image)

    # —— 坐标换算:参考画布像素 -> 设备像素 ——
    def _ref_to_device(self, x: int, y: int) -> tuple[int, int]:
        dx = int(x * self._touch.max_x / REF_WIDTH)
        dy = int(y * self._touch.max_y / REF_HEIGHT)
        return dx, dy

    # —— 匹配 ——
    def appear(self, template_name: str, ref_frame=None) -> MatchResult:
        tmpl = TEMPLATES[template_name]
        ref = ref_frame if ref_frame is not None else self.grab_ref()
        return tmpl.match(ref)

    def current_scene(self, ref_frame=None) -> str | None:
        ref = ref_frame if ref_frame is not None else self.grab_ref()
        for scene in SCENES.values():
            results = [TEMPLATES[m].match(ref).matched for m in scene.markers]
            hit = all(results) if scene.require_all else any(results)
            if hit:
                return scene.name
        return None

    def wait_scene(self, name: str, timeout: float = 30.0, interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.current_scene() == name:
                logger.info(f"到达场景: {name}")
                return True
            time.sleep(interval)
        logger.warning(f"等待场景 {name} 超时")
        return False

    # —— 状态确认(参考 SRC:动作前先确认所在场景)——
    def is_scene(self, name: str, ref_frame=None) -> bool:
        return self.current_scene(ref_frame=ref_frame) == name

    def is_in_battle(self, ref_frame=None) -> bool:
        """当前是否在对局中(左下角表情气泡常驻)。对局内任何操作前都应先过这一关。"""
        ref = ref_frame if ref_frame is not None else self.grab_ref()
        from crplayer.scene.registry import TEMPLATES

        return TEMPLATES["battle_emote"].match(ref).matched

    def assert_in_battle(self, ref_frame=None) -> None:
        """不在对局中就抛错,阻止把牌点到结算/菜单上(这次踩的坑)。"""
        if not self.is_in_battle(ref_frame=ref_frame):
            raise RuntimeError("当前不在对局中,拒绝执行对局内操作")

    def wait_until(self, template_name: str, timeout: float = 30.0, interval: float = 0.3) -> bool:
        """轮询直到某模板出现(SRC 的 wait_until_appear)。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.appear(template_name).matched:
                return True
            time.sleep(interval)
        return False

    def appear_then_click(self, template_name: str, ref_frame=None) -> bool:
        """出现才点(SRC 的 appear_then_click):等价于带存在性检查的 click。"""
        return self.click(template_name, ref_frame=ref_frame)

    # —— 对局内操作(务必先确认在对局中)——
    # 手牌 4 槽在参考画布(904x1280)的中心坐标,接入新设备/分辨率需校准。
    HAND_SLOTS_REF = [(287, 1139), (420, 1139), (550, 1139), (679, 1139)]

    def deploy_card(self, slot: int, target_ref: tuple[int, int], use_drag: bool = False) -> bool:
        """放牌:先确认在对局中,再"选牌槽 -> 落点"。target_ref 为参考画布坐标。

        这是这次教训的修复点——不确认状态就放牌,会把牌点到结算/菜单上。
        """
        ref = self.grab_ref()
        if not self.is_in_battle(ref_frame=ref):
            logger.warning("deploy_card 被拒:当前不在对局中")
            return False
        if not (0 <= slot < len(self.HAND_SLOTS_REF)):
            raise ValueError(f"手牌槽越界: {slot}")

        sx, sy = self._ref_to_device(*self.HAND_SLOTS_REF[slot])
        tx, ty = self._ref_to_device(*target_ref)
        if use_drag:
            self._touch.drag(sx, sy, tx, ty)
        else:
            self._touch.tap(sx, sy)
            time.sleep(0.15)
            self._touch.tap(tx, ty)
        logger.info(f"放牌: slot{slot} -> ref{target_ref}")
        return True

    # —— 点击 ——
    def click(self, template_name: str, ref_frame=None) -> bool:
        """匹配到模板则点击其目标点(参考坐标换算到设备)。返回是否点击。"""
        res = self.appear(template_name, ref_frame=ref_frame)
        if not res.matched:
            logger.debug(f"{template_name} 未出现(score={res.score:.3f}),不点击")
            return False
        dx, dy = self._ref_to_device(*res.click)
        self._touch.tap(dx, dy)
        logger.info(f"点击 {template_name} @ ref{res.click} -> dev({dx},{dy})")
        return True

    def click_until_gone(
        self, template_name: str, timeout: float = 10.0, interval: float = 0.6
    ) -> bool:
        """反复点击直到该模板消失(用于关弹窗/确认)。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.click(template_name):
                return True
            time.sleep(interval)
        return False

    # —— 导航 ——
    def goto(self, target: str, timeout: float = 60.0) -> bool:
        """从当前场景经导航图走到 target。每步点击一个按钮并等待目标场景出现。"""
        start = self.current_scene()
        if start is None:
            logger.warning("当前场景未知,无法导航")
            return False
        if start == target:
            return True

        path = self._bfs(start, target)
        if not path:
            logger.warning(f"找不到 {start} -> {target} 的路径")
            return False
        logger.info(f"导航路径: {' -> '.join(path)}")

        for i in range(len(path) - 1):
            frm, to = path[i], path[i + 1]
            btn = self._edge_button(frm, to)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self.current_scene() == to:
                    break
                self.click(btn)
                time.sleep(1.0)
            else:
                logger.warning(f"从 {frm} 点击 {btn} 未能到达 {to}")
                return False
        return True

    @staticmethod
    def _bfs(start: str, target: str) -> list[str] | None:
        graph: dict[str, list[str]] = {}
        for frm, _btn, to in EDGES:
            graph.setdefault(frm, []).append(to)
        q = deque([[start]])
        seen = {start}
        while q:
            path = q.popleft()
            if path[-1] == target:
                return path
            for nxt in graph.get(path[-1], []):
                if nxt not in seen:
                    seen.add(nxt)
                    q.append(path + [nxt])
        return None

    @staticmethod
    def _edge_button(frm: str, to: str) -> str:
        for a, btn, b in EDGES:
            if a == frm and b == to:
                return btn
        raise KeyError(f"无边 {frm}->{to}")
