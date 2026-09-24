from django.core.management.base import BaseCommand

from apps.rag.services import sync_report
from apps.report.models import Report


class Command(BaseCommand):
    help = "Generate embedding (via Ollama) untuk semua Report dan simpan ke Qdrant"

    def handle(self, *args, **options):
        """Loop semua Report yang ada dan panggil `sync_report()` satu per satu.

        Perlu dijalankan manual setelah data dibuat lewat `bulk_create()`
        (mis. command `seed_reports`), karena `bulk_create()` tidak memicu
        signal `post_save` sehingga Report yang dibuat lewat situ belum
        otomatis punya vektor di Qdrant. Kegagalan satu Report (mis. Ollama
        sempat down) tidak menghentikan proses, cukup dicatat di stderr.
        """
        reports = Report.objects.all()
        total = reports.count()

        if total == 0:
            self.stdout.write(self.style.WARNING("Tidak ada data Report."))
            return

        success = 0
        for i, report in enumerate(reports.iterator(), start=1):
            try:
                sync_report(report)
                success += 1
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Report #{report.pk} gagal: {exc}"))

            if i % 50 == 0 or i == total:
                self.stdout.write(f"Progress: {i}/{total}")

        self.stdout.write(self.style.SUCCESS(f"Selesai. {success}/{total} Report berhasil di-sync ke Qdrant."))
