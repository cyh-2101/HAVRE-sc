#if os(iOS)
import SwiftUI
import HAVREMobileCore

@main
struct HAVREApp: App {
    @State private var model = AppModel()
    var body: some Scene {
        WindowGroup {
            RootView().environment(model).task { await model.resume() }
        }
    }
}
#endif

#if !os(iOS)
import Foundation

@main
struct UnsupportedHost {
    static func main() {
        print("HAVREiPhone requires iOS 17 or later; HAVREMobileCore is portable.")
    }
}
#endif
