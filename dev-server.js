const http = require("node:http");
const path = require("node:path");
const fs = require("node:fs/promises");
const { createReadStream } = require("node:fs");

const port = Number(process.env.PORT) || 3001;
const root = path.resolve(__dirname);

const mimeTypes = new Map([
    [".html", "text/html; charset=utf-8"],
    [".css", "text/css; charset=utf-8"],
    [".js", "application/javascript; charset=utf-8"],
    [".mjs", "application/javascript; charset=utf-8"],
    [".json", "application/json; charset=utf-8"],
    [".wasm", "application/wasm"],
    [".svg", "image/svg+xml"],
    [".png", "image/png"],
    [".jpg", "image/jpeg"],
    [".jpeg", "image/jpeg"],
    [".ico", "image/x-icon"],
    [".woff", "font/woff"],
    [".woff2", "font/woff2"],
    [".ttf", "font/ttf"],
    [".map", "application/json; charset=utf-8"],
]);

function getMimeType(filePath) {
    const ext = path.extname(filePath).toLowerCase();
    return mimeTypes.get(ext) || "application/octet-stream";
}

async function resolvePath(requestPath) {
    let normalized = decodeURIComponent(requestPath.split("?")[0]);
    if (!normalized || normalized === "/") {
        normalized = "index.html";
    }
    normalized = path.normalize(normalized);
    normalized = normalized.replace(/^([/\\]+)/, "");
    if (normalized.startsWith("..")) {
        return null;
    }
    const absolute = path.join(root, normalized);
    if (!absolute.startsWith(root)) {
        return null;
    }

    try {
        const stat = await fs.stat(absolute);
        if (stat.isDirectory()) {
            const indexPath = path.join(absolute, "index.html");
            await fs.access(indexPath);
            return indexPath;
        }
        return absolute;
    } catch (error) {
        return null;
    }
}

const server = http.createServer(async (req, res) => {
    const filePath = await resolvePath(req.url || "/");
    if (!filePath) {
        res.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("404 - Not Found");
        return;
    }

    res.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
    res.setHeader("Cross-Origin-Opener-Policy", "same-origin");

    try {
        res.writeHead(200, { "Content-Type": getMimeType(filePath) });
        createReadStream(filePath).pipe(res);
    } catch (error) {
        res.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
        res.end("500 - Internal Server Error");
    }
});

server.listen(port, () => {
    console.log(`Alpha Poker static server listening at http://localhost:${port}`);
});
