// Menu hamburger halaman pengaturan: satu panel tampil sekali, dipilih lewat laci menu atau #hash.
import { qs, qsa } from "../utils/dom.js";

export function initAdminMenu(root) {
  const panels = qsa("[data-panel]", root);
  const drawer = qs("[data-drawer]", root);
  const backdrop = qs("[data-menu-backdrop]", root);
  const toggle = qs("[data-menu-toggle]", root);
  const title = qs("[data-panel-title]", root);
  const saveBar = qs("[data-save-bar]", root);
  const links = qsa("[data-nav]", drawer);
  const ids = panels.map((p) => p.id);
  const fallback = ids[0];

  function setOpen(open) {
    drawer.hidden = backdrop.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (open) (qs('[aria-current="page"]', drawer) || links[0])?.focus();
    else if (document.activeElement && drawer.contains(document.activeElement)) toggle.focus();
  }

  function show(id, { updateHash = true } = {}) {
    const target = ids.includes(id) ? id : fallback;
    panels.forEach((p) => (p.hidden = p.id !== target));
    links.forEach((a) => {
      if (a.dataset.nav === target) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
    const panel = panels.find((p) => p.id === target);
    if (title) title.textContent = panel.dataset.title || "";
    // Tombol Simpan hanya relevan untuk panel parameter (bagian dari formulir).
    if (saveBar) saveBar.hidden = !panel.hasAttribute("data-settings-panel");
    if (updateHash && location.hash !== `#${target}`) history.replaceState(null, "", `#${target}`);
    setOpen(false);
    return target;
  }

  toggle.addEventListener("click", () => setOpen(drawer.hidden));
  backdrop.addEventListener("click", () => setOpen(false));
  qs("[data-menu-close]", drawer).addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !drawer.hidden) setOpen(false);
  });
  links.forEach((a) =>
    a.addEventListener("click", (event) => {
      event.preventDefault();
      show(a.dataset.nav);
      window.scrollTo({ top: 0 });
    }),
  );
  window.addEventListener("hashchange", () => show(location.hash.slice(1), { updateHash: false }));

  show(location.hash.slice(1), { updateHash: false });
  return { show };
}
