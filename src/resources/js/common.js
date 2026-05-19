// ── Theme + Schrift: sofort anwenden (render-blocking, vor Body-Render) ───────
// Dieses IIFE läuft bevor der Browser den Body rendert, da common.js in <head>
// ohne defer/async geladen wird. So wird Flash of Wrong Theme (FOWT) verhindert.
(function () {
  var stored = localStorage.getItem("rag-theme") || "auto";
  var effective =
    stored === "auto"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : stored;
  document.documentElement.setAttribute("data-bs-theme", effective);

  // rem-Basis ändern (nicht body-fontSize) — Bootstrap-Komponenten nutzen rem relativ zu :root
  var fontPx = { small: "14px", medium: "16px", large: "18px" };
  var sz = localStorage.getItem("rag-font-size") || "medium";
  document.documentElement.style.fontSize = fontPx[sz] || "16px";
})();

// ── Gemeinsame Hilfsfunktionen ────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

marked.use({ gfm: true, breaks: true });

function safeParse(markdown) {
  return DOMPurify.sanitize(marked.parse(markdown));
}

function toggleTheme() {
  var current = document.documentElement.getAttribute("data-bs-theme") || "light";
  var next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-bs-theme", next);
  localStorage.setItem("rag-theme", next);
  var btn = document.getElementById("theme-toggle");
  if (btn) btn.textContent = next === "dark" ? "☀" : "☾";
}

function setFontSize(size) {
  var fontPx = { small: "14px", medium: "16px", large: "18px" };
  localStorage.setItem("rag-font-size", size);
  document.documentElement.style.fontSize = fontPx[size] || "16px";
  _updateSettingsUI();
}

function _updateSettingsUI() {
  var theme = localStorage.getItem("rag-theme") || "auto";
  var size = localStorage.getItem("rag-font-size") || "medium";
  document.querySelectorAll("[data-theme-pref]").forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.themePref === theme);
  });
  document.querySelectorAll("[data-font-size]").forEach(function (btn) {
    btn.classList.toggle("active", btn.dataset.fontSize === size);
  });
}

// ── DOM-Event-Handler (alle in einem Listener) ────────────────────────────────

document.addEventListener("DOMContentLoaded", function () {
  // Bestehend: Confirm-Dialog-Delegation
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // Theme-Toggle-Button in der Navbar
  var themeBtn = document.getElementById("theme-toggle");
  if (themeBtn) {
    themeBtn.textContent =
      document.documentElement.getAttribute("data-bs-theme") === "dark" ? "☀" : "☾";
    themeBtn.addEventListener("click", toggleTheme);
  }

  // Login-Ladefeedback: Button deaktivieren während LDAP authentifiziert
  var loginForm = document.querySelector('form[action="/login"]');
  if (loginForm) {
    loginForm.addEventListener("submit", function () {
      var btn = loginForm.querySelector('button[type="submit"]');
      if (!btn) return;
      btn.disabled = true;
      btn.innerHTML =
        '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Anmelden…';
      // Sicherheitsnetz: Button nach 15s wieder freigeben falls keine Server-Antwort kommt
      setTimeout(function () {
        btn.disabled = false;
        btn.textContent = "Anmelden";
      }, 15000);
    });
  }

  // Settings-Modal: Theme-Präferenz-Buttons
  document.querySelectorAll("[data-theme-pref]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var pref = btn.dataset.themePref;
      localStorage.setItem("rag-theme", pref);
      var effective =
        pref === "auto"
          ? window.matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light"
          : pref;
      document.documentElement.setAttribute("data-bs-theme", effective);
      var toggle = document.getElementById("theme-toggle");
      if (toggle) toggle.textContent = effective === "dark" ? "☀" : "☾";
      _updateSettingsUI();
    });
  });

  // Settings-Modal: Schriftgröße-Buttons
  document.querySelectorAll("[data-font-size]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      setFontSize(btn.dataset.fontSize);
    });
  });

  // Settings-Modal: Aktive Einstellungen hervorheben beim Öffnen
  var settingsModal = document.getElementById("settingsModal");
  if (settingsModal) settingsModal.addEventListener("show.bs.modal", _updateSettingsUI);

  // UTC-Zeitstempel → Lokale Zeit konvertieren
  document.querySelectorAll(".local-time[data-utc]").forEach(function (el) {
    var utc = el.getAttribute("data-utc");
    if (!utc) return;
    try {
      // Python datetime.isoformat() auf naiven UTC-Datetimes gibt kein 'Z' zurück —
      // ohne Suffix interpretiert new Date() den String als Lokalzeit (falsch).
      if (!utc.endsWith("Z") && !utc.includes("+")) utc += "Z";
      var d = new Date(utc);
      el.textContent = d.toLocaleString("de-DE", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      // Fallback: Server-gerenderter Text bleibt unverändert
    }
  });
});
