// Helper DOM kecil.
export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

// Ganti elemen panel dengan HTML baru. Fokus keyboard dipulihkan lewat data-focus-id.
export function replacePanel(element, html) {
  const template = document.createElement("template");
  template.innerHTML = html.trim();
  const next = template.content.firstElementChild;
  if (!next) return null;

  const active = document.activeElement;
  const focusId = element.contains(active) ? active.dataset.focusId : null;

  element.replaceWith(next);

  if (focusId) {
    const target = next.querySelector(`[data-focus-id="${CSS.escape(focusId)}"]`);
    if (target) target.focus({ preventScroll: true });
  }
  return next;
}

// Pembaruan otomatis ditunda selagi pengguna menunjuk atau memfokuskan panel,
// supaya klik tidak hilang karena elemen diganti di tengah interaksi.
export function isInteracting(element) {
  return element.matches(":hover") || element.contains(document.activeElement);
}
