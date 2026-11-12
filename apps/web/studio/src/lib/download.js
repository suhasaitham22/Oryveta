/* Saves bytes the browser already holds. No network request, no retained URL. */
export function downloadBlob(name, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function downloadJson(name, data) {
  downloadBlob(name, new Blob([JSON.stringify(data, null, 2)], {type: "application/json"}));
}
