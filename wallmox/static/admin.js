/* Wallmox admin panel helpers. */
(() => {
  // Scale the 1024x600 status page to fit the preview frame.
  const screen = document.getElementById("preview-screen");
  if (screen) {
    const frame = screen.querySelector("iframe");
    const fit = () => { frame.style.transform = `scale(${screen.clientWidth / 1024})`; };
    new ResizeObserver(fit).observe(screen);
    fit();
  }

  // Test the Proxmox connection with the values currently in the form.
  const testBtn = document.getElementById("test-btn");
  if (testBtn) {
    const form = document.getElementById("proxmox-form");
    const out = document.getElementById("test-result");
    const label = testBtn.textContent;
    testBtn.addEventListener("click", async () => {
      testBtn.disabled = true;
      testBtn.textContent = testBtn.dataset.busy;
      try {
        const body = new FormData(form);
        const resp = await fetch(testBtn.dataset.url, {
          method: "POST", body, headers: { "X-CSRF-Token": body.get("csrf") },
        });
        const data = await resp.json();
        out.textContent = data.message;
        out.className = "test-result " + (data.ok ? "is-ok" : "is-error");
      } catch (err) {
        out.textContent = String(err);
        out.className = "test-result is-error";
      } finally {
        out.hidden = false;
        testBtn.disabled = false;
        testBtn.textContent = label;
      }
    });
  }

  // Copy buttons.
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const input = document.getElementById(btn.dataset.copy);
      try { await navigator.clipboard.writeText(input.value); }
      catch { input.select(); document.execCommand("copy"); }
      const old = btn.textContent;
      btn.textContent = btn.dataset.done;
      setTimeout(() => { btn.textContent = old; }, 1200);
    });
  });
})();
