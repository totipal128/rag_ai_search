# Menghubungkan RAG dengan LLM / Model AI

Dokumen ini menjelaskan bagaimana Qdrant (lihat [`docs/QDRANT.md`](QDRANT.md)) dihubungkan dengan model AI (LLM) untuk membentuk alur RAG (Retrieval-Augmented Generation) yang lengkap: dari pertanyaan pengguna sampai jawaban yang dihasilkan.

## Alur RAG di proyek ini

```
Pertanyaan user
      │
      ▼
1. Embed pertanyaan (embedding model)  ──► vector 384-dim
      │
      ▼
2. Cari Report paling mirip di Qdrant  ──► ReportVectorStore.search()
      │
      ▼
3. Susun konteks dari hasil pencarian  ──► original_text tiap Report
      │
      ▼
4. Kirim konteks + pertanyaan ke LLM   ──► LLM generate jawaban
      │
      ▼
Jawaban + daftar sumber (Report mana yang dipakai)
```

Dua model AI yang dibutuhkan:

| Tahap | Jenis model | Model default proyek ini |
|---|---|---|
| Embedding (langkah 1) | Text embedding model | `all-minilm` (384 dim, cocok dengan `REPORT_EMBEDDING_DIM`) |
| Generation (langkah 4) | Chat/instruct LLM | `llama3.2:3b` |

## Kenapa lewat format OpenAI-compatible API?

Proyek ini terhubung ke LLM lewat **format API OpenAI** (`/v1/chat/completions`, `/v1/embeddings`), bukan library khusus satu vendor. Alasannya:

- Hampir semua server LLM modern mendukung format ini: **Ollama**, vLLM, LM Studio, text-generation-inference, llama.cpp server, sampai OpenAI/Azure OpenAI sendiri.
- Kode di `apps/rag` jadi **tidak peduli** LLM-nya jalan di mana — lokal (laptop ini), server lain di jaringan kantor, atau cloud. Yang beda cuma nilai environment variable `LLM_BASE_URL`.
- Tidak perlu ganti kode kalau nanti pindah dari Ollama lokal ke server yang lebih besar.

## Konfigurasi (`.env`)

```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2:3b
EMBEDDING_MODEL=all-minilm
```

