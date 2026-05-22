"use client";

export type MemoryKind = "card" | "chunk";
export type MemoryScope = "user" | "avatar";
export type EntityKind = "person" | "place" | "event" | "topic" | "org";

export type LinkedEntity = {
  id: string;
  kind: EntityKind;
  name: string;
  slug: string;
};

export type Memory = {
  id: string;
  user_id: string;
  avatar_id: string | null;
  scope: MemoryScope;
  kind: MemoryKind;
  content: string;
  created_at: string;
  linked_entities: LinkedEntity[];
};

export type Entity = {
  id: string;
  user_id: string;
  kind: EntityKind;
  name: string;
  slug: string;
  description: string | null;
  attributes: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type GraphNode = {
  id: string; // memory:<uuid> | entity:<uuid>
  kind: string; // memory_card | memory_chunk | entity_person | ...
  label: string;
};

export type GraphEdge = {
  source: string;
  target: string;
  relation: string;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

function apiBase(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
}

async function jsonOrThrow(res: Response): Promise<any> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j?.detail ?? j?.message ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`HTTP ${res.status}: ${detail}`);
  }
  return await res.json();
}

export type SearchFilters = {
  query: string;
  user_id: string;
  top_k?: number;
  include_cards?: boolean;
  include_chunks?: boolean;
  entity_ids?: string[];
  date_from?: string; // ISO 8601
  date_to?: string; // ISO 8601
};

export async function memorySearch(
  filters: SearchFilters
): Promise<{ items: Memory[] }> {
  const res = await fetch(`${apiBase()}/memory/search`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(filters),
  });
  return await jsonOrThrow(res);
}

export async function memoryInspect(
  user_id: string,
  opts: { limit?: number; offset?: number; kind?: MemoryKind | "any" } = {}
): Promise<{ items: Memory[] }> {
  const include_cards = opts.kind !== "chunk";
  const include_chunks = opts.kind !== "card";
  const res = await fetch(`${apiBase()}/memory/inspect`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      user_id,
      limit: opts.limit ?? 50,
      offset: opts.offset ?? 0,
      include_cards,
      include_chunks,
    }),
  });
  return await jsonOrThrow(res);
}

export async function memoryPatch(
  memory_id: string,
  content: string
): Promise<Memory> {
  const res = await fetch(`${apiBase()}/memory/${memory_id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return await jsonOrThrow(res);
}

export async function memoryDelete(
  user_id: string,
  ids: string[]
): Promise<{ deleted_count: number }> {
  const res = await fetch(`${apiBase()}/memory/delete`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ user_id, ids }),
  });
  return await jsonOrThrow(res);
}

export async function memoryGraph(
  params: {
    date_from?: string;
    date_to?: string;
    entity_id?: string;
    limit_memories?: number;
  } = {}
): Promise<GraphResponse> {
  const qs = new URLSearchParams();
  if (params.date_from) qs.set("date_from", params.date_from);
  if (params.date_to) qs.set("date_to", params.date_to);
  if (params.entity_id) qs.set("entity_id", params.entity_id);
  if (params.limit_memories)
    qs.set("limit_memories", String(params.limit_memories));
  const url = `${apiBase()}/memory/graph${qs.size ? `?${qs.toString()}` : ""}`;
  const res = await fetch(url, { credentials: "include" });
  return await jsonOrThrow(res);
}

// ---- Entities ----

export async function entitiesList(opts: {
  kind?: EntityKind;
  limit?: number;
  offset?: number;
} = {}): Promise<{ items: Entity[] }> {
  const qs = new URLSearchParams();
  if (opts.kind) qs.set("kind", opts.kind);
  if (opts.limit !== undefined) qs.set("limit", String(opts.limit));
  if (opts.offset !== undefined) qs.set("offset", String(opts.offset));
  const url = `${apiBase()}/entities${qs.size ? `?${qs.toString()}` : ""}`;
  const res = await fetch(url, { credentials: "include" });
  return await jsonOrThrow(res);
}

export async function entityGet(entity_id: string): Promise<Entity> {
  const res = await fetch(`${apiBase()}/entities/${entity_id}`, {
    credentials: "include",
  });
  return await jsonOrThrow(res);
}

export async function entityCreate(params: {
  kind: EntityKind;
  name: string;
  description?: string | null;
}): Promise<Entity> {
  const res = await fetch(`${apiBase()}/entities`, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return await jsonOrThrow(res);
}

export async function entityUpdate(
  entity_id: string,
  params: { name?: string; description?: string | null }
): Promise<Entity> {
  const res = await fetch(`${apiBase()}/entities/${entity_id}`, {
    method: "PATCH",
    credentials: "include",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return await jsonOrThrow(res);
}

export async function entityDelete(entity_id: string): Promise<void> {
  const res = await fetch(`${apiBase()}/entities/${entity_id}`, {
    method: "DELETE",
    credentials: "include",
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function entityMemories(
  entity_id: string,
  limit = 100
): Promise<{ memory_ids: string[] }> {
  const res = await fetch(
    `${apiBase()}/entities/${entity_id}/memories?limit=${limit}`,
    { credentials: "include" }
  );
  return await jsonOrThrow(res);
}
