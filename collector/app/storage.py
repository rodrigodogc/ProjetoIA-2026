"""Persistência: configuração (classes/velocidades) e gravações em disco."""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")

DEFAULT_CONFIG = {
    "classes": ["parado", "normal", "desbalanceado_leve", "desbalanceado_forte", "folga", "desalinhado"],
    "speeds": ["baixa", "media", "alta"],
    "targets": {"sessions": 3, "duration_s": 90},
    "trim_s": 2.0,
}


def slug(text: str, default: str = "") -> str:
    """'Desbalanceado Leve' -> 'desbalanceado_leve' (sem acento, só a-z0-9_)."""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s[:40] or default


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.rec_dir = root / "recordings"
        self.rec_dir.mkdir(parents=True, exist_ok=True)
        self.cfg_path = root / "config.json"

    # ---- configuração ----
    def load_config(self) -> dict:
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        if self.cfg_path.exists():
            try:
                user = json.loads(self.cfg_path.read_text("utf-8"))
                cfg.update({k: v for k, v in user.items() if k in cfg})
            except (OSError, ValueError):
                pass
        return cfg

    def save_config(self, cfg: dict) -> None:
        self.cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")

    def ensure_in_config(self, label: str, speed: str) -> None:
        cfg = self.load_config()
        changed = False
        if label and label not in cfg["classes"]:
            cfg["classes"].append(label)
            changed = True
        if speed and speed not in cfg["speeds"]:
            cfg["speeds"].append(speed)
            changed = True
        if changed:
            self.save_config(cfg)

    # ---- caminhos ----
    def meta_path(self, rid: str) -> Path:
        return self.rec_dir / f"{rid}.json"

    def npy_path(self, rid: str) -> Path:
        return self.rec_dir / f"{rid}.npy"

    def raw_path(self, rid: str) -> Path:
        return self.rec_dir / f"{rid}.raw"

    # ---- gravações ----
    def new_id(self, label: str, speed: str, session: str, now: datetime) -> str:
        base = f"{label}_{speed or 'na'}_s{session}_{now:%Y%m%d-%H%M%S}"
        rid, i = base, 2
        while self.meta_path(rid).exists() or self.raw_path(rid).exists():
            rid, i = f"{base}-{i}", i + 1
        return rid

    def get(self, rid: str) -> dict | None:
        if not ID_RE.match(rid) or not self.meta_path(rid).exists():
            return None
        try:
            return json.loads(self.meta_path(rid).read_text("utf-8"))
        except (OSError, ValueError):
            return None

    def list(self) -> list[dict]:
        out = []
        for p in self.rec_dir.glob("*.json"):
            try:
                out.append(json.loads(p.read_text("utf-8")))
            except (OSError, ValueError):
                continue
        out.sort(key=lambda m: m.get("started_at", ""), reverse=True)
        return out

    def patch(self, rid: str, fields: dict) -> dict | None:
        meta = self.get(rid)
        if meta is None:
            return None
        meta.update(fields)
        self.meta_path(rid).write_text(json.dumps(meta, indent=2, ensure_ascii=False), "utf-8")
        return meta

    def delete(self, rid: str) -> bool:
        if not ID_RE.match(rid) or not self.meta_path(rid).exists():
            return False
        for p in (self.meta_path(rid), self.npy_path(rid), self.raw_path(rid)):
            p.unlink(missing_ok=True)
        return True
