(function () {
  document.addEventListener('click', function (event) {
    const target = event.target;
    if (!target || !target.closest) return;
    const option = target.closest('[data-parent-picker-option]');
    if (!option) return;
    event.preventDefault();
    const input = document.getElementById(option.dataset.parentPickerInput);
    const hidden = document.getElementById(option.dataset.parentPickerHidden);
    const results = document.getElementById(option.dataset.parentPickerResults);
    if (input) input.value = option.dataset.parentPickerLabel || option.textContent.trim();
    if (hidden) hidden.value = option.dataset.parentPickerValue || '';
    if (results) results.innerHTML = '';
  });
})();
