"""Uma gravação em andamento: acumula int16 em disco e fecha em .npy + .json."""
from __future__ import annotations

import json

import numpy as np

from .storage import Store


class Recording:
    def __init__(self, store: Store, rid: str, meta: dict, target_samples: int):
        self.store = store
        self.id = rid
        self.meta = meta
        self.target = target_samples
        self.n = 0
        self.gaps: list[dict] = []
        self.clipped = 0
        self._f = open(store.raw_path(rid), "wb")

    @property
    def lost_packets(self) -> int:
        return sum(g["lost_packets"] for g in self.gaps)

    def write(self, raw: np.ndarray) -> bool:
        """Grava até completar o alvo. Devolve True quando chegou ao fim."""
        room = self.target - self.n
        if room > 0:
            chunk = raw[:room]
            self._f.write(np.ascontiguousarray(chunk, dtype="<i2").tobytes())
            self.n += len(chunk)
        return self.n >= self.target

    def mark_gap(self, lost_packets: int, samples_per_packet: int) -> None:
        self.gaps.append({
            "at_sample": self.n,
            "lost_packets": lost_packets,
            "lost_samples_est": lost_packets * samples_per_packet,
        })

    def cancel(self) -> None:
        self._f.close()
        self.store.raw_path(self.id).unlink(missing_ok=True)

    def finish(self, stopped_by: str) -> dict | None:
        """Converte para .npy e grava os metadados. None se não houve amostras."""
        self._f.close()
        raw_path = self.store.raw_path(self.id)
        if self.n == 0:
            raw_path.unlink(missing_ok=True)
            return None
        arr = np.fromfile(raw_path, dtype="<i2").reshape(-1, 3)
        np.save(self.store.npy_path(self.id), arr)
        raw_path.unlink(missing_ok=True)

        m = self.meta
        fs = m["fs"]
        duration = len(arr) / fs
        useful = duration - 2 * m["trim_s"]
        issues = []
        if stopped_by == "disconnect":
            issues.append("interrompida: dispositivo desconectou")
        if self.lost_packets:
            issues.append(f"{self.lost_packets} pacotes perdidos")
        if self.clipped:
            issues.append(f"{self.clipped} amostras saturadas")
        if useful < 10:
            issues.append(f"poucos dados úteis ({max(useful, 0):.0f} s)")
        m.update({
            "n_samples": int(len(arr)),
            "duration_s": round(duration, 3),
            "stopped_by": stopped_by,
            "lost_packets": self.lost_packets,
            "gaps": self.gaps,
            "clipped": self.clipped,
            "issues": issues,
            "quality": "ok" if not issues else "warn",
        })
        self.store.meta_path(self.id).write_text(json.dumps(m, indent=2, ensure_ascii=False), "utf-8")
        return m
