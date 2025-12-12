import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import Home from "./page";

describe("Home page", () => {
    it("renders a heading", () => {
        render(<Home />);
        expect(
            screen.getByRole("heading", { name: /Reflections — Local Avatar AI/i }),
        ).toBeInTheDocument();
    });
});


