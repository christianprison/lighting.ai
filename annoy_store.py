"""
annoy_store.py

Integration eines Annoy-Index mit der bestehenden SQLite-Datenbank
(`lighting.db` und `Database`-Klasse).

- Vektoren: [features..., bar, beat_in_bar, timestamp_sec]
- Metadaten pro Vektor in Tabelle `annoy_vector_metadata`:
  (annoy_id, song_title, song_part, recording_date)
"""

from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import json

from annoy import AnnoyIndex

from config import DATA_DIR
from database import Database


class AnnoyVectorStore:
    """
    Wrapper um AnnoyIndex + SQLite-Metadaten in `lighting.db`.

    Nutzung:
        db = Database()
        store = AnnoyVectorStore(db, feature_dim=64)
        store.add_vector_with_timing_and_metadata(...)
        store.build_and_save()
        results = store.query_with_metadata(query_vector, top_k=10)
    """

    def __init__(
        self,
        db: Database,
        feature_dim: int,
        index_path: Optional[Path] = None,
        metric: str = "angular",
        num_trees: int = 50,
    ):
        self.db = db
        self.feature_dim = feature_dim
        self.total_dim = feature_dim + 3  # +3 für bar, beat_in_bar, timestamp_sec
        self.metric = metric
        self.num_trees = num_trees

        base_dir = DATA_DIR / "annoy_indexes"
        base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = index_path or (base_dir / "song_segments.ann")
        self.meta_path = self.index_path.with_suffix(".meta.json")

        self.index = AnnoyIndex(self.total_dim, metric)
        self._next_id = 0

        # optionale zusätzliche Metadaten im Speicher (z.B. bar/beat/time)
        self.memory_metadata: Dict[int, Dict[str, Any]] = {}

        # Falls Index existiert: laden
        if self.index_path.exists() and self.meta_path.exists():
            self._load_index_and_meta()
            self._sync_next_id_from_db()

    # ------------------------------------------------------------------ #
    # Hinzufügen von Vektoren + Metadaten
    # ------------------------------------------------------------------ #

    def add_vector_with_timing_and_metadata(
        self,
        features: List[float],
        bar: int,
        beat_in_bar: int,
        timestamp_sec: float,
        song_title: str,
        song_part: str,
        recording_date: Optional[str] = None,
        extra_meta: Optional[Dict[str, Any]] = None,
    ) -> int:
        """
        Fügt einen Vektor + Taktinformationen + Song-Metadaten hinzu.

        :return: vergebene Annoy-ID
        """
        if len(features) != self.feature_dim:
            raise ValueError(
                f"features muss Länge {self.feature_dim} haben, "
                f"hat aber {len(features)}"
            )

        vector = list(features) + [float(bar), float(beat_in_bar), float(timestamp_sec)]

        vec_id = self._next_id
        self.index.add_item(vec_id, vector)

        # Metadaten in lighting.db speichern
        self.db.add_annoy_vector_metadata(
            annoy_id=vec_id,
            song_title=song_title,
            song_part=song_part,
            recording_date=recording_date,
        )

        # Zusätzliche Infos im Speicher halten (Timing etc.)
        meta = {
            "bar": bar,
            "beat_in_bar": beat_in_bar,
            "timestamp_sec": timestamp_sec,
        }
        if extra_meta:
            meta.update(extra_meta)
        self.memory_metadata[vec_id] = meta

        self._next_id += 1
        return vec_id

    # ------------------------------------------------------------------ #
    # Build / Save / Load
    # ------------------------------------------------------------------ #

    def build_and_save(self) -> None:
        """Baut den Annoy-Index und speichert Index + Meta-Information."""
        if self._next_id == 0:
            return
        self.index.build(self.num_trees)
        self.index.save(str(self.index_path))
        self._save_meta()

    def _save_meta(self) -> None:
        data = {
            "feature_dim": self.feature_dim,
            "metric": self.metric,
            "num_trees": self.num_trees,
            "next_id": self._next_id,
            "memory_metadata": self.memory_metadata,
        }
        self.meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_index_and_meta(self) -> None:
        self.index = AnnoyIndex(self.total_dim, self.metric)
        self.index.load(str(self.index_path))

        data = json.loads(self.meta_path.read_text(encoding="utf-8"))
        self.feature_dim = data["feature_dim"]
        self.total_dim = self.feature_dim + 3
        self.metric = data["metric"]
        self.num_trees = data["num_trees"]
        self._next_id = data.get("next_id", 0)
        self.memory_metadata = {
            int(k): v for k, v in data.get("memory_metadata", {}).items()
        }

    def _sync_next_id_from_db(self) -> None:
        """Synchronisiert _next_id mit den vorhandenen Metadaten aus der DB."""
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT MAX(annoy_id) AS max_id FROM annoy_vector_metadata")
        row = cur.fetchone()
        max_id = row["max_id"] if row and row["max_id"] is not None else -1
        if max_id + 1 > self._next_id:
            self._next_id = max_id + 1

    # ------------------------------------------------------------------ #
    # Abfrage
    # ------------------------------------------------------------------ #

    def query_with_metadata(
        self, query_vector: List[float], top_k: int = 10
    ) -> List[Tuple[int, float, Dict[str, Any]]]:
        """
        Abfrage des Index mit Rückgabe der Metadaten aus lighting.db.

        :param query_vector: Feature-Vektor (Länge feature_dim) oder voller Vektor
        :param top_k: Anzahl der Nachbarn
        :return: Liste von (annoy_id, distance, metadata_dict)
        """
        if len(query_vector) == self.feature_dim:
            q = list(query_vector) + [0.0, 0.0, 0.0]
        elif len(query_vector) == self.total_dim:
            q = list(query_vector)
        else:
            raise ValueError(
                f"query_vector muss Länge {self.feature_dim} oder {self.total_dim} haben"
            )

        ids, distances = self.index.get_nns_by_vector(q, top_k, include_distances=True)

        results: List[Tuple[int, float, Dict[str, Any]]] = []
        conn = self.db.get_connection()
        cur = conn.cursor()

        for vec_id, dist in zip(ids, distances):
            cur.execute(
                "SELECT * FROM annoy_vector_metadata WHERE annoy_id = ?", (vec_id,)
            )
            row = cur.fetchone()
            meta: Dict[str, Any] = dict(row) if row else {}

            # Timing-Infos aus memory_metadata hinzufügen (falls vorhanden)
            if vec_id in self.memory_metadata:
                meta.update(self.memory_metadata[vec_id])

            results.append((vec_id, dist, meta))

        return results


if __name__ == "__main__":
    # Kleine Demo, nutzt die bestehende lighting.db
    db = Database()
    store = AnnoyVectorStore(db=db, feature_dim=64)

    # Dummy-Feature-Vektor
    dummy_features = [0.1] * 64

    vec_id = store.add_vector_with_timing_and_metadata(
        features=dummy_features,
        bar=1,
        beat_in_bar=1,
        timestamp_sec=0.0,
        song_title="Demo-Song",
        song_part="Intro",
        recording_date="2025-11-02",
        extra_meta={"song_id": 1, "segment_index": 0},
    )

    store.build_and_save()

    print(f"Annoy-ID des gespeicherten Vektors: {vec_id}")

    results = store.query_with_metadata(dummy_features, top_k=3)
    for rid, dist, meta in results:
        print(f"ID={rid}, dist={dist:.4f}, meta={meta}")


