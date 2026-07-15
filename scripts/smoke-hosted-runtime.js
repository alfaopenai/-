const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
    getRuntimeCapabilities,
    isLoopbackHostname,
    normalizeHostname
} = require("../runtime-capability-policy");

function runHostedRuntimeSmoke() {
    assert.equal(normalizeHostname("[::1]"), "::1");
    for (const hostname of ["localhost", "127.0.0.1", "::1", "[::1]"]) {
        assert.equal(isLoopbackHostname(hostname), true, hostname);
        assert.equal(getRuntimeCapabilities({ protocol: "http:", hostname }).localReaderAvailable, true, hostname);
    }

    for (const locationLike of [
        { protocol: "https:", hostname: "alpha-poker-web.onrender.com" },
        { protocol: "https:", hostname: "poker.example.com" },
        { protocol: "file:", hostname: "" },
        { protocol: "http:", hostname: "127.0.0.2" }
    ]) {
        const capabilities = getRuntimeCapabilities(locationLike);
        assert.equal(capabilities.localReaderAvailable, false, JSON.stringify(locationLike));
        assert.equal(capabilities.hosted, true, JSON.stringify(locationLike));
    }

    const appSource = fs.readFileSync(path.resolve(__dirname, "..", "app.js"), "utf8");
    assert.ok(appSource.includes("RUNTIME_CAPABILITIES.localReaderAvailable"));
    assert.ok(appSource.includes("קריאת GG זמינה באפליקציית שולחן העבודה"));
}

if (require.main === module) {
    try {
        runHostedRuntimeSmoke();
        console.log("hosted-runtime-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runHostedRuntimeSmoke };
