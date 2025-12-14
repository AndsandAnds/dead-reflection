"use client";

export type Avatar = {
    id: string;
    user_id: string;
    name: string;
    persona_prompt?: string | null;
    image_url?: string | null;
    voice_config?: Record<string, any> | null;
    created_at: string;
    updated_at: string;
};

function apiBase(): string {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export async function avatarsList(): Promise<{
    items: Avatar[];
    active_avatar_id: string | null;
}> {
    const res = await fetch(`${apiBase()}/avatars`, { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
}

export async function avatarsCreate(params: {
    name: string;
    persona_prompt?: string;
    image_url?: string;
    set_active?: boolean;
}): Promise<Avatar> {
    const res = await fetch(`${apiBase()}/avatars`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
}

export async function avatarsSetActive(avatar_id: string | null): Promise<void> {
    const res = await fetch(`${apiBase()}/avatars/active`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ avatar_id }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function avatarsDelete(avatar_id: string): Promise<void> {
    const res = await fetch(`${apiBase()}/avatars/delete`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ avatar_id }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function avatarsGenerateImage(
    avatar_id: string,
    params: {
        prompt: string;
        negative_prompt?: string;
        width?: number;
        height?: number;
        steps?: number;
        cfg_scale?: number;
        sampler_name?: string;
        seed?: number;
    }
): Promise<{ image_url: string }> {
    const res = await fetch(`${apiBase()}/avatars/${avatar_id}/generate-image`, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
}


