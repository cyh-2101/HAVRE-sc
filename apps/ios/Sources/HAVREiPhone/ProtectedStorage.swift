#if os(iOS)
import Foundation
import Security
import HAVREMobileCore

enum ProtectedStorage {
    private static let keychainService = "local.havre.iphone"
    static var queueURL: URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return root.appendingPathComponent("HAVRE", isDirectory: true)
            .appendingPathComponent("offline-queue.json")
    }
    static var messageCacheURL: URL {
        queueURL.deletingLastPathComponent().appendingPathComponent("messages.json")
    }
    static var enrollmentURL: URL {
        queueURL.deletingLastPathComponent().appendingPathComponent("enrollment.json")
    }

    static func writeCache(_ data: Data, to url: URL) throws {
        try FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        var mutable = url; try mutable.setResourceValues(values)
    }

    static func storeBearer(_ data: Data, account: String) throws {
        SecItemDelete([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: account,
        ] as CFDictionary)
        let status = SecItemAdd([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: account,
            kSecValueData: data,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ] as CFDictionary, nil)
        guard status == errSecSuccess else { throw NSError(domain: NSOSStatusErrorDomain, code: Int(status)) }
    }

    static func bearer(account: String) throws -> Data {
        var result: CFTypeRef?
        let status = SecItemCopyMatching([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ] as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(status))
        }
        return data
    }

    static func eraseAll(account: String) throws {
        let keychainStatus = SecItemDelete([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: keychainService,
            kSecAttrAccount: account,
        ] as CFDictionary)
        guard keychainStatus == errSecSuccess || keychainStatus == errSecItemNotFound else {
            throw NSError(domain: NSOSStatusErrorDomain, code: Int(keychainStatus))
        }
        var removalError: Error?
        for url in [queueURL, messageCacheURL, enrollmentURL]
        where FileManager.default.fileExists(atPath: url.path) {
            do { try FileManager.default.removeItem(at: url) }
            catch { removalError = removalError ?? error }
        }
        if let removalError { throw removalError }
    }
}

struct KeychainTokenSource: BearerTokenSource {
    let account: String
    func token() async throws -> String {
        guard let value = String(data: try ProtectedStorage.bearer(account: account), encoding: .utf8),
              !value.isEmpty else { throw URLError(.userAuthenticationRequired) }
        return value
    }
}

struct EphemeralTokenSource: BearerTokenSource {
    let value: String
    func token() async throws -> String { value }
}
#endif
