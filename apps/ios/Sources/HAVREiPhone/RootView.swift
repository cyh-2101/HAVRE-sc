#if os(iOS)
import SwiftUI
import HAVREMobileCore

struct RootView: View {
    @Environment(AppModel.self) private var model
    @State private var voice = VoiceController()
    var body: some View {
        @Bindable var model = model
        NavigationStack {
            VStack {
                List(model.messages) { message in
                    VStack(alignment: .leading) {
                        Text(message.role == .owner ? "You" : "HAVRE").font(.caption)
                        Text(message.text)
                    }
                    .swipeActions { Button("Play") { model.speak(message.text) } }
                }
                Picker("Privacy", selection: $model.privacyClass) {
                    ForEach(PrivacyClass.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.menu)
                HStack {
                    TextField("Talk with HAVRE", text: $model.draft, axis: .vertical)
                    Button(voice.machine.state == .listening ? "Stop" : "Voice") {
                        Task {
                            if voice.machine.state == .listening {
                                if let text = voice.stopAfterOwnerTap() { model.draft = text }
                            } else {
                                await voice.startAfterOwnerTap()
                            }
                            model.voiceState = voice.machine.state
                        }
                    }
                        .accessibilityHint("Starts a user-initiated microphone session")
                    Button("Send") { Task { await model.send() } }
                }.padding()
            }
            .navigationTitle("HAVRE")
            .toolbar {
                NavigationLink("Scene") { SceneControlsView() }
                NavigationLink("Privacy") { EnrollmentView() }
            }
            .safeAreaInset(edge: .bottom) {
                Text(model.statusMessage).font(.caption).padding(.horizontal)
            }
        }
    }
}

struct SceneControlsView: View {
    @Environment(AppModel.self) private var model
    @State private var sceneID = ""
    @State private var revision = 1
    @State private var signal: SceneSignalType = .needHelp
    @State private var transition: SceneTransitionAction = .start
    @State private var reason = "owner action from iPhone"
    var body: some View {
        Form {
            Section("Low-bandwidth signal") {
                TextField("Existing Scene Session ID", text: $sceneID)
                Stepper("Expected revision: \(revision)", value: $revision, in: 1...100_000)
                Picker("Signal", selection: $signal) {
                    ForEach(SceneSignalType.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                }
                Button("Queue signal") {
                    guard let id = UUID(uuidString: sceneID) else { return }
                    Task { await model.enqueueSceneSignal(SceneSignalDraft(
                        sceneSessionID: id, expectedRevision: revision, signalType: signal
                    )) }
                }
                Picker("Transition", selection: $transition) {
                    ForEach(SceneTransitionAction.allCases, id: \.self) {
                        Text($0.rawValue).tag($0)
                    }
                }
                TextField("Reason", text: $reason)
                Button("Queue transition") {
                    guard let id = UUID(uuidString: sceneID), !reason.isEmpty else { return }
                    Task { await model.enqueueSceneTransition(SceneTransitionDraft(
                        sceneSessionID: id, expectedRevision: revision,
                        action: transition, reason: reason,
                        terminalStatus: transition == .close ? "completed" : nil
                    )) }
                }
                Text("Signals go to the existing Scene Session API and never create a second policy engine.")
                    .font(.footnote)
            }
        }.navigationTitle("Scene")
    }
}

struct EnrollmentView: View {
    @Environment(AppModel.self) private var model
    var body: some View {
        @Bindable var model = model
        Form {
            Section("Existing HAVRE Core") {
                TextField("https://owner-host", text: $model.baseURLText)
                    .textInputAutocapitalization(.never).keyboardType(.URL)
                SecureField("Owner bearer token", text: $model.bearerDraft)
                Button("Verify & enroll") { Task { await model.enroll() } }
                Button("Retry ordered queue") { Task { await model.resume() } }
            }
            Section("Privacy") {
                Text("Bearer credentials stay in the device-only Keychain. Queue/cache files are protected and excluded from backup.")
                Button("Enable notification actions") {
                    Task { await model.requestNotificationPermission() }
                }
                Picker("Lock-screen preview", selection: $model.notificationPreviewPolicy) {
                    ForEach(NotificationPreviewPolicy.allCases, id: \.self) {
                        Text($0.rawValue).tag($0)
                    }
                }
                if model.notificationPreviewPolicy == .ownerConfigured {
                    TextField("Owner-chosen generic text", text: $model.ownerNotificationText)
                }
                Button("Refresh authorized inbox") {
                    Task { await model.refreshNotificationInbox() }
                }
                ForEach(model.inboxItems) { item in
                    VStack(alignment: .leading) {
                        Text(item.previewText ?? "Private HAVRE inbox item").font(.caption)
                        HStack {
                            Button("Dismiss") { Task { _ = await queueAction(item, .dismissed) } }
                            Button("Snooze") { Task { _ = await queueAction(item, .snoozed) } }
                            Button("Stop") { Task { _ = await queueAction(item, .stopped) } }
                        }
                        TextField("Reply", text: Binding(
                            get: { model.replyDrafts.text(for: item.deliveryAttemptID) },
                            set: { model.replyDrafts.set($0, for: item.deliveryAttemptID) }
                        ))
                        Button("Send linked reply") {
                            let text = model.replyDrafts.text(for: item.deliveryAttemptID)
                                .trimmingCharacters(in: .whitespacesAndNewlines)
                            guard !text.isEmpty else { return }
                            Task {
                                if await queueAction(item, .responded, responseText: text) {
                                    _ = model.replyDrafts.take(for: item.deliveryAttemptID)
                                }
                            }
                        }
                    }
                }
                Text("This asks for local notification permission only. Remote APNs registration is not active.")
                    .font(.footnote)
                Text("The device setting may make a Core-authorized preview stricter, but cannot reveal full content when Core authorizes only a generic preview.")
                    .font(.footnote)
                Button("Erase local app data", role: .destructive) {
                    Task { await model.eraseLocalData() }
                }
            }
        }.navigationTitle("Connection & Privacy")
    }

    @MainActor private func queueAction(
        _ item: ProactiveInboxItem, _ action: DeliveryAction,
        responseText: String? = nil
    ) async -> Bool {
        let snooze = action == .snoozed ? Date().addingTimeInterval(3600) : nil
        return await model.enqueueDeliveryAction(QueuedDeliveryAction(
            link: DeliveryLink(
                proposalID: item.proposalID, deliveryAttemptID: item.deliveryAttemptID
            ),
            action: action, responseText: responseText, snoozeUntil: snooze
        ))
    }
}
#endif
