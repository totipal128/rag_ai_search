from django.db import models

from qdrant_client.models import (
    Distance,
    PointIdsList,
    PointStruct,
    VectorParams,
)

from apps.rag.qdrant_client import get_qdrant_client
from apps.report.models import Report


class AIModel(models.Model):
    """Konfigurasi satu provider/model AI (chat atau embedding), disimpan di DB
    lewat endpoint `POST /api/ai-models/` (lihat Swagger `/api/docs/`) supaya
    tidak perlu edit `.env` manual tiap ganti provider.

    Paling banyak satu baris `is_active=True` per `purpose` — `save()` di
    bawah otomatis menonaktifkan baris aktif lain dengan `purpose` yang sama,
    supaya jelas mana yang dipakai.
    """

    PURPOSE_CHAT = "chat"
    PURPOSE_EMBEDDING = "embedding"
    PURPOSE_CHOICES = [
        (PURPOSE_CHAT, "Chat / Generation"),
        (PURPOSE_EMBEDDING, "Embedding"),
    ]

    name = models.CharField(max_length=255, help_text="Label bebas, mis. '9router - rli-cloude'")
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    base_url = models.CharField(max_length=255, help_text="Endpoint OpenAI-compatible, mis. http://localhost:11434/v1")
    api_key = models.CharField(max_length=255, blank=True)
    model_name = models.CharField(max_length=255, help_text="Nama model yang dikirim ke API, mis. 'llama3.2:3b'")
    dim = models.IntegerField(null=True, blank=True, help_text="Dimensi vektor — khusus purpose=embedding")
    is_active = models.BooleanField(default=False, help_text="Model yang sedang dipakai app untuk purpose ini")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"[{self.purpose}] {self.name} ({self.model_name})"

    def save(self, *args, **kwargs):
        if self.is_active:
            AIModel.objects.filter(purpose=self.purpose, is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)


class EmbeddingState(models.Model):
    """Menyimpan konfigurasi embedding (model, base_url, dimensi) yang dipakai
    terakhir kali collection Qdrant `reports` dibuat/di-rebuild.

    Selalu satu baris (singleton, pk=1). Dipakai untuk mendeteksi kalau
    `EMBEDDING_MODEL`/`EMBEDDING_BASE_URL`/`REPORT_EMBEDDING_DIM` di `.env`
    berubah dari konfigurasi yang dipakai collection yang ada sekarang, supaya
    collection lama (dimensi/model berbeda, jadi datanya tidak valid lagi)
    tidak dipakai diam-diam. Lihat management command `rebuild_embeddings`.
    """

    model_name = models.CharField(max_length=255)
    base_url = models.CharField(max_length=255)
    dim = models.IntegerField()
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls) -> "EmbeddingState | None":
        return cls.objects.filter(pk=1).first()

    @classmethod
    def matches(cls, config: dict) -> bool:
        """True kalau `config` (hasil `embedding_config()`) sama dengan state tersimpan."""
        state = cls.current()
        if state is None:
            return False
        return (
            state.model_name == config["model"]
            and state.base_url == config["base_url"]
            and state.dim == config["dim"]
        )

    @classmethod
    def save_current(cls, config: dict) -> None:
        cls.objects.update_or_create(
            pk=1,
            defaults={
                "model_name": config["model"],
                "base_url": config["base_url"],
                "dim": config["dim"],
            },
        )


class RebuildProgress(models.Model):
    """Progres proses `rebuild_embeddings()` (drop & re-embed ulang semua Report),
    disimpan di DB (bukan memori proses) supaya bisa dibaca dari proses lain —
    penting karena command CLI (`python manage.py rebuild_embeddings`) dan
    endpoint API (`POST /api/ai-models/rebuild-embeddings/`) jalan di proses
    Python yang beda dari yang mengecek progresnya
    (`GET /api/ai-models/rebuild-embeddings/status/`).

    Selalu satu baris (singleton, pk=1), ditimpa tiap kali `rebuild_embeddings()`
    benar-benar jalan (bukan saat `status='up_to_date'` — progres lama tetap
    dipertahankan sebagai riwayat run terakhir).
    """

    STATUS_IDLE = "idle"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_IDLE, "Idle"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IDLE)
    model_name = models.CharField(max_length=255, blank=True, help_text="EMBEDDING_MODEL yang dipakai run ini")
    base_url = models.CharField(max_length=255, blank=True, help_text="Base URL embedding yang dipakai run ini")
    dim = models.IntegerField(null=True, blank=True, help_text="REPORT_EMBEDDING_DIM yang dipakai run ini")
    total = models.IntegerField(default=0)
    processed = models.IntegerField(default=0)
    success = models.IntegerField(default=0)
    failed_ids = models.JSONField(default=list)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def current(cls) -> "RebuildProgress":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def percent(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.processed / self.total * 100, 1)


