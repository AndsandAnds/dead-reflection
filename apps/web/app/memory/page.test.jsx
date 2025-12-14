import { cleanup, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MemoryPage from "./page";

vi.mock("next/navigation", () => ({
    useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe("Memory page", () => {
    it("renders heading and calls inspect on mount", async () => {
        const fetchSpy = vi.fn().mockImplementation(async (url) => {
            if (String(url).endsWith("/auth/me")) {
                return { ok: true, json: async () => ({ user: { id: "u1", email: "e", name: "Once" } }) };
            }
            if (String(url).endsWith("/memory/inspect")) {
                return { ok: true, json: async () => ({ items: [] }) };
            }
            throw new Error(`Unhandled fetch: ${url}`);
        });
        globalThis.fetch = fetchSpy;

        render(<MemoryPage />);

        expect(screen.getByRole("heading", { name: /Memory/i })).toBeInTheDocument();

        // Wait until initial load fires.
        await screen.findByText(/\(no items\)/i);
        expect(fetchSpy).toHaveBeenCalled();
        expect(
            fetchSpy.mock.calls.some((c) => String(c[0]).includes("/memory/inspect"))
        ).toBe(true);
    });
});


