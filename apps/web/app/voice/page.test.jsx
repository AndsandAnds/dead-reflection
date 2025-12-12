import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VoicePage from "./page";

describe("Voice page", () => {
    it("renders a heading", () => {
        render(<VoicePage />);
        expect(screen.getByRole("heading", { name: /Voice/i })).toBeInTheDocument();
    });
});


