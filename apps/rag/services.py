import time

from django.utils import timezone

from apps.rag.llm_client import embed_text, embedding_config, generate_answer
from apps.rag.models import EmbeddingState, RebuildProgress, ReportVectorStore
from apps.report.models import Report

FIVE_W_TWO_H_LABELS = [
    ("what", "Apa"),
    ("who", "Siapa"),
    ("when", "Kapan"),
    ("where", "Dimana"),
    ("why", "Mengapa"),
    ("how", "Bagaimana"),
    ("how_much", "Berapa"),
]


def build_report_text(report) -> str:
    """Gabungkan field-field Report (title, 5W2H, lokasi, narasi) jadi satu
    teks polos, supaya bisa di-embed jadi satu vektor lewat `embed_text()`.

    Field 5W2H yang kosong (list kosong) sengaja dilewati supaya tidak
    menambah noise "Apa: " tanpa isi di teks yang di-embed.
    """
    parts = [report.title]

    for field_name, label in FIVE_W_TWO_H_LABELS:
        value = getattr(report, field_name)
        if value:
            parts.append(f"{label}: {', '.join(value)}")

    if report.location:
        parts.append(f"Lokasi: {report.location}")

    if report.original_text:
        parts.append(report.original_text)

    return "\n".join(parts)


def sync_report(report) -> list[float]:
    """Generate embedding dari isi satu Report lewat Ollama, lalu simpan/replace
    vektornya di Qdrant lewat `ReportVectorStore.upsert()`.

    Dipanggil otomatis oleh signal `post_save` (lihat `apps/rag/signals.py`)
    setiap kali sebuah Report dibuat/diubah, dan juga dipakai management
    command `sync_reports` untuk backfill data lama secara massal.
    Mengembalikan vektornya kalau pemanggil butuh (mis. untuk debugging).
    """
    vector = embed_text(build_report_text(report))
    ReportVectorStore.upsert(report, vector)
    return vector


def rebuild_embeddings(force: bool = False, progress_callback=None) -> dict:
    """Drop collection Qdrant `reports` lalu re-embed ulang SEMUA Report, kalau
    konfigurasi embedding aktif (`EMBEDDING_MODEL`/`EMBEDDING_BASE_URL`/
    `REPORT_EMBEDDING_DIM`) berbeda dari `EmbeddingState` tersimpan — atau
    selalu, kalau `force=True`.

    Dipakai bersama oleh management command `rebuild_embeddings` dan endpoint
    `POST /api/ai-models/rebuild-embeddings/`, supaya logic-nya satu tempat.
    Operasi ini **destruktif & bisa lama** (satu network call embedding per
    Report) — tidak dijalankan otomatis di mana pun, harus dipicu eksplisit.

    Progres disimpan ke `RebuildProgress` (DB, singleton) setiap Report selesai
    diproses — bukan cuma di memori — supaya proses lain (mis. endpoint
    `GET /api/ai-models/rebuild-embeddings/status/`) bisa baca progresnya
    secara live walau proses yang menjalankan rebuild ini beda (command CLI
    vs worker request HTTP). `progress_callback(processed, total)` opsional
    dipanggil di titik yang sama, dipakai command CLI untuk print persentase
    ke terminal.

    Return dict `status` ("up_to_date" kalau tidak melakukan apa-apa, atau
    "rebuilt" kalau benar-benar drop+resync), plus config yang dipakai dan
    ringkasan hasil (`total`, `success`, `failed_ids`).
    """
    config = embedding_config()

    if not force and EmbeddingState.matches(config):
        return {
            "status": "up_to_date",
            **config,
            "total": Report.objects.count(),
            "success": None,
            "failed_ids": [],
        }

    ReportVectorStore.drop_collection()

    reports = Report.objects.all()
    total = reports.count()

    progress = RebuildProgress.current()
    progress.status = RebuildProgress.STATUS_RUNNING
    progress.model_name = config["model"]
    progress.base_url = config["base_url"]
    progress.dim = config["dim"]
    progress.total = total
    progress.processed = 0
    progress.success = 0
    progress.failed_ids = []
    progress.started_at = timezone.now()
    progress.finished_at = None
    progress.save()

    success = 0
    failed_ids = []
    for i, report in enumerate(reports.iterator(), start=1):
        try:
            sync_report(report)
            success += 1
        except Exception:
            failed_ids.append(report.pk)

        progress.processed = i
        progress.success = success
        progress.failed_ids = failed_ids
        progress.save(update_fields=["processed", "success", "failed_ids"])

        if progress_callback:
            progress_callback(i, total)

    EmbeddingState.save_current(config)

    progress.status = RebuildProgress.STATUS_DONE
    progress.finished_at = timezone.now()
    progress.save(update_fields=["status", "finished_at"])

    return {
        "status": "rebuilt",
        **config,
        "total": total,
        "success": success,
        "failed_ids": failed_ids,
    }


def ask_report(query: str, top_k: int = 5) -> dict:
    """Jalankan alur RAG lengkap untuk satu pertanyaan:

    1. `query` di-embed jadi vektor (`embed_text`).
    2. Vektor itu dipakai mencari `top_k` Report paling mirip di Qdrant
       (`ReportVectorStore.search`).
    3. Isi Report-Report itu dijadikan konteks untuk LLM menjawab
       (`generate_answer`), supaya jawabannya berdasar data nyata, bukan
       karangan LLM.

    Dipakai oleh endpoint `POST /api/rag/ask/` (`apps/rag/views.py`).
    Hasilnya dict berisi `answer` (teks jawaban), `sources` (daftar Report
    yang jadi rujukan, beserta skor kemiripannya), dan `timing` (durasi tiap
    tahap dalam milidetik) — supaya lambatnya jawaban bisa ditelusuri: apakah
    di embedding, pencarian vector, atau generation LLM-nya.
    """
    started = time.monotonic()

    t0 = time.monotonic()
    query_vector = embed_text(query)
    embedding_ms = round((time.monotonic() - t0) * 1000)

    t0 = time.monotonic()
    hits = ReportVectorStore.search(query_vector, limit=top_k)
    vector_search_ms = round((time.monotonic() - t0) * 1000)

    context = [hit.payload.get("original_text") or hit.payload.get("title") for hit in hits]

    t0 = time.monotonic()
    answer = generate_answer(query, context)
    generation_ms = round((time.monotonic() - t0) * 1000)

    total_ms = round((time.monotonic() - started) * 1000)

    return {
        "answer": answer,
        "sources": [
            {
                "report_id": hit.payload.get("report_id"),
                "title": hit.payload.get("title"),
                "score": hit.score,
            }
            for hit in hits
        ],
        "timing": {
            "embedding_ms": embedding_ms,
            "vector_search_ms": vector_search_ms,
            "generation_ms": generation_ms,
            "total_ms": total_ms,
        },
    }
