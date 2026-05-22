"use client";

export type RecentTurnRole = "user" | "assistant" | "system";

export type RecentTurn = {
  role: RecentTurnRole;
  content: string;
};

export type RecentConversation = {
  conversation_id: string | null;
  turns: RecentTurn[];
};

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

/**
 * Tail of the user's most-recent conversation for the active avatar.
 *
 * Used by /voice on mount so navigating away and back doesn't wipe the
 * transcript. Backed by the same `load_recent_context` service method
 * that the voice WS server uses to seed agent context — both code paths
 * are guaranteed to see the same window.
 */
export async function conversationsRecent(
  limit = 40
): Promise<RecentConversation> {
  const res = await fetch(`${apiBase()}/conversations/recent?limit=${limit}`, {
    credentials: "include",
    // Defeat any cache between us and the API so a freshly-finished
    // turn shows up on the very next navigation back to /voice.
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return await res.json();
}
