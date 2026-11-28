"""Penulis video. ffmpeg (H.264, bisa diputar di browser) dipakai bila ada; cadangannya OpenCV (mp4v)."""
import shutil
import subprocess


class WriterError(RuntimeError):
    pass


class FfmpegWriter:
    codec = "h264"

    def __init__(self, path, width, height, fps, ffmpeg):
        # MP4 pecahan (fragmented): berkas tetap bisa diputar walau server mati mendadak.
        cmd = [
            ffmpeg, "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:g}", "-i", "-",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
            "-movflags", "+frag_keyframe+empty_moov+default_base_moof", str(path),
        ]
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise WriterError("ffmpeg tidak bisa dijalankan.") from exc

    def write(self, frame):
        try:
            self._proc.stdin.write(frame.tobytes())
        except (OSError, ValueError) as exc:
            raise WriterError("ffmpeg berhenti.") from exc

    def close(self):
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._proc.kill()


class CvWriter:
    codec = "mp4v"

    def __init__(self, path, width, height, fps):
        import cv2

        self._w = None
        for code in ("avc1", "mp4v"):
            w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*code), fps, (width, height))
            if w.isOpened():
                self._w, self.codec = w, "h264" if code == "avc1" else "mp4v"
                break
            w.release()
        if self._w is None:
            raise WriterError("OpenCV tidak bisa membuat berkas video.")

    def write(self, frame):
        self._w.write(frame)

    def close(self):
        self._w.release()


def default_writer_factory(path, width, height, fps):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return FfmpegWriter(path, width, height, fps, ffmpeg)
    return CvWriter(path, width, height, fps)
