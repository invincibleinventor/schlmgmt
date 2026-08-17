(() => {
  const sidebar = document.querySelector(".sidebar");
  const toggle = document.querySelector(".nav-toggle");
  const scrim = document.querySelector(".nav-scrim");

  const setNavigation = (open, { restoreFocus = false } = {}) => {
    if (!sidebar || !toggle || !scrim) return;
    sidebar.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    scrim.hidden = !open;
    if (open) {
      // The sidebar is visibility:hidden until `.open` applies, and a hidden
      // element cannot take focus, so this waits for the style to land.
      requestAnimationFrame(() => sidebar.querySelector("nav a")?.focus());
    } else if (restoreFocus) {
      // Without this, closing with Escape or the scrim leaves focus on a
      // hidden element and keyboard users lose their place.
      toggle.focus();
    }
  };

  const closeNavigation = () => setNavigation(false, { restoreFocus: true });

  toggle?.addEventListener("click", () => {
    setNavigation(!sidebar?.classList.contains("open"));
  });
  scrim?.addEventListener("click", closeNavigation);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && sidebar?.classList.contains("open")) closeNavigation();
  });

  // The sidebar becomes permanently visible above 980px; leaving `.open` and
  // the scrim set on resize traps clicks behind an invisible overlay.
  const desktop = window.matchMedia("(min-width: 981px)");
  const syncToViewport = () => {
    if (desktop.matches && sidebar?.classList.contains("open")) setNavigation(false);
  };
  desktop.addEventListener("change", syncToViewport);
  syncToViewport();

  document.querySelectorAll("[data-confirm]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (!window.confirm(element.getAttribute("data-confirm") || "Continue?")) event.preventDefault();
    });
  });
})();
