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
const _chatConfig = document.getElementById("chat-config");
const _STREAM_TIMEOUT_MS = _chatConfig
  ? parseInt(_chatConfig.dataset.streamTimeout, 10) || 270000
  : 270000;
const _USER_ID = _chatConfig ? (_chatConfig.dataset.userId || "0") : "0";

// ── Zustandspersistenz (sessionStorage) ──────────────────────────────────────
let _currentInstanceId  = null;
let _currentQuestion    = null;
let _currentFullAnswer  = "";
let _currentSourcesData = [];
let _stateTurns         = [];
let _saveDebounceTimer  = null;

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

// ── sessionStorage ────────────────────────────────────────────────────────────

function _storageKey() {
  return "chat-state-" + _USER_ID + "-" + _currentInstanceId;
}

function _saveState(turns, partial) {
  if (!_currentInstanceId) return;
  try {
    sessionStorage.setItem(_storageKey(), JSON.stringify({ turns: turns, partial: partial }));
  } catch (_) {}
}

function _loadState() {
  if (!_currentInstanceId) return { turns: [], partial: null };
  try {
    return JSON.parse(sessionStorage.getItem(_storageKey())) || { turns: [], partial: null };
  } catch (_) {
    return { turns: [], partial: null };
  }
}

function _clearState() {
  if (!_currentInstanceId) return;
  try { sessionStorage.removeItem(_storageKey()); } catch (_) {}
}

function _debouncedSave(partial) {
  if (_saveDebounceTimer) clearTimeout(_saveDebounceTimer);
  _saveDebounceTimer = setTimeout(function () {
    _saveDebounceTimer = null;
    _saveState(_stateTurns, partial);
  }, 500);
}

// ── Gespeicherten Turn in #chat-box rendern (Wiederherstellung) ───────────────

function _renderTurn(chatBox, question, answer, interrupted) {
  const questionDiv = document.createElement("div");
  questionDiv.className = "mb-2";
  questionDiv.innerHTML = "<strong>Sie:</strong> " + escapeHtml(question);
  chatBox.appendChild(questionDiv);

  const answerSpan = document.createElement("span");
  const answerDiv  = document.createElement("div");
  answerDiv.className = "mb-2";
  const label = document.createElement("strong");
  label.textContent = "Assistent:";
  answerDiv.appendChild(label);
  answerDiv.appendChild(document.createTextNode(" "));

  if (interrupted) {
    const badge = document.createElement("span");
    badge.className = "badge bg-secondary ms-1 me-1";
    badge.textContent = "unterbrochen";
    answerDiv.appendChild(badge);
  }

  answerDiv.appendChild(answerSpan);
  chatBox.appendChild(answerDiv);

  if (answer) {
    answerSpan.innerHTML = safeParse(answer);
    if (!interrupted && navigator.clipboard) {
      const copyBtn = document.createElement("button");
      copyBtn.className = "btn btn-outline-secondary btn-sm mt-1";
      copyBtn.textContent = "Antwort kopieren";
      copyBtn.addEventListener("click", function () {
        navigator.clipboard.writeText(answer).then(function () {
          copyBtn.textContent = "Kopiert ✓";
          setTimeout(function () { copyBtn.textContent = "Antwort kopieren"; }, 2000);
        });
      });
      answerDiv.appendChild(copyBtn);
    }
  } else {
    answerSpan.textContent = "[Keine Antwort erhalten.]";
  }
}

// ── Chat leeren ───────────────────────────────────────────────────────────────

