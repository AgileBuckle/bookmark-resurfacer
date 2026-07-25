"use strict";

// External file (no inline JS / no inline handlers) so a strict
// `script-src 'self'` CSP can be enforced.

function showEdit(id, editing) {
  var view = document.getElementById("view-" + id);
  var edit = document.getElementById("edit-" + id);
  if (!view || !edit) return;
  view.hidden = editing;
  edit.hidden = !editing;
}

function filterBookmarks() {
  var input = document.getElementById("search");
  var query = (input ? input.value : "").toLowerCase().trim();
  var items = document.querySelectorAll(".bookmark-item");
  var anyVisible = false;

  items.forEach(function (item) {
    var text = (item.getAttribute("data-search-text") || "").toLowerCase();
    var match = !query || text.indexOf(query) !== -1;
    item.hidden = !match;
    if (match) anyVisible = true;
  });

  var noResults = document.getElementById("no-results");
  if (noResults) noResults.hidden = anyVisible || !query;

  var noBookmarks = document.getElementById("no-bookmarks");
  if (noBookmarks) noBookmarks.hidden = true;
}

document.addEventListener("DOMContentLoaded", function () {
  var search = document.getElementById("search");
  if (search) search.addEventListener("input", filterBookmarks);

  document.addEventListener("click", function (event) {
    var editBtn = event.target.closest(".js-edit");
    if (editBtn) {
      showEdit(editBtn.dataset.id, true);
      return;
    }
    var cancelBtn = event.target.closest(".js-cancel-edit");
    if (cancelBtn) {
      showEdit(cancelBtn.dataset.id, false);
    }
  });

  document.querySelectorAll("form.js-confirm").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.dataset.confirm || "Are you sure?")) {
        event.preventDefault();
      }
    });
  });
});
