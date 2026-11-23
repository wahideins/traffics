#!/usr/bin/env python3
"""Server RTSP palsu untuk mencoba dashboard tanpa kamera sungguhan.

ffmpeg membuat video uji (testsrc2) dan mengirimnya sebagai paket RTP; skrip ini
melayani klien RTSP (DESCRIBE/SETUP/PLAY, transport TCP interleaved) dan
meneruskan paket tersebut. Hanya untuk pengujian lokal, bukan server produksi.

Contoh:
    python tools/fake_rtsp_server.py
        -> rtsp://127.0.0.1:8554/live

    python tools/fake_rtsp_server.py --user admin --password 's4ndi@ku'
        -> rtsp://admin:...@127.0.0.1:8554/live (autentikasi Basic)

Butuh ffmpeg di PATH. Hentikan dengan Ctrl+C.
"""
import argparse
import base64
import os
import random
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time


class Relay:
    """Menerima paket RTP dari ffmpeg (UDP lokal) dan membagikannya ke klien yang sedang PLAY."""

    def __init__(self, rtp_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 22)
        self.sock.bind(("127.0.0.1", rtp_port))
        self.sessions = set()
        self.lock = threading.Lock()

    def add(self, session):
        with self.lock:
            self.sessions.add(session)

    def remove(self, session):
        with self.lock:
            self.sessions.discard(session)

    def run(self):
        while True:
            packet = self.sock.recv(65536)
            with self.lock:
                targets = list(self.sessions)
            for session in targets:
                session.send_rtp(packet)


class Session:
    def __init__(self, conn):
        self.conn = conn
        self.write_lock = threading.Lock()
        self.channel = 0
        self.playing = False

    def send_rtp(self, packet):
        if not self.playing:
            return
        frame = b"$" + bytes([self.channel]) + len(packet).to_bytes(2, "big") + packet
        try:
            with self.write_lock:
                self.conn.sendall(frame)
        except OSError:
            self.playing = False

    def reply(self, status, cseq, headers=(), body=b""):
        lines = [f"RTSP/1.0 {status}", f"CSeq: {cseq}"] + [f"{k}: {v}" for k, v in headers]
        if body:
            lines.append(f"Content-Length: {len(body)}")
        data = ("\r\n".join(lines) + "\r\n\r\n").encode() + body
        with self.write_lock:
            self.conn.sendall(data)


def read_request(stream):
    """Baca satu permintaan RTSP; lewati paket interleaved ($) dari klien (mis. RTCP)."""
    while True:
        first = stream.read(1)
        if not first:
            return None
        if first == b"$":
            header = stream.read(3)
            if len(header) < 3:
                return None
            stream.read(int.from_bytes(header[1:3], "big"))
            continue
        line = first + stream.readline()
        if not line.strip():
            continue
        parts = line.decode("latin-1").split()
        if len(parts) < 2:
            return None
        headers = {}
        while True:
            raw = stream.readline()
            if not raw or raw in (b"\r\n", b"\n"):
                break
            key, _, value = raw.decode("latin-1").partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length", "0") or 0)
        if length:
            stream.read(length)
        return parts[0].upper(), parts[1], headers


def prepare_sdp(text):
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line]
    out = []
    for line in lines:
        if line.startswith("m=video"):
            parts = line.split()
            parts[1] = "0"  # port ditentukan saat SETUP
            line = " ".join(parts)
        out.append(line)
    out.append("a=control:streamid=0")
    return ("\r\n".join(out) + "\r\n").encode()


def make_handler(args, sdp, relay):
    expected = None
    if args.user:
        expected = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            session = Session(self.request)
            session_id = f"{random.randint(10**7, 10**8 - 1)}"
            try:
                while True:
                    request = read_request(self.rfile)
                    if request is None:
                        break
                    method, url, headers = request
                    cseq = headers.get("cseq", "0")

                    if expected and headers.get("authorization") != expected:
                        session.reply("401 Unauthorized", cseq, [("WWW-Authenticate", 'Basic realm="fake"')])
                        continue

                    if method == "OPTIONS":
                        session.reply("200 OK", cseq, [("Public", "OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN, GET_PARAMETER")])
                    elif method == "DESCRIBE":
                        session.reply(
                            "200 OK", cseq,
                            [("Content-Type", "application/sdp"), ("Content-Base", url.rstrip("/") + "/")],
                            sdp,
                        )
                    elif method == "SETUP":
                        transport = headers.get("transport", "")
                        if "interleaved=" not in transport:
                            session.reply("461 Unsupported Transport", cseq)
                            continue
                        channels = transport.split("interleaved=")[1].split(";")[0]
                        session.channel = int(channels.split("-")[0])
                        session.reply(
                            "200 OK", cseq,
                            [("Transport", f"RTP/AVP/TCP;unicast;interleaved={channels}"), ("Session", session_id)],
                        )
                    elif method == "PLAY":
                        session.reply("200 OK", cseq, [("Session", session_id), ("Range", "npt=0.000-")])
                        session.playing = True
                        relay.add(session)
                    elif method in ("GET_PARAMETER", "SET_PARAMETER"):
                        session.reply("200 OK", cseq, [("Session", session_id)])
                    elif method == "TEARDOWN":
                        session.reply("200 OK", cseq, [("Session", session_id)])
                        break
                    else:
                        session.reply("501 Not Implemented", cseq)
            except (OSError, ValueError):
                pass
            finally:
                session.playing = False
                relay.remove(session)

    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument("--path", default="live")
    parser.add_argument("--size", default="640x360")
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--rtp-port", type=int, default=15004, help="port UDP lokal untuk RTP dari ffmpeg")
    parser.add_argument("--user", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg tidak ditemukan di PATH.")

    def _terminate(*_):
        raise KeyboardInterrupt  # agar blok finally ikut mematikan ffmpeg

    signal.signal(signal.SIGTERM, _terminate)

    relay = Relay(args.rtp_port)  # bind dulu sebelum ffmpeg mulai mengirim
    workdir = tempfile.mkdtemp(prefix="fake-rtsp-")
    sdp_path = os.path.join(workdir, "stream.sdp")
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-loglevel", "error", "-re",
            "-f", "lavfi", "-i", f"testsrc2=size={args.size}:rate={args.fps}",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-g", str(args.fps * 2), "-bf", "0",
            "-f", "rtp", "-sdp_file", sdp_path,
            f"rtp://127.0.0.1:{args.rtp_port}?pkt_size=1200",
        ]
    )
    try:
        for _ in range(100):
            if os.path.exists(sdp_path) and os.path.getsize(sdp_path) > 0:
                break
            if ffmpeg.poll() is not None:
                sys.exit("ffmpeg berhenti sebelum siap.")
            time.sleep(0.1)
        else:
            sys.exit("ffmpeg tidak menghasilkan SDP.")
        with open(sdp_path, encoding="utf-8") as handle:
            sdp = prepare_sdp(handle.read())

        threading.Thread(target=relay.run, daemon=True).start()
        with Server((args.host, args.port), make_handler(args, sdp, relay)) as server:
            auth = f"{args.user}:****@" if args.user else ""
            print(f"RTSP palsu siap: rtsp://{auth}{args.host}:{args.port}/{args.path}  (Ctrl+C untuk berhenti)", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ffmpeg.terminate()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
