# Menjalankan Ollama lewat Docker

Dokumen ini menjelaskan cara menjalankan Ollama sebagai LLM lokal lewat Docker — cara yang dipakai di proyek ini untuk menyediakan model chat (`llama3.2:3b`) dan embedding (`all-minilm`) yang dipakai `apps/rag` (lihat [`docs/LLM_INTEGRATION.md`](LLM_INTEGRATION.md)).

## Kenapa Docker, bukan install native?

Di laptop pengembangan proyek ini (macOS 13, CPU Intel lama), dua cara install native Ollama sama-sama tidak bisa dipakai:

- **Homebrew formula** (`brew install ollama`) — build dari source, tapi crash saat compile salah satu varian SIMD CPU (`ggml-cpu-zen4`) karena Xcode Command Line Tools di macOS 13 sudah usang.
- **Aplikasi resmi / cask** (`brew install --cask ollama-app`) — mensyaratkan macOS 14+.

Menjalankan Ollama lewat **image Docker resmi** menghindari kedua masalah itu sepenuhnya: image sudah dikompilasi sebelumnya (tidak perlu compiler lokal) dan tidak terikat versi macOS host — hanya butuh Docker.

## 1. Jalankan container

```bash
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama
```

Penjelasan opsi:

| Opsi | Fungsi |
|---|---|
| `-d` | Jalankan di background |
| `--name ollama` | Nama container, dipakai untuk `docker exec`/`docker logs` |
| `-p 11434:11434` | Expose API Ollama ke `localhost:11434` — port yang sama persis dengan default `LLM_BASE_URL=http://localhost:11434/v1` di `.env` proyek ini |
| `-v ollama:/root/.ollama` | Volume persist supaya model yang sudah ditarik tidak hilang saat container dihapus/restart |

Cek container sudah jalan:

```bash
docker ps --filter name=ollama
```

## 2. Tarik model yang dibutuhkan

Model ditarik dari dalam container lewat `docker exec`:

```bash
docker exec ollama ollama pull llama3.2:3b   # model chat/generation
docker exec ollama ollama pull all-minilm    # model embedding (384 dim)
```

Cek daftar model yang sudah ada di container:

```bash
docker exec ollama ollama list
```

## 3. Tes API-nya

Ollama otomatis menyediakan endpoint OpenAI-compatible di `/v1/*`:

```bash
# Daftar model
curl http://localhost:11434/v1/models

# Tes chat completion
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.2:3b",
    "messages": [{"role": "user", "content": "Halo, kamu siapa?"}]
  }'

# Tes embedding
curl http://localhost:11434/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "all-minilm", "input": "contoh teks"}'
```

Karena `.env` proyek ini sudah default ke `LLM_BASE_URL=http://localhost:11434/v1`, begitu container ini jalan dan modelnya sudah ditarik, `apps/rag/llm_client.py` dan endpoint `POST /api/rag/ask/` langsung bisa dipakai tanpa konfigurasi tambahan.

## Perintah operasional lain

```bash
# Lihat log (mis. kalau model gagal ditarik atau API error)
docker logs -f ollama

# Stop / start ulang container (model tetap ada karena disimpan di volume)
docker stop ollama
docker start ollama

# Hapus container tapi model tetap tersimpan di volume `ollama`
docker rm -f ollama

# Update ke image versi terbaru
docker pull ollama/ollama
docker rm -f ollama
docker run -d --name ollama -p 11434:11434 -v ollama:/root/.ollama ollama/ollama

# Hapus model tertentu untuk hemat disk
docker exec ollama ollama rm nama-model
```

## Catatan performa

Container ini jalan **CPU-only** — Docker Desktop di macOS tidak meneruskan akses GPU host ke container Linux di dalamnya, jadi performanya setara dengan menjalankan Ollama secara native di CPU yang sama. Untuk laptop dengan RAM 16 GB dan tanpa GPU yang didukung, model kecil (`3b` ke bawah) seperti `llama3.2:3b` adalah pilihan yang wajar — model lebih besar akan terasa lambat.
