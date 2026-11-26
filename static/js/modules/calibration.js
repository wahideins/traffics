// Dialog kalibrasi: pengguna mengklik arah A, median, dan jarak referensi di atas gambar kamera.
import { postForm } from "../api.js";
import { qs, qsa } from "../utils/dom.js";

const TOOLS = { axis: 2, median: 1, ref: 2, roi: 2 };
const NEXT = { axis: "median", median: "ref", ref: "roi", roi: "roi" };
const TOOL_HINT = {
  axis: "Klik titik awal, lalu titik akhir, searah lalu lintas Arah A.",
  median: "Klik satu titik di pemisah jalur (lewati bila jalan tanpa median).",
  ref: "Klik dua titik di jalan yang jarak aslinya Anda ketahui, lalu isi jaraknya.",
  roi: "Klik dua sudut berlawanan untuk membingkai area jalan (lewati untuk memakai seluruh gambar).",
};

const saved = new Map(); // kalibrasi terbaru per kamera (halaman tidak memuat ulang panel)
let current = null;

const dialog = () => document.getElementById("calibration-dialog");
const stage = () => qs("[data-cal-stage]", dialog());

function fresh() {
  return { tool: "axis", axis: [], median: null, ref: [], roi: [], line_pos: 0.5, one_way: false, ref_m: "" };
}

function fromStored(data) {
  const state = fresh();
  if (!data) return state;
  state.axis = (data.axis || []).map((p) => [p[0], p[1]]);
  state.median = data.median ? [data.median[0], data.median[1]] : null;
  state.ref = (data.ref || []).map((p) => [p[0], p[1]]);
  state.roi = (data.roi || []).map((p) => [p[0], p[1]]);
  state.line_pos = data.line_pos ?? 0.5;
  state.one_way = Boolean(data.one_way);
  state.ref_m = data.ref_m ? String(data.ref_m).replace(".", ",") : "";
  return state;
}

function setLine(name, a, b) {
  const line = qs(`[data-cal-line="${name}"]`, dialog());
  if (!a || !b) {
    line.setAttribute("visibility", "hidden");
    return;
  }
  line.setAttribute("visibility", "visible");
  line.setAttribute("x1", a[0]);
  line.setAttribute("y1", a[1]);
  line.setAttribute("x2", b[0]);
  line.setAttribute("y2", b[1]);
}

function countLine(axis, pos, rect) {
  // Tegak lurus panah, dihitung dalam piksel agar tegak lurus sungguhan (bukan ter-skala aspek).
  const [p0, p1] = axis;
  const w = rect.width || 1;
  const h = rect.height || 1;
  const vx = (p1[0] - p0[0]) * w;
  const vy = (p1[1] - p0[1]) * h;
  const len = Math.hypot(vx, vy) || 1;
  const ux = vx / len;
  const uy = vy / len;
  const cx = p0[0] * w + vx * pos;
  const cy = p0[1] * h + vy * pos;
  const half = 0.3 * Math.max(w, h);
  return [
    [(cx + uy * half) / w, (cy - ux * half) / h],
    [(cx - uy * half) / w, (cy + ux * half) / h],
  ];
}

function render() {
  const s = current;
  const rect = stage().getBoundingClientRect();
  setLine("axis", s.axis[0], s.axis[1]);
  setLine("ref", s.ref[0], s.ref[1]);
  const roiEl = qs("[data-cal-roi]", dialog());
  if (s.roi.length === 2) {
    const [a, b] = s.roi;
    roiEl.setAttribute("visibility", "visible");
    roiEl.setAttribute("x", Math.min(a[0], b[0]));
    roiEl.setAttribute("y", Math.min(a[1], b[1]));
    roiEl.setAttribute("width", Math.abs(a[0] - b[0]));
    roiEl.setAttribute("height", Math.abs(a[1] - b[1]));
  } else {
    roiEl.setAttribute("visibility", "hidden");
  }
  if (s.axis.length === 2) {
    const [a, b] = countLine(s.axis, s.line_pos, rect);
    setLine("count", a, b);
  } else {
    setLine("count");
  }

  const markers = qs("[data-cal-markers]", dialog());
  markers.replaceChildren();
  const add = (point, kind, label) => {
    const el = document.createElement("span");
    el.className = `cal-marker cal-marker--${kind}`;
    el.style.left = `${point[0] * 100}%`;
    el.style.top = `${point[1] * 100}%`;
    el.title = label;
    markers.append(el);
  };
  s.axis.forEach((p, i) => add(p, "axis", i === 0 ? "Awal Arah A" : "Akhir Arah A"));
  if (s.median) add(s.median, "median", "Median");
  s.ref.forEach((p, i) => add(p, "ref", `Referensi ${i + 1}`));
  s.roi.forEach((p, i) => add(p, "roi", `Sudut area ${i + 1}`));

  qsa("[data-cal-tool]", dialog()).forEach((button) => {
    const tool = button.dataset.calTool;
    const count = tool === "median" ? (s.median ? 1 : 0) : s[tool].length;
    button.classList.toggle("is-active", s.tool === tool);
    button.classList.toggle("is-done", count === TOOLS[tool]);
    button.setAttribute("aria-pressed", String(s.tool === tool));
  });

  qs("[data-cal-msg]", dialog()).textContent = TOOL_HINT[s.tool];
  qs("[data-cal-linepos-out]", dialog()).textContent = Math.round(s.line_pos * 100);
  qs('[data-cal-input="line_pos"]', dialog()).value = Math.round(s.line_pos * 100);
  qs('[data-cal-input="ref_m"]', dialog()).value = s.ref_m;
  qs('[data-cal-input="one_way"]', dialog()).checked = s.one_way;
}

