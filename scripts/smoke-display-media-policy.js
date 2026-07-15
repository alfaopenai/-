const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const {
    getClubGgTitleScore,
    isAllowedAppOrigin,
    isTrustedDisplayMediaRequest,
    selectClubGgWindowSource
} = require("./display-media-policy");

function thumbnail(empty = false) {
    return { isEmpty: () => empty };
}

function runDisplayMediaPolicySmoke() {
    for (const origin of [
        "http://127.0.0.1:7000",
        "http://127.0.0.1:3001/",
        "http://localhost:7000/index.html",
        "http://localhost:3001/?ggBrowser=1"
    ]) {
        assert.equal(isAllowedAppOrigin(origin), true, origin);
    }
    for (const origin of [
        "https://127.0.0.1:7000",
        "http://127.0.0.1:8787",
        "http://127.0.0.1:7000.evil.example",
        "http://evil.example:7000",
        "file:///index.html",
        ""
    ]) {
        assert.equal(isAllowedAppOrigin(origin), false, origin);
    }

    assert.equal(isTrustedDisplayMediaRequest({
        securityOrigin: "http://127.0.0.1:7000",
        userGesture: true,
        videoRequested: true
    }), true);
    assert.equal(isTrustedDisplayMediaRequest({
        frame: { url: "http://localhost:3001/?ggBrowser=1" },
        userGesture: true
    }), true);
    assert.equal(isTrustedDisplayMediaRequest({
        securityOrigin: "http://127.0.0.1:7000",
        userGesture: false
    }), false);
    assert.equal(isTrustedDisplayMediaRequest({
        securityOrigin: "http://127.0.0.1:7000",
        userGesture: true,
        videoRequested: false
    }), false);
    assert.equal(isTrustedDisplayMediaRequest({
        securityOrigin: "http://evil.example:7000",
        userGesture: true
    }), false);

    assert.equal(getClubGgTitleScore("NLH 1-2 - 1/2"), 2);
    assert.equal(getClubGgTitleScore("PLO 5/10"), 2);
    assert.equal(getClubGgTitleScore("ClubGG Lobby"), 1);
    assert.equal(getClubGgTitleScore("Alpha Poker - NLH helper"), 0);
    assert.equal(getClubGgTitleScore("Alpha Poker http://localhost:7000"), 0);

    const lobby = { id: "lobby", name: "ClubGG Lobby", thumbnail: thumbnail() };
    const table = { id: "table", name: "NLH 1-2 - 1/2", thumbnail: thumbnail() };
    const ownApp = { id: "own", name: "Alpha Poker - NLH localhost", thumbnail: thumbnail() };
    const hiddenTable = { id: "hidden", name: "PLO 5/10", thumbnail: thumbnail(true) };
    assert.equal(
        selectClubGgWindowSource([ownApp, lobby, hiddenTable, table]),
        table,
        "a visible table title wins over the lobby and excluded app window"
    );
    assert.equal(selectClubGgWindowSource([ownApp, hiddenTable]), null);
    assert.equal(selectClubGgWindowSource([]), null);

    const mainSource = fs.readFileSync(path.resolve(__dirname, "..", "main.js"), "utf8");
    assert.equal(mainSource.includes("types: [\"window\"]"), true);
    assert.equal(mainSource.includes("selectClubGgWindowSource(sources)"), true);
    assert.equal(mainSource.includes("sources[0]"), false, "the first screen/window must never be selected blindly");
    const readyBlock = mainSource.slice(mainSource.indexOf("app.whenReady()"));
    assert.ok(
        readyBlock.indexOf("configureDisplayMediaHandler();") < readyBlock.indexOf("createWindow(appUrl);"),
        "display-media handler must be configured before the BrowserWindow is created"
    );
}

if (require.main === module) {
    try {
        runDisplayMediaPolicySmoke();
        console.log("display-media-policy-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runDisplayMediaPolicySmoke };
