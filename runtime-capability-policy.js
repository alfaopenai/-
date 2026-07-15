(function exposeRuntimeCapabilityPolicy(root, factory) {
    const policy = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = policy;
    }
    if (root) {
        Object.defineProperty(root, "AlphaPokerRuntimeCapabilityPolicy", {
            configurable: false,
            enumerable: false,
            writable: false,
            value: policy
        });
    }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    function normalizeHostname(value) {
        const hostname = String(value || "").trim().toLowerCase();
        return hostname.startsWith("[") && hostname.endsWith("]")
            ? hostname.slice(1, -1)
            : hostname;
    }

    function isLoopbackHostname(value) {
        return ["127.0.0.1", "localhost", "::1"].includes(normalizeHostname(value));
    }

    function getRuntimeCapabilities(locationLike = {}) {
        const protocol = String(locationLike.protocol || "").trim().toLowerCase();
        const localReaderAvailable = ["http:", "https:"].includes(protocol)
            && isLoopbackHostname(locationLike.hostname);
        return Object.freeze({
            localReaderAvailable,
            hosted: !localReaderAvailable
        });
    }

    return Object.freeze({
        getRuntimeCapabilities,
        isLoopbackHostname,
        normalizeHostname
    });
}));
