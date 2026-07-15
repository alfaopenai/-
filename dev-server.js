const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs/promises");
const { createReadStream } = require("node:fs");

const defaultPort = Number(process.env.PORT) || 7000;
const defaultHost = process.env.HOST || "127.0.0.1";
const defaultRoot = path.resolve(__dirname);

const CONTENT_SECURITY_POLICY = [
    "default-src 'self'",
    "script-src 'self'",
    // The table and drag overlays use element.style for runtime positioning.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "media-src 'self' blob:",
    "connect-src 'self' http://127.0.0.1:8787 http://localhost:8787 ws://127.0.0.1:8787 ws://localhost:8787",
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
    "form-action 'self'"
].join("; ");

const PUBLIC_FILES = Object.freeze([
    "index.html",
    "styles.css",
    "premium.css",
    "app.js",
    "poker-position-policy.js",
    "reader-session-policy.js",
    "runtime-capability-policy.js",
    "favicon.svg",
    "assets/poker-room-backdrop.png",
    "assets/pot-chips.png",
    "assets/card-back.png",
    "mock/gg_snapshot_example.json",
    "solver/index.js",
    "solver/strategy/singleStreetCfr.js",
    "solver/strategy/texasCfr.js",
    "solver/strategy/pycfrAdapter.js",
    "solver/strategy/postflopWasm.js"
]);
const publicFileSet = new Set(PUBLIC_FILES);

const mimeTypes = new Map([
    [".html", "text/html; charset=utf-8"],
    [".css", "text/css; charset=utf-8"],
    [".js", "application/javascript; charset=utf-8"],
    [".json", "application/json; charset=utf-8"],
    [".svg", "image/svg+xml"],
    [".png", "image/png"]
]);

function getMimeType(filePath) {
    return mimeTypes.get(path.extname(filePath).toLowerCase()) || "application/octet-stream";
}

function isLoopbackHost(host) {
    const normalized = String(host || "").trim().toLowerCase();
    return normalized === "127.0.0.1" || normalized === "localhost" || normalized === "::1";
}

function isAllowedHostHeader(hostHeader, localPort) {
    const normalized = String(hostHeader || "").trim().toLowerCase();
    const port = Number(localPort);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
        return false;
    }
    return normalized === `127.0.0.1:${port}`
        || normalized === `localhost:${port}`
        || normalized === `[::1]:${port}`;
}

function normalizePublicPath(requestUrl) {
    let decoded;
    try {
        const rawPath = String(requestUrl || "/").split(/[?#]/, 1)[0];
        decoded = decodeURIComponent(rawPath);
    } catch (error) {
        return null;
    }
    if (decoded.includes("\0") || decoded.includes("\\")) {
        return null;
    }
    const relative = decoded.replace(/^\/+/, "") || "index.html";
    if (
        relative.startsWith("/")
        || relative.split("/").some((segment) => segment === "." || segment === ".." || segment === "")
        || path.posix.normalize(relative) !== relative
        || !publicFileSet.has(relative)
    ) {
        return null;
    }
    return relative;
}

async function resolvePath(requestUrl, root = defaultRoot) {
    const publicPath = normalizePublicPath(requestUrl);
    if (!publicPath) {
        return null;
    }
    const absoluteRoot = path.resolve(root);
    const candidate = path.resolve(absoluteRoot, ...publicPath.split("/"));
    const relative = path.relative(absoluteRoot, candidate);
    if (relative.startsWith("..") || path.isAbsolute(relative)) {
        return null;
    }
    try {
        const [rootRealPath, fileRealPath, stat] = await Promise.all([
            fs.realpath(absoluteRoot),
            fs.realpath(candidate),
            fs.stat(candidate)
        ]);
        const realRelative = path.relative(rootRealPath, fileRealPath);
        if (realRelative.startsWith("..") || path.isAbsolute(realRelative) || !stat.isFile()) {
            return null;
        }
        return fileRealPath;
    } catch (error) {
        return null;
    }
}

function setCommonHeaders(res) {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", CONTENT_SECURITY_POLICY);
    res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
    res.setHeader("Cross-Origin-Opener-Policy", "same-origin");
}

function sendText(res, statusCode, message, extraHeaders = {}) {
    setCommonHeaders(res);
    res.writeHead(statusCode, {
        "Content-Type": "text/plain; charset=utf-8",
        ...extraHeaders
    });
    res.end(message);
}

function createStaticServer({ root = defaultRoot } = {}) {
    return http.createServer(async (req, res) => {
        if (!isAllowedHostHeader(req.headers.host, req.socket.localPort)) {
            sendText(res, 421, "421 - Misdirected Request");
            return;
        }
        if (req.method !== "GET" && req.method !== "HEAD") {
            sendText(res, 405, "405 - Method Not Allowed", { Allow: "GET, HEAD" });
            return;
        }

        const filePath = await resolvePath(req.url || "/", root);
        if (!filePath) {
            sendText(res, 404, "404 - Not Found");
            return;
        }

        setCommonHeaders(res);
        res.writeHead(200, { "Content-Type": getMimeType(filePath) });
        if (req.method === "HEAD") {
            res.end();
            return;
        }
        const stream = createReadStream(filePath);
        stream.on("error", () => {
            if (!res.headersSent) {
                sendText(res, 500, "500 - Internal Server Error");
                return;
            }
            res.destroy();
        });
        stream.pipe(res);
    });
}

function startStaticServer({ port = defaultPort, host = defaultHost, root = defaultRoot } = {}) {
    if (!isLoopbackHost(host)) {
        return Promise.reject(new Error(`Static server host must be loopback, received: ${host}`));
    }
    const server = createStaticServer({ root });
    return new Promise((resolve, reject) => {
        const handleError = (error) => {
            server.removeListener("listening", handleListening);
            reject(error);
        };
        const handleListening = () => {
            server.removeListener("error", handleError);
            resolve(server);
        };
        server.once("error", handleError);
        server.once("listening", handleListening);
        server.listen(port, host);
    });
}

if (require.main === module) {
    startStaticServer().then((server) => {
        const address = server.address();
        console.log(`Alpha Poker static server listening at http://${defaultHost}:${address.port}`);
    }).catch((error) => {
        console.error(`Alpha Poker static server failed: ${error.message}`);
        process.exitCode = 1;
    });
}

module.exports = {
    CONTENT_SECURITY_POLICY,
    PUBLIC_FILES,
    createStaticServer,
    isAllowedHostHeader,
    normalizePublicPath,
    resolvePath,
    startStaticServer
};
