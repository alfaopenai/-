const { spawn } = require("node:child_process");
const path = require("node:path");

const root = path.resolve(__dirname, "..");
const pythonCommand = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

const defaultCommands = [
    {
        name: "backend",
        command: pythonCommand,
        args: ["-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8787"]
    },
    { name: "web", command: process.execPath, args: ["dev-server.js"] }
];

function supervise(commands, options = {}) {
    const spawnImpl = options.spawnImpl || spawn;
    const cwd = options.cwd || root;
    const env = options.env || process.env;
    const setProcessExitCode = options.setProcessExitCode !== false;
    const children = [];
    let shuttingDown = false;
    let failure = null;

    const shutdown = (signal = "SIGTERM") => {
        if (shuttingDown) {
            return;
        }
        shuttingDown = true;
        children.forEach(({ child }) => {
            if (child.exitCode === null && child.signalCode === null && !child.killed) {
                child.kill(signal);
            }
        });
    };

    const fail = (name, message, code = 1) => {
        if (shuttingDown) {
            return;
        }
        const normalizedCode = Number.isInteger(code) && code > 0 ? code : 1;
        failure = { name, message, code: normalizedCode };
        process.stderr.write(`[${name}] ${message}\n`);
        if (setProcessExitCode) {
            process.exitCode = normalizedCode;
        }
        if (typeof options.onFailure === "function") {
            options.onFailure(failure);
        }
        shutdown();
    };

    for (const commandSpec of commands) {
        if (shuttingDown) {
            break;
        }
        const { name, command, args = [] } = commandSpec;
        let child;
        try {
            child = spawnImpl(command, args, {
                cwd,
                shell: false,
                stdio: "pipe",
                env
            });
        } catch (error) {
            fail(name, `failed to start: ${error.message}`);
            break;
        }

        const record = { name, child };
        children.push(record);
        if (child.stdout) {
            child.stdout.on("data", (chunk) => process.stdout.write(`[${name}] ${chunk}`));
        }
        if (child.stderr) {
            child.stderr.on("data", (chunk) => process.stderr.write(`[${name}] ${chunk}`));
        }
        child.once("error", (error) => {
            fail(name, `failed to start: ${error.message}`);
        });
        child.once("exit", (code, signal) => {
            if (shuttingDown) {
                return;
            }
            const detail = signal
                ? `exited from signal ${signal}`
                : `exited with code ${code}`;
            fail(name, detail, Number(code) || 1);
        });
    }

    return {
        children,
        get failure() {
            return failure;
        },
        get shuttingDown() {
            return shuttingDown;
        },
        shutdown
    };
}

if (require.main === module) {
    const supervisor = supervise(defaultCommands);
    const handleSignal = (signal) => {
        supervisor.shutdown(signal);
        process.exitCode = 0;
    };
    process.once("SIGINT", () => handleSignal("SIGINT"));
    process.once("SIGTERM", () => handleSignal("SIGTERM"));
}

module.exports = { defaultCommands, supervise };