| Variabel | Keterangan |
|---|---|
| `LLM_BASE_URL` | Endpoint OpenAI-compatible untuk chat/generation. Ollama expose ini otomatis di `http://localhost:11434/v1` |
| `LLM_API_KEY` | Ollama tidak memverifikasi API key, tapi SDK OpenAI mengharuskan diisi (boleh string apa saja) |
| `LLM_MODEL` | Nama model untuk chat/generation |
| `EMBEDDING_MODEL` | Nama model untuk embedding |
| `EMBEDDING_BASE_URL` | Opsional, lihat [Provider embedding berbeda dari provider chat](#provider-embedding-berbeda-dari-provider-chat) |
| `EMBEDDING_API_KEY` | Opsional, idem |

### Provider embedding berbeda dari provider chat

`apps/rag` memakai **dua client terpisah** ([`get_llm_client()`](../apps/rag/llm_client.py) untuk chat, [`get_embedding_client()`](../apps/rag/llm_client.py) untuk embedding), supaya kamu bisa pakai provider yang berbeda untuk masing-masing tahap — mis. chat lewat gateway multi-model (banyak pilihan LLM bagus untuk generation), tapi embedding tetap lewat Ollama karena tidak semua provider di gateway itu punya endpoint `/embeddings`.

```env
# Chat/generation lewat gateway multi-model
LLM_BASE_URL=http://localhost:20128/v1
LLM_API_KEY=sk-...
LLM_MODEL=rli-cloude

# Embedding tetap lewat Ollama lokal — kalau EMBEDDING_BASE_URL/EMBEDDING_API_KEY
# tidak diset, keduanya otomatis ikut LLM_BASE_URL/LLM_API_KEY (satu provider
# untuk keduanya, seperti sebelumnya)
EMBEDDING_BASE_URL=http://localhost:11434/v1
EMBEDDING_API_KEY=ollama
EMBEDDING_MODEL=all-minilm
```

Kalau memang mau pakai satu provider yang sama untuk keduanya, cukup isi `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`/`EMBEDDING_MODEL` seperti biasa — `EMBEDDING_BASE_URL`/`EMBEDDING_API_KEY` boleh dikosongkan/dihapus.

**Catatan:** ganti dimensi `EMBEDDING_MODEL` (mis. dari `all-minilm` 384-dim ke model lain dengan dimensi berbeda) tetap butuh menyesuaikan `REPORT_EMBEDDING_DIM` dan membuat ulang collection Qdrant — lihat [Catatan penting: dimensi embedding](#catatan-penting-dimensi-embedding) di bawah.

### Menghubungkan ke server LLM lain (bukan Ollama lokal)

Cukup ubah `LLM_BASE_URL` dan `LLM_API_KEY`, tidak ada kode yang perlu diubah:

```env
# Contoh: server LLM lain di jaringan kantor (harus reachable dari mesin ini)
LLM_BASE_URL=http://192.168.69.80:8000/v1
LLM_API_KEY=isi-jika-server-butuh-auth

# Contoh: OpenAI cloud
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
```

## Kode: `apps/rag/llm_client.py`

Client singleton yang membungkus SDK `openai` supaya diarahkan ke `LLM_BASE_URL`:

```python
from apps.rag.llm_client import embed_text, generate_answer

vector = embed_text("dugaan pelanggaran keselamatan kerja")
jawaban = generate_answer("Ada laporan apa saja soal pelanggaran K3?", context=["...isi laporan..."])
```

- `embed_text(text)` → memanggil `client.embeddings.create()`, hasilnya list of float sepanjang `REPORT_EMBEDDING_DIM`.
- `generate_answer(query, context)` → memanggil `client.chat.completions.create()` dengan system prompt yang membatasi LLM hanya menjawab berdasarkan konteks yang diberikan (mengurangi halusinasi).

## Kode: `apps/rag/services.py` — menggabungkan Qdrant + LLM

```python
from apps.rag.services import ask_report

hasil = ask_report("Ada laporan apa saja soal pelanggaran K3?", top_k=5)
print(hasil["answer"])
print(hasil["sources"])  # [{"report_id": 12, "title": "...", "score": 0.83}, ...]
```

Fungsi `ask_report()` inilah yang menjalankan seluruh alur di diagram atas: embed query → `ReportVectorStore.search()` → `generate_answer()`.

## Endpoint API: `POST /api/rag/ask/`

Endpoint ini sudah terdaftar di Swagger (`/api/docs/`), tanpa autentikasi:

```bash
curl -X POST http://localhost:8000/api/rag/ask/ \
  -H "Content-Type: application/json" \
  -d '{"query": "Ada laporan apa saja soal pelanggaran K3?", "top_k": 5}'
```

Response:

```json
{
  "answer": "Berdasarkan laporan yang tersedia, ...",
  "sources": [
    {"report_id": 12, "title": "Laporan Pengawasan Ketenagakerjaan - Medan #12", "score": 0.83}
  ]
}
```

## Menjalankan Ollama sebagai LLM lokal

Cara yang dipakai di proyek ini adalah lewat **Docker** (lihat [`docs/OLLAMA_DOCKER.md`](OLLAMA_DOCKER.md) untuk penjelasan lengkap dan alasannya):

```bash
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama
docker exec ollama ollama pull llama3.2:3b   # model untuk chat/generation
docker exec ollama ollama pull all-minilm    # model untuk embedding
```

Setelah kedua model ditarik, endpoint `http://localhost:11434/v1` langsung aktif dan bisa dipakai tanpa konfigurasi tambahan — sudah cocok dengan default `.env` di proyek ini.

> Kalau di mesinmu Ollama native bisa di-install langsung (`brew install ollama` atau app resmi), cara itu juga tetap valid — cukup pastikan API-nya expose di port `11434` seperti biasa.

## Catatan penting: dimensi embedding

`all-minilm` menghasilkan vektor **384 dimensi**, sama dengan `REPORT_EMBEDDING_DIM` yang sudah diset untuk collection Qdrant `reports`. Kalau ganti `EMBEDDING_MODEL` ke model dengan dimensi berbeda (mis. `nomic-embed-text` = 768 dim), `REPORT_EMBEDDING_DIM` di `.env` **harus** disesuaikan, dan collection Qdrant lama perlu dibuat ulang (dimensi vektor tidak bisa diubah setelah collection dibuat) — lihat [`docs/QDRANT.md`](QDRANT.md#dimensi-vektor-report_embedding_dim).
