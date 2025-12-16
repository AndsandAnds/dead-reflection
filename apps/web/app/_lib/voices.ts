"use client";

function apiBase(): string {
    return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

export type VoicesList = {
    engine: string | null;
    configured: boolean;
    voices: string[];
};

export async function voiceListVoices(): Promise<VoicesList> {
    const res = await fetch(`${apiBase()}/voice/voices`, { credentials: "include" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return {
        engine: data?.engine ?? null,
        configured: Boolean(data?.configured),
        voices: Array.isArray(data?.voices) ? data.voices.map(String) : [],
    };
}


