/**
 * Minimal WebMCP polyfill for our self-hosted demo pages.
 *
 * `document.modelContext.registerTool()` below matches the REAL spec
 * (webmachinelearning/webmcp) exactly -- same method name, same tool
 * shape { name, description, inputSchema, execute }, same AbortSignal
 * unregister pattern, same `toolchange` event.
 *
 * getTools() and callTool() are OUR addition, not the spec's. As of the
 * explainer we read (Aug 2026), the spec explicitly leaves external
 * discovery/invocation as TODO:
 *   "TODO: Spec and describe the modelContext.getTools() and
 *    modelContext.executeTool() APIs."
 * Real browsers don't implement WebMCP yet and there's no reference
 * polyfill in the spec repo (it's spec text only, no JS). Since we
 * control both sides of these demo pages, we filled that gap ourselves
 * with the smallest reasonable surface so an outside agent (our
 * capability-check script, injected via Playwright from Python) can
 * discover and call tools that were registered through the real,
 * documented API. This is a deliberate scope decision worth stating
 * plainly in the literature survey / research-gap section, not
 * something to gloss over.
 */
(function () {
  if (typeof window === "undefined") return;
  if (window.document.modelContext) return; // a native/real implementation already won -- don't shadow it

  const registry = new Map();

  class ModelContext extends EventTarget {
    registerTool(tool, options) {
      if (!tool || typeof tool.name !== "string" || !tool.name) {
        throw new TypeError('registerTool requires a tool object with a non-empty string "name"');
      }
      if (typeof tool.execute !== "function") {
        throw new TypeError(`Tool "${tool.name}" must have an "execute" function`);
      }
      if (registry.has(tool.name)) {
        throw new DOMException(`Tool "${tool.name}" is already registered`, "InvalidStateError");
      }

      registry.set(tool.name, tool);
      this.dispatchEvent(new CustomEvent("toolchange", { detail: { type: "register", name: tool.name } }));

      const signal = options && options.signal;
      if (signal) {
        const unregister = () => {
          if (registry.delete(tool.name)) {
            this.dispatchEvent(
              new CustomEvent("toolchange", { detail: { type: "unregister", name: tool.name } })
            );
          }
        };
        if (signal.aborted) {
          unregister();
        } else {
          signal.addEventListener("abort", unregister, { once: true });
        }
      }
    }

    // --- Not part of the official spec yet (see file header). ---
    getTools() {
      return Array.from(registry.values()).map(({ name, description, inputSchema }) => ({
        name,
        description: description || "",
        inputSchema: inputSchema || null,
      }));
    }

    async callTool(name, args) {
      const tool = registry.get(name);
      if (!tool) {
        throw new DOMException(`No tool registered with name "${name}"`, "NotFoundError");
      }
      return await tool.execute(args || {});
    }
  }

  window.document.modelContext = new ModelContext();
})();
