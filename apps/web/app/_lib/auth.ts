export type AuthUser = {
    id: string;
    email: string;
    name: string;
    active_avatar_id?: string | null;
};

function apiBase(): string {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function readApiErrorMessage(res: Response): Promise<string> {
    // Best-effort parse of FastAPI error payloads.
    try {
        const data: any = await res.json();
        const detail =
            data?.detail ??
            data?.message ??
            data?.exception?.details ??
            data?.exception?.message ??
            null;
        if (detail) return String(detail);
    } catch {
        // ignore
    }
    return res.statusText || "request_failed";
}

export async function authMe(): Promise<AuthUser | null> {
    try {
        const res = await fetch(`${apiBase()}/auth/me`, { credentials: "include" });
        if (!res.ok) return null;
        const data = await res.json();
        return data?.user ?? null;
    } catch {
        // Network error (API down / wrong NEXT_PUBLIC_API_BASE_URL / CORS handshake issues).
        // Treat as unauthenticated to avoid crashing pages.
        return null;
    }
}

export async function authLogin(params: {
    email: string;
    password: string;
}): Promise<AuthUser> {
    const res = await fetch(`${apiBase()}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
    });
    if (!res.ok) {
        const msg = await readApiErrorMessage(res);
        throw new Error(`HTTP ${res.status}: ${msg}`);
    }
    const data = await res.json();
    return data.user;
}

export async function authSignup(params: {
    name: string;
    email: string;
    password: string;
}): Promise<AuthUser> {
    const res = await fetch(`${apiBase()}/auth/signup`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
    });
    if (!res.ok) {
        const msg = await readApiErrorMessage(res);
        throw new Error(`HTTP ${res.status}: ${msg}`);
    }
    const data = await res.json();
    return data.user;
}

export async function authLogout(): Promise<void> {
    await fetch(`${apiBase()}/auth/logout`, {
        method: "POST",
        credentials: "include",
    });
}


