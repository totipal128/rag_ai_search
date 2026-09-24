from rest_framework import serializers

from apps.rag.models import AIModel


class AIModelSerializer(serializers.ModelSerializer):
    name = serializers.CharField(required=False)
    purpose = serializers.CharField(required=False)
    base_url = serializers.CharField(required=False)
    api_key = serializers.CharField(required=False)
    model_name = serializers.CharField(required=False)
    dim = serializers.CharField(required=False)
    
    class Meta:
        model = AIModel
        fields = '__all__'
        extra_kwargs = {
            # write_only supaya api_key tidak ikut kebawa balik di response GET/list
            'api_key': {'write_only': True},
        }


class AIModelCountSerializer(serializers.Serializer):
    chat = serializers.IntegerField(help_text="Jumlah AIModel dengan purpose='chat'")
    embedding = serializers.IntegerField(help_text="Jumlah AIModel dengan purpose='embedding'")
    total = serializers.IntegerField(help_text="Total seluruh AIModel, semua purpose")
    active_embedding = serializers.CharField(
        allow_null=True, help_text="Nama model embedding yang sedang aktif (is_active=True), null kalau belum ada"
    )
    active_chat = serializers.CharField(
        allow_null=True, help_text="Nama model chat yang sedang aktif (is_active=True), null kalau belum ada"
    )


class AIModelTestRequestSerializer(serializers.Serializer):
    input_text = serializers.CharField(
        required=False,
        default="Halo, ini teks tes koneksi model AI.",
        help_text=(
            "Teks yang dikirim untuk tes. Untuk model purpose='embedding' dipakai sebagai "
            "input embeddings.create(); untuk purpose='chat' dipakai sebagai isi pesan user "
            "ke chat.completions.create()."
        ),
    )


class AIModelTestResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField(help_text="True kalau API model AI merespons sukses (bukan error)")
    purpose = serializers.CharField(help_text="'chat' atau 'embedding', diambil dari field AIModel.purpose")
    model_name = serializers.CharField()
    base_url = serializers.CharField()
    latency_ms = serializers.IntegerField(help_text="Waktu tempuh request dalam milidetik")
    dim = serializers.IntegerField(
        required=False, allow_null=True,
        help_text="Panjang vektor hasil embeddings.create() — hanya diisi kalau purpose='embedding' dan ok=True",
    )
    sample_response = serializers.CharField(
        required=False, allow_null=True,
        help_text="Cuplikan jawaban chat.completions.create() — hanya diisi kalau purpose='chat' dan ok=True",
    )
    error = serializers.CharField(
        required=False, allow_null=True,
        help_text="Pesan error dari API (mis. model tidak ditemukan, base_url tidak reachable) — diisi kalau ok=False",
    )


class RebuildEmbeddingsRequestSerializer(serializers.Serializer):
    force = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "False (default): hanya drop & re-embed kalau konfigurasi embedding "
            "(EMBEDDING_MODEL/EMBEDDING_BASE_URL/REPORT_EMBEDDING_DIM) berubah dari "
            "terakhir kali collection dibuat — aman dipanggil berkali-kali tanpa efek "
            "kalau tidak ada perubahan. True: paksa drop & re-embed ulang semua Report "
            "walau konfigurasinya sama persis."
        ),
    )


class RebuildEmbeddingsStartedSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["started", "up_to_date", "already_running"],
        help_text=(
            "'started': job rebuild baru saja dimulai di background thread — poll "
            "GET /api/ai-models/rebuild-embeddings/status/ untuk progresnya. "
            "'up_to_date': konfigurasi embedding tidak berubah, tidak ada yang dijalankan "
            "sama sekali (tidak ada thread yang dibuat). 'already_running': ada job rebuild "
            "lain yang masih berjalan — request ini ditolak, bukan menumpuk job baru."
        ),
    )
    detail = serializers.CharField(help_text="Pesan singkat untuk manusia, jelasin status di atas")


class RebuildEmbeddingsStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["idle", "running", "done"],
        help_text=(
            "'idle': belum pernah ada rebuild dijalankan. 'running': sedang berjalan "
            "sekarang (poll ulang endpoint ini untuk lihat `percent` naik). 'done': run "
            "terakhir sudah selesai (baik lewat command CLI maupun endpoint rebuild-embeddings)."
        ),
    )
    model = serializers.CharField(help_text="EMBEDDING_MODEL run ini (kosong kalau status='idle')")
    base_url = serializers.CharField(help_text="Base URL embedding run ini (kosong kalau status='idle')")
    dim = serializers.IntegerField(allow_null=True, help_text="REPORT_EMBEDDING_DIM run ini")
    total = serializers.IntegerField(help_text="Total Report yang diproses pada run ini")
    processed = serializers.IntegerField(help_text="Jumlah Report yang sudah diproses (sukses maupun gagal)")
    success = serializers.IntegerField(help_text="Jumlah Report yang berhasil di-embed ulang sejauh ini")
    percent = serializers.FloatField(help_text="processed/total dalam persen, dibulatkan 1 desimal")
    failed_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="ID Report yang gagal di-embed sejauh ini pada run ini",
    )
    started_at = serializers.DateTimeField(allow_null=True, help_text="Waktu run terakhir mulai, null kalau belum pernah jalan")
    finished_at = serializers.DateTimeField(
        allow_null=True, help_text="Waktu run terakhir selesai, null kalau sedang berjalan/belum pernah jalan"
    )


class EmbeddingStatusSerializer(serializers.Serializer):
    active_source = serializers.ChoiceField(
        choices=["ai_model", "env"],
        help_text=(
            "Dari mana konfigurasi embedding yang dipakai SEKARANG berasal: 'ai_model' "
            "(ada baris AIModel purpose='embedding' dengan is_active=True) atau 'env' "
            "(fallback ke EMBEDDING_MODEL/EMBEDDING_BASE_URL/REPORT_EMBEDDING_DIM di .env, "
            "kalau belum ada AIModel embedding yang diaktifkan)."
        ),
    )
    active_ai_model_id = serializers.IntegerField(
        allow_null=True, help_text="ID AIModel yang aktif dipakai, null kalau active_source='env'"
    )
    active_model = serializers.CharField(help_text="Nama model embedding yang dipakai sekarang")
    active_base_url = serializers.CharField(help_text="Base URL embedding yang dipakai sekarang")
    active_dim = serializers.IntegerField(help_text="Dimensi vektor embedding yang dipakai sekarang")
    collection_exists = serializers.BooleanField(help_text="True kalau collection Qdrant 'reports' sudah pernah dibuat")
    collection_points_count = serializers.IntegerField(
        allow_null=True, help_text="Jumlah vector tersimpan di collection sekarang, null kalau collection_exists=False"
    )
    collection_dim = serializers.IntegerField(
        allow_null=True, help_text="Dimensi vector collection yang ada sekarang, null kalau collection_exists=False"
    )
    in_sync = serializers.BooleanField(
        help_text=(
            "True kalau konfigurasi embedding aktif SAMA dengan yang dipakai terakhir kali "
            "collection dibuat (EmbeddingState) — False berarti perlu "
            "POST /api/ai-models/rebuild-embeddings/ supaya collection sinkron lagi."
        )
    )
    last_rebuilt_at = serializers.DateTimeField(
        allow_null=True, help_text="Kapan EmbeddingState terakhir disimpan (collection terakhir dibuat/di-rebuild)"
    )


class AskRequestSerializer(serializers.Serializer):
    query = serializers.CharField()
    top_k = serializers.IntegerField(required=False, default=5, min_value=1, max_value=20)


class AskSourceSerializer(serializers.Serializer):
    report_id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField(allow_null=True)
    score = serializers.FloatField()


class AskTimingSerializer(serializers.Serializer):
    embedding_ms = serializers.IntegerField(help_text="Waktu embed `query` jadi vektor (embed_text/embeddings.create)")
    vector_search_ms = serializers.IntegerField(help_text="Waktu pencarian nearest-neighbor di Qdrant (ReportVectorStore.search)")
    generation_ms = serializers.IntegerField(help_text="Waktu LLM men-generate jawaban (generate_answer/chat.completions.create)")
    total_ms = serializers.IntegerField(help_text="Total waktu ask_report() dari awal sampai akhir (embedding + vector search + generation)")


class AskResponseSerializer(serializers.Serializer):
    answer = serializers.CharField()
    sources = AskSourceSerializer(many=True)
    timing = AskTimingSerializer(help_text="Rincian waktu proses tiap tahap, dalam milidetik")
