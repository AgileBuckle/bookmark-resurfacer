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

  var copyBtn = document.getElementById("copy-api-key");
  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var input = document.getElementById("api_key_display");
      if (!input) return;
      navigator.clipboard.writeText(input.value).then(function () {
        var original = copyBtn.textContent;
        copyBtn.textContent = "Copied!";
        setTimeout(function () {
          copyBtn.textContent = original;
        }, 2000);
      });
    });
  }

  var regenBtn = document.getElementById("regenerate-api-key");
  if (regenBtn) {
    var label = regenBtn.textContent.trim().toLowerCase().indexOf("regenerate") !== -1
      ? "Regenerate"
      : "Generate";
    regenBtn.addEventListener("click", async function () {
      if (label === "Regenerate" && !window.confirm("Regenerate the API key? The old key will stop working immediately.")) {
        return;
      }
      regenBtn.disabled = true;
      try {
        var res = await fetch("/api/regenerate-api-key", {
          method: "POST",
          headers: { "X-CSRF-Token": regenBtn.dataset.csrf || "" },
          credentials: "same-origin",
        });
        var data = await res.json().catch(function () {
          return {};
        });
        if (res.ok && data.api_key) {
          var input = document.getElementById("api_key_display");
          if (input) input.value = data.api_key;
          if (copyBtn) copyBtn.hidden = false;
          regenBtn.textContent = "Regenerate API Key";
          label = "Regenerate";
          window.alert("API key generated. Copy it now — it will not be shown again.");
        } else {
          window.alert(data.detail || "Failed to generate API key.");
        }
      } catch (e) {
        window.alert("Request failed.");
      } finally {
        regenBtn.disabled = false;
      }
    });
  }
});
