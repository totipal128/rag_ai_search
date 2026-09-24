from django.db import models

# Field 5W+2H — disimpan sebagai JSONField berisi array string.
FIVE_W_TWO_H_FIELDS = ["what", "who", "when", "where", "why", "how", "how_much"]


class Report(models.Model):
    title = models.TextField(blank=True)
    # 5W + 2H — JSONField, tiap field menyimpan array string, mis. ["a", "b"]
    what = models.JSONField(blank=True, default=list)
    who = models.JSONField(blank=True, default=list)
    when = models.JSONField(blank=True, default=list)
    where = models.JSONField(blank=True, default=list)
    why = models.JSONField(blank=True, default=list)
    how = models.JSONField(blank=True, default=list)
    how_much = models.JSONField(blank=True, default=list)

    original_text = models.TextField(blank=True, null=True)

    # Lokasi
    location = models.CharField(max_length=255, blank=True, null=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)


    def save(self, *args, **kwargs):
        # Field 5W+2H selalu berkontrak sebagai array string. Kalau ada yang meng-assign
        # string tunggal atau None (mis. dari shell/admin/skrip data), normalisasi di sini
        # supaya yang tersimpan & ditampilkan tetap konsisten satu array, bukan JSON string.
        for field_name in FIVE_W_TWO_H_FIELDS:
            value = getattr(self, field_name)
            if value is None:
                setattr(self, field_name, [])
            elif isinstance(value, str):
                setattr(self, field_name, [value])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Report #{self.pk} - {self.title}"