function copyText(text) {
  if (!text) {
    return Promise.reject(new Error("Nothing to copy"));
  }
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
  return Promise.resolve();
}

document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", async () => {
    const targetId = button.getAttribute("data-copy-target");
    const target = targetId ? document.getElementById(targetId) : null;
    const text = target ? target.textContent : "";
    try {
      await copyText(text);
      const original = button.textContent;
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = original;
      }, 1200);
    } catch (err) {
      button.textContent = "Copy failed";
    }
  });
});

function showLoadingBar() {
  if (document.querySelector(".loading-bar")) {
    return;
  }
  const bar = document.createElement("div");
  bar.className = "loading-bar";
  document.body.appendChild(bar);
  document.body.classList.add("is-loading");
}

document.querySelectorAll("form[data-loading]").forEach((form) => {
  form.addEventListener("submit", () => {
    const button = form.querySelector("button[type=\"submit\"]");
    if (!button) {
      return;
    }
    const loadingText = button.getAttribute("data-loading-text");
    if (loadingText) {
      button.textContent = loadingText;
    }
    button.classList.add("is-loading");
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    if (form.classList.contains("search-form")) {
      showLoadingBar();
    }
  });
});

const storyNavLinks = document.querySelectorAll(".story-nav-link");
if (storyNavLinks.length) {
  const prefersReducedMotion = window.matchMedia
    ? window.matchMedia("(prefers-reduced-motion: reduce)")
    : { matches: false };
  storyNavLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href");
      if (!href || !href.startsWith("#")) {
        return;
      }
      const target = document.querySelector(href);
      if (!target) {
        return;
      }
      event.preventDefault();
      const behavior = prefersReducedMotion.matches ? "auto" : "smooth";
      target.scrollIntoView({ behavior, block: "start" });
      history.replaceState(null, "", href);
    });
  });
}
