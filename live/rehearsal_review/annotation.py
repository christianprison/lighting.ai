"""annotation.py — Bar/Part annotation data model and file I/O.

Manuelle Takt- und Part-Annotationen für Probe-Aufnahmen.  Die Annotationen
werden neben dem JSONL-Event-Log gespeichert:

    {session_stem}_annotations.json

Format::

    {
      "<song_id>": {
        "song_id":   "<song_id>",
        "song_name": "<name>",
        "markers": [
          {"t": 1.234, "bar_num": 1, "part_name": "Intro"},
          {"t": 3.800, "bar_num": 2, "part_name": ""},
          ...
        ]
      },
      ...
    }

Alle Zeiten (``t``) sind **relativ zum Segment-Start** (= 0 = erster
Takt des Songs in der Aufnahme), nicht relativ zum WAV-Anfang.
Der Segment-Offset (= start_t des SongSegment) wird separat gespeichert.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class BarMarker:
    """Manuell gesetzter Taktgrenzen-Marker."""
    t: float          # Sekunden seit Segment-Start (= relative Zeit im Song)
    bar_num: int      # 1-basiert, wird automatisch vergeben
    part_name: str = ""   # nicht leer → dieser Takt ist auch ein Part-Start


@dataclass
class SongAnnotation:
    """Alle Takt-Annotationen für einen Song innerhalb einer Session."""
    song_id: str
    song_name: str
    segment_start_t: float = 0.0   # WAV-Offset des Segment-Starts (Sekunden)
    start_bar_num: int = 1         # Takt-Nummer des ersten Markers in der DB
    markers: list[BarMarker] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Marker-Verwaltung
    # ------------------------------------------------------------------

    def add_marker(self, t: float, part_name: str = "") -> BarMarker:
        """Fügt einen Takt-Marker bei Zeit *t* ein.

        Hält die Liste nach *t* sortiert und nummeriert alle Marker danach neu.
        """
        # Einfügeposition finden (sortiert nach t)
        idx = len(self.markers)
        for i, m in enumerate(self.markers):
            if m.t > t:
                idx = i
                break
        marker = BarMarker(t=t, bar_num=0, part_name=part_name)
        self.markers.insert(idx, marker)
        self._renumber()
        return marker

    def remove_nearest(
        self, t: float, max_dist_sec: float = 1.0
    ) -> Optional[BarMarker]:
        """Entfernt den Marker, der *t* am nächsten liegt.

        Gibt den entfernten Marker zurück oder None wenn keiner in Reichweite.
        """
        if not self.markers:
            return None
        best_idx = min(range(len(self.markers)),
                       key=lambda i: abs(self.markers[i].t - t))
        if abs(self.markers[best_idx].t - t) <= max_dist_sec:
            removed = self.markers.pop(best_idx)
            self._renumber()
            return removed
        return None

    def set_part_name(self, bar_num: int, part_name: str) -> bool:
        """Setzt/leert den Part-Namen eines Markers. True wenn gefunden."""
        for m in self.markers:
            if m.bar_num == bar_num:
                m.part_name = part_name
                return True
        return False

    def nearest_marker(self, t: float) -> Optional[BarMarker]:
        """Gibt den Marker zurück, der *t* am nächsten liegt (ohne Limit)."""
        if not self.markers:
            return None
        return min(self.markers, key=lambda m: abs(m.t - t))

    def _renumber(self) -> None:
        for i, m in enumerate(self.markers):
            m.bar_num = self.start_bar_num + i

    # ------------------------------------------------------------------
    # Serialisierung
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "song_id":         self.song_id,
            "song_name":       self.song_name,
            "segment_start_t": self.segment_start_t,
            "start_bar_num":   self.start_bar_num,
            "markers": [
                {"t": m.t, "bar_num": m.bar_num, "part_name": m.part_name}
                for m in self.markers
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SongAnnotation":
        ann = cls(
            song_id=d["song_id"],
            song_name=d.get("song_name", ""),
            segment_start_t=float(d.get("segment_start_t", 0.0)),
            start_bar_num=int(d.get("start_bar_num", 1)),
        )
        ann.markers = [
            BarMarker(
                t=float(m["t"]),
                bar_num=int(m["bar_num"]),
                part_name=m.get("part_name", ""),
            )
            for m in d.get("markers", [])
        ]
        return ann


# ---------------------------------------------------------------------------
# Datei-I/O
# ---------------------------------------------------------------------------

def annotation_path(jsonl_path: Path) -> Path:
    """Gibt den Pfad zur Annotations-Datei zurück."""
    return jsonl_path.with_name(jsonl_path.stem + "_annotations.json")


def load_annotations(jsonl_path: Path) -> dict[str, SongAnnotation]:
    """Lädt Annotationen aus der ``_annotations.json``-Datei.

    Gibt ein leeres Dict zurück wenn die Datei nicht existiert.
    """
    p = annotation_path(jsonl_path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text("utf-8"))
        return {k: SongAnnotation.from_dict(v) for k, v in data.items()}
    except Exception:
        return {}


def save_annotations(
    jsonl_path: Path,
    annotations: dict[str, SongAnnotation],
) -> None:
    """Speichert Annotationen in die ``_annotations.json``-Datei."""
    p = annotation_path(jsonl_path)
    data = {k: v.to_dict() for k, v in annotations.items()}
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
