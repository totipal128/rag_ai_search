import random

from django.core.management.base import BaseCommand
from faker import Faker

from apps.report.models import Report

JENIS_PENGAWASAN = [
    "Pengawasan Proyek Konstruksi Jalan",
    "Pengawasan Distribusi BBM Bersubsidi",
    "Pengawasan Peredaran Obat dan Makanan",
    "Pengawasan Lingkungan Hidup",
    "Pengawasan Ketenagakerjaan",
    "Pengawasan Pasar Tradisional",
    "Pengawasan Penyaluran Bantuan Sosial",
    "Pengawasan Keamanan Pangan",
    "Pengawasan Bangunan Tanpa Izin",
    "Pengawasan Perizinan Usaha",
    "Pengawasan Pengelolaan Limbah B3",
    "Pengawasan Proyek Pembangunan Gedung Sekolah",
    "Pengawasan Distribusi Pupuk Bersubsidi",
    "Pengawasan Kualitas Air Bersih",
    "Pengawasan Tambang Rakyat",
]

WHO_POOL = [
    "Tim Inspektorat Daerah",
    "Dinas Lingkungan Hidup",
    "Satuan Polisi Pamong Praja",
    "Dinas Perindustrian dan Perdagangan",
    "Kepolisian Sektor setempat",
    "Camat",
    "Lurah",
    "Warga sekitar",
    "Pengawas Ketenagakerjaan",
    "Dinas Pekerjaan Umum",
    "Badan Lingkungan Hidup Daerah",
    "Komisi Pengawas",
]

WHAT_POOL = [
    "dugaan pelanggaran prosedur keselamatan kerja",
    "penyimpangan penggunaan anggaran proyek",
    "temuan bahan baku kadaluarsa",
    "aktivitas pembangunan tanpa Izin Mendirikan Bangunan (IMB)",
    "dugaan penyalahgunaan bantuan sosial",
    "pencemaran limbah ke saluran air warga",
    "ketidaksesuaian spesifikasi material dengan RAB",
    "keterlambatan progres pekerjaan dari jadwal",
    "penjualan produk tanpa label BPOM",
    "praktik penimbunan bahan bakar bersubsidi",
]

WHY_POOL = [
    "adanya laporan masyarakat melalui pengaduan resmi",
    "hasil temuan rutin tim pengawas lapangan",
    "tindak lanjut pengaduan dari media sosial",
    "sesuai jadwal pengawasan tahunan",
    "instruksi langsung dari kepala dinas terkait",
    "hasil audit internal triwulanan",
    "laporan dari perangkat desa setempat",
]

HOW_POOL = [
    "peninjauan langsung ke lokasi kegiatan",
    "pemeriksaan dokumen dan administrasi proyek",
    "wawancara dengan pihak terkait dan saksi",
    "pengambilan sampel untuk uji laboratorium",
    "pengukuran dan dokumentasi kondisi lapangan",
    "koordinasi lintas instansi terkait temuan",
    "pemantauan berkala selama satu minggu",
]

def random_how_much_pool():
    return [
        "kerugian ditaksir sekitar Rp {:,} juta".format(random.randint(5, 500)),
        "melibatkan {} unit bangunan/fasilitas".format(random.randint(1, 10)),
        "{} orang saksi telah dimintai keterangan".format(random.randint(1, 8)),
        "estimasi volume terdampak {} meter kubik".format(random.randint(10, 1000)),
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
    help = "Generate dummy data laporan pengawasan untuk tabel Report"

    def add_arguments(self, parser):
        parser.add_argument(
            "--total",
            type=int,
            default=500,
            help="Jumlah data dummy yang dibuat (default: 500)",
        )
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Hapus semua data Report sebelum generate data baru",
        )

    def handle(self, *args, **options):
        total = options["total"]
        fake = Faker("id_ID")

        if options["flush"]:
            deleted, _ = Report.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Menghapus {deleted} data lama."))

        reports = []
        for i in range(total):
            jenis = random.choice(JENIS_PENGAWASAN)
            provinsi, kota, base_lat, base_lng = random.choice(PROVINSI_KOTA)

            what = random.sample(WHAT_POOL, k=random.randint(1, 2))
            who = random.sample(WHO_POOL, k=random.randint(1, 3))
            why = random.sample(WHY_POOL, k=random.randint(1, 2))
            how = random.sample(HOW_POOL, k=random.randint(1, 3))
            how_much = random.sample(random_how_much_pool(), k=random.randint(1, 2))

            tanggal = fake.date_between(start_date="-1y", end_date="today")
            when = [tanggal.strftime("%Y-%m-%d")]
            where = [f"{kota}, {provinsi}"]

            original_text = (
                f"Pada tanggal {tanggal.strftime('%d %B %Y')}, dilakukan {jenis.lower()} "
                f"di wilayah {kota}, {provinsi}. Kegiatan pengawasan ini dilatarbelakangi oleh "
                f"{'; '.join(why)}. Ditemukan {'; '.join(what)}. Pengawasan dilakukan oleh "
                f"{', '.join(who)} melalui {'; '.join(how)}. Berdasarkan hasil pemeriksaan, "
                f"{'; '.join(how_much)}."
            )

            reports.append(
                Report(
                    title=f"Laporan {jenis} - {kota} #{i + 1}",
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
        self.stdout.write(self.style.SUCCESS(f"Berhasil membuat {len(reports)} data laporan pengawasan."))
