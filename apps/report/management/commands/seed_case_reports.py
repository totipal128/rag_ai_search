import random

from django.core.management.base import BaseCommand
from faker import Faker

from apps.report.models import Report

JENIS_KASUS = [
    "Dugaan Pembunuhan",
    "Peredaran Narkotika",
    "Dugaan Penistaan Agama",
    "Pencurian dengan Pemberatan",
    "Penipuan dan Penggelapan",
    "Kekerasan Dalam Rumah Tangga (KDRT)",
    "Perjudian Online",
    "Dugaan Terorisme",
    "Perdagangan Orang (TPPO)",
    "Korupsi Dana Desa",
    "Penganiayaan Berat",
    "Pemerasan dan Ancaman",
]

WHO_POOL = [
    "Kepolisian Resor setempat",
    "Kejaksaan Negeri",
    "Badan Narkotika Nasional (BNN)",
    "Densus 88 Anti Teror",
    "Satgas TPPO",
    "Unit Reserse Kriminal Polda",
    "Komnas HAM",
    "Majelis Ulama Indonesia (MUI) setempat",
    "Dinas Sosial",
    "Pusat Pelayanan Terpadu Perempuan dan Anak",
]

WHAT_POOL = [
    "penemuan barang bukti di lokasi kejadian",
    "laporan resmi dari korban atau keluarga korban",
    "hasil pemeriksaan awal tim forensik",
    "temuan transaksi keuangan yang mencurigakan",
    "unggahan konten di media sosial yang dilaporkan warga",
    "kesaksian saksi mata di lokasi kejadian",
    "hasil pengembangan dari kasus sebelumnya",
    "penangkapan tersangka dalam operasi rutin",
]

WHY_POOL = [
    "laporan resmi dari korban/keluarga korban ke kantor polisi",
    "hasil operasi tangkap tangan aparat penegak hukum",
    "aduan masyarakat melalui hotline atau layanan pengaduan",
    "tindak lanjut informasi intelijen",
    "viral dan meresahkan warga di media sosial",
    "hasil patroli rutin aparat keamanan",
]

HOW_POOL = [
    "olah tempat kejadian perkara (TKP) oleh tim identifikasi",
    "pemeriksaan intensif terhadap saksi dan tersangka",
    "uji forensik terhadap barang bukti yang diamankan",
    "penyelidikan dan penyidikan sesuai prosedur hukum",
    "koordinasi lintas instansi (Kepolisian, Kejaksaan, BNN)",
    "gelar perkara untuk menentukan status hukum kasus",
]

HOW_MUCH_TEMPLATES = [
    lambda: f"{random.randint(1, 5)} tersangka telah diamankan",
    lambda: f"barang bukti berupa narkotika jenis sabu seberat {random.randint(1, 500)} gram",
    lambda: f"kerugian ditaksir sekitar Rp {random.randint(5, 800)} juta",
    lambda: f"{random.randint(1, 10)} orang saksi telah dimintai keterangan",
    lambda: "kasus masih dalam tahap penyelidikan lebih lanjut",
]

PROVINSI_KOTA = [
    ("Jawa Barat", "Bandung", -6.9175, 107.6191),
    ("Jawa Tengah", "Semarang", -6.9932, 110.4203),
    ("Jawa Timur", "Surabaya", -7.2575, 112.7521),
    ("DKI Jakarta", "Jakarta Selatan", -6.2615, 106.8106),
    ("Banten", "Serang", -6.1149, 106.1503),
    ("Sumatera Utara", "Medan", 3.5952, 98.6722),
    ("Sumatera Barat", "Padang", -0.9471, 100.4172),
    ("Kalimantan Timur", "Samarinda", -0.5022, 117.1536),
    ("Kalimantan Selatan", "Banjarmasin", -3.3194, 114.5906),
    ("Sulawesi Selatan", "Makassar", -5.1477, 119.4327),
    ("Bali", "Denpasar", -8.6705, 115.2126),
    ("Nusa Tenggara Barat", "Mataram", -8.5833, 116.1167),
    ("Riau", "Pekanbaru", 0.5333, 101.4500),
    ("Yogyakarta", "Yogyakarta", -7.7956, 110.3695),
    ("Sulawesi Utara", "Manado", 1.4748, 124.8421),
]


class Command(BaseCommand):
    help = "Generate dummy data laporan kasus hukum/kriminal (fiktif) untuk tabel Report"

    def add_arguments(self, parser):
        parser.add_argument("--total", type=int, default=100)

    def handle(self, *args, **options):
        total = options["total"]
        fake = Faker("id_ID")

        reports = []
        for i in range(total):
            jenis = random.choice(JENIS_KASUS)
            provinsi, kota, base_lat, base_lng = random.choice(PROVINSI_KOTA)

            what = random.sample(WHAT_POOL, k=random.randint(1, 2))
            who = random.sample(WHO_POOL, k=random.randint(1, 3))
            why = random.sample(WHY_POOL, k=random.randint(1, 2))
            how = random.sample(HOW_POOL, k=random.randint(1, 3))
            how_much = [f() for f in random.sample(HOW_MUCH_TEMPLATES, k=random.randint(1, 2))]

            tanggal = fake.date_between(start_date="-1y", end_date="today")
            when = [tanggal.strftime("%Y-%m-%d")]
            where = [f"{kota}, {provinsi}"]

            original_text = (
                f"Pada tanggal {tanggal.strftime('%d %B %Y')}, ditangani kasus {jenis.lower()} "
                f"di wilayah {kota}, {provinsi}. Penanganan kasus ini bermula dari "
                f"{'; '.join(why)}. Ditemukan {'; '.join(what)}. Kasus ditangani oleh "
                f"{', '.join(who)} melalui {'; '.join(how)}. Berdasarkan perkembangan kasus, "
                f"{'; '.join(how_much)}."
            )

            reports.append(
                Report(
                    title=f"Laporan Kasus {jenis} - {kota} #{i + 1}",
                    what=what,
                    who=who,
                    when=when,
                    where=where,
                    why=why,
                    how=how,
                    how_much=how_much,
                    original_text=original_text,
                    location=f"{kota}, {provinsi}",
                    latitude=round(base_lat + random.uniform(-0.05, 0.05), 6),
                    longitude=round(base_lng + random.uniform(-0.05, 0.05), 6),
                )
            )

        Report.objects.bulk_create(reports)
        self.stdout.write(self.style.SUCCESS(f"Berhasil membuat {len(reports)} data laporan kasus (fiktif)."))
