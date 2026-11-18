// Language of the page. The fixed texts of index.html carry a key (data-t: the element's text, data-t-title,
// data-t-ph: placeholder, data-t-aria: aria-label); the server sends every text in the chosen language
// (/api/i18n, English where a translation is missing) and they are written in here, before the viewer's script runs.
// app.js waits for window.vfI18n and takes the texts its own code builds from the same table.
(() => {
  const ATTRS = { tTitle: "title", tPh: "placeholder", tAria: "aria-label" };
  function apply(strings, root = document) {
    root.querySelectorAll("[data-t]").forEach((el) => { if (strings[el.dataset.t]) el.textContent = strings[el.dataset.t]; });
    for (const [key, attr] of Object.entries(ATTRS)) {
      root.querySelectorAll(`[data-${key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase())}]`).forEach((el) => {
        if (strings[el.dataset[key]]) el.setAttribute(attr, strings[el.dataset[key]]);
      });
    }
  }
  const show = () => document.documentElement.classList.remove("i18n-wait");
  window.vfI18n = fetch("/api/i18n").then((r) => r.json()).then((data) => {
    document.documentElement.lang = data.lang;
    try { localStorage.setItem("vf.lang", data.lang); } catch { /* storage unavailable */ }
    apply(data.strings);
    return data;
  }).catch(() => ({ lang: "en", languages: [], strings: {} })).finally(show);
  setTimeout(show, 3000);          // whatever happens, the page is shown
})();
