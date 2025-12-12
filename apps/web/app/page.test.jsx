import { render } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({
    redirect: (path) => redirectMock(path),
}));

import Home from "./page";

describe("Home page", () => {
    it("redirects to /voice", () => {
        render(<Home />);
        expect(redirectMock).toHaveBeenCalledWith("/voice");
    });
});


