// AudioWorkletProcessor for capturing mono Float32 PCM frames from the mic.
// This runs on the audio rendering thread; it posts frames to the main thread.

class MicCaptureProcessor extends AudioWorkletProcessor {
    process(inputs) {
        const input = inputs[0];
        if (input && input[0]) {
            // Copy the channel data so it remains valid after this callback returns.
            const frame = new Float32Array(input[0]);
            this.port.postMessage(frame);
        }
        return true;
    }
}

registerProcessor("mic-capture", MicCaptureProcessor);


