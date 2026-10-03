import assert from "node:assert/strict";
import test from "node:test";
import { loadTypeScript } from "../../../packages/native-client/tests/load-typescript.mjs";

const { suspendWorkbenchDialogs, restoreWorkbenchDialogs } = await loadTypeScript("../src/modal-lifecycle.ts", import.meta.url);
const { consumeMobileBack } = await loadTypeScript("../src/back-navigation.ts", import.meta.url);

function workspace() {
  const dialogs = [];
  const stack = [];
  const document = { activeElement: null, querySelectorAll: () => dialogs.filter(dialog => dialog.open) };
  const root = {
    ownerDocument: document,
    contains: element => element?.root === root,
    querySelectorAll: () => dialogs.filter(dialog => dialog.modal),
  };
  function dialog() {
    const node = new EventTarget();
    const attributes = new Map();
    Object.assign(node, {
      root,
      isConnected: true,
      open: true,
      modal: true,
      closeCount: 0,
      restoreCount: 0,
      autofocusOnRestore: [],
      getAttribute: name => attributes.get(name) ?? null,
      setAttribute: (name, value) => { attributes.set(name, value); },
      removeAttribute: name => { attributes.delete(name); },
      matches: () => node.modal,
      closest: () => node.modal ? node : null,
      close() {
        node.closeCount += 1; node.open = false; node.modal = false;
        stack.splice(stack.indexOf(node), 1);
        document.activeElement = null;
        node.dispatchEvent(new Event("close"));
      },
      showModal() {
        node.restoreCount += 1; node.open = true; node.modal = true;
        node.autofocusOnRestore.push(attributes.has("autofocus"));
        stack.push(node); document.activeElement = node;
      },
    });
    dialogs.push(node); stack.push(node);
    return node;
  }
  function control(owner, editable = false) {
    return {
      root,
      isConnected: true,
      isContentEditable: false,
      focusCount: 0,
      value: "未保存的轮胎研究草稿",
      selectionStart: 2,
      selectionEnd: 5,
      closest: selector => selector === "dialog:modal" && !owner.modal ? null : owner,
      matches: () => editable,
      focus() { this.focusCount += 1; document.activeElement = this; },
    };
  }
  return { root, document, stack, dialog, control };
}

test("connection loss exits the modal layer without cancelling or discarding a busy draft", () => {
  const app = workspace();
  const modal = app.dialog();
  const input = app.control(modal, true);
  app.document.activeElement = input;
  let cancels = 0;
  modal.addEventListener("cancel", event => { cancels += 1; event.preventDefault(); });
  const suspended = suspendWorkbenchDialogs(app.root);
  assert.equal(modal.open, false);
  assert.equal(app.stack.length, 0, "the retry screen must have no blocking business modal");
  assert.equal(cancels, 0, "suspending must preserve the form's business state and busy policy");
  assert.equal(suspendWorkbenchDialogs(app.root, suspended), suspended);
  restoreWorkbenchDialogs(app.root, suspended);
  assert.equal(modal.open, true);
  assert.equal(modal.modal, true);
  assert.equal(input.value, "未保存的轮胎研究草稿");
  assert.deepEqual([input.selectionStart, input.selectionEnd], [2, 5]);
  assert.equal(input.focusCount, 0, "restoring a draft must not summon the soft keyboard");
  assert.deepEqual(modal.autofocusOnRestore, [true]);
  assert.equal(modal.getAttribute("autofocus"), null);
  assert.equal(consumeMobileBack(app.document, () => false), true);
  assert.equal(cancels, 1, "Back must still delegate to the original dialog cancel policy");
  assert.equal(modal.open, true, "a busy dialog's prevented cancel must still keep it open");
});

test("recovery reopens the previously focused modal last and restores safe control focus", () => {
  const app = workspace();
  const focusedModal = app.dialog();
  const otherModal = app.dialog();
  const button = app.control(focusedModal);
  app.document.activeElement = button;
  focusedModal.setAttribute("autofocus", "original");
  const suspended = suspendWorkbenchDialogs(app.root);
  restoreWorkbenchDialogs(app.root, suspended);
  assert.deepEqual(app.stack, [otherModal, focusedModal]);
  assert.equal(app.document.activeElement, button);
  assert.equal(button.focusCount, 1);
  assert.equal(focusedModal.getAttribute("autofocus"), "original");
});

test("recovery cannot reopen nodes discarded by a session reset", () => {
  const app = workspace();
  const modal = app.dialog();
  const button = app.control(modal);
  app.document.activeElement = button;
  const suspended = suspendWorkbenchDialogs(app.root);
  modal.isConnected = false; button.isConnected = false;
  restoreWorkbenchDialogs(app.root, suspended);
  assert.equal(modal.restoreCount, 0);
  assert.equal(button.focusCount, 0);
  assert.equal(app.stack.length, 0);
});

test("a component reopening its existing modal while disconnected is suspended again once", () => {
  const app = workspace();
  const modal = app.dialog();
  const suspended = suspendWorkbenchDialogs(app.root);
  modal.showModal();
  const repeated = suspendWorkbenchDialogs(app.root, suspended);
  assert.equal(repeated.dialogs.length, 1);
  assert.equal(app.stack.length, 0);
  restoreWorkbenchDialogs(app.root, repeated);
  assert.deepEqual(app.stack, [modal]);
  assert.equal(modal.closeCount, 2);
});
