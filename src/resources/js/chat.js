// Chat-Seite: Frage absenden, SSE-Antwort empfangen, Quellen rendern, Verlauf speichern.

(function () {
  const input = document.getElementById("question-input");
  if (input) {
    input.addEventListener("keydown", function (e) {
      if (e.ctrlKey && e.key === "Enter") {
        e.preventDefault();
        submitQuestion(e);
      }
    });
  }

  const instanceSelect = document.querySelector("form[method='get'] select[name='instance_id']");
  if (instanceSelect) {
    instanceSelect.addEventListener("change", function () {
      this.form.submit();
    });
  }

  const chatForm = document.getElementById("chat-form");
  if (chatForm) {
    chatForm.addEventListener("submit", submitQuestion);
  }

  const newChatBtn = document.getElementById("new-chat-btn");
  if (newChatBtn) newChatBtn.addEventListener("click", clearChat);
})();

// ── Zeitzähler ────────────────────────────────────────────────────────────────

let _elapsedTimer = null;
let _elapsedSeconds = 0;
let _currentAbortController = null;
let _streamTimeout = null;
// Modul-Variable für _startElapsedTimer — zeigt immer auf den aktiven Indikator-Span.
let _thinkingIndicatorEl = null;
const _STREAM_TIMEOUT_MS = window._LLM_STREAM_TIMEOUT_MS || 270000;

function _startElapsedTimer() {
  _elapsedSeconds = 0;
  _elapsedTimer = setInterval(function () {
    _elapsedSeconds++;
    if (_thinkingIndicatorEl) {
      _thinkingIndicatorEl.innerHTML =
        '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
        "Antwort wird generiert… " +
        '<span class="text-muted small">(' + _elapsedSeconds + "s)</span>";
    }
  }, 1000);
}

function _stopElapsedTimer() {
  if (_elapsedTimer) {
    clearInterval(_elapsedTimer);
    _elapsedTimer = null;
  }
}

// ── Chat leeren ───────────────────────────────────────────────────────────────

function clearChat() {
  if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
  if (_currentAbortController) {
    _currentAbortController.abort();
    _currentAbortController = null;
  }
  _stopElapsedTimer();
  _thinkingIndicatorEl = null;
  document.getElementById("chat-box").innerHTML = "";
  document.getElementById("sources-box").innerHTML =
    "<span class='text-muted'>Hier erscheinen die Quell-Abschnitte nach der Antwort.</span>";
  document.getElementById("question-input").value = "";
  const sendBtn = document.getElementById("send-btn");
  if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = "Senden"; }
  document.getElementById("question-input").focus();
}

// ── Hauptfunktion ─────────────────────────────────────────────────────────────

