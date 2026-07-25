"use strict";

// External file (no inline JS) so a strict `script-src 'self'` CSP applies.

document.addEventListener("DOMContentLoaded", function () {
  var btn = document.getElementById("send-test");
  if (!btn) return;

  btn.addEventListener("click", async function () {
    btn.disabled = true;
    var original = btn.textContent;
    btn.textContent = "Sending...";
    try {
      var res = await fetch("/api/send-test", {
        method: "POST",
        // State-changing requests must carry the CSRF token.
        headers: { "X-CSRF-Token": btn.dataset.csrf || "" },
        credentials: "same-origin",
      });
      var data = await res.json().catch(function () {
        return {};
      });
      if (res.ok && data.sent) {
        window.alert("Test email sent!");
      } else {
        window.alert(
          data.error || data.detail || "Failed to send. Check settings and server logs."
        );
      }
    } catch (e) {
      window.alert("Request failed. Check your connection and the server logs.");
    } finally {
      btn.disabled = false;
      btn.textContent = original;
    }
  });
});
