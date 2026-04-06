"""detection — Gemeinsames Audio-Erkennungspaket für Live-App und Rehearsal-App.

Dieses Paket enthält den gesamten Erkennungsalgorithmus, der von beiden Apps
verwendet wird:

  beat_detector  — PLL-basierte Beat-Erkennung aus mehrkanaligem XR18-Audio
  fingerprint    — Audio-Fingerprinting / Feature-Extraktion pro Takt
  hmm            — HMM-basierte Takt-Positionsschätzung
  reference_db   — SQLite-Backend für Songs, Takte und Feature-Vektoren

Änderungen am Algorithmus werden hier vorgenommen und wirken automatisch auf
beide Apps.
"""