function submitQuestion(e) {
  e.preventDefault();

  // Laufenden Stream und Timeout abbrechen (z.B. neue Frage während alter noch streamt)
  if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
  if (_currentAbortController) {
    _currentAbortController.abort();
  }
  _stopElapsedTimer();
  _currentAbortController = new AbortController();

  // Sicherheitsnetz: Browser-seitiger Timeout falls der Server-Thread hängt und
  // kein event:error sendet. Wert > LLM_TIMEOUT_SECONDS (240s) + Übertragungspuffer.
  _streamTimeout = setTimeout(function () {
    _streamTimeout = null;
    if (_currentAbortController) {
      _currentAbortController.abort();
      _currentAbortController = null;
      showStreamError(new Error("Zeitüberschreitung — das Modell hat nicht rechtzeitig geantwortet."));
    }
  }, _STREAM_TIMEOUT_MS);

  const form = document.getElementById("chat-form");
  const question = document.getElementById("question-input").value.trim();
  if (!question) return;

  const instanceId = form.querySelector("[name=instance_id]").value;
  const chatBox = document.getElementById("chat-box");
  const sendBtn = document.getElementById("send-btn");

  // Benutzerfrage anzeigen — createElement statt innerHTML+= (kein Re-Parse des gesamten chatBox-Inhalts)
  const questionDiv = document.createElement("div");
  questionDiv.className = "mb-2";
  questionDiv.innerHTML = "<strong>Sie:</strong> " + escapeHtml(question);
  chatBox.appendChild(questionDiv);

  // Antwort-Platzhalter — keine IDs, direkte DOM-Referenzen als Closure-Variablen.
  // IDs würden bei mehreren Fragen zu Duplikaten führen; getElementById liefert dann
  // stets das erste Element und überschreibt frühere Antworten.
  const thinkingIndicator = document.createElement("span");
  thinkingIndicator.className = "text-muted ms-1";
  thinkingIndicator.innerHTML =
    '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
    "Denke nach…";

  const streamingAnswer = document.createElement("span");

  const answerDiv = document.createElement("div");
  answerDiv.className = "mb-2";
  const answerLabel = document.createElement("strong");
  answerLabel.textContent = "Assistent:";
  answerDiv.appendChild(answerLabel);
  answerDiv.appendChild(document.createTextNode(" "));
  answerDiv.appendChild(thinkingIndicator);
  answerDiv.appendChild(streamingAnswer);
  chatBox.appendChild(answerDiv);

  // Modul-Variable für _startElapsedTimer auf den neuen Indikator zeigen lassen
  _thinkingIndicatorEl = thinkingIndicator;

  // Zum Spinner scrollen — sowohl chatBox-intern als auch Seite
  chatBox.scrollTop = chatBox.scrollHeight;
  answerDiv.scrollIntoView({ behavior: "smooth", block: "nearest" });

  // Button-Zustand
  sendBtn.disabled = true;
  sendBtn.textContent = "Läuft…";
  document.getElementById("question-input").value = "";

  document.getElementById("sources-box").innerHTML =
    "<span class='text-muted'><span class='spinner-border spinner-border-sm me-1' role='status'></span>Quellen werden gesucht…</span>";

  const formData = new FormData();
  formData.append("question", question);
  formData.append("instance_id", instanceId);

  // SSE-Zustand
  let sseBuffer = "";
  let currentEventType = "message";
  let firstToken = true;
  let fullAnswer = "";
  let sourcesData = [];

  function _restoreButton() {
    sendBtn.disabled = false;
    sendBtn.textContent = "Senden";
  }

  function handleSseData(eventType, data) {
    if (eventType === "error") {
      const payload = JSON.parse(data);
      showStreamError(new Error(payload.message));
      return;
    }

    if (eventType === "sources") {
      sourcesData = JSON.parse(data);
      renderSources(sourcesData);

      // Phase 2: LLM generiert — Zeitzähler starten
      thinkingIndicator.innerHTML =
        '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>' +
        "Antwort wird generiert… " +
        '<span class="text-muted small">(0s)</span>';
      _startElapsedTimer();
      return;
    }

    if (eventType === "done") {
      if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
      _stopElapsedTimer();
      _currentAbortController = null;
      const payload = JSON.parse(data);
      fullAnswer = payload.answer;

      // Fallback: Falls Tokens gebuffert ankamen und streamingAnswer noch leer ist,
      // vollständige Antwort aus dem done-Payload rendern.
      thinkingIndicator.remove();
      if (!streamingAnswer.innerHTML.trim() && fullAnswer) {
        streamingAnswer.innerHTML = safeParse(fullAnswer);
        chatBox.scrollTop = chatBox.scrollHeight;
      }

      saveHistory(question, fullAnswer, instanceId, sourcesData);
      _restoreButton();
      return;
    }

    // Token — Indikator erst entfernen wenn sichtbarer Inhalt gerendert ist.
    // Ollama schickt am Anfang häufig leere Strings oder "\n" — diese würden sonst
    // den Indikator entfernen, obwohl noch kein Text sichtbar ist.
    const token = JSON.parse(data);
    fullAnswer += token;
    const rendered = safeParse(fullAnswer);
    if (firstToken && rendered.replace(/<[^>]*>/g, "").trim()) {
      _stopElapsedTimer();
      thinkingIndicator.remove();
      firstToken = false;
    }
    streamingAnswer.innerHTML = rendered;
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  function processSseChunk(rawText) {
    sseBuffer += rawText;
    const lines = sseBuffer.split("\n");
    sseBuffer = lines.pop();

    for (const line of lines) {
      if (line === "") {
        currentEventType = "message";
      } else if (line.startsWith("event: ")) {
        currentEventType = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        handleSseData(currentEventType, line.slice(6));
      }
    }
  }

  fetch("/chat/stream", {
    method: "POST",
    body: formData,
    signal: _currentAbortController.signal,
  })
    .then(function (response) {
      if (!response.ok) throw new Error("HTTP " + response.status);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      function read() {
        reader
          .read()
          .then(function ({ done, value }) {
            if (done) {
              if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
              _currentAbortController = null;
              _stopElapsedTimer();
              // Stream endete — Aufräumen falls done-Event ausblieb
              thinkingIndicator.remove();
              if (!streamingAnswer.innerHTML.trim()) {
                streamingAnswer.textContent = "[Keine Antwort erhalten.]";
              }
              _restoreButton();
              return;
            }
            processSseChunk(decoder.decode(value, { stream: true }));
            read();
          })
          .catch(function (err) {
            if (err.name === "AbortError") return;
            showStreamError(err);
          });
      }
      read();
    })
    .catch(function (err) {
      if (err.name === "AbortError") return;
      showStreamError(err);
    });

  function showStreamError(err) {
    if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
    _stopElapsedTimer();
    _restoreButton();
    thinkingIndicator.remove();
    streamingAnswer.textContent = "[Verbindungsfehler: " + err.message + "]";
    document.getElementById("sources-box").innerHTML =
      "<span class='text-muted'>Keine Quellen verfügbar.</span>";
  }
}

// ── Quellen rendern ───────────────────────────────────────────────────────────

function renderSources(sources) {
  const box = document.getElementById("sources-box");
  if (!sources.length) {
    box.innerHTML = "<span class='text-muted'>Keine Quellen gefunden.</span>";
    return;
  }
  box.innerHTML = sources
    .map(function (s) {
      const filename = s.filename || (s.source || "").split("/").pop() || "Unbekannt";
      const meta = [
        s.page !== undefined && s.page !== null ? "S. " + escapeHtml(String(s.page)) : null,
        s.score !== undefined && s.score !== null
          ? "Score: " + parseFloat(s.score).toFixed(3)
          : null,
      ]
        .filter(Boolean)
        .join(" · ");
      return (
        '<div class="border-bottom pb-1 mb-1">' +
        '<div class="fw-bold text-truncate" title="' + escapeHtml(s.source || "") + '">' +
        escapeHtml(filename) + "</div>" +
        (meta ? '<div class="text-muted" style="font-size:0.8em">' + meta + "</div>" : "") +
        '<div class="mt-1">' + escapeHtml(s.excerpt) + "…</div>" +
        "</div>"
      );
    })
    .join("");
}

// ── Verlauf speichern ─────────────────────────────────────────────────────────

function saveHistory(question, answer, instanceId, sources) {
  const fd = new FormData();
  fd.append("question", question);
  fd.append("answer", answer);
  fd.append("instance_id", instanceId);
  fd.append("context_docs", JSON.stringify(sources));
  fetch("/chat/save-history", { method: "POST", body: fd });
}
