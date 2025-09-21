(function (globalScope) {
    const root = typeof globalScope !== "undefined" && globalScope ? globalScope : globalThis;
    let namespace = root.AlphaPoker;
    if (!namespace || typeof namespace !== "object") {
        namespace = Object.create(null);
        Object.defineProperty(root, "AlphaPoker", {
            value: namespace,
            writable: false,
            configurable: false,
            enumerable: false
        });
    }

    if (!namespace.Solvers) {
        const registry = Object.create(null);
        const order = [];

        function normalizeConfig(config) {
            if (!config || typeof config !== "object") {
                throw new TypeError("Solver registration requires a config object.");
            }
            const { id, solve } = config;
            if (!id || typeof id !== "string") {
                throw new TypeError("Solver registration requires a string id.");
            }
            if (typeof solve !== "function") {
                throw new TypeError(`Solver "${id}" must provide a solve(context) function.`);
            }
            return {
                id,
                label: typeof config.label === "string" && config.label.trim() ? config.label.trim() : id,
                description: typeof config.description === "string" ? config.description : "",
                priority: Number.isFinite(config.priority) ? config.priority : 0,
                version: typeof config.version === "string" ? config.version : "0.0.0",
                origin: typeof config.origin === "string" ? config.origin : "",
                tags: Array.isArray(config.tags) ? config.tags.slice() : [],
                solve,
                exports: config.exports || null
            };
        }

        function register(config) {
            const normalized = normalizeConfig(config);
            const existingIndex = order.indexOf(normalized.id);
            if (existingIndex !== -1) {
                order.splice(existingIndex, 1);
            }
            order.push(normalized.id);
            registry[normalized.id] = normalized;
            return Object.assign({}, normalized);
        }

        function has(id) {
            return Boolean(registry[id]);
        }

        function get(id) {
            return registry[id] || null;
        }

        function list() {
            return order.map((id) => registry[id]).filter(Boolean);
        }

        function solveAll(context, options = Object.create(null)) {
            const results = [];
            let primary = null;
            const entries = list();
            for (let i = 0; i < entries.length; i += 1) {
                const entry = entries[i];
                const outcome = {
                    id: entry.id,
                    label: entry.label,
                    priority: entry.priority,
                    version: entry.version,
                    origin: entry.origin,
                    tags: entry.tags.slice(),
                    ok: false,
                    summary: null,
                    detail: null,
                    diagnostics: null,
                    error: null
                };
                try {
                    const produced = entry.solve(context, options) || Object.create(null);
                    outcome.ok = produced.ok !== false;
                    if (produced.summary !== undefined) {
                        outcome.summary = produced.summary;
                    }
                    if (produced.detail !== undefined) {
                        outcome.detail = produced.detail;
                    }
                    if (produced.diagnostics !== undefined) {
                        outcome.diagnostics = produced.diagnostics;
                    }
                    outcome.raw = produced;
                    if (outcome.ok && outcome.summary) {
                        if (!primary || entry.priority > primary.priority) {
                            primary = outcome;
                        }
                    }
                } catch (error) {
                    outcome.ok = false;
                    outcome.error = error;
                }
                results.push(outcome);
            }

            if (!primary) {
                const viable = results
                    .filter((item) => item && item.ok && item.summary)
                    .sort((a, b) => b.priority - a.priority);
                if (viable.length) {
                    primary = viable[0];
                }
            }

            return {
                primary,
                results
            };
        }

        namespace.Solvers = Object.freeze({
            register,
            has,
            get,
            list,
            solveAll
        });
    }
})(typeof window !== "undefined" ? window : globalThis);

