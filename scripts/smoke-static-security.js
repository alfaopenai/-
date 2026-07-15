const assert = require("node:assert/strict");
const http = require("node:http");
const path = require("node:path");
const {
    CONTENT_SECURITY_POLICY,
    PUBLIC_FILES,
    startStaticServer
} = require("../dev-server");

const root = path.resolve(__dirname, "..");

function request(port, pathname, options = {}) {
    return new Promise((resolve, reject) => {
        const req = http.request({
            hostname: "127.0.0.1",
            port,
            path: pathname,
            method: options.method || "GET",
            headers: { Host: options.host || `127.0.0.1:${port}` }
        }, (response) => {
            const chunks = [];
            response.on("data", (chunk) => chunks.push(chunk));
            response.on("end", () => resolve({
                status: response.statusCode,
                headers: response.headers,
                body: Buffer.concat(chunks)
            }));
        });
        req.once("error", reject);
        req.end();
    });
}

async function runStaticSecuritySmoke() {
    const server = await startStaticServer({ port: 0, host: "127.0.0.1", root });
    const port = server.address().port;
    try {
        for (const file of PUBLIC_FILES) {
            const response = await request(port, `/${file}`);
            assert.equal(response.status, 200, `public asset ${file}`);
            assert.equal(response.headers["cache-control"], "no-store");
            assert.equal(response.headers["x-content-type-options"], "nosniff");
            assert.equal(response.headers["content-security-policy"], CONTENT_SECURITY_POLICY);
        }
        assert.equal((await request(port, "/")).status, 200);

        const directives = new Map(CONTENT_SECURITY_POLICY.split("; ").map((directive) => {
            const [name, ...values] = directive.split(" ");
            return [name, values];
        }));
        assert.deepEqual(directives.get("default-src"), ["'self'"]);
        assert.deepEqual(directives.get("script-src"), ["'self'"]);
        assert.equal(directives.get("script-src").includes("'unsafe-inline'"), false);
        assert.deepEqual(directives.get("style-src"), ["'self'", "'unsafe-inline'"]);
        assert.deepEqual(directives.get("object-src"), ["'none'"]);
        assert.deepEqual(directives.get("base-uri"), ["'none'"]);
        for (const source of [
            "http://127.0.0.1:8787",
            "http://localhost:8787",
            "ws://127.0.0.1:8787",
            "ws://localhost:8787"
        ]) {
            assert.ok(directives.get("connect-src").includes(source), `missing connect-src ${source}`);
        }

        const privatePaths = [
            "/.git/config",
            "/backend/data/gg_history.sqlite",
            "/backend/main.py",
            "/tests/test_fast_reader.py",
            "/dev-server.js",
            "/main.js",
            "/package.json",
            "/run-dev.out.log",
            "/output/frame.png",
            "/solver/strategy/webWorkerSolver.js",
            "/%2e%2e/package.json",
            "/backend%2fmain.py"
        ];
        for (const pathname of privatePaths) {
            const response = await request(port, pathname);
            assert.equal(response.status, 404, `private path ${pathname}`);
            assert.equal(response.headers["content-security-policy"], CONTENT_SECURITY_POLICY);
        }

        assert.equal((await request(port, "/", { host: "evil.example" })).status, 421);
        assert.equal((await request(port, "/", { host: `127.0.0.1:${port + 1}` })).status, 421);
        assert.equal((await request(port, "/", { method: "POST" })).status, 405);
        const head = await request(port, "/app.js", { method: "HEAD" });
        assert.equal(head.status, 200);
        assert.equal(head.body.length, 0);
        await assert.rejects(
            startStaticServer({ port: 0, host: "0.0.0.0", root }),
            /loopback/
        );
    } finally {
        await new Promise((resolve) => server.close(resolve));
    }
}

if (require.main === module) {
    runStaticSecuritySmoke().then(() => {
        console.log(`static-security-smoke ok (${PUBLIC_FILES.length} public assets)`);
    }).catch((error) => {
        console.error(error);
        process.exitCode = 1;
    });
}

module.exports = { runStaticSecuritySmoke };
