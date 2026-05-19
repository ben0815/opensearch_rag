// Chat-Verlauf: gespeicherte Antworten als Markdown rendern.
document.querySelectorAll(".md-answer").forEach(function (el) {
  el.innerHTML = safeParse(el.textContent);
});
