// Minimal clipboard wiring for install-block copy buttons. No dependencies.
(function () {
  "use strict";

  function flash(btn, ok) {
    var label = btn.querySelector(".copy-label");
    if (!label) return;
    var original = label.dataset.original || label.textContent;
    label.dataset.original = original;
    label.textContent = ok ? "Copied" : "Error";
    btn.classList.toggle("is-copied", ok);
    btn.classList.toggle("is-failed", !ok);
    setTimeout(function () {
      label.textContent = original;
      btn.classList.remove("is-copied");
      btn.classList.remove("is-failed");
    }, 1600);
  }

  function writeFallback(text) {
    // Older browsers / non-HTTPS fallback.
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return ok;
    } catch (e) {
      return false;
    }
  }

  document.addEventListener("click", function (event) {
    var btn = event.target.closest(".copy-btn");
    if (!btn) return;
    var text = btn.getAttribute("data-copy") || "";
    if (!text) return;

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard
        .writeText(text)
        .then(function () { flash(btn, true); })
        .catch(function () { flash(btn, writeFallback(text)); });
    } else {
      flash(btn, writeFallback(text));
    }
  });
})();
