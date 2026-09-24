from django.core.management.base import BaseCommand

from apps.rag.services import rebuild_embeddings


class Command(BaseCommand):
    help = (
        "Cek apakah EMBEDDING_MODEL/EMBEDDING_BASE_URL/REPORT_EMBEDDING_DIM di .env berubah "
        "dari konfigurasi terakhir kali collection Qdrant 'reports' dibuat. Kalau berubah "
        "(atau --force), drop collection lama lalu re-embed ulang semua Report."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Rebuild walau konfigurasi embedding tidak berubah",
        )

    def handle(self, *args, **options):
        """Wrapper tipis di atas `apps.rag.services.rebuild_embeddings()` — dipakai
        juga oleh endpoint `POST /api/ai-models/rebuild-embeddings/`, supaya logic
        drop+resync-nya satu tempat. Command ini cuma cetak hasilnya ke stdout,
        plus persentase progres tiap 50 Report lewat `progress_callback`.

        Progres yang sama juga bisa dicek dari proses lain (mis. lewat Swagger)
        selama command ini jalan, lewat `GET /api/ai-models/rebuild-embeddings/status/`
        — `progress_callback` di sini cuma untuk tampilan terminal, sumber
        datanya (`RebuildProgress`) sama-sama diupdate oleh `rebuild_embeddings()`.
        """
        def print_progress(processed: int, total: int) -> None:
            if processed % 50 == 0 or processed == total:
                percent = round(processed / total * 100, 1) if total else 100.0
                self.stdout.write(f"Progress: {processed}/{total} ({percent}%)")

        result = rebuild_embeddings(force=options["force"], progress_callback=print_progress)

        if result["status"] == "up_to_date":
            self.stdout.write(self.style.SUCCESS(
                f"Konfigurasi embedding tidak berubah (model={result['model']}, "
                f"base_url={result['base_url']}, dim={result['dim']}). "
                "Tidak ada yang perlu di-rebuild. Pakai --force untuk paksa rebuild."
            ))
            return

        self.stdout.write(
            f"Rebuild collection 'reports': model={result['model']}, "
            f"base_url={result['base_url']}, dim={result['dim']}"
        )
        for report_id in result["failed_ids"]:
            self.stderr.write(self.style.ERROR(f"Report #{report_id} gagal di-embed"))

        self.stdout.write(self.style.SUCCESS(
            f"Selesai. {result['success']}/{result['total']} Report berhasil di-embed ulang. "
            "Konfigurasi embedding disimpan."
        ))
