/** Respect each dialog's own cancel/busy policy before touching workbench state. */
export function consumeMobileBack(document: Document, workbenchBack?: () => boolean): boolean {
  const dialogs = Array.from(document.querySelectorAll<HTMLDialogElement>("dialog[open]"));
  const focused = document.activeElement?.closest<HTMLDialogElement>("dialog[open]");
  const dialog = focused || dialogs.at(-1);
  if (dialog) {
    dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
    return true;
  }
  return workbenchBack?.() || false;
}
