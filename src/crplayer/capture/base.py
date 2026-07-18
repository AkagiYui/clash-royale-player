"""采集源抽象接口。

视频采集(scrcpy)与触控执行(MaaTouch)是两条独立通道,这里只负责"拿到帧"。
每帧带时间戳,下游不要假设检测结果就是"当前时刻"(见架构文档阶段二延迟补偿)。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Frame:
    """一帧图像 + 采集时间戳。"""

    image: np.ndarray            # BGR, shape (H, W, 3), dtype=uint8
    timestamp: float = field(default_factory=time.time)

    @property
    def height(self) -> int:
        return int(self.image.shape[0])

    @property
    def width(self) -> int:
        return int(self.image.shape[1])


class CaptureSource(ABC):
    """采集源。用作上下文管理器,或手动 open()/close()。"""

    def __enter__(self) -> CaptureSource:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> None:  # noqa: B027 - 默认无需初始化
        """建立连接(可选)。"""

    @abstractmethod
    def grab(self) -> Frame:
        """抓取一帧(阻塞直到拿到)。"""

    def close(self) -> None:  # noqa: B027 - 默认无需清理
        """释放资源(可选)。"""