function clearChat() {
  if (_streamTimeout) { clearTimeout(_streamTimeout); _streamTimeout = null; }
  if (_saveDebounceTimer) { clearTimeout(_saveDebounceTimer); _saveDebounceTimer = null; }
  if (_currentAbortController) {
    _currentAbortController.abort();
    _currentAbortController = null;
  }
  _stopElapsedTimer();
  _thinkingIndicatorEl = null;
  _clearState();
  _stateTurns         = [];
  _currentQuestion    = null;
  _currentFullAnswer  = "";
  _currentSourcesData = [];
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

  if (_currentAbortController && _currentFullAnswer) {
    if (_saveDebounceTimer) { clearTimeout(_saveDebounceTimer); _saveDebounceTimer = null; }
    _stateTurns.push({
      question:    _currentQuestion,
      answer:      _currentFullAnswer,
      sources:     _currentSourcesData,
      interrupted: true,
    });
    _saveState(_stateTurns, null);
  }
  // Unconditionales Reset: verhindert doppelten Push bei Mehrfachabsendung mit leerer Frage
  _currentQuestion    = null;
  _currentFullAnswer  = "";
  _currentSourcesData = [];

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
  _currentQuestion = question;
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
      _currentSourcesData = sourcesData;
      _saveState(_stateTurns, { question: _currentQuestion, answer: "", sources: _currentSourcesData });
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
      _currentFullAnswer = fullAnswer;

      // Fallback: Falls Tokens gebuffert ankamen und streamingAnswer noch leer ist,
      // vollständige Antwort aus dem done-Payload rendern.
      thinkingIndicator.remove();
      if (!streamingAnswer.innerHTML.trim() && fullAnswer) {
        streamingAnswer.innerHTML = safeParse(fullAnswer);
        chatBox.scrollTop = chatBox.scrollHeight;
      }

      if (fullAnswer && navigator.clipboard) {
        var copyBtn = document.createElement("button");
        copyBtn.className = "btn btn-outline-secondary btn-sm mt-1";
        copyBtn.textContent = "Antwort kopieren";
        copyBtn.addEventListener("click", function () {
          navigator.clipboard.writeText(fullAnswer).then(function () {
            copyBtn.textContent = "Kopiert ✓";
            setTimeout(function () { copyBtn.textContent = "Antwort kopieren"; }, 2000);
          });
        });
        answerDiv.appendChild(copyBtn);
      }

      if (_saveDebounceTimer) { clearTimeout(_saveDebounceTimer); _saveDebounceTimer = null; }
      _stateTurns.push({ question: _currentQuestion, answer: fullAnswer, sources: sourcesData });
      _saveState(_stateTurns, null);

      saveHistory(question, fullAnswer, instanceId, sourcesData);
      _restoreButton();
      return;
    }

    // Token — Indikator erst entfernen wenn sichtbarer Inhalt gerendert ist.
    // Ollama schickt am Anfang häufig leere Strings oder "\n" — diese würden sonst
    // den Indikator entfernen, obwohl noch kein Text sichtbar ist.
    const token = JSON.parse(data);
    fullAnswer += token;
    _currentFullAnswer = fullAnswer;
    const rendered = safeParse(fullAnswer);
    if (firstToken && rendered.replace(/<[^>]*>/g, "").trim()) {
      _stopElapsedTimer();
      thinkingIndicator.remove();
      firstToken = false;
    }
    streamingAnswer.innerHTML = rendered;
    chatBox.scrollTop = chatBox.scrollHeight;
    _debouncedSave({ question: _currentQuestion, answer: _currentFullAnswer, sources: _currentSourcesData });
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
    headers: { "X-CSRF-Token": getCsrfToken() },
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
              if (_currentFullAnswer) {
                if (_saveDebounceTimer) { clearTimeout(_saveDebounceTimer); _saveDebounceTimer = null; }
                _stateTurns.push({
                  question:    _currentQuestion,
                  answer:      _currentFullAnswer,
                  sources:     _currentSourcesData,
                  interrupted: true,
                });
                _saveState(_stateTurns, null);
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
  fetch("/chat/save-history", {
    method: "POST",
    body: fd,
    headers: { "X-CSRF-Token": getCsrfToken() },
  }).catch(function (err) {
    console.warn("Verlauf konnte nicht gespeichert werden:", err.message);
  });
}

// ── Initialisierung: State aus sessionStorage wiederherstellen ────────────────
// Eigene IIFE am Dateiende — let-Variablen sind hier bereits deklariert.
(function () {
  const instanceInput = document.querySelector('#chat-form input[name="instance_id"]');
  if (!instanceInput) return;
  _currentInstanceId = instanceInput.value;
  const state = _loadState();
  _stateTurns = state.turns || [];
  const chatBox = document.getElementById("chat-box");
  if (!chatBox || (!_stateTurns.length && !state.partial)) return;
  _stateTurns.forEach(function (turn) {
    _renderTurn(chatBox, turn.question, turn.answer, turn.interrupted || false);
  });
  if (state.partial) {
    _renderTurn(chatBox, state.partial.question, state.partial.answer, true);
    renderSources(state.partial.sources || []);
  } else {
    renderSources(_stateTurns[_stateTurns.length - 1].sources || []);
  }
  chatBox.scrollTop = chatBox.scrollHeight;
})();

// ── beforeunload: Partial-Antwort in History retten (Option B) ────────────────
window.addEventListener("beforeunload", function () {
  if (!_currentAbortController) return;
  if (!_currentFullAnswer || _currentFullAnswer.length < 20) return;
  if (_saveDebounceTimer) { clearTimeout(_saveDebounceTimer); _saveDebounceTimer = null; }
  const params = new URLSearchParams();
  params.append("question",     _currentQuestion);
  params.append("answer",       _currentFullAnswer + " [unterbrochen]");
  params.append("instance_id",  _currentInstanceId);
  params.append("context_docs", JSON.stringify(_currentSourcesData));
  params.append("csrf_token",   getCsrfToken());
  navigator.sendBeacon("/chat/save-history", params);
});
