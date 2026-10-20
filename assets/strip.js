// Home, Run and Orchestrator pages: the sections under the first one sit side by side; scroll right, use the numbers, or ← →.
(() => {
  const strip = document.getElementById("strip"), nav = document.getElementById("strip-nav");
  const slides = [...strip.children], pills = [...nav.querySelectorAll("[data-go]")];
  let cur = 0;
  const header = document.querySelector(".site-header");
  const pin = () => { nav.style.top = header.offsetHeight + "px"; };
  // bring the strip's top to just under the header and the step bar
  const toTop = (smooth = true) => window.scrollTo({ top: strip.getBoundingClientRect().top + scrollY - header.offsetHeight - nav.offsetHeight,
    behavior: smooth ? "smooth" : "auto" });
  const fit = () => { strip.style.height = slides[cur].offsetHeight + "px"; };
  const mark = (i) => { cur = i; pills.forEach((p, k) => { p.classList.toggle("on", k === i); p.setAttribute("aria-selected", k === i); });
    pills[i].scrollIntoView({ block: "nearest", inline: "nearest" }); fit(); };
  const go = (i, top = true) => { i = Math.max(0, Math.min(slides.length - 1, i));
    strip.scrollTo({ left: slides[i].offsetLeft - strip.offsetLeft });
    mark(i); if (top) toTop(); };
  nav.addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return;
    go(b.dataset.go != null ? +b.dataset.go : cur + (b.dataset.step === "next" ? 1 : -1)); });
  let t; strip.addEventListener("scroll", () => { clearTimeout(t); t = setTimeout(() => {
    const i = Math.round(strip.scrollLeft / strip.clientWidth); if (i !== cur) mark(i); }, 80); });
  document.addEventListener("keydown", (e) => { if (e.target.closest(".CodeMirror, input, textarea") || !nav.matches(":hover, :focus-within") && !strip.matches(":hover")) return;
    if (e.key === "ArrowRight") go(cur + 1, false); if (e.key === "ArrowLeft") go(cur - 1, false); });
  // content renders late (charts, tables, the test report): keep the strip as tall as the current slide
  new ResizeObserver(fit).observe(strip); slides.forEach((s) => new ResizeObserver(() => s === slides[cur] && fit()).observe(s));
  // links to #tests (or any section id) open its slide
  const byHash = () => { const k = slides.findIndex((s) => "#" + s.id === location.hash); if (k >= 0) { go(k, false); toTop(false); } };
  window.addEventListener("hashchange", byHash);
  document.addEventListener("click", (e) => { const a = e.target.closest('a[href^="#"]'); if (!a) return;
    const k = slides.findIndex((s) => "#" + s.id === a.getAttribute("href")); if (k >= 0) { e.preventDefault(); go(k); } });
  pin(); new ResizeObserver(pin).observe(header);
  mark(0); byHash();
})();
