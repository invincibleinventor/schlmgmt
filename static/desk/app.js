(() => {
  const sidebar = document.querySelector(".sidebar");
  const toggle = document.querySelector(".nav-toggle");
  const scrim = document.querySelector(".nav-scrim");

  const closeNavigation = () => {
    if (!sidebar || !toggle || !scrim) return;
    sidebar.classList.remove("open");
    toggle.setAttribute("aria-expanded", "false");
    scrim.hidden = true;
  };

  toggle?.addEventListener("click", () => {
    const open = !sidebar?.classList.contains("open");
    sidebar?.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    if (scrim) scrim.hidden = !open;
  });
  scrim?.addEventListener("click", closeNavigation);
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeNavigation();
  });

  document.querySelectorAll("[data-confirm]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (!window.confirm(element.getAttribute("data-confirm") || "Continue?")) event.preventDefault();
    });
  });
})();
