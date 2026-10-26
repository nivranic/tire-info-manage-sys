/** Existing TypeScript compiler only; no child process or emitted source files. */
const ts = require("typescript");
module.exports = function paletteTypescriptLoader(source) {
  const result = ts.transpileModule(source, {
    fileName: this.resourcePath,
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX, isolatedModules: true },
    reportDiagnostics: true,
  });
  for (const diagnostic of result.diagnostics || []) {
    if (diagnostic.category === ts.DiagnosticCategory.Error) this.emitError(new Error(ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")));
  }
  return result.outputText;
};
