# Qdrant Vector Database

Dokumen ini menjelaskan apa itu Qdrant, kenapa dipakai di proyek ini, dan cara menggunakannya lewat `ReportVectorStore` di [`apps/rag/models.py`](../apps/rag/models.py).

## Apa itu Qdrant?

[Qdrant](https://qdrant.tech/) adalah **vector database** open-source yang dirancang khusus untuk menyimpan dan mencari embedding vector (representasi numerik dari teks, gambar, dll.) berdasarkan kemiripan (*similarity search*), bukan pencocokan nilai persis seperti database relasional.

Dalam konteks RAG (Retrieval-Augmented Generation), Qdrant berfungsi sebagai tempat menyimpan embedding dari setiap `Report`, sehingga sistem bisa mencari laporan-laporan yang **secara makna** paling relevan dengan sebuah query — bukan sekadar cocok kata kunci.

## Kenapa Qdrant?

| Keunggulan | Penjelasan |
|---|---|
| **Similarity search cepat** | Menggunakan algoritma HNSW (Hierarchical Navigable Small World) untuk pencarian tetangga terdekat (ANN) yang sangat cepat walau data jutaan vektor. |
| **Payload + filter native** | Setiap vektor bisa dilampiri payload (metadata JSON) dan difilter saat searching (mis. cari laporan mirip **dan** lokasinya di kota tertentu), tanpa perlu join ke database lain. |
| **Distance metric fleksibel** | Mendukung Cosine, Euclidean, Dot Product — bisa disesuaikan dengan model embedding yang dipakai. |
| **Open-source & self-hosted** | Bisa dijalankan sendiri via Docker, gratis, data tetap di infrastruktur sendiri (penting untuk data sensitif seperti laporan pengawasan). |
| **REST & gRPC API** | Mudah diintegrasikan dari bahasa apa pun, termasuk Python via `qdrant-client`. |
| **Ringan untuk development** | Satu container Docker sudah cukup untuk development lokal, tidak butuh cluster rumit. |
| **Persistensi built-in** | Data tersimpan di disk (bukan hanya in-memory), aman dari restart container. |

## Konfigurasi di proyek ini

Koneksi diatur lewat environment variable di `.env`:

```env
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_API_KEY=
REPORT_EMBEDDING_DIM=384
```

Client singleton ada di [`apps/rag/qdrant_client.py`](../apps/rag/qdrant_client.py):

```python
from apps.rag.qdrant_client import get_qdrant_client

client = get_qdrant_client()
```

## `ReportVectorStore` — mengelola vektor yang terhubung ke `Report`

Kelas [`ReportVectorStore`](../apps/rag/models.py) di `apps/rag/models.py` adalah lapisan yang menghubungkan model Django `Report` dengan collection Qdrant bernama `reports`. Aturannya:

- **Point ID di Qdrant = `Report.pk`**, jadi satu `Report` maksimal punya satu vektor (upsert = replace).
- Payload otomatis menyimpan `report_id`, `title`, `location`, `when`, `why`, `original_text` — supaya hasil pencarian langsung terlihat konteksnya tanpa perlu query balik ke PostgreSQL.

### 1. Membuat collection (otomatis)

```python
from apps.rag.models import ReportVectorStore

ReportVectorStore.ensure_collection()
```

Dipanggil otomatis juga di dalam `upsert()` dan `search()`, jadi biasanya tidak perlu dipanggil manual.

### 2. Menyimpan / update vektor sebuah Report

```python
from apps.report.models import Report
from apps.rag.models import ReportVectorStore

report = Report.objects.get(pk=1)
vector = embed(report.original_text)  # hasil dari model embedding, panjang harus 384

ReportVectorStore.upsert(report, vector)
```

### 3. Mencari Report yang paling mirip

```python
query_vector = embed("dugaan pelanggaran keselamatan kerja di proyek konstruksi")

results = ReportVectorStore.search(query_vector, limit=5)

for point in results:
    print(point.id, point.score, point.payload["title"])
```

### 4. Menghapus vektor

```python
ReportVectorStore.delete(report_id=1)
```

Tidak perlu dipanggil manual saat menghapus `Report` lewat ORM — sudah otomatis lewat signal `post_delete` di [`apps/rag/signals.py`](../apps/rag/signals.py), jadi vektor di Qdrant selalu sinkron dengan data `Report` di PostgreSQL.

## Dimensi vektor (`REPORT_EMBEDDING_DIM`)

Dimensi vektor harus sama persis antara collection Qdrant dan model embedding yang menghasilkan vektornya. Default proyek ini `384`, cocok dengan model embedding ringan seperti `all-MiniLM-L6-v2` (sentence-transformers) atau `all-minilm` (Ollama). Kalau ganti model embedding dengan dimensi berbeda, ubah `REPORT_EMBEDDING_DIM` di `.env` lalu buat ulang collection-nya (collection lama dengan dimensi berbeda tidak kompatibel).

## Menjalankan Qdrant secara lokal

```bash
docker run -d --name qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant
```

- `6333` — REST API + dashboard bawaan di `http://localhost:6333/dashboard`
- `6334` — gRPC API

Dashboard bawaan berguna untuk melihat isi collection, jumlah point, dan mencoba query tanpa kode.
