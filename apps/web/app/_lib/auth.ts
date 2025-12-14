export type AuthUser = {
    id: string;
    email: string;
    name: string;
    active_avatar_id?: string | null;
};

function apiBase(): string {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export async function authMe(): Promise<AuthUser | null> {
    const res = await fetch(`${apiBase()}/auth/me`, { credentials: "include" });
    if (!res.ok) return null;
    const data = await res.json();
    return data?.user ?? null;
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data.user;
}

export async function authLogout(): Promise<void> {
    await fetch(`${apiBase()}/auth/logout`, {
        method: "POST",
        credentials: "include",
    });
}


