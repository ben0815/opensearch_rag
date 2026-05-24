// Client-side table sorting. Add data-sort="text|number|date" to <th> elements.
(function () {
  function getCellValue(row, colIndex, sortType) {
    var cell = row.querySelectorAll("td")[colIndex];
    if (!cell) return sortType === "number" ? 0 : "";
    if (sortType === "date") return cell.dataset.utc || cell.textContent.trim();
    if (sortType === "number") return parseFloat(cell.textContent.trim()) || 0;
    return cell.textContent.trim().toLowerCase();
  }

  function cmp(a, b, sortType) {
    if (sortType === "number") return a - b;
    if (sortType === "date") return new Date(a) - new Date(b);
    return a < b ? -1 : a > b ? 1 : 0;
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.style.cursor = "pointer";
      th.setAttribute("aria-sort", "none");
      th.dataset.label = th.textContent.replace(/\s*[↕↑↓]\s*$/, "").trim();
    });

    document.querySelectorAll("th[data-sort]").forEach(function (th) {
      th.addEventListener("click", function () {
        var tbody = th.closest("table").querySelector("tbody");
        var allThs = Array.from(th.closest("tr").querySelectorAll("th"));
        var colIndex = allThs.indexOf(th);
        var sortType = th.dataset.sort;
        var asc = th.getAttribute("aria-sort") !== "ascending";

        allThs.forEach(function (h) {
          if (h.dataset.sort) {
            h.setAttribute("aria-sort", "none");
            h.textContent = h.dataset.label + " ↕";
          }
        });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        th.textContent = th.dataset.label + " " + (asc ? "↑" : "↓");

        Array.from(tbody.querySelectorAll("tr")).sort(function (a, b) {
          return (asc ? 1 : -1) * cmp(
            getCellValue(a, colIndex, sortType),
            getCellValue(b, colIndex, sortType),
            sortType
          );
        }).forEach(function (row) { tbody.appendChild(row); });
      });
    });
  });
})();
