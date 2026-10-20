// Removes the characters a field does not accept while the user types or pastes.
// Fields opt in with data-input-filter (see core.forms.InputFilterModelForm);
// the server validates again on save.
(function () {
  const filters = {
    name: (value) => value.replace(/[^\p{L}\p{N} .'-]/gu, ""),
    "person-name": (value) => value.replace(/[^\p{L} .'-]/gu, ""),
    code: (value) => value.replace(/[^\p{L}\p{N}-]/gu, ""),
    digits: (value) => value.replace(/\D/g, ""),
    decimal: (value) => keepOneDot(value.replace(/[^\d.]/g, "")),
    "signed-decimal": (value) => {
      const sign = value.trimStart().startsWith("-") ? "-" : "";
      return sign + keepOneDot(value.replace(/[^\d.]/g, ""));
    },
  };

  function keepOneDot(value) {
    const dot = value.indexOf(".");
    return dot === -1 ? value : value.slice(0, dot + 1) + value.slice(dot + 1).replace(/\./g, "");
  }

  // Listening on the document also covers inline rows added with "Add another".
  document.addEventListener("input", (event) => {
    const field = event.target;
    const filter = field.dataset && filters[field.dataset.inputFilter];
    if (!filter) return;
    const filtered = filter(field.value);
    if (filtered !== field.value) {
      const cursor = Math.max(field.selectionStart - (field.value.length - filtered.length), 0);
      field.value = filtered;
      field.setSelectionRange(cursor, cursor);
    }
  });
})();
