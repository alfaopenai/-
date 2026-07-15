const { app, BrowserWindow, desktopCapturer, dialog, session } = require("electron");
const { startStaticServer } = require("./dev-server");
const {
    ensureBackendRunning,
    resolveBackendCwd,
    resolveBackendDataDir,
    stopOwnedBackend
} = require("./scripts/backend-lifecycle");
const {
    isTrustedDisplayMediaRequest,
    selectClubGgWindowSource
} = require("./scripts/display-media-policy");

const APP_HOST = "127.0.0.1";
const APP_PORTS = [7000, 3001];
let staticServer = null;
let backendOwner = null;
let finishingQuit = false;

function configureDisplayMediaHandler() {
    session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
        let completed = false;
        const finish = (result = {}) => {
            if (completed) {
                return;
            }
            completed = true;
            callback(result);
        };
        if (!isTrustedDisplayMediaRequest(request, APP_PORTS)) {
            finish();
            return;
        }
        desktopCapturer.getSources({
            types: ["window"],
            thumbnailSize: { width: 320, height: 180 },
            fetchWindowIcons: false
        }).then((sources) => {
            const source = selectClubGgWindowSource(sources);
            finish(source ? { video: source } : {});
        }).catch(() => finish());
    });
}

function createWindow(appUrl) {
    const win = new BrowserWindow({
        width: 1280,
        height: 900,
        minWidth: 1024,
        minHeight: 700,
        autoHideMenuBar: true,
        backgroundColor: "#111826",
        webPreferences: {
            contextIsolation: true
        }
    });

    win.loadURL(appUrl);
}

async function startAppServer() {
    let lastError = null;
    for (const port of APP_PORTS) {
        try {
            staticServer = await startStaticServer({ port, host: APP_HOST, root: __dirname });
            return `http://${APP_HOST}:${port}/`;
        } catch (error) {
            lastError = error;
            if (!error || error.code !== "EADDRINUSE") {
                throw error;
            }
        }
    }
    throw lastError || new Error("No local port is available for the application server.");
}

let appUrl = null;

app.whenReady().then(async () => {
    configureDisplayMediaHandler();
    const backendDataDir = resolveBackendDataDir(app.getPath("userData"));
    backendOwner = await ensureBackendRunning({
        cwd: resolveBackendCwd({
            isPackaged: app.isPackaged,
            resourcesPath: process.resourcesPath,
            appDir: __dirname
        }),
        env: {
            ...process.env,
            ALPHA_POKER_DATA_DIR: backendDataDir
        },
        onStdout: (chunk) => process.stdout.write(`[backend] ${chunk}`),
        onStderr: (chunk) => process.stderr.write(`[backend] ${chunk}`)
    });
    appUrl = await startAppServer();
    createWindow(appUrl);

    app.on("activate", () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            createWindow(appUrl);
        }
    });
}).catch(async (error) => {
    console.error(`Could not start Alpha Poker: ${error.message}`);
    dialog.showErrorBox(
        "Alpha Poker could not start",
        `${error.message}\n\nVerify that Python and the backend dependencies are installed, or set the PYTHON environment variable to the correct executable.`
    );
    await stopOwnedBackend(backendOwner);
    backendOwner = null;
    if (staticServer) {
        staticServer.close();
        staticServer = null;
    }
    app.quit();
});

app.on("before-quit", (event) => {
    if (staticServer) {
        staticServer.close();
        staticServer = null;
    }
    if (backendOwner && backendOwner.owned && !finishingQuit) {
        event.preventDefault();
        finishingQuit = true;
        stopOwnedBackend(backendOwner).finally(() => {
            backendOwner = null;
            app.quit();
        });
    }
});

app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
        app.quit();
    }
});
