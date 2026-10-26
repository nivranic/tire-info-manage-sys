// Preserve real module URLs so the SDK's legal ESM cycles keep their native identity.
import "../../api-client/tests/device-ai/json-esm-hook.mjs";

export function loadTypeScript(relative, from) {
  return import(new URL(relative, from).href);
}
