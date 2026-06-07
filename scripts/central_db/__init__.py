"""Central-DB portierung — lighting-ai-db.json <-> Supabase schema (v3.1).

Pure, offline transform (``transform.py``) + thin Supabase I/O wrappers
(``import_to_supabase.py`` / ``export_from_supabase.py``). The transform is
side-effect free so the round-trip can be tested without a live database.
"""
