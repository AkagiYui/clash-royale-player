"""UI 层级状态守卫(uiautomator2)。

用途:感知/决策主循环之外的"看门狗"——检测游戏是否还在前台、是否弹出了系统/游戏弹窗
(更新提示、ANR、广告、断线重连等)。这类事件靠像素 CV 不可靠,用 Android 无障碍层级
(uiautomator)读文本/按钮最稳。

与 scrcpy 采集、MaaTouch 执行相互独立;按需调用,不必每帧都 dump(dump 层级有开销)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger
from lxml import etree

# 皇室战争的两个包名:国际服 / 腾讯国服
CR_PACKAGES = {
    "com.supercell.clashroyale",
    "com.tencent.tmgp.supercell.clashroyale",
}


@dataclass
class UiStatus:
    """一次 UI 状态快照。"""

    package: str = ""
    activity: str = ""
    in_game: bool = False           # 前台是否为皇室战争
    texts: list[str] = field(default_factory=list)     # 屏幕上可见文本
    clickable_texts: list[str] = field(default_factory=list)  # 可点击控件的文本(多半是弹窗按钮)

    @property
    def likely_popup(self) -> bool:
        """在游戏内却出现了一批可点击文本按钮,通常意味着弹窗遮挡。"""
        return self.in_game and len(self.clickable_texts) > 0


class UiGuard:
    def __init__(self, serial: str | None = None, cr_packages: set[str] | None = None):
        self.serial = serial
        self.cr_packages = cr_packages or CR_PACKAGES
        self._d = None

    def connect(self):
        if self._d is None:
            import uiautomator2 as u2

            self._d = u2.connect(self.serial) if self.serial else u2.connect()
            logger.info("uiautomator2 已连接")
        return self._d

    def status(self, *, with_texts: bool = True) -> UiStatus:
        """采集一次 UI 状态。with_texts=False 时只查前台包(更快)。"""
        d = self.connect()
        cur = d.app_current()
        pkg = cur.get("package", "")
        st = UiStatus(
            package=pkg,
            activity=cur.get("activity", ""),
            in_game=pkg in self.cr_packages,
        )
        if with_texts:
            st.texts, st.clickable_texts = self._scrape_texts(d)
        return st

    @staticmethod
    def _scrape_texts(d) -> tuple[list[str], list[str]]:
        try:
            xml = d.dump_hierarchy()
        except Exception as e:  # pragma: no cover
            logger.debug(f"dump_hierarchy 失败: {e}")
            return [], []
        try:
            root = etree.fromstring(xml.encode("utf-8"))
        except Exception:  # pragma: no cover
            return [], []

        texts: list[str] = []
        clickable: list[str] = []
        for node in root.iter("node"):
            label = (node.get("text") or "").strip() or (node.get("content-desc") or "").strip()
            if not label:
                continue
            texts.append(label)
            if node.get("clickable") == "true":
                clickable.append(label)
        # 去重保序
        return list(dict.fromkeys(texts)), list(dict.fromkeys(clickable))

    # —— 便捷动作 ——
    def wait_game_foreground(self, timeout: float = 30.0, interval: float = 1.0) -> bool:
        """轮询等待皇室战争回到前台(如刚从弹窗/桌面切回)。"""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.status(with_texts=False).in_game:
                return True
            time.sleep(interval)
        return False

    def tap_text(self, text: str) -> bool:
        """点击含指定文本的控件(用于关掉已知弹窗,如"取消"/"关闭")。成功返回 True。"""
        d = self.connect()
        el = d(text=text)
        if el.exists:
            el.click()
            return True
        return False
