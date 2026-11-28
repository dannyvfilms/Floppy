// Copy controls: any element with data-copy-target="<selector of a readonly
// input>". One delegated document listener handles every control, so controls
// that arrive later still work without per-node wiring: boosted navigation
// swaps, and the server fallback a React island restores when it unmounts or
// fails to mount (those are clones, which carry no listeners).
(function () {
  if (window.floppyCopyItemsReady) {
    // The script re-runs on boosted navigation; the listener is already live.
    return;
  }
  window.floppyCopyItemsReady = true;

  function targetInput(copyButton) {
    return document.querySelector(copyButton.getAttribute("data-copy-target"));
  }

  function isCopyTarget(input) {
    return [...document.querySelectorAll("[data-copy-target]")].some(
      (copyButton) => targetInput(copyButton) === input
    );
  }

  function copyFrom(copyButton, input) {
    const text = input.value;

    input.select();
    input.setSelectionRange(0, 99999); // For mobile devices

    // Try clipboard API first
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard
        .writeText(text)
        .then(() => {
          showSuccess();
        })
        .catch(() => {
          console.error("Clipboard API failed");
          tryExecCommand();
        });
    } else {
      tryExecCommand();
    }

    function tryExecCommand() {
      try {
        if (document.execCommand("copy")) {
          showSuccess();
        } else {
          showError();
        }
      } catch (err) {
        console.error("execCommand failed");
        showError();
      }
    }

    function showSuccess() {
      // Replace the icon with a checkmark for 3 seconds, then restore
      const svg = copyButton.querySelector('svg');
      if (!svg) return;
      const originalSvg = svg.outerHTML;
      svg.outerHTML = `<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"20\" height=\"20\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\" class=\"w-5 h-5 text-emerald-400\"><polyline points=\"20 6 9 17 4 12\"></polyline></svg>`;
      setTimeout(() => {
        copyButton.querySelector('svg').outerHTML = originalSvg;
      }, 3000);
    }

    function showError() {
      alert(
        gettext("Could not copy to clipboard. Please select the text and press Ctrl+C/Cmd+C to copy.")
      );
    }
  }

  document.addEventListener("click", function (event) {
    const copyButton = event.target.closest?.("[data-copy-target]");
    if (copyButton) {
      const input = targetInput(copyButton);
      if (!input) {
        console.error(`Could not find input for selector: ${copyButton.getAttribute("data-copy-target")}`);
        return;
      }
      copyFrom(copyButton, input);
      return;
    }
    // Clicking a copy target input selects all of its text.
    const input = event.target.closest?.("input");
    if (input && isCopyTarget(input)) {
      input.select();
    }
  });
})();
