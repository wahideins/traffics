// Halaman kalibrasi: penanda arah/median/jarak/area dan zona lajur (poligon) di atas gambar kamera.
import { postForm } from "../api.js";
import { qs, qsa } from "../utils/dom.js";

const TOOLS = { axis: 2, median: 1, ref: 2, roi: 2 };
const NEXT = { axis: "median", median: "ref", ref: "roi", roi: "roi" };
const HINT = {
  axis: "Klik titik awal, lalu titik akhir, searah lalu lintas Arah A.",
  median: "Klik satu titik di pemisah jalur (lewati bila jalan tanpa median).",
  ref: "Klik dua titik di jalan yang jarak aslinya Anda ketahui, lalu isi jaraknya.",
  roi: "Klik dua sudut berlawanan untuk membingkai area jalan (lewati untuk memakai seluruh gambar).",
  zone: "Klik sudut-sudut zona. Klik titik pertama atau tekan Enter untuk menutup; Esc membatalkan.",
};
const stillError = () =>
  `Gambar diam gagal diambil (${stillDetail}). Memakai video langsung sebagai latar; Anda tetap bisa menandai. Tekan "Coba ambil gambar lagi" untuk mencoba lagi.`;
const PALETTE = ["#3d8cff", "#ef4444", "#22c55e", "#a855f7", "#f59e0b", "#14b8a6", "#ec4899", "#84cc16"];
const MAX_ZONES = 8;
const CLOSE_PX = 14;
const SVG = "http://www.w3.org/2000/svg";

let root;
let s; // keadaan
let dirty = false;
let drag = null;
let suppressClick = false;
let statsTimer = null;
let stillFailed = false;

const $ = (sel) => qs(sel, root);
const stage = () => $("[data-cal-stage]");

const round4 = (v) => Math.round(v * 10000) / 10000;
const pts = (list) => (list || []).map((p) => [p[0], p[1]]);

function fromStored(data) {
  const state = {
    tool: "axis", axis: [], median: null, ref: [], roi: [], zones: [], active: null, drawing: false,
    line_pos: 0.5, one_way: false, zones_only: false, ref_m: "",
  };
  if (!data || !data.axis) return state;
  state.axis = pts(data.axis);
  state.median = data.median ? [data.median[0], data.median[1]] : null;
  state.ref = pts(data.ref);
  state.roi = pts(data.roi);
  state.zones = (data.zones || []).map((z) => ({ name: z.name, color: z.color, direction: z.direction || "a", points: pts(z.points) }));
  state.line_pos = data.line_pos ?? 0.5;
  state.one_way = Boolean(data.one_way);
  state.zones_only = Boolean(data.zones_only);
  state.ref_m = data.ref_m ? String(data.ref_m).replace(".", ",") : "";
  state.tool = state.axis.length === 2 ? "zone" : "axis";
  return state;
}

function setDirty(value = true) {
  dirty = value;
  $("[data-cal-dirty]").hidden = !dirty;
}

function status(kind, text) {
  const el = $("[data-cal-status]");
  el.textContent = text;
  el.className = `form-status${kind ? ` form-status--${kind}` : ""}`;
}

// ---- gambar ---------------------------------------------------------------
function setLine(name, a, b) {
  const line = qs(`[data-cal-line="${name}"]`, root);
  if (!a || !b) return line.setAttribute("visibility", "hidden");
  line.setAttribute("visibility", "visible");
  line.setAttribute("x1", a[0]);
  line.setAttribute("y1", a[1]);
  line.setAttribute("x2", b[0]);
  line.setAttribute("y2", b[1]);
}

