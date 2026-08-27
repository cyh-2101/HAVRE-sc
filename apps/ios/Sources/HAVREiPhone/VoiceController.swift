#if os(iOS)
import AVFoundation
import Speech
import Observation
import HAVREMobileCore

@MainActor @Observable
final class VoiceController {
    private let recognizer = SFSpeechRecognizer()
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var tapInstalled = false
    private var stoppingIntentionally = false
    private(set) var machine = VoiceSessionMachine()
    private(set) var transcript = ""
    private(set) var failureMessage: String?

    func startAfterOwnerTap() async {
        guard machine.state != .listening,
              machine.state != .transcribing,
              machine.state != .requestingPermission else { return }
        transcript = ""; failureMessage = nil
        machine.ownerTappedStart()
        guard machine.state == .requestingPermission else { return }
        stoppingIntentionally = false
        let speech = await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0) }
        }
        let mic = await withCheckedContinuation { continuation in
            AVAudioSession.sharedInstance().requestRecordPermission {
                continuation.resume(returning: $0)
            }
        }
        guard speech == .authorized, mic else {
            machine.permissionResult(granted: false)
            failureMessage = "Microphone and Speech permission are required."
            return
        }
        guard recognizer?.supportsOnDeviceRecognition == true else {
            machine.permissionResult(granted: false)
            failureMessage = "On-device transcription is unavailable; cloud speech is not authorized."
            return
        }
        machine.permissionResult(granted: true)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = true
        self.request = request
        let input = engine.inputNode
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) {
            buffer, _ in request.append(buffer)
        }
        tapInstalled = true
        task = recognizer?.recognitionTask(with: request) { [weak self] result, error in
            Task { @MainActor in
                if let result { self?.transcript = result.bestTranscription.formattedString }
                if error != nil, self?.stoppingIntentionally == false {
                    self?.stopCapture(); self?.machine.fail()
                    self?.failureMessage = "Transcription stopped unexpectedly."
                }
            }
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            engine.prepare(); try engine.start()
        } catch {
            stopCapture()
            machine.reset(); failureMessage = "Microphone session could not start."
        }
    }

    func stopAfterOwnerTap() -> String? {
        machine.ownerTappedStop()
        stoppingIntentionally = true
        stopCapture()
        machine.transcript(transcript)
        if case let .ready(text) = machine.state { return text }
        return nil
    }

    func reset() {
        stoppingIntentionally = true
        stopCapture(); transcript = ""; failureMessage = nil; machine.reset()
    }

    private func stopCapture() {
        if engine.isRunning { engine.stop() }
        if tapInstalled { engine.inputNode.removeTap(onBus: 0); tapInstalled = false }
        request?.endAudio(); task?.cancel(); request = nil; task = nil
        try? AVAudioSession.sharedInstance().setActive(
            false, options: .notifyOthersOnDeactivation
        )
    }
}
#endif
