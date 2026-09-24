# RAG AI Search

Proyek Django untuk contoh aplikasi RAG (Retrieval-Augmented Generation), dengan PostgreSQL sebagai database utama dan Qdrant sebagai vector database.

## Requirement

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) — package/project manager
- Docker (untuk menjalankan PostgreSQL dan Qdrant secara lokal)

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Siapkan environment variables

Salin `.env.example` menjadi `.env`, lalu sesuaikan nilainya:

```bash
cp .env.example .env
```

Variabel yang tersedia:

| Variabel | Keterangan | Default |
|---|---|---|
| `DB_NAME` | Nama database PostgreSQL | `rag_ai_search` |
| `DB_USER` | User PostgreSQL | `postgres` |
| `DB_PASSWORD` | Password PostgreSQL | `postgres` |
| `DB_HOST` | Host PostgreSQL | `localhost` |
| `DB_PORT` | Port PostgreSQL | `5432` |
| `QDRANT_HOST` | Host Qdrant | `localhost` |
| `QDRANT_PORT` | Port Qdrant | `6333` |
| `QDRANT_API_KEY` | API key Qdrant (kosongkan jika tidak dipakai) | - |
| `LLM_BASE_URL` | Endpoint OpenAI-compatible untuk chat/generation | `http://localhost:11434/v1` |
| `LLM_API_KEY` | API key untuk `LLM_BASE_URL` | `ollama` |
| `LLM_MODEL` | Nama model untuk chat/generation | `llama3.2:3b` |
| `EMBEDDING_MODEL` | Nama model untuk embedding | `all-minilm` |
| `EMBEDDING_BASE_URL` | Opsional — endpoint khusus embedding kalau providernya beda dari `LLM_BASE_URL` (mis. chat lewat gateway multi-model, embedding tetap lewat Ollama) | ikut `LLM_BASE_URL` |
| `EMBEDDING_API_KEY` | Opsional — API key untuk `EMBEDDING_BASE_URL` | ikut `LLM_API_KEY` |

### 3. Jalankan PostgreSQL, Qdrant & Ollama

Cara termudah, pakai `docker-compose.yml` yang sudah disediakan — menjalankan ketiga service sekaligus (variabel dibaca otomatis dari `.env`):

```bash
docker compose up -d
```

Ini juga menjalankan job `ollama-pull` sekali jalan untuk menarik model `LLM_MODEL` dan `EMBEDDING_MODEL` yang dipakai `apps/rag` (lihat [`docs/OLLAMA_DOCKER.md`](docs/OLLAMA_DOCKER.md)). Cek statusnya:

```bash
docker compose ps
docker compose logs -f ollama-pull
```

Alternatif, menjalankan tiap container manual:

```bash
docker run -d --name pg-vector -p 5433:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=rag_ai_search \
  pgvector/pgvector:pg16

docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

Sesuaikan nilai `-e` dan port dengan `.env` yang sudah dibuat di langkah sebelumnya.

### 4. Migrasi database

```bash
uv run python manage.py migrate
```

Untuk membuat migrasi baru setelah mengubah model:

```bash
uv run python manage.py makemigrations
```

### 5. Buat superuser (opsional, untuk akses `/admin/`)

```bash
uv run python manage.py createsuperuser
```

### 6. Jalankan development server

```bash
uv run python manage.py runserver
```

Aplikasi berjalan di `http://localhost:8000`.

## Dokumentasi API

- Swagger UI: `http://localhost:8000/api/docs/`
- ReDoc: `http://localhost:8000/api/redoc/`
- OpenAPI schema (JSON): `http://localhost:8000/api/schema/`
- Django Admin: `http://localhost:8000/admin/`

## Struktur aplikasi

Semua Django app custom ada di folder `apps/`:

- `apps/report` — CRUD laporan (model `Report`, endpoint `/api/reports/`)
- `apps/rag` — integrasi RAG dengan Qdrant dan LLM (`apps/rag/qdrant_client.py`, `apps/rag/models.py`, `apps/rag/llm_client.py`, `apps/rag/services.py`), endpoint `POST /api/rag/ask/`. Dokumentasi:
  - Cara pakai dan keunggulan Qdrant: [`docs/QDRANT.md`](docs/QDRANT.md)
  - Cara menghubungkan ke LLM/model AI: [`docs/LLM_INTEGRATION.md`](docs/LLM_INTEGRATION.md)
  - Cara menjalankan Ollama lewat Docker: [`docs/OLLAMA_DOCKER.md`](docs/OLLAMA_DOCKER.md)

## Perintah `manage.py` lain yang umum dipakai

```bash
# Cek konfigurasi project
uv run python manage.py check

# Buka Django shell
uv run python manage.py shell

# Jalankan test
uv run python manage.py test

# Kumpulkan static files (untuk produksi)
uv run python manage.py collectstatic
```