function countLine(axis, pos, rect) {
  // Tegak lurus panah dihitung dalam piksel agar tegak lurus sungguhan (bukan ter-skala aspek).
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

function renderZonesSvg() {
  const g = $("[data-cal-zones]");
  g.replaceChildren();
  s.zones.forEach((zone, i) => {
    if (zone.points.length < 2) return;
    const closed = !(s.drawing && i === s.active);
    const el = document.createElementNS(SVG, closed ? "polygon" : "polyline");
    el.setAttribute("points", zone.points.map((p) => `${p[0]},${p[1]}`).join(" "));
    el.setAttribute("class", `cal-zone${i === s.active ? " is-active" : ""}`);
    el.style.setProperty("--zone", zone.color);
    g.append(el);
  });
}

function renderMarkers() {
  const markers = $("[data-cal-markers]");
  markers.replaceChildren();
  const add = (point, kind, label, extra = {}) => {
    const el = document.createElement("span");
    el.className = `cal-marker cal-marker--${kind}`;
    el.style.left = `${point[0] * 100}%`;
    el.style.top = `${point[1] * 100}%`;
    el.title = label;
    if (extra.color) el.style.background = extra.color;
    if (extra.zone !== undefined) {
      el.dataset.zone = extra.zone;
      el.dataset.vertex = extra.vertex;
    }
    markers.append(el);
  };
  s.axis.forEach((p, i) => add(p, "axis", i === 0 ? "Awal Arah A" : "Akhir Arah A"));
  if (s.median) add(s.median, "median", "Median");
  s.ref.forEach((p, i) => add(p, "ref", `Referensi ${i + 1}`));
  s.roi.forEach((p, i) => add(p, "roi", `Sudut area ${i + 1}`));
  s.zones.forEach((zone, zi) =>
    zone.points.forEach((p, vi) =>
      add(p, "zone", `${zone.name}: titik ${vi + 1} (seret untuk geser, klik dua kali untuk hapus)`, {
        color: zone.color, zone: zi, vertex: vi,
      }),
    ),
  );

  const labels = $("[data-cal-labels]");
  labels.replaceChildren();
  s.zones.forEach((zone) => {
    if (zone.points.length < 3 && s.drawing) return;
    if (!zone.points.length) return;
    const cx = zone.points.reduce((a, p) => a + p[0], 0) / zone.points.length;
    const top = Math.min(...zone.points.map((p) => p[1]));
    const el = document.createElement("span");
    el.className = "cal-zone-label";
    el.textContent = zone.name;
    el.style.left = `${cx * 100}%`;
    el.style.top = `${top * 100}%`;
    el.style.background = zone.color;
    labels.append(el);
  });
}

function renderTools() {
  qsa("[data-cal-tool]", root).forEach((button) => {
    const tool = button.dataset.calTool;
    const done = tool === "zone"
      ? s.zones.length > 0 && !s.drawing
      : (tool === "median" ? (s.median ? 1 : 0) : s[tool].length) === TOOLS[tool];
    button.classList.toggle("is-active", s.tool === tool);
    button.classList.toggle("is-done", done);
    button.setAttribute("aria-pressed", String(s.tool === tool));
  });
}

function renderMain() {
  const rect = stage().getBoundingClientRect();
  setLine("axis", s.axis[0], s.axis[1]);
  setLine("ref", s.ref[0], s.ref[1]);
  const roiEl = $("[data-cal-roi]");
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
  renderZonesSvg();
  renderMarkers();
  renderTools();
  $("[data-cal-msg]").textContent = previewOn() ? "" : stillFailed ? stillError() : HINT[s.tool];
  $('[data-action="retry-still"]').hidden = !stillFailed;
  $("[data-cal-linepos-out]").textContent = Math.round(s.line_pos * 100);
  $('[data-cal-input="line_pos"]').value = Math.round(s.line_pos * 100);
  $('[data-cal-input="ref_m"]').value = s.ref_m;
  $('[data-cal-input="one_way"]').checked = s.one_way;
  $('[data-cal-input="zones_only"]').checked = s.zones_only;
}

function renderZoneList() {
  const list = $("[data-zone-list]");
  list.replaceChildren();
  s.zones.forEach((zone, i) => {
    const li = document.createElement("li");
    li.className = `zone-item${i === s.active ? " is-active" : ""}`;
    li.innerHTML =
      '<input type="color" class="zone-item__color" aria-label="Warna zona">' +
      '<input type="text" class="input zone-item__name" maxlength="30" aria-label="Nama zona">' +
      '<select class="input zone-item__dir" aria-label="Arah lalu lintas zona">' +
      '<option value="a">Arah A (searah panah)</option><option value="b">Arah B (berlawanan panah)</option>' +
      '<option value="both">Dua arah</option></select>' +
      '<button type="button" class="btn btn--ghost zone-item__del" aria-label="Hapus zona">Hapus</button>';
    const color = qs(".zone-item__color", li);
    const name = qs(".zone-item__name", li);
    color.value = zone.color;
    name.value = zone.name;
    const dir = qs(".zone-item__dir", li);
    dir.value = zone.direction;
    dir.addEventListener("change", () => {
      zone.direction = dir.value;
      setDirty();
    });
    color.addEventListener("input", () => {
      zone.color = color.value;
      setDirty();
      renderMain();
    });
    name.addEventListener("input", () => {
      zone.name = name.value;
      setDirty();
      renderMarkers();
    });
    name.addEventListener("focus", () => {
      if (s.active !== i) {
        s.active = i;
        qsa(".zone-item", list).forEach((el, k) => el.classList.toggle("is-active", k === i));
        renderZonesSvg();
      }
    });
    qs(".zone-item__del", li).addEventListener("click", () => {
      s.zones.splice(i, 1);
      if (s.drawing && s.active === i) s.drawing = false;
      s.active = s.zones.length ? Math.min(i, s.zones.length - 1) : null;
      setDirty();
      render();
    });
    li.addEventListener("click", (event) => {
      if (event.target === li) {
        s.active = i;
        renderZoneList();
        renderZonesSvg();
      }
    });
    list.append(li);
  });
  $('[data-action="finish-zone"]').hidden = !s.drawing;
  $('[data-action="add-zone"]').disabled = s.zones.length >= MAX_ZONES;
}

function render() {
  renderMain();
  renderZoneList();
}

// ---- interaksi ------------------------------------------------------------
function pointFromEvent(event) {
  const rect = stage().getBoundingClientRect();
  return [
    round4(Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))),
    round4(Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))),
  ];
}