class ReportVectorStore:
    """Mengelola vektor embedding Report di Qdrant.

    Setiap point di collection ini memakai `Report.id` sebagai point ID,
    sehingga satu Report punya paling banyak satu vektor (upsert = replace).
    """

    collection_name = "reports"
    distance = Distance.COSINE

    @classmethod
    def vector_size(cls) -> int:
        """Dimensi vektor embedding yang aktif SEKARANG.

        Sengaja method, bukan class attribute statis (`= int(os.environ...)`
        yang dievaluasi sekali saat modul di-import) — supaya ikut berubah
        real-time kalau `AIModel` embedding yang `is_active=True` diganti
        lewat API (lihat `embedding_config()` di `apps/rag/llm_client.py`),
        tanpa perlu restart proses. Bug sebelumnya: nilai statis bikin
        `upsert()` selalu gagal (`ValueError` dim mismatch) setelah ganti ke
        `AIModel` dengan dimensi berbeda dari `REPORT_EMBEDDING_DIM` di `.env`.
        """
        from apps.rag.llm_client import embedding_config

        return embedding_config()["dim"]

    @classmethod
    def collection_info(cls) -> dict | None:
        """Info ringkas collection Qdrant `reports` untuk endpoint
        `GET /api/ai-models/embedding-status/` — None kalau collection belum
        pernah dibuat sama sekali (mis. sebelum `upsert()`/`search()` pertama).
        """
        client = get_qdrant_client()
        if not client.collection_exists(cls.collection_name):
            return None
        info = client.get_collection(cls.collection_name)
        return {
            "points_count": info.points_count,
            "dim": info.config.params.vectors.size,
        }

    @classmethod
    def ensure_collection(cls) -> None:
        """Buat collection `reports` di Qdrant kalau belum ada.

        Dipanggil otomatis di awal `upsert()` dan `search()`, jadi biasanya
        tidak perlu dipanggil manual. Aman dipanggil berkali-kali (idempoten).
        """
        client = get_qdrant_client()
        if not client.collection_exists(cls.collection_name):
            client.create_collection(
                collection_name=cls.collection_name,
                vectors_config=VectorParams(size=cls.vector_size(), distance=cls.distance),
            )

    @classmethod
    def _payload(cls, report: Report) -> dict:
        """Susun metadata Report yang ikut disimpan di Qdrant (bukan cuma vektornya).

        Payload ini dikembalikan bersama hasil `search()`, jadi pemanggil bisa
        langsung tahu Report mana yang cocok tanpa query balik ke PostgreSQL.
        """
        return {
            "report_id": report.pk,
            "title": report.title,
            "location": report.location,
            "when": report.when,
            "why": report.why,
            "original_text": report.original_text,
        }

    @classmethod
    def upsert(cls, report: Report, vector: list[float]) -> None:
        """Simpan atau ganti vektor milik satu Report.

        Point ID di Qdrant = `report.pk`, jadi satu Report maksimal punya satu
        vektor — memanggil ini lagi untuk Report yang sama akan menimpa
        (replace) vektor lama, bukan menambah duplikat.
        """
        expected_size = cls.vector_size()
        if len(vector) != expected_size:
            raise ValueError(
                f"Panjang vector {len(vector)} tidak sesuai dengan vector_size aktif ({expected_size})"
            )

        cls.ensure_collection()
        client = get_qdrant_client()
        client.upsert(
            collection_name=cls.collection_name,
            points=[
                PointStruct(
                    id=report.pk,
                    vector=vector,
                    payload=cls._payload(report),
                )
            ],
        )

    @classmethod
    def drop_collection(cls) -> None:
        """Hapus seluruh collection Qdrant `reports` (bukan cuma satu vector).

        Qdrant tidak mendukung ubah `vector_size` pada collection yang sudah
        ada, jadi kalau `EMBEDDING_MODEL` ganti ke model dengan dimensi
        berbeda, satu-satunya cara adalah drop lalu buat ulang (dipanggil
        management command `rebuild_embeddings`). Panggilan `upsert()`/
        `search()` berikutnya otomatis buat collection baru lewat
        `ensure_collection()` dengan `vector_size` yang aktif saat ini.
        """
        client = get_qdrant_client()
        if client.collection_exists(cls.collection_name):
            client.delete_collection(cls.collection_name)

    @classmethod
    def delete(cls, report_id: int) -> None:
        """Hapus vektor milik sebuah Report berdasarkan ID-nya.

        Tidak error kalau collection atau point-nya belum/tidak ada, supaya
        aman dipanggil dari signal `post_delete` tanpa perlu pengecekan dulu.
        """
        client = get_qdrant_client()
        if not client.collection_exists(cls.collection_name):
            return
        client.delete(
            collection_name=cls.collection_name,
            points_selector=PointIdsList(points=[report_id]),
        )

    @classmethod
    def search(cls, vector: list[float], limit: int = 5):
        """Cari Report yang vektornya paling mirip (nearest neighbor) dengan `vector`.

        Mengembalikan list titik terurut dari paling mirip, tiap titik punya
        `.id` (Report.pk), `.score` (skor kemiripan), dan `.payload` (metadata
        dari `_payload()`).
        """
        cls.ensure_collection()
        client = get_qdrant_client()
        result = client.query_points(
            collection_name=cls.collection_name,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        return result.points