function status(kind, text) {
  const el = qs("[data-cal-status]", dialog());
  el.textContent = text;
  el.className = `form-status${kind ? ` form-status--${kind}` : ""}`;
}

function onStageClick(event) {
  const rect = stage().getBoundingClientRect();
  const point = [
    Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  ].map((v) => Math.round(v * 10000) / 10000);

  const s = current;
  if (s.tool === "median") {
    s.median = point;
  } else {
    if (s[s.tool].length >= 2) s[s.tool] = [];
    s[s.tool].push(point);
  }
  const done = s.tool === "median" ? Boolean(s.median) : s[s.tool].length === 2;
  if (done) s.tool = NEXT[s.tool];
  status("", "");
  render();
}

function open(button) {
  const id = button.dataset.cameraId;
  let stored = saved.get(id);
  if (!stored && button.dataset.calibration) {
    try {
      stored = JSON.parse(button.dataset.calibration);
    } catch {
      stored = null;
    }
  }
  current = fromStored(stored);
  current.cameraId = id;
  current.url = button.dataset.calibrationUrl;
  qs("[data-cal-camera]", dialog()).textContent = `${id} · ${button.dataset.cameraName}`;
  status("", "");

  const img = qs("[data-cal-img]", dialog());
  img.onload = () => {
    render();
  };
  img.onerror = () => {
    qs("[data-cal-msg]", dialog()).textContent = "Belum ada gambar dari kamera. Pastikan statusnya LIVE lalu buka lagi.";
  };
  img.src = `${button.dataset.snapshotUrl}?t=${Date.now()}`;
  dialog().showModal();
  render();
}

async function save() {
  const s = current;
  const payload = { axis: s.axis, line_pos: s.line_pos, one_way: s.one_way };
  if (s.roi.length) payload.roi = s.roi;
  if (s.median) payload.median = s.median;
  if (s.ref.length || s.ref_m) {
    payload.ref = s.ref;
    payload.ref_m = s.ref_m;
  }
  status("info", "Menyimpan…");
  const { ok, data } = await postForm(s.url, payload, { json: true });
  if (ok && data.ok) {
    saved.set(s.cameraId, payload);
    dialog().close();
    return;
  }
  const first = data.errors ? Object.values(data.errors)[0] : "Gagal menyimpan kalibrasi.";
  status("error", first);
}

export function initCalibration() {
  const root = dialog();
  if (!root) return;

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    switch (button.dataset.action) {
      case "open-calibration": return open(button);
      case "close-calibration": return root.close();
      case "save-calibration": return save();
      case "reset-calibration": {
        const { cameraId, url } = current;
        current = { ...fresh(), cameraId, url };
        status("", "");
        return render();
      }
    }
  });

  stage().addEventListener("click", onStageClick);
  window.addEventListener("resize", () => current && root.open && render());
  root.addEventListener("click", (event) => {
    if (event.target === root) root.close();
  });

  qsa("[data-cal-tool]", root).forEach((button) =>
    button.addEventListener("click", () => {
      current.tool = button.dataset.calTool;
      render();
    }),
  );
  qs('[data-cal-input="line_pos"]', root).addEventListener("input", (event) => {
    current.line_pos = Number(event.target.value) / 100;
    render();
  });
  qs('[data-cal-input="ref_m"]', root).addEventListener("input", (event) => {
    current.ref_m = event.target.value.trim();
  });
  qs('[data-cal-input="one_way"]', root).addEventListener("change", (event) => {
    current.one_way = event.target.checked;
  });
}
