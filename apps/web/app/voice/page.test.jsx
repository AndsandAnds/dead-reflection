import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VoicePage from "./page";

vi.mock("next/navigation", () => ({
    useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

let wsSends = [];
let lastWsUrl = null;

class MockWebSocket {
    static OPEN = 1;
    constructor(url) {
        lastWsUrl = url;
        this.url = url;
        this.readyState = MockWebSocket.OPEN;
        this.bufferedAmount = 0;
        this.onopen = null;
        this.onmessage = null;
        this.onerror = null;
        this.onclose = null;
        globalThis.__lastWs = this;
        setTimeout(() => this.onopen && this.onopen(), 0);
    }
    send(data) {
        wsSends.push(data);
    }
    close() {
        this.readyState = 3;
        this.onclose && this.onclose();
    }
}

class MockAudioContext {
    constructor() {
        this.sampleRate = 48000;
        this.currentTime = 0;
        this.destination = {};
        this.audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) };
    }
    createMediaStreamSource() {
        return { connect: vi.fn(), disconnect: vi.fn() };
    }
    createAnalyser() {
        return {
            fftSize: 1024,
            connect: vi.fn(),
            getFloatTimeDomainData: vi.fn((arr) => arr.fill(0)),
        };
    }
    createGain() {
        return {
            gain: {
                value: 1.0,
                setValueAtTime: vi.fn(),
                linearRampToValueAtTime: vi.fn(),
            },
            connect: vi.fn(),
        };
    }
    createOscillator() {
        return {
            type: "sine",
            frequency: { value: 0 },
            connect: vi.fn(),
            start: vi.fn(),
            stop: vi.fn(),
        };
    }
    close() {
        // noop
    }
}

class MockAudioWorkletNode {
    constructor() {
        this.port = { onmessage: null };
        // expose for tests
        globalThis.__lastWorklet = this;
    }
    disconnect() {
        // noop
    }
}

beforeEach(() => {
    wsSends = [];
    lastWsUrl = null;
    globalThis.WebSocket = MockWebSocket;
    globalThis.AudioContext = MockAudioContext;
    globalThis.AudioWorkletNode = MockAudioWorkletNode;
    globalThis.fetch = vi.fn().mockImplementation(async (url) => {
        if (String(url).endsWith("/auth/me")) {
            return {
                ok: true,
                json: async () => ({ user: { id: "u1", email: "e", name: "Once" } }),
            };
        }
        throw new Error(`Unhandled fetch: ${url}`);
    });
    globalThis.requestAnimationFrame = () => 1;
    globalThis.cancelAnimationFrame = () => { };
    globalThis.navigator.mediaDevices = {
        getUserMedia: vi.fn().mockResolvedValue({
            getTracks: () => [{ stop: vi.fn() }],
        }),
    };
});

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    try {
        delete globalThis.__lastWorklet;
        delete globalThis.__lastWs;
    } catch {
        // ignore
    }
});

describe("Voice page", () => {
    it("renders a heading", () => {
        render(<VoicePage />);
        expect(
            screen.getByRole("heading", { name: /Lumina|Voice/i })
        ).toBeInTheDocument();
    });

    it("opens a WS and sends hello + binary audio frames", async () => {
        render(<VoicePage />);
        fireEvent.click(screen.getAllByRole("button", { name: /Start mic/i })[0]);

        // allow ws onopen + async start() to run
        await new Promise((r) => setTimeout(r, 0));

        expect(lastWsUrl).toMatch(/\/ws\/voice$/);
        const jsonMsgs = wsSends
            .filter((x) => typeof x === "string")
            .map((x) => JSON.parse(x));
        expect(jsonMsgs.some((m) => m.type === "cancel")).toBe(true);
        expect(jsonMsgs.some((m) => m.type === "hello")).toBe(true);

        // simulate a mic frame
        const worklet = globalThis.__lastWorklet;
        expect(worklet).toBeTruthy();
        worklet.port.onmessage({ data: new Float32Array([0.25, -0.25, 0]) });

        const hasBinary = wsSends.some((x) => x instanceof ArrayBuffer);
        expect(hasBinary).toBe(true);
    });

    it("auto-sends end after sustained silence", async () => {
        const nowSpy = vi.spyOn(performance, "now");
        let t = 0;
        nowSpy.mockImplementation(() => t);

        render(<VoicePage />);
        fireEvent.click(screen.getAllByRole("button", { name: /Start mic/i })[0]);
        // Wait until the UI has entered "running" so the statusRef is updated.
        await screen.findByRole("button", { name: /Stop \(transcribe\)/i });

        // Make handler think time has passed and audio is silent.
        const worklet = globalThis.__lastWorklet;
        t = 2000;
        worklet.port.onmessage({ data: new Float32Array([0, 0, 0, 0]) });
        // Re-deliver silence quickly; should not send a second "end".
        t = 2100;
        worklet.port.onmessage({ data: new Float32Array([0, 0, 0, 0]) });

        const endCount = wsSends
            .filter((x) => typeof x === "string")
            .map((x) => JSON.parse(x))
            .filter((m) => m.type === "end").length;
        expect(endCount).toBe(1);
        nowSpy.mockRestore();
    });

    it("push-to-talk: Space starts mic, Space release stops/transcribes", async () => {
        render(<VoicePage />);

        // Press Space to start.
        fireEvent.keyDown(window, { code: "Space" });
        await screen.findByRole("button", { name: /Stop \(transcribe\)/i });

        // Release Space to stop -> should send end exactly once.
        fireEvent.keyUp(window, { code: "Space" });

        const endCount = wsSends
            .filter((x) => typeof x === "string")
            .map((x) => JSON.parse(x))
            .filter((m) => m.type === "end").length;
        expect(endCount).toBe(1);
    });

    it("does not duplicate assistant messages when deltas are followed by final", async () => {
        render(<VoicePage />);
        // connect socket
        fireEvent.click(screen.getAllByRole("button", { name: /Start mic/i })[0]);
        await new Promise((r) => setTimeout(r, 0));

        const ws = globalThis.__lastWs;
        expect(ws).toBeTruthy();

        // Simulate streaming deltas then final assistant message.
        ws.onmessage({ data: JSON.stringify({ type: "assistant_delta", delta: "Hello" }) });
        ws.onmessage({ data: JSON.stringify({ type: "assistant_delta", delta: " world" }) });
        ws.onmessage({ data: JSON.stringify({ type: "assistant_message", text: "Hello world" }) });

        await screen.findByText("Hello world");
        const matches = screen.getAllByText("Hello world");
        expect(matches.length).toBe(1);
    });

    it("does not duplicate assistant messages when final is repeated", async () => {
        render(<VoicePage />);
        // connect socket
        fireEvent.click(screen.getAllByRole("button", { name: /Start mic/i })[0]);
        await new Promise((r) => setTimeout(r, 0));

        const ws = globalThis.__lastWs;
        expect(ws).toBeTruthy();

        ws.onmessage({ data: JSON.stringify({ type: "assistant_message", text: "Same" }) });
        ws.onmessage({ data: JSON.stringify({ type: "assistant_message", text: "Same" }) });

        await screen.findByText("Same");
        expect(screen.getAllByText("Same").length).toBe(1);
    });
});


