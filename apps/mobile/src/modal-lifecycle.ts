export interface SuspendedWorkbenchDialogs {
  dialogs: HTMLDialogElement[];
  focus: HTMLElement | null;
}

/** Exit the browser's modal layer without cancelling or unmounting any business form. */
export function suspendWorkbenchDialogs(root: HTMLElement, previous: SuspendedWorkbenchDialogs | null = null): SuspendedWorkbenchDialogs | null {
  const opened = Array.from(root.querySelectorAll<HTMLDialogElement>("dialog:modal"));
  if (!opened.length) return previous;
  const active = root.ownerDocument.activeElement as HTMLElement | null;
  const focus = active && root.contains(active) ? active : previous?.focus || null;
  const focusedDialog = focus?.closest<HTMLDialogElement>("dialog:modal");
  const dialogs = [...new Set([...(previous?.dialogs || []), ...opened])];
  // Reopen the focused modal last when there are nested business dialogs.
  if (focusedDialog && dialogs.includes(focusedDialog)) dialogs.push(...dialogs.splice(dialogs.indexOf(focusedDialog), 1));
  for (const dialog of opened) dialog.close();
  return { dialogs, focus };
}

export function restoreWorkbenchDialogs(root: HTMLElement, suspended: SuspendedWorkbenchDialogs | null): void {
  if (!suspended) return;
  for (const dialog of suspended.dialogs) {
    if (!dialog.isConnected || !root.contains(dialog) || dialog.open) continue;
    // showModal normally focuses the first input. Keep the keyboard closed until a new tap.
    const autofocus = dialog.getAttribute("autofocus");
    dialog.setAttribute("autofocus", "");
    try { dialog.showModal(); }
    finally {
      if (autofocus === null) dialog.removeAttribute("autofocus");
      else dialog.setAttribute("autofocus", autofocus);
    }
  }
  const focus = suspended.focus;
  if (focus?.isConnected && root.contains(focus) && focus.closest<HTMLDialogElement>("dialog")?.open && !focus.matches("input, textarea, select") && !focus.isContentEditable) focus.focus({ preventScroll: true });
}
