const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const packageJson = require("../package.json");
const { resolveBackendCwd, resolveBackendDataDir } = require("./backend-lifecycle");

function runPackagedBackendPathSmoke() {
    const appDir = path.resolve(__dirname, "..");
    assert.equal(
        resolveBackendCwd({ isPackaged: false, appDir }),
        appDir
    );

    const resourcesPath = path.resolve(appDir, "synthetic-electron-resources");
    const packagedCwd = resolveBackendCwd({
        isPackaged: true,
        resourcesPath,
        appDir: path.join(resourcesPath, "app.asar")
    });
    assert.equal(packagedCwd, path.join(resourcesPath, "app.asar.unpacked"));
    assert.equal(packagedCwd.includes(`${path.sep}app.asar${path.sep}`), false);
    assert.throws(
        () => resolveBackendCwd({ isPackaged: true }),
        /resourcesPath/
    );

    const userDataPath = path.resolve(appDir, "synthetic-user-data");
    const dataDir = resolveBackendDataDir(userDataPath);
    assert.equal(dataDir, path.join(userDataPath, "backend-data"));
    assert.equal(dataDir.startsWith(resourcesPath), false);
    assert.throws(() => resolveBackendDataDir(""), /userData/);

    const devSupervisorSource = fs.readFileSync(path.join(appDir, "scripts", "dev.js"), "utf8");
    assert.equal(devSupervisorSource.includes("ALPHA_POKER_DATA_DIR"), false);
    const electronMainSource = fs.readFileSync(path.join(appDir, "main.js"), "utf8");
    assert.equal(electronMainSource.includes("ALPHA_POKER_DATA_DIR"), true);
    assert.equal(electronMainSource.includes("app.getPath(\"userData\")"), true);

    const build = packageJson.build || {};
    assert.ok(Array.isArray(build.asarUnpack));
    assert.ok(build.asarUnpack.includes("backend/**/*"));
    assert.ok(Array.isArray(build.files));
    for (const exclusion of [
        "!backend/data/**",
        "!backend/**/*.sqlite",
        "!backend/**/*.sqlite-*",
        "!backend/**/*.jsonl"
    ]) {
        assert.ok(build.files.includes(exclusion), `missing package exclusion ${exclusion}`);
    }
}

if (require.main === module) {
    try {
        runPackagedBackendPathSmoke();
        console.log("packaged-backend-path-smoke ok");
    } catch (error) {
        console.error(error);
        process.exitCode = 1;
    }
}

module.exports = { runPackagedBackendPathSmoke };
