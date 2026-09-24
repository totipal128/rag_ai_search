import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.rag.models import ReportVectorStore
from apps.report.models import Report

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Report)
def sync_report_vector(sender, instance, **kwargs):
    """Setiap kali sebuah Report disimpan (create/update), otomatis generate
    ulang embedding-nya lewat Ollama dan simpan ke Qdrant.

    Import `sync_report` ditaruh di dalam fungsi (bukan di top-level) untuk
    menghindari circular import, karena `apps.rag.services` juga meng-import
    dari `apps.rag.models`. Kalau Ollama/Qdrant sedang tidak bisa diakses,
    error-nya cuma dicatat di log (`logger.exception`) supaya penyimpanan
    Report tetap berhasil walau sinkronisasi vektornya gagal.

    Catatan: signal ini TIDAK terpicu oleh `bulk_create()` (dipakai mis. di
    `seed_reports`), jadi data yang dibuat lewat situ perlu di-backfill manual
    lewat command `sync_reports`.
    """
    from apps.rag.services import sync_report

    try:
        sync_report(instance)
    except Exception:
        logger.exception("Gagal sinkronisasi vektor Report #%s ke Qdrant", instance.pk)


@receiver(post_delete, sender=Report)
def delete_report_vector(sender, instance, **kwargs):
    """Setiap kali sebuah Report dihapus, otomatis hapus juga vektornya di
    Qdrant supaya tidak ada vektor "yatim" yang menunjuk ke Report yang
    sudah tidak ada.
    """
    ReportVectorStore.delete(instance.pk)
