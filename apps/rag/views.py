import threading

from django.db.models import Count
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ModelViewSet

from apps.rag.llm_client import embedding_config, test_ai_model
from apps.rag.models import AIModel, EmbeddingState, RebuildProgress, ReportVectorStore
from apps.rag.serializers import (
    AIModelCountSerializer,
    AIModelSerializer,
    AIModelTestRequestSerializer,
    AIModelTestResultSerializer,
    AskRequestSerializer,
    AskResponseSerializer,
    EmbeddingStatusSerializer,
    RebuildEmbeddingsRequestSerializer,
    RebuildEmbeddingsStartedSerializer,
    RebuildEmbeddingsStatusSerializer,
)
from apps.rag.services import ask_report, rebuild_embeddings


class AIModelViewSet(ModelViewSet):
    """CRUD konfigurasi model AI (chat/embedding) — dipakai supaya provider bisa
    ditambah/diganti lewat API (`/api/ai-models/`, terdaftar otomatis di Swagger
    `/api/docs/`) tanpa perlu edit `.env` manual.

    Selain CRUD standar (list/create/retrieve/update/delete), ada 5 action
    tambahan:
    - `GET /api/ai-models/count/` — jumlah model AI yang terdaftar, per purpose.
    - `POST /api/ai-models/{id}/test/` — tes langsung ke API model AI tsb.
    - `POST /api/ai-models/rebuild-embeddings/` — mulai load ulang (drop &
      re-embed) seluruh vektor Report di Qdrant **di background thread**
      kalau konfigurasi embedding berubah — balas langsung, tidak nunggu selesai.
    - `GET /api/ai-models/rebuild-embeddings/status/` — cek persentase progres
      rebuild di atas, baik yang dipicu lewat endpoint ini maupun lewat
      `python manage.py rebuild_embeddings`.
    - `GET /api/ai-models/embedding-status/` — ringkasan kesehatan embedding:
      model aktif sekarang (dari `AIModel` atau `.env`), dan apakah collection
      Qdrant sudah sinkron dengan konfigurasi itu.
    """

    queryset = AIModel.objects.all()
    serializer_class = AIModelSerializer
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Jumlah model AI terdaftar (per purpose)",
        description=(
            "Menghitung berapa banyak `AIModel` yang sudah didaftarkan lewat "
            "`POST /api/ai-models/`, dipecah per `purpose` (`chat` vs `embedding`), "
            "plus total keseluruhan.\n\n"
            "Berguna sebelum memanggil `/api/rag/ask/` — kalau `embedding` masih 0, "
            "berarti belum ada konfigurasi embedding yang didaftarkan lewat endpoint ini "
            "(app tetap bisa jalan pakai `EMBEDDING_MODEL` di `.env` sebagai fallback, "
            "lihat `docs/LLM_INTEGRATION.md`).\n\n"
            "Field `active_embedding`/`active_chat` menunjukkan `model_name` dari baris "
            "`AIModel` yang `is_active=True` untuk masing-masing purpose (null kalau belum "
            "ada satupun yang diaktifkan)."
        ),
        responses=AIModelCountSerializer,
        examples=[
            OpenApiExample(
                "Contoh response",
                value={
                    "chat": 2,
                    "embedding": 1,
                    "total": 3,
                    "active_embedding": "all-minilm",
                    "active_chat": "rli-cloude",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["get"])
    def count(self, request):
        """`GET /api/ai-models/count/` — hitung jumlah `AIModel` per `purpose`,
        plus model mana yang sedang `is_active=True` untuk tiap purpose.
        """
        counts = dict(
            AIModel.objects.values_list("purpose").annotate(total=Count("id")).order_by()
        )
        active_embedding = (
            AIModel.objects.filter(purpose=AIModel.PURPOSE_EMBEDDING, is_active=True)
            .values_list("model_name", flat=True)
            .first()
        )
        active_chat = (
            AIModel.objects.filter(purpose=AIModel.PURPOSE_CHAT, is_active=True)
            .values_list("model_name", flat=True)
            .first()
        )

        result = {
            "chat": counts.get(AIModel.PURPOSE_CHAT, 0),
            "embedding": counts.get(AIModel.PURPOSE_EMBEDDING, 0),
            "total": AIModel.objects.count(),
            "active_embedding": active_embedding,
            "active_chat": active_chat,
        }
        return Response(AIModelCountSerializer(result).data)

    @extend_schema(
        summary="Tes koneksi & fungsi satu model AI",
        description=(
            "Memanggil langsung API model AI ini **satu kali** untuk memastikan "
            "`base_url`/`api_key`/`model_name` yang tersimpan benar-benar valid, "
            "sebelum dipakai sungguhan oleh `apps/rag` (mis. lewat `/api/rag/ask/` "
            "atau `python manage.py rebuild_embeddings`).\n\n"
            "Perilaku tergantung `purpose` dari model ini:\n"
            "- `purpose='embedding'` → panggil `POST {base_url}/embeddings` dengan "
            "`input_text` sebagai input, response berisi `dim` (panjang vektor "
            "yang dihasilkan — bandingkan dengan `REPORT_EMBEDDING_DIM`/`dim` di "
            "`AIModel` untuk cek kecocokan sebelum dipakai).\n"
            "- `purpose='chat'` → panggil `POST {base_url}/chat/completions` dengan "
            "`input_text` sebagai isi pesan user, response berisi `sample_response` "
            "(jawaban model).\n\n"
            "Tes ini **tidak mengubah state apapun** — tidak menyentuh client "
            "singleton yang lagi dipakai app, tidak mengubah `is_active`, dan "
            "tidak butuh model ini `is_active=True` untuk bisa dites. Kalau API-nya "
            "error (base_url tidak reachable, model tidak ada, auth gagal, dll), "
            "response tetap **HTTP 200** dengan `ok=false` dan `error` berisi pesan "
            "error aslinya — supaya gagal-nya gampang dibaca dari Swagger, bukan "
            "cuma muncul di traceback 500."
        ),
        request=AIModelTestRequestSerializer,
        responses=AIModelTestResultSerializer,
        examples=[
            OpenApiExample(
                "Tes model embedding — sukses",
                value={
                    "ok": True,
                    "purpose": "embedding",
                    "model_name": "all-minilm",
                    "base_url": "http://localhost:11434/v1",
                    "latency_ms": 84,
                    "dim": 384,
                },
                response_only=True,
            ),
            OpenApiExample(
                "Tes model chat — gagal",
                value={
                    "ok": False,
                    "purpose": "chat",
                    "model_name": "rli-cloude",
                    "base_url": "http://localhost:20128/v1",
                    "latency_ms": 312,
                    "error": "Error code: 400 - {'error': {'message': 'Invalid model format'}}",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        """`POST /api/ai-models/{id}/test/` — panggil `test_ai_model()` untuk
        model ini dengan `input_text` dari body request (default kalau kosong).
        """
        ai_model = self.get_object()
        serializer = AIModelTestRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = test_ai_model(ai_model, serializer.validated_data["input_text"])
        return Response(AIModelTestResultSerializer(result).data)

    @extend_schema(
        summary="Mulai load ulang (drop & re-embed) semua vektor Report di Qdrant, di background",
        description=(
            "Endpoint untuk kasus: kamu ganti `EMBEDDING_MODEL`/`EMBEDDING_BASE_URL`/"
            "`AIModel` aktif ke model dengan **dimensi vektor berbeda** dari yang dipakai "
            "sekarang (mis. `all-minilm` 384-dim → `gemini-embedding-2-preview` 3072-dim). "
            "Qdrant tidak bisa mengubah `vector_size` collection yang sudah ada, jadi "
            "satu-satunya cara adalah drop collection lama lalu buat ulang dengan dimensi "
            "baru — proses ini melakukan itu **plus** re-embed ulang semua Report dari "
            "PostgreSQL (source of truth), supaya collection Qdrant `reports` sinkron lagi.\n\n"
            "⚠️ **Proses ini jalan di background thread, TIDAK blocking** — endpoint ini "
            "balas **segera** (HTTP 202) begitu job dimulai, tidak menunggu sampai semua "
            "Report selesai di-embed (yang bisa makan waktu lama: 1 network call embedding "
            "per Report). Untuk tahu progres/hasil akhirnya, **poll** "
            "`GET /api/ai-models/rebuild-embeddings/status/` sampai `status='done'`.\n\n"
            "**Deteksi otomatis** — sebelum memulai thread apapun, dibandingkan dulu dengan "
            "`EmbeddingState` (fingerprint konfigurasi embedding terakhir kali collection "
            "dibuat):\n"
            "- Kalau **sama** dan `force=false` (default) → tidak memulai apa-apa, balas "
            "`status: 'up_to_date'` (HTTP 200). Aman dipanggil berkali-kali/dari cron tanpa "
            "boros re-embed.\n"
            "- Kalau **beda**, atau `force=true` → mulai thread background yang drop "
            "collection lalu embed ulang SEMUA Report, balas `status: 'started'` (HTTP 202).\n"
            "- Kalau **sudah ada job lain sedang jalan** (`RebuildProgress.status='running'`) "
            "→ request ini **ditolak** (balas `status: 'already_running'`, HTTP 409), tidak "
            "menumpuk job kedua yang bisa bentrok drop collection dengan job pertama."
        ),
        request=RebuildEmbeddingsRequestSerializer,
        responses=RebuildEmbeddingsStartedSerializer,
        examples=[
            OpenApiExample(
                "Job dimulai",
                value={"status": "started", "detail": "Rebuild embeddings dimulai di background."},
                response_only=True,
            ),
            OpenApiExample(
                "Konfigurasi tidak berubah",
                value={"status": "up_to_date", "detail": "Konfigurasi embedding tidak berubah, tidak ada yang di-rebuild."},
                response_only=True,
            ),
            OpenApiExample(
                "Sudah ada job berjalan",
                value={"status": "already_running", "detail": "Rebuild embeddings lain sedang berjalan."},
                response_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["post"], url_path="rebuild-embeddings")
    def rebuild_embeddings_action(self, request):
        """`POST /api/ai-models/rebuild-embeddings/` — validasi cepat (sudah jalan?
        sudah up to date?) secara sinkron, lalu kalau memang perlu rebuild,
        jalankan `apps.rag.services.rebuild_embeddings()` di `threading.Thread`
        terpisah supaya request ini tidak ikut blocking menunggu semua Report
        selesai di-embed. Nama method sengaja beda (`_action`) dari fungsi
        service yang di-import, supaya tidak membingungkan pembaca soal
        shadowing nama.
        """
        serializer = RebuildEmbeddingsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        force = serializer.validated_data["force"]

        if RebuildProgress.current().status == RebuildProgress.STATUS_RUNNING:
            return Response(
                RebuildEmbeddingsStartedSerializer({
                    "status": "already_running",
                    "detail": (
                        "Rebuild embeddings lain sedang berjalan. Cek progresnya di "
                        "GET /api/ai-models/rebuild-embeddings/status/."
                    ),
                }).data,
                status=409,
            )

        config = embedding_config()
        if not force and EmbeddingState.matches(config):
            return Response(
                RebuildEmbeddingsStartedSerializer({
                    "status": "up_to_date",
                    "detail": (
                        f"Konfigurasi embedding tidak berubah (model={config['model']}, "
                        f"dim={config['dim']}). Tidak ada yang di-rebuild. Pakai "
                        "force=true untuk paksa rebuild."
                    ),
                }).data,
            )

        threading.Thread(target=rebuild_embeddings, kwargs={"force": force}, daemon=True).start()

        return Response(
            RebuildEmbeddingsStartedSerializer({
                "status": "started",
                "detail": (
                    "Rebuild embeddings dimulai di background. Cek progresnya di "
                    "GET /api/ai-models/rebuild-embeddings/status/."
                ),
            }).data,
            status=202,
        )

    @extend_schema(
        summary="Cek persentase progres rebuild embeddings",
        description=(
            "Baca progres `rebuild_embeddings()` run terakhir dari `RebuildProgress` "
            "(disimpan di DB, bukan memori proses) — jadi tetap bisa dicek walau "
            "rebuild-nya dipicu dari proses lain: baik lewat "
            "`POST /api/ai-models/rebuild-embeddings/` maupun lewat terminal "
            "`python manage.py rebuild_embeddings`.\n\n"
            "Karena `POST /api/ai-models/rebuild-embeddings/` jalan di background thread "
            "dan balas segera (lihat deskripsi endpoint itu), cara pakai endpoint ini: "
            "panggil `POST .../rebuild-embeddings/` sekali, lalu **poll endpoint ini** "
            "setiap beberapa detik untuk lihat `percent` naik sampai `status='done'`.\n\n"
            "`status`:\n"
            "- `idle` — belum pernah ada rebuild dijalankan sama sekali di database ini.\n"
            "- `running` — sedang berjalan sekarang; `processed`/`percent` bertambah "
            "tiap satu Report selesai di-embed.\n"
            "- `done` — run terakhir sudah selesai (`finished_at` terisi). Kalau run "
            "berikutnya ternyata `status='up_to_date'` (config tidak berubah), progres "
            "di sini **tidak direset** — tetap menampilkan hasil run nyata terakhir."
        ),
        responses=RebuildEmbeddingsStatusSerializer,
        examples=[
            OpenApiExample(
                "Sedang berjalan",
                value={
                    "status": "running",
                    "model": "gemini/gemini-embedding-2-preview",
                    "base_url": "http://localhost:20128/v1",
                    "dim": 3072,
                    "total": 1200,
                    "processed": 750,
                    "success": 748,
                    "percent": 62.5,
                    "failed_ids": [431, 902],
                    "started_at": "2026-09-24T09:30:12Z",
                    "finished_at": None,
                },
                response_only=True,
            ),
            OpenApiExample(
                "Sudah selesai",
                value={
                    "status": "done",
                    "model": "all-minilm",
                    "base_url": "http://localhost:11434/v1",
                    "dim": 384,
                    "total": 1200,
                    "processed": 1200,
                    "success": 1199,
                    "percent": 100.0,
                    "failed_ids": [902],
                    "started_at": "2026-09-24T09:30:12Z",
                    "finished_at": "2026-09-24T09:47:58Z",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="rebuild-embeddings/status")
    def rebuild_embeddings_status(self, request):
        """`GET /api/ai-models/rebuild-embeddings/status/` — baca singleton
        `RebuildProgress` apa adanya (tidak memicu proses baru).
        """
        progress = RebuildProgress.current()
        return Response(RebuildEmbeddingsStatusSerializer({
            "status": progress.status,
            "model": progress.model_name,
            "base_url": progress.base_url,
            "dim": progress.dim,
            "total": progress.total,
            "processed": progress.processed,
            "success": progress.success,
            "percent": progress.percent,
            "failed_ids": progress.failed_ids,
            "started_at": progress.started_at,
            "finished_at": progress.finished_at,
        }).data)

    @extend_schema(
        summary="Status kesehatan embedding: model aktif & sinkron dengan Qdrant?",
        description=(
            "Ringkasan satu-halaman soal embedding yang sedang dipakai app:\n"
            "- Model/base_url/dimensi embedding yang **aktif sekarang**, dan dari mana "
            "asalnya (`active_source`): baris `AIModel` (`purpose='embedding'`, "
            "`is_active=True`) kalau ada, atau fallback `.env` kalau belum ada yang "
            "diaktifkan lewat `POST /api/ai-models/`.\n"
            "- Kondisi collection Qdrant `reports` sekarang (`collection_points_count`, "
            "`collection_dim`).\n"
            "- `in_sync`: apakah konfigurasi aktif itu **sama** dengan yang dipakai "
            "terakhir kali collection dibuat/di-rebuild. `in_sync=false` artinya query "
            "`/api/rag/ask/` kemungkinan akan gagal atau hasilnya tidak relevan (vector "
            "query beda 'bahasa' dengan vector yang tersimpan) — panggil "
            "`POST /api/ai-models/rebuild-embeddings/` untuk menyinkronkan.\n\n"
            "Cek endpoint ini dulu sebelum mengaktifkan (`is_active=true`) sebuah "
            "`AIModel` embedding baru, supaya tahu apakah setelah itu perlu rebuild."
        ),
        responses=EmbeddingStatusSerializer,
        examples=[
            OpenApiExample(
                "Sinkron — dari AIModel",
                value={
                    "active_source": "ai_model",
                    "active_ai_model_id": 2,
                    "active_model": "all-minilm",
                    "active_base_url": "http://localhost:11434/v1",
                    "active_dim": 384,
                    "collection_exists": True,
                    "collection_points_count": 1200,
                    "collection_dim": 384,
                    "in_sync": True,
                    "last_rebuilt_at": "2026-09-24T09:53:29Z",
                },
                response_only=True,
            ),
            OpenApiExample(
                "Tidak sinkron — perlu rebuild",
                value={
                    "active_source": "ai_model",
                    "active_ai_model_id": 5,
                    "active_model": "gemini/gemini-embedding-2-preview",
                    "active_base_url": "http://localhost:20128/v1",
                    "active_dim": 3072,
                    "collection_exists": True,
                    "collection_points_count": 1200,
                    "collection_dim": 384,
                    "in_sync": False,
                    "last_rebuilt_at": "2026-09-24T09:53:29Z",
                },
                response_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["get"], url_path="embedding-status")
    def embedding_status(self, request):
        """`GET /api/ai-models/embedding-status/` — gabungkan `embedding_config()`
        (config aktif), `EmbeddingState` (fingerprint terakhir dipakai rebuild),
        dan `ReportVectorStore.collection_info()` (kondisi collection Qdrant nyata).
        """
        config = embedding_config()
        state = EmbeddingState.current()
        collection = ReportVectorStore.collection_info()

        result = {
            "active_source": config["source"],
            "active_ai_model_id": config["ai_model_id"],
            "active_model": config["model"],
            "active_base_url": config["base_url"],
            "active_dim": config["dim"],
            "collection_exists": collection is not None,
            "collection_points_count": collection["points_count"] if collection else None,
            "collection_dim": collection["dim"] if collection else None,
            "in_sync": EmbeddingState.matches(config),
            "last_rebuilt_at": state.updated_at if state else None,
        }
        return Response(EmbeddingStatusSerializer(result).data)


class AskReportView(APIView):
    """Tanya jawab RAG: cari Report paling relevan di Qdrant, lalu minta LLM menjawab berdasarkan konteks itu."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        request=AskRequestSerializer,
        responses=AskResponseSerializer,
        description=(
            "Jalankan alur RAG: embed `query` → cari `top_k` Report paling mirip di "
            "Qdrant → kirim isinya sebagai konteks ke LLM untuk generate jawaban.\n\n"
            "Response berisi `timing` (dalam milidetik) supaya lambatnya jawaban bisa "
            "ditelusuri per-tahap:\n"
            "- `embedding_ms` — waktu embed `query` jadi vektor (lewat model embedding "
            "aktif, lihat `GET /api/ai-models/embedding-status/`).\n"
            "- `vector_search_ms` — waktu pencarian nearest-neighbor di Qdrant.\n"
            "- `generation_ms` — waktu LLM men-generate jawaban dari konteks (biasanya "
            "paling dominan, terutama kalau providernya gateway eksternal yang lambat).\n"
            "- `total_ms` — total ketiganya."
        ),
        examples=[
            OpenApiExample(
                "Contoh response",
                value={
                    "answer": "Ditemukan 3 laporan terkait dugaan pelanggaran prosedur keselamatan kerja...",
                    "sources": [
                        {"report_id": 518, "title": "Laporan Pengawasan Ketenagakerjaan - Serang #17", "score": 0.67},
                    ],
                    "timing": {
                        "embedding_ms": 84,
                        "vector_search_ms": 12,
                        "generation_ms": 1661,
                        "total_ms": 1757,
                    },
                },
                response_only=True,
            ),
        ],
    )
    def post(self, request):
        """Terima `{"query": "...", "top_k": 5}`, jalankan `ask_report()`,
        dan kembalikan jawaban LLM beserta daftar Report yang jadi sumbernya,
        plus `timing` (rincian durasi tiap tahap dalam ms).
        """
        serializer = AskRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = ask_report(
            query=serializer.validated_data["query"],
            top_k=serializer.validated_data["top_k"],
        )
        return Response(AskResponseSerializer(result).data)
