const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
    abortControllerEntries,
    advanceSnapshotConfirmation,
    classifyDroppedFrame,
    decideSnapshotApplication,
    isCurrentSession,
    registerAbortController,
    releaseAbortController,
    selectCaptureMode,
    shouldUseBrowserCapture
} = require("../reader-session-policy");

function runReaderSessionSmoke() {
    assert.equal(isCurrentSession(7, 7), true);
    assert.equal(isCurrentSession("7", 7), true);
    assert.equal(isCurrentSession(6, 7), false);
    assert.equal(selectCaptureMode(true), "browser");
    assert.equal(selectCaptureMode(false), "auto");
    const chromeUserAgent = "Mozilla/5.0 Chrome/126.0.0.0 Safari/537.36";
    const electronUserAgent = `${chromeUserAgent} Electron/30.0.6`;
    assert.equal(shouldUseBrowserCapture({
        displayMediaAvailable: true,
        userAgent: chromeUserAgent
    }), true, "Chrome defaults to browser capture");
    assert.equal(shouldUseBrowserCapture({
        displayMediaAvailable: true,
        userAgent: electronUserAgent
    }), false, "Electron defaults to native auto capture");
    assert.equal(shouldUseBrowserCapture({
        browserOverride: "1",
        displayMediaAvailable: true,
        userAgent: electronUserAgent
    }), true, "?ggBrowser=1 overrides Electron default");
    assert.equal(shouldUseBrowserCapture({
        nativeOverride: "1",
        displayMediaAvailable: true,
        userAgent: chromeUserAgent
    }), false, "?ggNative=1 overrides Chrome default");
    assert.equal(shouldUseBrowserCapture({
        browserOverride: "0",
        displayMediaAvailable: true,
        userAgent: chromeUserAgent
    }), false, "?ggBrowser=0 disables browser capture");
    assert.equal(shouldUseBrowserCapture({
        displayMediaAvailable: false,
        userAgent: chromeUserAgent
    }), false);

    const collection = new Set();
    const currentController = new AbortController();
    const currentEntry = registerAbortController(collection, currentController, 7, 7);
    assert.equal(currentController.signal.aborted, false);
    assert.equal(collection.has(currentEntry), true);
    releaseAbortController(collection, currentEntry);
    assert.equal(collection.size, 0);

    const staleController = new AbortController();
    registerAbortController(collection, staleController, 6, 7);
    assert.equal(staleController.signal.aborted, true);
    const activeController = new AbortController();
    registerAbortController(collection, activeController, 7, 7);
    abortControllerEntries(collection);
    assert.equal(activeController.signal.aborted, true);
    assert.equal(collection.size, 0);

    let decision = advanceSnapshotConfirmation(null, "flop:A", 10);
    assert.equal(decision.confirmed, false);
    assert.deepEqual(decision.pending, { signature: "flop:A", frameSeq: 10 });

    decision = advanceSnapshotConfirmation(decision.pending, "flop:A", 10);
    assert.equal(decision.confirmed, false, "the same frame must not self-confirm");
    decision = advanceSnapshotConfirmation(decision.pending, "flop:A", 9);
    assert.equal(decision.confirmed, false, "an older frame must not confirm");
    assert.equal(decision.pending.frameSeq, 10);
    decision = advanceSnapshotConfirmation(decision.pending, "flop:A", 11);
    assert.equal(decision.confirmed, true, "a distinct newer frame may confirm");
    assert.equal(decision.pending, null);

    decision = advanceSnapshotConfirmation(null, "turn:B", null);
    assert.equal(decision.confirmed, false);
    decision = advanceSnapshotConfirmation(decision.pending, "turn:B", null);
    assert.equal(decision.confirmed, false, "missing frameSeq must never confirm");
    decision = advanceSnapshotConfirmation(decision.pending, "river:C", 20);
    assert.equal(decision.confirmed, false, "a changed signature starts a new confirmation");

    let application = decideSnapshotApplication(null, "fast-roi:D", 30, 0.8);
    assert.equal(application.apply, false, "medium fast-reader confidence needs confirmation");
    application = decideSnapshotApplication(application.pending, "fast-roi:D", 30, 0.8);
    assert.equal(application.apply, false, "the same fast-reader frame cannot self-confirm");
    application = decideSnapshotApplication(application.pending, "fast-roi:D", 31, 0.8);
    assert.equal(application.apply, true, "a newer matching fast-reader frame may confirm");
    application = decideSnapshotApplication(null, "fast-roi:E", 40, 0.9);
    assert.equal(application.apply, true, "direct confidence applies immediately");
    for (const confidence of [0.75, 0.899]) {
        application = decideSnapshotApplication(null, `fast-boundary:${confidence}`, 50, confidence);
        assert.equal(application.apply, false, `confidence ${confidence} must not bypass confirmation`);
    }
    application = decideSnapshotApplication({ signature: "old", frameSeq: 2 }, "low:F", 41, 0.74);
    assert.equal(application.apply, false);
    assert.equal(application.pending, null, "low confidence clears pending confirmation");

    for (const reason of ["reader-busy", "processing", "duplicate-seq", "out-of-order-seq"]) {
        assert.equal(classifyDroppedFrame(reason), "transient", reason);
    }
    for (const reason of ["reader-not-running", "capture-mode-not-browser", "session-stale", "unknown"]) {
        assert.equal(classifyDroppedFrame(reason), "terminal", reason);
    }

    const appSource = fs.readFileSync(path.resolve(__dirname, "..", "app.js"), "utf8");
    assert.equal(appSource.includes("isFastGgReaderSnapshot"), false);
    assert.equal(appSource.includes("handleGgDroppedFramePayload(payload, options, sessionId)"), true);
    assert.equal(appSource.includes("GG_READER_SESSION_POLICY.selectCaptureMode(useBrowserCapture)"), true);
    assert.equal(appSource.includes("?ggBrowser=1 לצילום דרך הדפדפן"), true);
}

if (require.main === module) {
    try {
        runReaderSessionSmoke();
        console.log("reader-session-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runReaderSessionSmoke };
