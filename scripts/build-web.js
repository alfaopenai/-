const path = require("node:path");
const fs = require("node:fs/promises");
const { PUBLIC_FILES } = require("../dev-server");

const root = path.resolve(__dirname, "..");
const publishRoot = path.resolve(root, "web-dist");

function assertInsideRoot(candidate, parent, label) {
    const relative = path.relative(parent, candidate);
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
        throw new Error(`${label} must stay inside ${parent}: ${candidate}`);
    }
}

function validatePublicPath(publicPath) {
    const value = String(publicPath || "");
    const normalized = value.replaceAll("\\", "/");
    if (
        !value
        || normalized !== value
        || path.posix.isAbsolute(value)
        || path.posix.normalize(value) !== value
        || value.split("/").some((segment) => !segment || segment === "." || segment === "..")
    ) {
        throw new Error(`Invalid public path: ${value}`);
    }
    return value;
}

async function collectFiles(directory, prefix = "") {
    const entries = await fs.readdir(directory, { withFileTypes: true });
    const files = [];
    for (const entry of entries) {
        const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
        const absolute = path.join(directory, entry.name);
        if (entry.isSymbolicLink()) {
            throw new Error(`Publish output contains a symlink: ${relative}`);
        }
        if (entry.isDirectory()) {
            files.push(...await collectFiles(absolute, relative));
        } else if (entry.isFile()) {
            files.push(relative.replaceAll("\\", "/"));
        } else {
            throw new Error(`Unsupported publish output entry: ${relative}`);
        }
    }
    return files;
}

async function buildWeb() {
    if (path.dirname(publishRoot) !== root || path.basename(publishRoot) !== "web-dist") {
        throw new Error(`Refusing to clean unexpected publish directory: ${publishRoot}`);
    }

    const rootRealPath = await fs.realpath(root);
    await fs.rm(publishRoot, { recursive: true, force: true });
    await fs.mkdir(publishRoot, { recursive: true });

    for (const rawPublicPath of PUBLIC_FILES) {
        const publicPath = validatePublicPath(rawPublicPath);
        const source = path.resolve(root, ...publicPath.split("/"));
        const destination = path.resolve(publishRoot, ...publicPath.split("/"));
        assertInsideRoot(source, root, "Source");
        assertInsideRoot(destination, publishRoot, "Destination");

        const [sourceRealPath, sourceStat] = await Promise.all([
            fs.realpath(source),
            fs.lstat(source)
        ]);
        assertInsideRoot(sourceRealPath, rootRealPath, "Resolved source");
        if (sourceStat.isSymbolicLink() || !sourceStat.isFile()) {
            throw new Error(`Public entry must be a regular file: ${publicPath}`);
        }

        await fs.mkdir(path.dirname(destination), { recursive: true });
        await fs.copyFile(sourceRealPath, destination);
    }

    const expected = [...new Set(PUBLIC_FILES)].sort();
    const actual = (await collectFiles(publishRoot)).sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
        throw new Error(`Publish output mismatch\nexpected=${JSON.stringify(expected)}\nactual=${JSON.stringify(actual)}`);
    }

    console.log(`web-build ok (${actual.length} curated files -> ${publishRoot})`);
    return { files: actual, publishRoot };
}

if (require.main === module) {
    buildWeb().catch((error) => {
        console.error(error);
        process.exitCode = 1;
    });
}

module.exports = { buildWeb, collectFiles, validatePublicPath };
