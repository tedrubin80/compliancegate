const demoScenarios = {
  watch: {
    title: "compliancegate / watch",
    speaker: "Watch",
    message: "Modified: src/payments/tokenizer.ts. Heuristic scan on added lines matched PCI pack pattern before you staged.",
    diff: `<span class="add">+ const pan = req.body.cardNumber</span>\n<span class="add">+ logger.info("processing", { pan })</span>`,
    concern: { level: "blocker", text: "CRITICAL: Possible PAN logged to stdout." },
    verdict: { state: "block", text: "ALERT — review before git add" },
    doc: "ok session c71712ce — finding queued"
  },
  commit: {
    title: "compliancegate / pre-commit",
    speaker: "Pre-commit",
    message: "Reviewing staged diff: 3 files, base + hipaa packs. LLM unavailable — heuristic-only pass with 1 critical finding.",
    diff: `<span class="add">+ OPENAI_API_KEY="sk-live-..."</span>\n<span class="del">- process.env.OPENAI_API_KEY</span>`,
    concern: { level: "blocker", text: "CRITICAL: Hardcoded secret in config/env.ts" },
    verdict: { state: "block", text: "COMMIT BLOCKED — threshold: critical" },
    doc: "ok decision logged — .compliancegate/reports/"
  },
  push: {
    title: "compliancegate / pre-push",
    speaker: "Loopback",
    message: "Session review: 6 reviews, 4 decisions, 2 unresolved high findings. Re-checking accumulated context before push to origin.",
    diff: `<span class="comment"># session summary</span>\nreviews: 6 · findings: 8 · packs: base, pci\nunresolved high: SSL verify=false, PII in error handler`,
    concern: { level: "concern", text: "HIGH: SSL verification disabled in http/client.ts" },
    verdict: { state: "block", text: "PUSH BLOCKED — threshold: high" },
    doc: "ok loopback complete — override: CG_SKIP=1 (logged)"
  }
};

const commands = {
  init: { title: "compliancegate init", desc: "Install hooks, create config.yaml, and scaffold storage for your mode." },
  watch: { title: "compliancegate watch", desc: "Live file watcher with debounced compliance alerts." },
  review: { title: "compliancegate review", desc: "On-demand review of current git diff." },
  rules: { title: "compliancegate rules show hipaa", desc: "Inspect rules and patterns for a pack before enabling." },
  status: { title: "compliancegate status", desc: "Storage mode, active session, unresolved findings." },
  sync: { title: "compliancegate sync-db", desc: "Push sanitized metadata to Postgres or MySQL." },
  end: { title: "compliancegate end-session", desc: "Close session and write final markdown reports." }
};

const levelTag = { watch: "MEDIUM", concern: "HIGH", blocker: "CRITICAL" };

function renderCommands() {
  const grid = document.getElementById("commandGrid");
  if (!grid) return;
  const entries = Object.entries(commands);
  grid.innerHTML = entries.map(([key, cmd], i) =>
    `<button class="command-chip${i === 0 ? " active" : ""}" type="button" data-command="${key}">${cmd.title.replace("compliancegate ", "")}</button>`
  ).join("");

  grid.querySelectorAll(".command-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      grid.querySelectorAll(".command-chip").forEach(c => c.classList.remove("active"));
      chip.classList.add("active");
      const cmd = commands[chip.dataset.command];
      const detail = document.getElementById("commandDetail");
      if (detail && cmd) detail.innerHTML = `<h4>${cmd.title}</h4><p>${cmd.desc}</p>`;
    });
  });
}

function renderDemo(key) {
  const s = demoScenarios[key];
  const content = document.getElementById("demoContent");
  const doc = document.getElementById("demoDoc");
  const title = document.getElementById("demoTitle");
  if (!s || !content) return;

  if (title) title.textContent = s.title;

  content.innerHTML = `
    <div class="demo-message">
      <div class="speaker">${s.speaker}</div>
      ${s.message}
    </div>
    <div class="diff-preview">${s.diff}</div>
    <div class="demo-concern ${s.concern.level}">
      <span class="severity-tag">${levelTag[s.concern.level]}</span> ${s.concern.text}
    </div>
    <div class="demo-verdict ${s.verdict.state}">${s.verdict.text}</div>
  `;
  if (doc) doc.textContent = s.doc;
}

function initDemo() {
  const tabs = document.querySelectorAll(".demo-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      renderDemo(tab.dataset.scenario);
    });
  });
  renderDemo("watch");

  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  let i = 0;
  const keys = ["watch", "commit", "push"];
  setInterval(() => {
    if (document.hidden) return;
    i = (i + 1) % keys.length;
    const key = keys[i];
    tabs.forEach(t => t.classList.toggle("active", t.dataset.scenario === key));
    renderDemo(key);
  }, 9000);
}

function initCopyButtons() {
  document.querySelectorAll(".copy-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const el = document.getElementById(btn.dataset.copy);
      if (!el) return;
      const text = el.textContent.replace(/&amp;/g, "&");
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "Copied";
        btn.classList.add("copied");
        setTimeout(() => { btn.textContent = "Copy"; btn.classList.remove("copied"); }, 2000);
      } catch {
        btn.textContent = "Failed";
        setTimeout(() => { btn.textContent = "Copy"; }, 2000);
      }
    });
  });
}

function initNav() {
  const toggle = document.getElementById("navToggle");
  const links = document.getElementById("navLinks");
  if (!toggle || !links) return;
  toggle.addEventListener("click", () => links.classList.toggle("open"));
  links.querySelectorAll("a").forEach(a => a.addEventListener("click", () => links.classList.remove("open")));
}

function initReveal() {
  const els = document.querySelectorAll(".reveal");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    els.forEach(el => el.classList.add("visible"));
    return;
  }
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add("visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1, rootMargin: "0px 0px -30px 0px" });
  els.forEach(el => observer.observe(el));
}

document.addEventListener("DOMContentLoaded", () => {
  renderCommands();
  initDemo();
  initCopyButtons();
  initNav();
  initReveal();
});
