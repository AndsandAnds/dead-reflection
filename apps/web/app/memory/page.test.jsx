import { cleanup, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import MemoryPage from "./page";

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe("Memory page", () => {
    it("renders heading and calls inspect on mount", async () => {
        const fetchSpy = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ items: [] }),
        });
        globalThis.fetch = fetchSpy;

        render(<MemoryPage />);

        expect(screen.getByRole("heading", { name: /Memory/i })).toBeInTheDocument();

        // Wait until initial load fires.
        await screen.findByText(/\(no items\)/i);
        expect(fetchSpy).toHaveBeenCalled();
        expect(String(fetchSpy.mock.calls[0][0])).toMatch(/\/memory\/inspect$/);
    });
});


