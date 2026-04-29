const { spawn } = require("node:child_process");

const commands = [
    { name: "backend", command: "npm", args: ["run", "start:backend"] },
    { name: "web", command: "npm", args: ["run", "start:web"] },
];

const children = commands.map(({ name, command, args }) => {
    const child = spawn(command, args, {
        shell: true,
        stdio: "pipe",
        env: process.env,
    });

    child.stdout.on("data", (chunk) => process.stdout.write(`[${name}] ${chunk}`));
    child.stderr.on("data", (chunk) => process.stderr.write(`[${name}] ${chunk}`));
    child.on("exit", (code) => {
        if (code !== 0) {
            process.exitCode = code || 1;
        }
    });

    return child;
});

function shutdown() {
    children.forEach((child) => {
        if (!child.killed) {
            child.kill();
        }
    });
}

process.on("SIGINT", () => {
    shutdown();
    process.exit();
});

process.on("SIGTERM", () => {
    shutdown();
    process.exit();
});
