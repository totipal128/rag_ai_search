import os
from functools import lru_cache

from qdrant_client import QdrantClient


@lru_cache
def get_qdrant_client() -> QdrantClient:
    """Buat/ambil satu instance QdrantClient yang dipakai bersama (singleton).

    `lru_cache` tanpa argumen membuat fungsi ini selalu mengembalikan objek
    client yang sama setelah panggilan pertama, jadi koneksi ke Qdrant tidak
    dibuat berulang-ulang tiap kali dipanggil.
    """
    return QdrantClient(
        host=os.environ.get('QDRANT_HOST', 'localhost'),
        port=int(os.environ.get('QDRANT_PORT', '6333')),
        api_key=os.environ.get('QDRANT_API_KEY') or None,
    )
