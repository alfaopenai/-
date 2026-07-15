const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

const DEFAULT_STATUS_URL = "http://127.0.0.1:8787/api/gg-reader/status";
const DEFAULT_BACKEND_ARGS = [
    "-m",
    "uvicorn",
    "backend.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8787"
];

function checkBackendReachable(statusUrl = DEFAULT_STATUS_URL, timeoutMs = 500) {
    return new Promise((resolve) => {
        let settled = false;
        const finish = (reachable) => {
            if (settled) {
                return;
            }
            settled = true;
            resolve(Boolean(reachable));
        };
        let request;
        try {
            request = http.get(statusUrl, (response) => {
                response.resume();
                finish(response.statusCode >= 200 && response.statusCode < 300);
            });
        } catch (error) {
            finish(false);
            return;
        }
        request.setTimeout(timeoutMs, () => {
            request.destroy();
            finish(false);
        });
        request.once("error", () => finish(false));
    });
}

function delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}

function appendOutput(current, chunk, limit = 8000) {
    const next = `${current}${String(chunk || "")}`;
    return next.length > limit ? next.slice(next.length - limit) : next;
}

function resolveBackendCwd(options = {}) {
    if (options.isPackaged) {
        if (!options.resourcesPath) {
            throw new Error("Electron resourcesPath is required in packaged mode");
        }
        return path.resolve(options.resourcesPath, "app.asar.unpacked");
    }
    return path.resolve(options.appDir || process.cwd());
}

function resolveBackendDataDir(userDataPath) {
    if (!userDataPath) {
        throw new Error("Electron userData path is required for backend persistence");
    }
    return path.resolve(userDataPath, "backend-data");
}

async function terminateChild(child, timeoutMs = 2000) {
    if (!child || child.exitCode !== null || child.signalCode !== null) {
        return;
    }
    await new Promise((resolve) => {
        let settled = false;
        const finish = () => {
            if (settled) {
                return;
            }
            settled = true;
            clearTimeout(forceTimer);
            clearTimeout(giveUpTimer);
            child.removeListener("exit", finish);
            resolve();
        };
        const forceTimer = setTimeout(() => {
            if (child.exitCode === null && child.signalCode === null) {
                child.kill("SIGKILL");
            }
        }, Math.max(100, timeoutMs));
        const giveUpTimer = setTimeout(finish, Math.max(250, timeoutMs + 1000));
        child.once("exit", finish);
        try {
            child.kill("SIGTERM");
        } catch (error) {
            finish();
        }
    });
}

async function ensureBackendRunning(options = {}) {
    const statusUrl = options.statusUrl || DEFAULT_STATUS_URL;
    const requestTimeoutMs = Number(options.requestTimeoutMs) || 500;
    if (await checkBackendReachable(statusUrl, requestTimeoutMs)) {
        return { owned: false, child: null, statusUrl };
    }

    const pythonCommand = options.pythonCommand
        || process.env.PYTHON
        || (process.platform === "win32" ? "python" : "python3");
    const args = Array.isArray(options.args) ? options.args : DEFAULT_BACKEND_ARGS;
    const spawnImpl = options.spawnImpl || spawn;
    const startupTimeoutMs = Number(options.startupTimeoutMs) || 15000;
    const pollIntervalMs = Math.max(50, Number(options.pollIntervalMs) || 150);
    let child;
    try {
        child = spawnImpl(pythonCommand, args, {
            cwd: options.cwd || process.cwd(),
            env: options.env || process.env,
            shell: false,
            windowsHide: true,
            stdio: ["ignore", "pipe", "pipe"]
        });
    } catch (error) {
        throw new Error(`Could not launch Python backend with "${pythonCommand}": ${error.message}`);
    }

    let spawnError = null;
    let exitResult = null;
    let stderr = "";
    child.once("error", (error) => {
        spawnError = error;
    });
    child.once("exit", (code, signal) => {
        exitResult = { code, signal };
    });
    if (child.stdout) {
        child.stdout.on("data", (chunk) => {
            if (typeof options.onStdout === "function") {
                options.onStdout(chunk);
            }
        });
    }
    if (child.stderr) {
        child.stderr.on("data", (chunk) => {
            stderr = appendOutput(stderr, chunk);
            if (typeof options.onStderr === "function") {
                options.onStderr(chunk);
            }
        });
    }

    const deadline = Date.now() + startupTimeoutMs;
    while (Date.now() < deadline) {
        const reachable = await checkBackendReachable(statusUrl, requestTimeoutMs);
        if (reachable) {
            await delay(Math.min(150, pollIntervalMs));
            if (exitResult || spawnError) {
                if (await checkBackendReachable(statusUrl, requestTimeoutMs)) {
                    return { owned: false, child: null, statusUrl };
                }
                break;
            }
            return { owned: true, child, statusUrl };
        }
        if (spawnError || exitResult) {
            break;
        }
        await delay(pollIntervalMs);
    }

    await terminateChild(child, 1000);
    const detail = spawnError
        ? spawnError.message
        : exitResult
            ? `process exited with code ${exitResult.code}${exitResult.signal ? ` (${exitResult.signal})` : ""}`
            : `startup timed out after ${startupTimeoutMs}ms`;
    const stderrDetail = stderr.trim() ? `\n${stderr.trim()}` : "";
    throw new Error(
        `Could not start the local poker reader backend with "${pythonCommand}": ${detail}.${stderrDetail}`
    );
}

async function stopOwnedBackend(owner, timeoutMs = 2000) {
    if (!owner || !owner.owned || !owner.child) {
        return false;
    }
    await terminateChild(owner.child, timeoutMs);
    owner.owned = false;
    owner.child = null;
    return true;
}

module.exports = {
    DEFAULT_BACKEND_ARGS,
    DEFAULT_STATUS_URL,
    checkBackendReachable,
    ensureBackendRunning,
    resolveBackendCwd,
    resolveBackendDataDir,
    stopOwnedBackend,
    terminateChild
};
