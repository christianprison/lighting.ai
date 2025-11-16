"""
live_matcher.py

Matching eines neuen Live-Takts gegen die bestehende Annoy-Vektordatenbank.

Ein Vektor besteht aus:
    [features..., bar, beat_in_bar, timestamp_sec]

Die Metadaten zu jedem Vektor (Songtitel, Songteil, Aufnahmedatum)
werden in der Tabelle `annoy_vector_metadata` in `lighting.db` verwaltet
und über `AnnoyVectorStore`/`Database` abgefragt.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict, Any

from database import Database
from annoy_store import AnnoyVectorStore


@dataclass
class MatchResult:
    annoy_id: int
    distance: float
    song_title: str
    song_part: str
    recording_date: Optional[str]
    bar: Optional[int] = None
    beat_in_bar: Optional[int] = None
    timestamp_sec: Optional[float] = None
    raw_metadata: Dict[str, Any] = None


class LiveBarMatcher:
    """
    Ermittelt für einen neuen Live-Takt den wahrscheinlichsten Song-Teil.

    Strategie:
      1. Annoy-Index nach nächstgelegenen Vektoren abfragen
      2. Metadaten (song_title, song_part, recording_date, bar, beat, time) einbeziehen
      3. Scoring:
         - Primär: Distanz (kleiner = besser)
         - Sekundär: zeitliche Nähe der Aufnahme zum aktuellen Session-Datum
    """

    def __init__(
        self,
        feature_dim: int,
        session_date: Optional[str] = None,
        metric: str = "angular",
        num_trees: int = 50,
    ):
        """
        :param feature_dim: Dimension der reinen Feature-Vektoren
        :param session_date: Datum der aktuellen Probe (YYYY-MM-DD), optional
        :param metric: Distanzmetrik für Annoy
        :param num_trees: (nur relevant, wenn neue Vektoren hinzugefügt werden)
        """
        self.db = Database()
        self.store = AnnoyVectorStore(
            db=self.db,
            feature_dim=feature_dim,
            metric=metric,
            num_trees=num_trees,
        )

        self.session_date = self._parse_date(session_date) if session_date else None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def match_live_bar(
        self,
        features: List[float],
        bar: int,
        beat_in_bar: int,
        timestamp_sec: float,
        top_k: int = 10,
    ) -> Optional[MatchResult]:
        """
        Vergleicht einen Live-Takt mit der Vektordatenbank und gibt
        den wahrscheinlichsten Song-Teil zurück.
        """
        if len(features) != self.store.feature_dim:
            raise ValueError(
                f"features muss Länge {self.store.feature_dim} haben, "
                f"hat aber {len(features)}"
            )

        # Query-Vektor inkl. Timing-Infos
        query_vec = list(features) + [float(bar), float(beat_in_bar), float(timestamp_sec)]

        # Nächste Nachbarn aus Annoy holen
        neighbours = self.store.query_with_metadata(query_vec, top_k=top_k)
        if not neighbours:
            return None

        # Bestes Ergebnis anhand Distanz + Datum bestimmen
        best = None
        best_score = float("inf")

        for annoy_id, dist, meta in neighbours:
            song_title = meta.get("song_title", "UNBEKANNT")
            song_part = meta.get("song_part", "")
            rec_date_str = meta.get("recording_date")
            bar_meta = meta.get("bar")
            beat_meta = meta.get("beat_in_bar")
            t_meta = meta.get("timestamp_sec")

            rec_date = self._parse_date(rec_date_str) if rec_date_str else None

            # Basisscore: Distanz
            score = dist

            # Falls Session-Datum und Recording-Datum bekannt, Nähe belohnen
            if self.session_date and rec_date:
                delta_days = abs((self.session_date - rec_date).days)
                # Gewichtung: pro Jahr Abstand +10% zur Distanz
                score *= (1.0 + 0.1 * (delta_days / 365.0))

            # Optionale Bonus-/Malusfaktoren:
            # z.B. wenn Taktzahl ähnlich ist, leicht bevorzugen
            if bar_meta is not None and abs(bar_meta - bar) <= 2:
                score *= 0.95

            if best is None or score < best_score:
                best_score = score
                best = MatchResult(
                    annoy_id=annoy_id,
                    distance=dist,
                    song_title=song_title,
                    song_part=song_part,
                    recording_date=rec_date_str,
                    bar=bar_meta,
                    beat_in_bar=beat_meta,
                    timestamp_sec=t_meta,
                    raw_metadata=meta,
                )

        return best

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_date(date_str: Optional[str]) -> Optional[date]:
        if not date_str:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None


if __name__ == "__main__":
    # Kleine Demo: zufälliger Live-Takt (hier Dummy-Daten)
    import random

    feature_dim = 32
    matcher = LiveBarMatcher(feature_dim=feature_dim, session_date="2025-11-02")

    live_features = [random.random() for _ in range(feature_dim)]
    bar = 5
    beat_in_bar = 2
    timestamp_sec = 12.34

    result = matcher.match_live_bar(
        features=live_features,
        bar=bar,
        beat_in_bar=beat_in_bar,
        timestamp_sec=timestamp_sec,
        top_k=10,
    )

    if result:
        print("Wahrscheinlichster Song-Teil:")
        print(f"  Annoy-ID     : {result.annoy_id}")
        print(f"  Distanz      : {result.distance:.4f}")
        print(f"  Songtitel    : {result.song_title}")
        print(f"  Songteil     : {result.song_part}")
        print(f"  Aufnahmedatum: {result.recording_date}")
        print(f"  Meta         : {result.raw_metadata}")
    else:
        print("Keine passenden Kandidaten gefunden.")


