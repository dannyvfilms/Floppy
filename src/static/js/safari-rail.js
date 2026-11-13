// Safari on Duo paints beneath its side controls only if the document extends
// beyond the layout viewport. Keep that extra column decorative, outside the
// app shell, so cards and controls retain their existing width.
(function () {
  const root = document.documentElement;
  const standalone = window.matchMedia("(display-mode: standalone)");
  const safari = /iPhone/.test(navigator.userAgent) &&
    /Version\/.+Safari\//.test(navigator.userAgent) &&
    !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent) &&
    navigator.maxTouchPoints > 1;
  if (!safari) return;

  let frame;
  let shell;
  let header;
  const observer = new ResizeObserver(schedule);

  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(update);
  }

  function update() {
    const nextShell = document.querySelector(".app-shell");
    const nextHeader = document.querySelector(".app-topbar");
    if (shell !== nextShell || header !== nextHeader) {
      observer.disconnect();
      shell = nextShell;
      header = nextHeader;
      if (shell) observer.observe(shell);
      if (header) observer.observe(header);
    }

    let rail = document.getElementById("safari-rail");
    // Pinch zoom is not a rail: leave its geometry alone and allow panning.
    const zoomed = window.visualViewport && window.visualViewport.scale > 1.01;
    root.toggleAttribute("data-safari-rail-zoomed", !!zoomed);
    if (zoomed && rail && !standalone.matches && !navigator.standalone) return;

    // Decorative overflow can itself inflate innerWidth. clientWidth keeps
    // reporting the layout viewport and prevents the rail toggling itself off.
    const gap = Math.round(screen.width - root.clientWidth);
    const active = shell && header && !zoomed && !standalone.matches &&
      !navigator.standalone && gap >= 40 && gap <= 200;
    root.toggleAttribute("data-safari-rail", !!active);
    if (!active) {
      rail?.remove();
      return;
    }

    if (!rail) {
      rail = document.createElement("div");
      rail.id = "safari-rail";
      rail.setAttribute("aria-hidden", "true");
      const cap = document.createElement("div");
      cap.className = "safari-rail__header";
      rail.appendChild(cap);
      // Before the shell so original decorative art can paint over this base.
      document.body.prepend(rail);
    }
    const height = Math.ceil(shell.getBoundingClientRect().bottom + window.scrollY);
    shell.style.setProperty("--safari-rail-width", `${gap}px`);
    shell.style.setProperty("--safari-rail-height", `${height}px`);
    rail.style.width = `${gap}px`;
    rail.style.height = `${height}px`;
    rail.style.background = getComputedStyle(shell).background;
    const cap = rail.firstElementChild;
    const style = getComputedStyle(header);
    cap.style.height = `${header.getBoundingClientRect().height}px`;
    cap.style.background = style.background;
    cap.style.borderBottom = style.borderBottom;
    cap.style.boxShadow = style.boxShadow;
    // Safari keeps clientHeight at the expanded-toolbar height. Its root
    // scroll timeline instead uses innerHeight as the toolbar collapses.
    rail.style.setProperty("--rail-scroll", `${Math.max(0, height - window.innerHeight)}px`);
  }

  window.addEventListener("resize", schedule);
  window.addEventListener("orientationchange", schedule);
  window.visualViewport?.addEventListener("resize", schedule);
  standalone.addEventListener("change", schedule);
  document.addEventListener("htmx:afterSettle", schedule);
  new MutationObserver(schedule).observe(root, { attributes: true, attributeFilter: ["class", "style"] });
  schedule();
})();
