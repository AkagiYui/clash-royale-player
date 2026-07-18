"""场上单位检测 + 定位 —— YOLOv8/v11(Ultralytics + PyTorch)。

设备自动选择:macOS 用 MPS,有 CUDA 用 CUDA,否则 CPU(架构文档技术栈选型)。
需要一份皇室战争专用权重(models/*.pt)。未提供时检测返回空列表,但整条链路仍可跑通
——换上训练好的权重即可,无需改动其它代码。

后续可导出 Core ML(macOS ANE 加速)/ ONNX,推理部署路径切换不影响本接口。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from crplayer.perception.layout import Layout
from crplayer.state.schema import Action, BBox, GridPos, Side, Unit

_MODELS_DIR = Path(__file__).resolve().parents[3] / "models"


def _pick_device(explicit: str | None) -> str:
    if explicit:
        return explicit
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return "mps"
    except Exception:  # pragma: no cover - torch 缺失/异常时回退
        pass
    return "cpu"


class UnitDetector:
    def __init__(
        self,
        model_path: str | Path | None = None,
        device: str | None = None,
        conf: float = 0.25,
    ):
        self.conf = conf
        self.device = _pick_device(device)
        self.model = None
        self._names: dict[int, str] = {}

        path = self._resolve_model_path(model_path)
        if path is None:
            logger.warning(
                "未找到皇室战争检测权重(models/*.pt)。单位检测将返回空——"
                "训练/放入权重后即可自动生效。"
            )
            return

        from ultralytics import YOLO

        self.model = YOLO(str(path))
        self._names = dict(self.model.names)
        logger.info(f"已加载检测权重 {path.name},device={self.device},类别数={len(self._names)}")

    @staticmethod
    def _resolve_model_path(model_path: str | Path | None) -> Path | None:
        if model_path:
            p = Path(model_path)
            return p if p.exists() else None
        # 约定:自动挑 models/ 下第一个 .pt
        if _MODELS_DIR.exists():
            cands = sorted(_MODELS_DIR.glob("*.pt"))
            if cands:
                return cands[0]
        return None

    def detect(self, canvas, layout: Layout) -> list[Unit]:
        """在归一化画布上检测单位,返回归一化坐标 + 逻辑网格的 Unit 列表。"""
        if self.model is None:
            return []

        h, w = canvas.shape[:2]
        results = self.model.predict(
            canvas, conf=self.conf, device=self.device, verbose=False
        )
        arena = layout.roi("arena", "roi")
        cols = int(layout.get("arena", "grid_cols", default=18))
        rows = int(layout.get("arena", "grid_rows", default=32))

        units: list[Unit] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            for b in boxes:
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0].tolist())
                cls_id = int(b.cls[0])
                conf = float(b.conf[0])
                name = self._names.get(cls_id, str(cls_id))

                bbox = BBox(x1 / w, y1 / h, x2 / w, y2 / h)
                grid = self._to_grid(bbox.cx, bbox.cy, arena, cols, rows)
                side = self._infer_side(bbox.cy, arena)
                units.append(
                    Unit(
                        name=name,
                        bbox=bbox,
                        confidence=round(conf, 3),
                        grid=grid,
                        side=side,
                        action=Action.UNKNOWN,
                    )
                )
        return units

    @staticmethod
    def _to_grid(cx: float, cy: float, arena, cols: int, rows: int) -> GridPos | None:
        """归一化坐标 -> 逻辑网格(以竞技场 ROI 为参照)。"""
        u = (cx - arena.x) / arena.w if arena.w else 0.0
        v = (cy - arena.y) / arena.h if arena.h else 0.0
        return GridPos(col=round(u * cols, 2), row=round(v * rows, 2))

    @staticmethod
    def _infer_side(cy: float, arena) -> Side:
        """启发式:竞技场上半为敌方,下半为己方。训练好的模型应直接输出阵营,
        届时可用检测结果覆盖本推断。"""
        mid = arena.y + arena.h / 2.0
        return Side.ENEMY if cy < mid else Side.ALLY
