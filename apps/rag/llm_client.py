import os
import time
from functools import lru_cache

from openai import OpenAI


@lru_cache
def get_llm_client() -> OpenAI:
    """Buat/ambil satu instance client OpenAI SDK untuk chat/generation (singleton) .

    Memakai SDK `openai` bukan berarti terikat ke OpenAI cloud — `base_url`
    diarahkan ke server yang kompatibel dengan format API OpenAI (di proyek
    ini: Ollama lewat Docker, lihat `docs/OLLAMA_DOCKER.md`, atau gateway
    multi-model lain). Ganti provider cukup dengan mengubah env var
    `LLM_BASE_URL`/`LLM_API_KEY`, tanpa ubah kode.
    """
    return OpenAI(
        base_url=os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'),
        api_key=os.environ.get('LLM_API_KEY', 'ollama'),
    )


def embedding_config() -> dict:
    """Konfigurasi embedding yang aktif sekarang.

    Prioritas:
    1. Baris `AIModel` (`apps/rag/models.py`) dengan `purpose='embedding'` dan
       `is_active=True` di database — diisi/diganti lewat
       `POST /api/ai-models/` tanpa perlu edit `.env` atau restart server.
    2. Kalau tidak ada baris aktif, fallback ke environment variable
       `EMBEDDING_MODEL`/`EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY`/
       `REPORT_EMBEDDING_DIM` (perilaku sebelum ada `AIModel`, `base_url`
       fallback lagi ke `LLM_BASE_URL`/`LLM_API_KEY` kalau `EMBEDDING_*` juga
       tidak diset).

    `source`/`ai_model_id` di hasilnya dipakai endpoint
    `GET /api/ai-models/embedding-status/` untuk menunjukkan dari mana
    konfigurasi yang sedang dipakai berasal. `model`/`base_url`/`dim` dipakai
    sebagai "fingerprint" oleh `EmbeddingState` untuk mendeteksi kapan
    konfigurasi berubah dari yang dipakai collection Qdrant `reports` yang
    ada sekarang — lihat management command/endpoint `rebuild_embeddings`.
    """
    from apps.rag.models import AIModel  # import lokal, hindari circular import saat app loading

    active = AIModel.objects.filter(purpose=AIModel.PURPOSE_EMBEDDING, is_active=True).first()
    if active is not None:
        return {
            "source": "ai_model",
            "ai_model_id": active.pk,
            "model": active.model_name,
            "base_url": active.base_url,
            "api_key": active.api_key or os.environ.get('LLM_API_KEY', 'ollama'),
            "dim": active.dim or int(os.environ.get('REPORT_EMBEDDING_DIM', '384')),
        }

    return {
        "source": "env",
        "ai_model_id": None,
        "model": os.environ.get('EMBEDDING_MODEL', 'all-minilm'),
        "base_url": os.environ.get(
            'EMBEDDING_BASE_URL',
            os.environ.get('LLM_BASE_URL', 'http://localhost:11434/v1'),
        ),
        "api_key": os.environ.get(
            'EMBEDDING_API_KEY',
            os.environ.get('LLM_API_KEY', 'ollama'),
        ),
        "dim": int(os.environ.get('REPORT_EMBEDDING_DIM', '384')),
    }


def get_embedding_client() -> OpenAI:
    """Buat client OpenAI SDK untuk embedding (terpisah dari `get_llm_client()`).

    Dipisah karena provider chat dan provider embedding tidak selalu sama —
    mis. gateway multi-model yang bagus untuk chat (banyak pilihan model LLM)
    tapi tidak semua providernya mendukung endpoint `/embeddings`.

    Sengaja **tidak** `@lru_cache` (beda dari `get_llm_client()`) — karena
    `embedding_config()` bisa berubah kapan saja lewat `is_active` di
    `AIModel` (tanpa restart server), client-nya harus selalu dibuat ulang
    dari config TERBARU tiap dipanggil. Membuat `OpenAI(...)` murah/tidak ada
    network call, jadi tidak masalah dibuat ulang tiap request.
    """
    config = embedding_config()
    return OpenAI(base_url=config["base_url"], api_key=config["api_key"])


