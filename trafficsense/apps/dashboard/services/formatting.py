"""Format angka.

Penting: Django memakai locale Indonesia sehingga float di template tampil
dengan koma (12,5). Nilai yang masuk ke CSS (tinggi/lebar bar, posisi) harus
berupa string bertitik, makanya dipakai `css_number` di sini.
"""


def format_int(value) -> str:
    """12345 -> '12.345' (pemisah ribuan gaya Indonesia)."""
    return f"{int(round(value)):,}".replace(",", ".")


def format_decimal(value, digits: int = 1) -> str:
    """12.5 -> '12,5' (untuk teks yang dibaca pengguna)."""
    return f"{value:.{digits}f}".replace(".", ",")


def css_number(value, digits: int = 1) -> str:
    """12.5 -> '12.5' (aman dipakai di atribut style)."""
    return f"{value:.{digits}f}"
