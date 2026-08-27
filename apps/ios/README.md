# HAVRE iPhone client

This Swift Package is the Stage 11 native entrance to the existing HAVRE API.
It does not contain a second personality, memory store, intervention policy, or
notification policy. Text and user-initiated voice become ordinary interaction
drafts; Scene controls call the existing Scene Session endpoints; notification
actions retain the original proposal and delivery-attempt identities.

Generate the native app project on a Mac with Xcode 16 and XcodeGen 2.42+:

```sh
cd apps/ios
xcodegen generate
xcodebuild -scheme HAVREiPhone -destination 'platform=iOS Simulator,name=iPhone 16' test
```

Then open `HAVREiPhone.xcodeproj`, select an iOS 17+ simulator/device, and run.
`Package.swift` separately keeps `HAVREMobileCore` buildable/testable on Linux.
Enrollment accepts only an owner-controlled HTTPS base URL; the bearer is stored
only in the device-bound Keychain. A versioned authenticated enrollment receipt
binds every protected queue/cache to one Core owner. The app quarantines all
transport until that binding is reverified on launch; switching owners requires
explicit local erasure first.

For an owner-local CA, install and explicitly trust only that owner-generated CA
profile on the test iPhone/simulator before enrollment. Do not disable App
Transport Security or add a catch-all trust handler to work around certificates.
The first connection to a LAN Core also uses iOS's narrowly declared Local
Network permission; the app does not browse Bonjour or discover unrelated hosts.

Voice starts only after an explicit tap. The app requests microphone and Speech
permissions at that point, requires on-device recognition, never implements a
wake word, and does not retain raw audio. If on-device recognition is unavailable,
voice fails closed instead of sending audio to a cloud speech service. Protected
queue/cache files use iOS file protection and are excluded from backup; the app
provides an explicit local-erasure control.

Remote APNs enrollment and production push transport are intentionally not
activated by this package: Apple processor eligibility, push credential
provisioning, and privacy-class routing require the Stage 11 Product Owner
privacy decision and real Apple signing environment. Local notification action
contracts remain linked and testable without inventing delivery authority.
Current Core inbox rows remain `simulation_only=true` and
`external_delivery_authorized=false`; the app may show their generic preview in
its own foreground inbox, but it schedules **zero** OS/lock-screen notifications.
The scheduler also checks both authorization flags, so local notifications cannot
turn Stage 6 simulation evidence into real delivery.

The checked-in project has no Push Notifications or background-audio entitlement.
Do not add either as a convenience workaround. A development candidate brain can
be used only behind the existing replaceable provider boundary; this client does
not name or hardcode any model or adapter.
