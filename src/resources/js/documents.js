// Dokumente-Seite: Upload via SSE, Instanz-Wechsel.

(function () {
  const instanceSelect = document.querySelector("form[method='get'] select[name='instance_id']");
  if (instanceSelect) {
    instanceSelect.addEventListener("change", function () {
      this.form.submit();
    });
  }

  const uploadForm = document.getElementById("upload-form");
  if (uploadForm) {
    uploadForm.addEventListener("submit", uploadFiles);
  }
})();

function uploadFiles(e) {
  e.preventDefault();
  const form = document.getElementById("upload-form");
  const fd = new FormData(form);
  const btn = document.getElementById("upload-btn");
  const progress = document.getElementById("upload-progress");

  if (!document.getElementById("file-input").files.length) return;

  btn.disabled = true;
  progress.innerHTML = '<div class="text-muted">⏳ Wird vorbereitet…</div>';

  let sseBuffer = "";

  function processSseChunk(rawText) {
    sseBuffer += rawText;
    const lines = sseBuffer.split("\n");
    sseBuffer = lines.pop();
    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const d = JSON.parse(line.slice(6));
        if (d.done) {
          progress.innerHTML += `<div class="text-success fw-bold">✓ ${d.total} Datei(en) erfolgreich verarbeitet.</div>`;
          setTimeout(function () {
            location.reload();
          }, 1500);
        } else if (d.error) {
          progress.innerHTML += `<div class="text-danger">✗ ${escapeHtml(d.file)}: ${escapeHtml(d.error)}</div>`;
          btn.disabled = false;
        } else {
          progress.innerHTML = `<div>${escapeHtml(d.file)} (${d.index}/${d.total}): ${d.progress}%</div>`;
        }
      } catch (_) {
        /* Ungültiges SSE-Fragment — ignorieren */
      }
    }
  }

  function showUploadError(err) {
    btn.disabled = false;
    progress.innerHTML += `<div class="text-danger">Verbindungsfehler: ${err.message}</div>`;
  }

  fetch("/documents/upload", { method: "POST", body: fd })
    .then(function (response) {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      function read() {
        reader
          .read()
          .then(function ({ done, value }) {
            if (done) {
              btn.disabled = false;
              return;
            }
            processSseChunk(decoder.decode(value, { stream: true }));
            read();
          })
          .catch(function (err) {
            showUploadError(err);
          });
      }
      read();
    })
    .catch(function (err) {
      showUploadError(err);
    });
}
