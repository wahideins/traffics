"""Indeks rekaman di SQLite (pustaka standar; tanpa migrasi Django).

Berkas video disimpan di disk; basis data hanya mencatat metadata agar mudah
dicari, diputar, dan dihapus. `path` disimpan relatif terhadap folder rekaman.
"""
import os
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera TEXT NOT NULL,
    started_at REAL NOT NULL,
    ended_at REAL,
    duration REAL NOT NULL DEFAULT 0,
    frames INTEGER NOT NULL DEFAULT 0,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    path TEXT NOT NULL,
    width INTEGER, height INTEGER, fps REAL,
    codec TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'recording'
);
CREATE INDEX IF NOT EXISTS idx_rec_camera_time ON recordings (camera, started_at DESC);
"""
COLUMNS = ("id", "camera", "started_at", "ended_at", "duration", "frames", "size_bytes", "path",
           "width", "height", "fps", "codec", "status")


class RecordingStore:
    def __init__(self, db_path, root):
        self.db_path = Path(db_path)
        self.root = Path(root)
        self._lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()
        self._recover()

    def close(self):
        with self._lock:
            self._db.close()

    def _recover(self):
        """Berkas yang masih 'recording' berarti server mati mendadak: tandai dan hitung ukurannya."""
        with self._lock:
            rows = self._db.execute("SELECT id, path, started_at FROM recordings WHERE status = 'recording'").fetchall()
            for row in rows:
                size = self._size(row["path"])
                self._db.execute(
                    "UPDATE recordings SET status = 'interrupted', size_bytes = ?, ended_at = COALESCE(ended_at, started_at) WHERE id = ?",
                    (size, row["id"]),
                )
            self._db.commit()

    def _size(self, rel):
        try:
            return os.path.getsize(self.root / rel)
        except OSError:
            return 0

    def full_path(self, rel):
        """Path absolut di dalam folder rekaman; ValueError bila keluar dari folder."""
        path = (self.root / rel).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Path di luar folder rekaman.")
        return path

    # --- tulis ------------------------------------------------------------
    def start(self, camera, started_at, rel_path, width, height, fps, codec):
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO recordings (camera, started_at, path, width, height, fps, codec) VALUES (?,?,?,?,?,?,?)",
                (camera, started_at, rel_path, width, height, fps, codec),
            )
            self._db.commit()
            return cur.lastrowid

    def finish(self, rec_id, ended_at, frames, status="done"):
        with self._lock:
            row = self._db.execute("SELECT path, fps FROM recordings WHERE id = ?", (rec_id,)).fetchone()
            if row is None:
                return
            fps = row["fps"] or 1.0
            self._db.execute(
                "UPDATE recordings SET ended_at = ?, frames = ?, duration = ?, size_bytes = ?, status = ? WHERE id = ?",
                (ended_at, frames, frames / fps, self._size(row["path"]), status, rec_id),
            )
            self._db.commit()

    def delete(self, rec_id):
        """Hapus baris dan berkasnya. True bila ada yang dihapus."""
        with self._lock:
            row = self._db.execute("SELECT path, status FROM recordings WHERE id = ?", (rec_id,)).fetchone()
            if row is None or row["status"] == "recording":
                return False
            self._db.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
            self._db.commit()
        try:
            self.full_path(row["path"]).unlink()
        except (OSError, ValueError):
            pass
        return True

    def delete_camera(self, camera):
        for rec in self.list(camera=camera, limit=100000):
            self.delete(rec["id"])

    def enforce_limit(self, max_bytes):
        """Hapus rekaman selesai tertua sampai total <= max_bytes. Kembalikan jumlah yang dihapus."""
        if max_bytes <= 0:
            return 0
        removed = 0
        while self.total_bytes() > max_bytes:
            with self._lock:
                row = self._db.execute(
                    "SELECT id FROM recordings WHERE status != 'recording' ORDER BY started_at ASC LIMIT 1"
                ).fetchone()
            if row is None or not self.delete(row["id"]):
                break
            removed += 1
        return removed

    # --- baca -------------------------------------------------------------
    def list(self, camera=None, limit=50, offset=0):
        sql, args = "SELECT * FROM recordings", []
        if camera:
            sql += " WHERE camera = ?"
            args.append(camera)
        sql += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        out = []
        for row in rows:
            item = {c: row[c] for c in COLUMNS}
            if item["status"] == "recording":
                item["size_bytes"] = self._size(item["path"])
            out.append(item)
        return out

    def get(self, rec_id):
        with self._lock:
            row = self._db.execute("SELECT * FROM recordings WHERE id = ?", (rec_id,)).fetchone()
        return {c: row[c] for c in COLUMNS} if row else None

    def count(self, camera=None):
        with self._lock:
            if camera:
                return self._db.execute("SELECT COUNT(*) FROM recordings WHERE camera = ?", (camera,)).fetchone()[0]
            return self._db.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]

    def total_bytes(self):
        with self._lock:
            done = self._db.execute("SELECT COALESCE(SUM(size_bytes),0) FROM recordings WHERE status != 'recording'").fetchone()[0]
            live = self._db.execute("SELECT path FROM recordings WHERE status = 'recording'").fetchall()
        return done + sum(self._size(r["path"]) for r in live)
