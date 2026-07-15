(function exposeReaderSessionPolicy(root, factory) {
    const policy = factory();
    if (typeof module === "object" && module.exports) {
        module.exports = policy;
    }
    if (root) {
        Object.defineProperty(root, "AlphaPokerReaderSessionPolicy", {
            configurable: false,
            enumerable: false,
            writable: false,
            value: policy
        });
    }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
    function isCurrentSession(sessionId, currentSessionId) {
        return Number(sessionId) === Number(currentSessionId);
    }

    function registerAbortController(collection, controller, sessionId, currentSessionId) {
        const entry = { controller, sessionId };
        collection.add(entry);
        if (!isCurrentSession(sessionId, currentSessionId)) {
            controller.abort();
        }
        return entry;
    }

    function releaseAbortController(collection, entry) {
        collection.delete(entry);
    }

    function abortControllerEntries(collection) {
        collection.forEach((entry) => entry.controller.abort());
        collection.clear();
    }

    function advanceSnapshotConfirmation(pending, signature, frameSeq) {
        const normalizedFrameSeq = Number(frameSeq);
        const hasFrameSeq = Number.isFinite(normalizedFrameSeq) && normalizedFrameSeq > 0;
        if (
            pending
            && pending.signature === signature
            && hasFrameSeq
            && Number.isFinite(pending.frameSeq)
            && normalizedFrameSeq > pending.frameSeq
        ) {
            return { confirmed: true, pending: null };
        }
        if (
            pending
            && pending.signature === signature
            && hasFrameSeq
            && Number.isFinite(pending.frameSeq)
            && normalizedFrameSeq <= pending.frameSeq
        ) {
            return { confirmed: false, pending };
        }
        return {
            confirmed: false,
            pending: {
                signature,
                frameSeq: hasFrameSeq ? normalizedFrameSeq : null
            }
        };
    }

    function decideSnapshotApplication(
        pending,
        signature,
        frameSeq,
        confidence,
        minimumConfidence = 0.75,
        directConfidence = 0.9
    ) {
        const normalizedConfidence = Number(confidence);
        if (!Number.isFinite(normalizedConfidence) || normalizedConfidence >= directConfidence) {
            return { apply: true, pending: null };
        }
        if (normalizedConfidence < minimumConfidence) {
            return { apply: false, pending: null };
        }
        const confirmation = advanceSnapshotConfirmation(pending, signature, frameSeq);
        return { apply: confirmation.confirmed, pending: confirmation.pending };
    }

    function classifyDroppedFrame(reason) {
        const normalizedReason = String(reason || "").trim().toLowerCase();
        if ([
            "reader-busy",
            "processing",
            "duplicate-seq",
            "out-of-order-seq"
        ].includes(normalizedReason)) {
            return "transient";
        }
        if ([
            "reader-not-running",
            "capture-mode-not-browser",
            "session-stale"
        ].includes(normalizedReason)) {
            return "terminal";
        }
        return "terminal";
    }

    function selectCaptureMode(useBrowserCapture) {
        return useBrowserCapture ? "browser" : "auto";
    }

    function shouldUseBrowserCapture(options = {}) {
        const browserOverride = String(options.browserOverride ?? "");
        const nativeOverride = String(options.nativeOverride ?? "");
        const displayMediaAvailable = Boolean(options.displayMediaAvailable);
        if (browserOverride === "1") {
            return displayMediaAvailable;
        }
        if (nativeOverride === "1" || browserOverride === "0") {
            return false;
        }
        const isElectron = /(?:^|\s)Electron\//i.test(String(options.userAgent || ""));
        return displayMediaAvailable && !isElectron;
    }

    return Object.freeze({
        abortControllerEntries,
        advanceSnapshotConfirmation,
        classifyDroppedFrame,
        decideSnapshotApplication,
        isCurrentSession,
        registerAbortController,
        releaseAbortController,
        selectCaptureMode,
        shouldUseBrowserCapture
    });
}));