function previewOn() {
  return $("[data-cal-preview]").checked;
}

function nextColor() {
  const used = new Set(s.zones.map((z) => z.color));
  return PALETTE.find((c) => !used.has(c)) || PALETTE[s.zones.length % PALETTE.length];
}

function nextName() {
  const names = new Set(s.zones.map((z) => z.name.toLowerCase()));
  for (let i = s.zones.length + 1; i < 100; i += 1) if (!names.has(`zona ${i}`)) return `Zona ${i}`;
  return "Zona";
}

function startZone() {
  if (s.zones.length >= MAX_ZONES) return status("error", `Maksimum ${MAX_ZONES} zona.`);
  if (s.drawing) finishZone();
  if (s.drawing) return;
  s.zones.push({ name: nextName(), color: nextColor(), direction: "a", points: [] });
  s.active = s.zones.length - 1;
  s.drawing = true;
  s.tool = "zone";
  status("", "");
  render();
}

function finishZone() {
  if (!s.drawing) return;
  const zone = s.zones[s.active];
  if (zone.points.length < 3) return status("error", "Zona butuh minimal 3 titik. Tambah titik atau tekan Esc untuk membatalkan.");
  s.drawing = false;
  setDirty();
  status("", "");
  render();
}

function cancelZone() {
  if (!s.drawing) return;
  s.zones.splice(s.active, 1);
  s.active = s.zones.length ? s.zones.length - 1 : null;
  s.drawing = false;
  status("", "");
  render();
}

function onStageClick(event) {
  if (suppressClick) {
    suppressClick = false;
    return;
  }
  if (previewOn()) return;
  const vertex = event.target.closest("[data-vertex]");
  if (vertex) {
    // Klik titik pertama zona yang sedang digambar = menutup poligon.
    const first = s.drawing && Number(vertex.dataset.zone) === s.active && Number(vertex.dataset.vertex) === 0;
    if (first && s.zones[s.active].points.length >= 3) finishZone();
    return;
  }
  const point = pointFromEvent(event);

  if (s.tool === "zone") {
    if (!s.drawing) startZone();
    const zone = s.zones[s.active];
    if (zone.points.length >= 3) {
      const rect = stage().getBoundingClientRect();
      const dx = (point[0] - zone.points[0][0]) * rect.width;
      const dy = (point[1] - zone.points[0][1]) * rect.height;
      if (Math.hypot(dx, dy) <= CLOSE_PX) return finishZone();
    }
    if (zone.points.length >= 24) return status("error", "Maksimum 24 titik per zona.");
    zone.points.push(point);
    setDirty();
    status("", "");
    return render();
  }

  if (s.tool === "median") {
    s.median = point;
  } else {
    if (s[s.tool].length >= 2) s[s.tool] = [];
    s[s.tool].push(point);
  }
  const done = s.tool === "median" ? Boolean(s.median) : s[s.tool].length === 2;
  if (done) s.tool = NEXT[s.tool];
  setDirty();
  status("", "");
  render();
}

function onPointerDown(event) {
  const marker = event.target.closest("[data-vertex]");
  if (!marker || previewOn()) return;
  event.preventDefault();
  drag = { zone: Number(marker.dataset.zone), vertex: Number(marker.dataset.vertex), moved: false };
  marker.setPointerCapture?.(event.pointerId);
}

function onPointerMove(event) {
  if (!drag) return;
  drag.moved = true;
  s.zones[drag.zone].points[drag.vertex] = pointFromEvent(event);
  setDirty();
  renderMain();
}

