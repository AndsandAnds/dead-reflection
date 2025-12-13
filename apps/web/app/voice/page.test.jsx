import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VoicePage from "./page";

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
    } catch {
        // ignore
    }
});

describe("Voice page", () => {
    it("renders a heading", () => {
        render(<VoicePage />);
        expect(screen.getByRole("heading", { name: /Voice/i })).toBeInTheDocument();
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
        nowSpy.mockReturnValueOnce(0); // startedMsRef

        render(<VoicePage />);
        fireEvent.click(screen.getAllByRole("button", { name: /Start mic/i })[0]);
        // Wait until the UI has entered "running" so the statusRef is updated.
        await screen.findByRole("button", { name: /Stop \(transcribe\)/i });

        // Make handler think time has passed and audio is silent.
        nowSpy.mockReturnValueOnce(2000);
        const worklet = globalThis.__lastWorklet;
        worklet.port.onmessage({ data: new Float32Array([0, 0, 0, 0]) });

        const endMsg = wsSends
            .filter((x) => typeof x === "string")
            .map((x) => JSON.parse(x))
            .find((m) => m.type === "end");
        expect(endMsg).toBeTruthy();
        nowSpy.mockRestore();
    });
});


