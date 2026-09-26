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

  // Update from the panel: start, then follow the log until Wallmox is back.
  const progress = document.getElementById("upd-progress");
  if (progress) {
    const msg = document.getElementById("upd-msg");
    const logEl = document.getElementById("upd-log");
    const startBtn = document.getElementById("upd-start");
    const oldVersion = progress.dataset.version;

    const follow = () => {
      progress.hidden = false;
      msg.textContent = progress.dataset.running;
      msg.className = "msg msg-warn";
      if (startBtn) startBtn.disabled = true;
      const tick = async () => {
        try {
          const resp = await fetch(progress.dataset.statusUrl, { cache: "no-store" });
          if (resp.redirected || !resp.ok) throw new Error("not ready");
          const st = await resp.json();
          logEl.textContent = st.log || "";
          logEl.scrollTop = logEl.scrollHeight;
          if (st.state === "done") {
            msg.textContent = progress.dataset.done;
            msg.className = "msg msg-ok";
            setTimeout(() => location.reload(), st.version !== oldVersion ? 1200 : 2500);
            return;
          }
          if (st.state === "failed") {
            msg.textContent = progress.dataset.failed;
            msg.className = "msg msg-error";
            if (startBtn) startBtn.disabled = false;
            return;
          }
        } catch (err) { /* Wallmox is restarting, keep waiting */ }
        setTimeout(tick, 2000);
      };
      tick();
    };

    if (progress.dataset.active) follow();
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        if (!confirm(startBtn.dataset.confirm)) return;
        const body = new FormData();
        body.append("csrf", startBtn.dataset.csrf);
        try {
          const resp = await fetch(startBtn.dataset.url, {
            method: "POST", body, headers: { "X-CSRF-Token": startBtn.dataset.csrf },
          });
          const data = await resp.json();
          if (data.ok) follow();
          else { msg.textContent = data.message || ""; msg.className = "msg"; progress.hidden = false; }
        } catch (err) { follow(); }
      });
    }
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
