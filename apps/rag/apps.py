import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class RagConfig(AppConfig):
    name = 'apps.rag'

    def ready(self):
        from apps.rag import signals  # noqa: F401
        self._warn_if_embedding_config_changed()
        self._reset_stale_rebuild_progress()

    def _reset_stale_rebuild_progress(self):
        """Kalau proses sebelumnya crash/di-kill di tengah `rebuild_embeddings()`
        (mis. server di-restart manual saat rebuild masih jalan di background
        thread-nya), `RebuildProgress.status` bisa tersangkut di 'running'
        selamanya — sebuah `threading.Thread` tidak mungkin selamat dari restart
        proses, jadi status 'running' yang masih ada saat app baru start PASTI
        basi (stale lock), bukan job yang sungguh masih berjalan.

        Tanpa reset ini, endpoint `POST /api/ai-models/rebuild-embeddings/`
        akan terus menolak permintaan baru (`already_running`) walau tidak ada
        proses apapun yang benar-benar jalan lagi.
        """
        import sys

        if any(cmd in sys.argv for cmd in ("makemigrations", "migrate")):
            return

        try:
            from apps.rag.models import RebuildProgress

            progress = RebuildProgress.current()
            if progress.status == RebuildProgress.STATUS_RUNNING:
                progress.status = RebuildProgress.STATUS_IDLE
                progress.save(update_fields=["status"])
                logger.warning(
                    "RebuildProgress status='running' ditemukan saat startup — "
                    "kemungkinan proses sebelumnya crash/di-restart di tengah rebuild. "
                    "Direset ke 'idle' supaya tidak memblokir rebuild baru selamanya."
                )
        except Exception:
            pass

    def _warn_if_embedding_config_changed(self):
        """Best-effort check: bandingkan EMBEDDING_MODEL/EMBEDDING_BASE_URL/
        REPORT_EMBEDDING_DIM aktif dengan `EmbeddingState` tersimpan, cuma
        untuk kasih warning di log kalau beda — TIDAK auto-drop collection
        Qdrant di sini (itu operasi destruktif, harus lewat command eksplisit
        `rebuild_embeddings`).

        Dibungkus try/except lebar dengan sengaja: `ready()` juga jalan saat
        `makemigrations`/`migrate` sebelum tabel `EmbeddingState` ada, atau
        saat DB belum reachable — best-effort, bukan syarat app bisa start.
        Perintah `makemigrations`/`migrate` sendiri dilewati supaya tidak
        query DB sebelum tabelnya pasti ada.
        """
        import sys

        if any(cmd in sys.argv for cmd in ("makemigrations", "migrate")):
            return

        try:
            from apps.rag.llm_client import embedding_config
            from apps.rag.models import EmbeddingState

            config = embedding_config()
            if not EmbeddingState.matches(config):
                logger.warning(
                    "Konfigurasi embedding aktif (model=%s, base_url=%s, dim=%s) berbeda dari "
                    "collection Qdrant 'reports' yang ada. Jalankan "
                    "`python manage.py rebuild_embeddings` untuk drop & re-embed ulang semua Report.",
                    config["model"], config["base_url"], config["dim"],
                )
        except Exception:
            pass
