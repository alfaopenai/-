const assert = require("node:assert/strict");
const http = require("node:http");
const {
    checkBackendReachable,
    ensureBackendRunning,
    stopOwnedBackend
} = require("./backend-lifecycle");
const { supervise } = require("./dev");

function listen(server, port = 0) {
    return new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, "127.0.0.1", () => resolve(server.address().port));
    });
}

function close(server) {
    return new Promise((resolve) => server.close(resolve));
}

async function freePort() {
    const server = http.createServer();
    const port = await listen(server);
    await close(server);
    return port;
}

async function smokeBackendOwnership() {
    const external = http.createServer((request, response) => {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end("{}");
    });
    const externalPort = await listen(external);
    const externalUrl = `http://127.0.0.1:${externalPort}/api/gg-reader/status`;
    try {
        const externalOwner = await ensureBackendRunning({
            statusUrl: externalUrl,
            requestTimeoutMs: 100,
            spawnImpl: () => {
                throw new Error("an already-running backend must not spawn");
            }
        });
        assert.equal(externalOwner.owned, false);
        assert.equal(await stopOwnedBackend(externalOwner), false);
        assert.equal(await checkBackendReachable(externalUrl, 100), true);
    } finally {
        await close(external);
    }

    const ownedPort = await freePort();
    const ownedUrl = `http://127.0.0.1:${ownedPort}/api/gg-reader/status`;
    const childSource = [
        "require('node:http')",
        ".createServer((request,response)=>{response.writeHead(200);response.end('{}')})",
        `.listen(${ownedPort},'127.0.0.1')`
    ].join("");
    const owner = await ensureBackendRunning({
        statusUrl: ownedUrl,
        pythonCommand: process.execPath,
        args: ["-e", childSource],
        cwd: process.cwd(),
        requestTimeoutMs: 100,
        pollIntervalMs: 50,
        startupTimeoutMs: 3000
    });
    try {
        assert.equal(owner.owned, true);
        assert.ok(owner.child && owner.child.pid);
        assert.equal(await checkBackendReachable(ownedUrl, 100), true);
    } finally {
        await stopOwnedBackend(owner, 500);
    }
    assert.equal(await checkBackendReachable(ownedUrl, 100), false);

    const missingPort = await freePort();
    await assert.rejects(
        ensureBackendRunning({
            statusUrl: `http://127.0.0.1:${missingPort}/api/gg-reader/status`,
            pythonCommand: "definitely-not-a-real-python-command-alpha-poker",
            requestTimeoutMs: 50,
            pollIntervalMs: 50,
            startupTimeoutMs: 500
        }),
        /Could not start the local poker reader backend/
    );
}

async function smokeSupervisorFailFast() {
    let resolveFailure;
    const failed = new Promise((resolve) => {
        resolveFailure = resolve;
    });
    const supervisor = supervise([
        {
            name: "long-lived",
            command: process.execPath,
            args: ["-e", "setInterval(() => {}, 1000)"]
        },
        {
            name: "fails-fast",
            command: process.execPath,
            args: ["-e", "setTimeout(() => process.exit(7), 80)"]
        }
    ], {
        cwd: process.cwd(),
        setProcessExitCode: false,
        onFailure: resolveFailure
    });
    try {
        const failure = await Promise.race([
            failed,
            new Promise((resolve, reject) => {
                setTimeout(() => reject(new Error("supervisor timeout")), 2500);
            })
        ]);
        assert.equal(failure.name, "fails-fast");
        assert.equal(failure.code, 7);
        assert.equal(supervisor.shuttingDown, true);
        const sibling = supervisor.children.find((entry) => entry.name === "long-lived").child;
        await new Promise((resolve) => setTimeout(resolve, 150));
        assert.equal(sibling.killed, true);
    } finally {
        supervisor.shutdown();
    }
}

async function runProcessLifecycleSmoke() {
    await smokeBackendOwnership();
    await smokeSupervisorFailFast();
}

if (require.main === module) {
    runProcessLifecycleSmoke().then(() => {
        console.log("process-lifecycle-smoke ok");
    }).catch((error) => {
        console.error(error);
        process.exitCode = 1;
    });
}

module.exports = { runProcessLifecycleSmoke };
