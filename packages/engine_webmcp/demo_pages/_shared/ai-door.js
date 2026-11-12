/**
 * Agent Street -- the "AI door" overlay.
 *
 * Makes the two engines visible to someone watching the screen:
 *   - green: the agent used the shop's AI door (a WebMCP tool -- Engine 1).
 *     Without this, Engine 1 is invisible: the page just changes, with no
 *     clicking at all.
 *   - blue ring: something clicked the page's front door (a person, or
 *     Engine 2 clicking like a person).
 *
 * Load it AFTER /webmcp-polyfill.js:
 *   <script src="/webmcp-polyfill.js"></script>
 *   <script src="/_shared/ai-door.js"></script>
 *
 * IT MUST NOT CHANGE WHAT THE ENGINES SEE.
 *   - It mounts outside <body> (as a child of <html>) inside a closed shadow
 *     root, so Engine 2's extract_text -- which reads body.innerText -- never
 *     includes the overlay's text. Verified in Chromium.
 *   - It wraps document.modelContext.callTool only to observe: arguments
 *     and return values pass through unchanged, and errors are re-thrown.
 *   - It does not touch getTools(), so the capability check is unaffected.
 */
(() => {
  const mc = document.modelContext;
  if (!mc || typeof mc.callTool !== "function" || mc.__aiDoorWrapped) return;

  // ---------- mount ----------
  const host = document.createElement("div");
  host.setAttribute("data-ai-door", "");
  document.documentElement.appendChild(host);   // outside <body>, on purpose
  const root = host.attachShadow({ mode: "closed" });

  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; }
      .wrap { font-family: "Atkinson Hyperlegible", system-ui, sans-serif; color: #16233A; }

      .chip {
        position: fixed; top: 14px; right: 14px; z-index: 2147483000;
        display: flex; align-items: center; gap: 0.55rem;
        font: 700 0.9375rem/1 "Atkinson Hyperlegible", system-ui, sans-serif;
        background: #fff; color: #15803D;
        border: 2px solid #15803D; border-radius: 999px;
        padding: 0.5rem 0.85rem 0.5rem 0.7rem; cursor: pointer;
        box-shadow: 0 2px 10px rgba(22, 35, 58, 0.18);
      }
      .chip:focus-visible { outline: 3px solid #1D4ED8; outline-offset: 2px; }
      .dot { width: 0.7rem; height: 0.7rem; border-radius: 50%; background: #15803D; }
      .chip.live .dot { animation: live 1.2s ease-out; }
      @keyframes live {
        0% { box-shadow: 0 0 0 0 rgba(21, 128, 61, 0.55); }
        100% { box-shadow: 0 0 0 14px rgba(21, 128, 61, 0); }
      }
      .count {
        background: #15803D; color: #fff; border-radius: 999px;
        min-width: 1.4rem; padding: 0.15rem 0.4rem; text-align: center; font-size: 0.8125rem;
      }

      .panel {
        position: fixed; top: 62px; right: 14px; z-index: 2147483000;
        width: min(24rem, calc(100vw - 28px));
        max-height: calc(100vh - 80px); overflow: auto;
        background: #fff; border: 1px solid #CBD4DA; border-radius: 12px;
        box-shadow: 0 10px 30px rgba(22, 35, 58, 0.22);
        padding: 1rem 1.1rem;
      }
      .panel[hidden] { display: none; }
      .panel h3 {
        margin: 0 0 0.35rem;
        font: 700 1.125rem/1.2 "Archivo", system-ui, sans-serif;
      }
      .panel p { margin: 0 0 0.85rem; color: #4B5A6E; font-size: 0.9375rem; line-height: 1.45; }
      .tools { list-style: none; margin: 0; padding: 0; }
      .tools li { padding: 0.6rem 0; border-top: 1px solid #E2E8EB; }
      .tools code {
        font: 700 0.9375rem/1.3 ui-monospace, "SF Mono", Menlo, Consolas, monospace;
        color: #15803D;
      }
      .tools span { display: block; font-size: 0.9375rem; line-height: 1.4; margin-top: 0.15rem; }
      .close {
        float: right; font: inherit; border: 0; background: none; cursor: pointer;
        font-size: 1.4rem; line-height: 1; color: #4B5A6E; padding: 0 0.2rem;
      }

      .toasts {
        position: fixed; right: 14px; bottom: 14px; z-index: 2147483000;
        display: flex; flex-direction: column; gap: 0.5rem; align-items: flex-end;
        width: min(23rem, calc(100vw - 28px));
      }
      .toast {
        width: 100%;
        background: #fff; border-radius: 10px; border-left: 6px solid #15803D;
        box-shadow: 0 6px 22px rgba(22, 35, 58, 0.2);
        padding: 0.7rem 0.9rem; font-size: 0.9375rem; line-height: 1.4;
        animation: rise 0.25s ease-out;
      }
      .toast.bad { border-left-color: #B42318; }
      .toast b { display: block; font-size: 1rem; }
      .toast .what { color: #15803D; font-weight: 700; }
      .toast .bad-what { color: #B42318; font-weight: 700; }
      .toast .args, .toast .res { color: #4B5A6E; overflow-wrap: anywhere; }
      @keyframes rise { from { transform: translateY(8px); opacity: 0; } to { transform: none; opacity: 1; } }

      .ring {
        position: fixed; z-index: 2147483001; pointer-events: none;
        width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
        border: 3px solid #1D4ED8; background: rgba(29, 78, 216, 0.12);
        animation: ring 0.7s ease-out forwards;
      }
      @keyframes ring { from { transform: scale(0.4); opacity: 1; } to { transform: scale(1.4); opacity: 0; } }

      @media (prefers-reduced-motion: reduce) {
        .chip.live .dot, .toast, .ring { animation: none; }
        .ring { opacity: 0.6; }
      }
    </style>
    <div class="wrap">
      <button class="chip" type="button" aria-expanded="false" aria-controls="door">
        <span class="dot" aria-hidden="true"></span>
        AI door open
        <span class="count">0</span>
      </button>
      <section class="panel" id="door" hidden aria-label="This shop's AI door">
        <button class="close" type="button" aria-label="Close">×</button>
        <h3>This shop's AI door</h3>
        <p>Actions this shop publishes for AI agents. An agent can call one directly,
           instead of finding and clicking the right buttons.</p>
        <ul class="tools"></ul>
        <p style="margin:0.85rem 0 0">Agents that don't use this door can still click and type,
           the way a person would. That is shown with a blue ring.</p>
      </section>
      <div class="toasts" role="status" aria-live="polite"></div>
    </div>`;

  const chip = root.querySelector(".chip");
  const panel = root.querySelector(".panel");
  const list = root.querySelector(".tools");
  const count = root.querySelector(".count");
  const toasts = root.querySelector(".toasts");

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function refreshTools() {
    let tools = [];
    try { tools = typeof mc.getTools === "function" ? mc.getTools() : []; } catch { tools = []; }
    count.textContent = String(tools.length);
    list.innerHTML = tools.map((t) =>
      `<li><code>${esc(t.name)}</code><span>${esc(t.description || "")}</span></li>`).join("");
  }

  function setOpen(open) {
    panel.hidden = !open;
    chip.setAttribute("aria-expanded", String(open));
    if (open) refreshTools();
  }
  chip.addEventListener("click", () => setOpen(panel.hidden));
  root.querySelector(".close").addEventListener("click", () => setOpen(false));

  // Tools register after this script runs in some pages; catch both cases.
  if (typeof mc.addEventListener === "function") mc.addEventListener("toolchange", refreshTools);
  document.addEventListener("DOMContentLoaded", refreshTools);
  setTimeout(refreshTools, 0);

  // ---------- describe a call in plain words ----------
  function argText(args) {
    const entries = Object.entries(args || {});
    if (!entries.length) return "no details needed";
    return entries.map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`).join(", ");
  }
  function resultText(res) {
    try {
      const t = res && res.content && res.content[0] && res.content[0].text;
      const s = t != null ? String(t) : JSON.stringify(res);
      return s.length > 110 ? s.slice(0, 107) + "..." : s;
    } catch { return ""; }
  }

  function toast(html, bad) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.innerHTML = html;
    toasts.appendChild(el);
    while (toasts.children.length > 3) toasts.firstElementChild.remove();
    setTimeout(() => el.remove(), 7000);
  }

  // ---------- observe AI-door calls (pass-through wrapper) ----------
  const original = mc.callTool.bind(mc);
  mc.callTool = async function (name, args) {
    const t0 = performance.now();
    try {
      const res = await original(name, args);
      const ms = Math.max(1, Math.round(performance.now() - t0));
      chip.classList.remove("live"); void chip.offsetWidth; chip.classList.add("live");
      toast(`<b>AI door: <span class="what">${esc(name)}</span></b>
             <div class="args">${esc(argText(args))}</div>
             <div class="res">Answered in ${ms} ms: ${esc(resultText(res))}</div>`);
      return res;
    } catch (err) {
      toast(`<b>AI door: <span class="bad-what">${esc(name)} failed</span></b>
             <div class="res">${esc(err && err.message ? err.message : err)}</div>`, true);
      throw err;
    }
  };
  mc.__aiDoorWrapped = true;

  // ---------- front-door clicks: a blue ring where the click landed ----------
  document.addEventListener("click", (e) => {
    if (e.composedPath && e.composedPath().includes(host)) return;   // ignore our own chip
    if (!e.clientX && !e.clientY) return;                            // keyboard "clicks"
    const r = document.createElement("div");
    r.className = "ring";
    r.style.left = e.clientX + "px";
    r.style.top = e.clientY + "px";
    root.appendChild(r);
    setTimeout(() => r.remove(), 800);
  }, true);
})();
