const DEFAULT_APP_PORTS = Object.freeze([7000, 3001]);
const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost"]);

function parseAppOrigin(value) {
    try {
        const url = new URL(String(value || ""));
        if (url.username || url.password || url.protocol !== "http:") {
            return null;
        }
        return url;
    } catch (error) {
        return null;
    }
}

function isAllowedAppOrigin(value, ports = DEFAULT_APP_PORTS) {
    const url = parseAppOrigin(value);
    if (!url || !LOOPBACK_HOSTS.has(url.hostname.toLowerCase())) {
        return false;
    }
    const allowedPorts = new Set(ports.map((port) => String(Number(port))));
    return allowedPorts.has(url.port);
}

function getRequestOrigin(request) {
    return request?.securityOrigin
        || request?.frame?.url
        || "";
}

function isTrustedDisplayMediaRequest(request, ports = DEFAULT_APP_PORTS) {
    return Boolean(
        request
        && request.userGesture === true
        && request.videoRequested !== false
        && isAllowedAppOrigin(getRequestOrigin(request), ports)
    );
}

function getClubGgTitleScore(name) {
    const title = String(name || "").trim();
    if (!title) {
        return 0;
    }
    if (/(?:alpha\s*poker|אלפא\s*פוקר|localhost|127\.0\.0\.1|\[::1\])/i.test(title)) {
        return 0;
    }
    if (/\b(?:NLH|PLO)\b/i.test(title)) {
        return 2;
    }
    if (/(?:Club\s*GG|GG\s*Club)/i.test(title)) {
        return 1;
    }
    return 0;
}

function isVisibleWindowSource(source) {
    if (!source || source.visible === false) {
        return false;
    }
    const thumbnail = source.thumbnail;
    if (thumbnail && typeof thumbnail.isEmpty === "function" && thumbnail.isEmpty()) {
        return false;
    }
    return true;
}

function selectClubGgWindowSource(sources) {
    let selected = null;
    let selectedScore = 0;
    for (const source of Array.isArray(sources) ? sources : []) {
        if (!isVisibleWindowSource(source)) {
            continue;
        }
        const score = getClubGgTitleScore(source.name);
        if (score > selectedScore) {
            selected = source;
            selectedScore = score;
        }
    }
    return selected;
}

module.exports = {
    DEFAULT_APP_PORTS,
    getClubGgTitleScore,
    getRequestOrigin,
    isAllowedAppOrigin,
    isTrustedDisplayMediaRequest,
    isVisibleWindowSource,
    selectClubGgWindowSource
};