function onPointerUp() {
  if (!drag) return;
  const moved = drag.moved;
  drag = null;
  if (moved) {
    suppressClick = true;
    renderMarkers();
  }
}

function onDoubleClick(event) {
  const marker = event.target.closest("[data-vertex]");
  if (!marker || previewOn()) return;
  const zone = s.zones[Number(marker.dataset.zone)];
  const min = s.drawing && s.zones[s.active] === zone ? 1 : 3;
  if (zone.points.length <= min) return status("error", "Zona butuh minimal 3 titik; hapus zonanya bila tidak diperlukan.");
  zone.points.splice(Number(marker.dataset.vertex), 1);
  suppressClick = true;
  setDirty();
  render();
}

function onKey(event) {
  if (event.target.matches("input, textarea, select")) return;
  if (event.key === "Enter") finishZone();
  else if (event.key === "Escape") cancelZone();
  else if ((event.key === "Backspace" || event.key === "z") && s.drawing) {
    s.zones[s.active].points.pop();
    event.preventDefault();
    render();
  }
}

// ---- gambar kamera & pratinjau ---------------------------------------------
let stillUrl = null;
let stillDetail = "";

// Ambil gambar diam lewat fetch agar penyebab kegagalan (status HTTP, pesan server) bisa ditampilkan.
// Bila tetap gagal, pakai video langsung sebagai latar supaya penanda tetap bisa digambar.
async function loadStill(attempt = 0) {
  const img = $("[data-cal-img]");
  stillFailed = false;
  stillDetail = "";
  try {
    const res = await fetch(`${root.dataset.snapshotUrl}?clean=1&t=${Date.now()}`, { credentials: "same-origin", cache: "no-store" });
    const type = res.headers.get("content-type") || "";
    if (!res.ok || !type.startsWith("image/")) {
      const body = (await res.text()).replace(/<[^>]*>/g, " ").trim().slice(0, 120);
      throw new Error(`HTTP ${res.status}${body ? ` – ${body}` : ""}`);
    }
    const blob = await res.blob();
    if (!blob.size) throw new Error("gambar kosong");
    if (stillUrl) URL.revokeObjectURL(stillUrl);
    stillUrl = URL.createObjectURL(blob);
    img.onload = () => render();
    img.onerror = () => failStill(img, new Error("gambar tidak dapat didekode browser"));
    img.src = stillUrl;
  } catch (error) {
    if (attempt < 2) return setTimeout(() => loadStill(attempt + 1), 1000);
    failStill(img, error);
  }
}

function failStill(img, error) {
  stillFailed = true;
  stillDetail = error.message || String(error);
  img.onload = () => render();
  img.onerror = null;
  img.src = `${root.dataset.streamUrl}?t=${Date.now()}`; // latar cadangan: video langsung
  render();
}

function renderStats(data) {
  const body = $("[data-cal-stats-body]");
  const note = $("[data-cal-stats-note]");
  body.replaceChildren();
  const fmt = (v) => (v == null ? "–" : `${v.toFixed(1).replace(".", ",")} dtk`);
  (data.zones || []).forEach((z) => {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = z.name;
    name.style.borderLeft = `4px solid ${z.color}`;
    tr.append(name);
    const classes = Object.entries(z.by_cls || {}).filter(([, n]) => n > 0).map(([k, n]) => `${k} ${n}`).join(" · ");
    const speed = (v) => (v == null ? "–" : `${Math.round(v)} km/j`);
    const total = classes ? `${z.total} (${classes})` : String(z.total ?? 0);
    [z.now, total, speed(z.avg_speed), z.speeding ?? 0, z.wrong ?? 0, fmt(z.avg_dwell), fmt(z.max_dwell)].forEach((v) => {
      const td = document.createElement("td");
      td.textContent = v;
      tr.append(td);
    });
    body.append(tr);
  });
  note.textContent = !data.ok
    ? "Deteksi belum berjalan untuk kamera ini (model belum dipilih atau sedang dimuat)."
    : (data.zones || []).length
      ? "Statistik dihitung sejak zona terakhir disimpan atau server menyala. Kendaraan dihitung saat selesai melewati zona."
      : "Belum ada zona tersimpan. Gambar zona lalu simpan.";
}

async function pollStats() {
  try {
    const res = await fetch(root.dataset.statsUrl, { credentials: "same-origin" });
    if (res.ok) renderStats(await res.json());
  } catch { /* abaikan */ }
}

