import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "./page";

vi.mock("next/navigation", () => ({
    useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

describe("Login page", () => {
    beforeEach(() => {
        globalThis.fetch = vi.fn().mockImplementation(async (url, opts) => {
            if (String(url).endsWith("/auth/me")) {
                return { ok: false, json: async () => ({}) };
            }
            if (String(url).endsWith("/auth/login")) {
                return {
                    ok: true,
                    json: async () => ({ user: { id: "u1", email: "e", name: "Once" } }),
                };
            }
            throw new Error(`Unhandled fetch: ${url} ${JSON.stringify(opts)}`);
        });
    });

    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it("renders Lumina login UI", () => {
        render(<LoginPage />);
        expect(
            screen.getByRole("heading", { name: /Welcome back/i })
        ).toBeInTheDocument();
        expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    });

    it("submits login", async () => {
        render(<LoginPage />);
        fireEvent.change(screen.getByLabelText(/Email/i), { target: { value: "a@b.com" } });
        fireEvent.change(screen.getByLabelText(/Password/i), { target: { value: "pw" } });
        fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
        // allow async
        await new Promise((r) => setTimeout(r, 0));
        expect(globalThis.fetch).toHaveBeenCalledWith(
            expect.stringMatching(/\/auth\/login$/),
            expect.objectContaining({ method: "POST", credentials: "include" })
        );
    });
});