def embed_text(text: str) -> list[float]:
    """Ubah sebuah teks jadi vektor embedding lewat model `EMBEDDING_MODEL`.

    Panjang vektor yang dihasilkan harus sama dengan `REPORT_EMBEDDING_DIM`
    (dipakai sebagai `vector_size` collection Qdrant di `ReportVectorStore`).
    """
    client = get_embedding_client()
    model = embedding_config()["model"]
    response = client.embeddings.create(model=model, input=text)
    return response.data[0].embedding


def generate_answer(query: str, context: list[str]) -> str:
    """Minta LLM (`LLM_MODEL`) menjawab `query` berdasarkan potongan teks di `context`.

    System prompt secara eksplisit membatasi LLM supaya hanya menjawab dari
    konteks yang diberikan (mengurangi halusinasi/karangan informasi yang
    tidak ada di laporan). `context` biasanya berisi `original_text` dari
    beberapa Report hasil `ReportVectorStore.search()`.
    """
    client = get_llm_client()
    model = os.environ.get('LLM_MODEL', 'llama3.2:3b')

    context_text = "\n\n".join(f"- {c}" for c in context) or "(tidak ada konteks relevan ditemukan)"
    messages = [
        {
            "role": "system",
            "content": (
                "Kamu adalah asisten yang menjawab pertanyaan berdasarkan laporan "
                "pengawasan berikut. Jawab hanya berdasarkan konteks yang diberikan, "
                "jangan mengarang informasi yang tidak ada di konteks."
            ),
        },
        {
            "role": "user",
            "content": f"Konteks:\n{context_text}\n\nPertanyaan: {query}",
        },
    ]

    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content


def test_ai_model(ai_model, input_text: str) -> dict:
    """Tes satu konfigurasi `AIModel` dengan memanggil API-nya langsung sekali.

    Sengaja membuat `OpenAI(...)` ad-hoc di sini (bukan lewat
    `get_llm_client()`/`get_embedding_client()`) supaya tes ini tidak
    menyentuh/mengubah client singleton yang sedang dipakai app secara live —
    murni percobaan koneksi untuk `ai_model` yang diminta, apapun statusnya
    (`is_active` atau bukan).

    Dipanggil endpoint `POST /api/ai-models/{id}/test/`. Semua error (base_url
    tidak reachable, model tidak ditemukan, auth gagal, dst) ditangkap dan
    dikembalikan sebagai `{"ok": False, "error": "..."}`, bukan exception,
    supaya endpoint-nya selalu balas HTTP 200 dengan hasil tes yang jelas.
    """
    client = OpenAI(base_url=ai_model.base_url, api_key=ai_model.api_key or "-")

    started = time.monotonic()
    try:
        if ai_model.purpose == ai_model.PURPOSE_EMBEDDING:
            response = client.embeddings.create(model=ai_model.model_name, input=input_text)
            vector = response.data[0].embedding
            return {
                "ok": True,
                "purpose": ai_model.purpose,
                "model_name": ai_model.model_name,
                "base_url": ai_model.base_url,
                "latency_ms": round((time.monotonic() - started) * 1000),
                "dim": len(vector),
            }

        response = client.chat.completions.create(
            model=ai_model.model_name,
            messages=[{"role": "user", "content": input_text}],
        )
        return {
            "ok": True,
            "purpose": ai_model.purpose,
            "model_name": ai_model.model_name,
            "base_url": ai_model.base_url,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "sample_response": response.choices[0].message.content,
        }
    except Exception as exc:
        return {
            "ok": False,
            "purpose": ai_model.purpose,
            "model_name": ai_model.model_name,
            "base_url": ai_model.base_url,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "error": str(exc),
        }