function setPreview(on) {
  const img = $("[data-cal-img]");
  stage().classList.toggle("is-preview", on);
  $("[data-cal-stats]").hidden = !on;
  clearInterval(statsTimer);
  if (on) {
    if (dirty) status("info", "Pratinjau memakai kalibrasi yang sudah disimpan; simpan dulu agar perubahan terlihat.");
    img.onload = null;
    img.src = `${root.dataset.streamUrl}?t=${Date.now()}`;
    pollStats();
    statsTimer = setInterval(() => !document.hidden && pollStats(), 1000);
  } else {
    status("", "");
    loadStill();
  }
  render();
}

// ---- simpan ------------------------------------------------------------------
async function save() {
  if (s.drawing) {
    finishZone();
    if (s.drawing) return;
  }
  const payload = { axis: s.axis, line_pos: s.line_pos, one_way: s.one_way };
  if (s.roi.length) payload.roi = s.roi;
  if (s.median) payload.median = s.median;
  if (s.ref.length || s.ref_m) {
    payload.ref = s.ref;
    payload.ref_m = s.ref_m;
  }
  payload.zones_only = s.zones_only;
  payload.zones = s.zones.map((z) => ({ name: z.name.trim(), color: z.color, direction: z.direction, points: z.points }));
  status("info", "Menyimpan…");
  const { ok, data } = await postForm(root.dataset.saveUrl, payload, { json: true });
  if (ok && data.ok) {
    setDirty(false);
    status("ok", "Kalibrasi tersimpan dan langsung dipakai.");
    return;
  }
  const first = data?.errors ? Object.values(data.errors)[0] : data?.message || "Gagal menyimpan kalibrasi.";
  status("error", first);
}

function reset() {
  if (!confirm("Hapus semua penanda dan zona di halaman ini? (Belum disimpan sampai Anda menekan Simpan.)")) return;
  s = { ...fromStored(null) };
  setDirty();
  status("", "");
  render();
}

export function initCalibrationPage() {
  root = qs("[data-cal-page]");
  if (!root) return;
  let stored = null;
  try {
    stored = JSON.parse(root.dataset.calibration || "null");
  } catch { /* abaikan */ }
  s = fromStored(stored);

  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    switch (button.dataset.action) {
      case "save-calibration": return save();
      case "reset-calibration": return reset();
      case "add-zone": return startZone();
      case "finish-zone": return finishZone();
      case "retry-still": return loadStill();
    }
  });

  const st = stage();
  st.addEventListener("click", onStageClick);
  st.addEventListener("pointerdown", onPointerDown);
  st.addEventListener("pointermove", onPointerMove);
  st.addEventListener("pointerup", onPointerUp);
  st.addEventListener("pointercancel", onPointerUp);
  st.addEventListener("dblclick", onDoubleClick);
  document.addEventListener("keydown", onKey);
  window.addEventListener("resize", render);
  window.addEventListener("beforeunload", (event) => {
    if (dirty) event.preventDefault();
  });

  qsa("[data-cal-tool]", root).forEach((button) =>
    button.addEventListener("click", () => {
      if (s.drawing) cancelZone();
      s.tool = button.dataset.calTool;
      render();
    }),
  );
  $('[data-cal-input="line_pos"]').addEventListener("input", (event) => {
    s.line_pos = Number(event.target.value) / 100;
    setDirty();
    renderMain();
  });
  $('[data-cal-input="ref_m"]').addEventListener("input", (event) => {
    s.ref_m = event.target.value.trim();
    setDirty();
  });
  $('[data-cal-input="zones_only"]').addEventListener("change", (event) => {
    s.zones_only = event.target.checked;
    setDirty();
  });
  $('[data-cal-input="one_way"]').addEventListener("change", (event) => {
    s.one_way = event.target.checked;
    setDirty();
  });
  $("[data-cal-preview]").addEventListener("change", (event) => setPreview(event.target.checked));

  // Alat "Zona" ada di sisi zona; tambahkan tombolnya ke daftar alat.
  const tools = $(".cal-steps");
  const zoneTool = document.createElement("button");
  zoneTool.type = "button";
  zoneTool.className = "cal-step";
  zoneTool.dataset.calTool = "zone";
  zoneTool.innerHTML = "<strong>Zona lajur</strong><span>Gambar poligon lajur; waktu tinggal tiap kendaraan dihitung</span>";
  zoneTool.addEventListener("click", () => {
    s.tool = "zone";
    render();
  });
  tools.append(zoneTool);

  loadStill();
  render();
}
