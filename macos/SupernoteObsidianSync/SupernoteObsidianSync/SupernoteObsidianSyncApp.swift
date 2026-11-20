//
//  SupernoteObsidianSyncApp.swift
//  SupernoteObsidianSync
//

import SwiftUI
import Combine
import AppKit


struct MenuSetupStatusView: View {
    @StateObject private var model = SettingsViewModel()
    private let refreshTimer = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if model.setupReady {
                Button("✅ Ready to sync") {
                    SettingsWindowController.shared.showSetup()
                }
            } else {
                Button("⚠️ Not ready to sync — Open Setup…") {
                    SettingsWindowController.shared.showSetup()
                }

                if let step = model.nextSetupStep {
                    Text("Next: \(step.title)")
                }
            }
        }
        .onAppear {
            model.load()
        }
        .onReceive(refreshTimer) { _ in
            model.load()
        }
    }
}

@main
struct SupernoteObsidianSyncApp: App {
    var body: some Scene {
        MenuBarExtra("Supsidian", systemImage: "long.text.page.and.pencil") {
            MenuSetupStatusView()

            Divider()

            Button("Sync Now") {
                let model = SettingsViewModel()

                if model.setupReady {
                    CommandRunner.shared.runSyncNow(model: model)
                } else {
                    SettingsWindowController.shared.showSetup()
                }
            }

            Button("Settings…") {
                SettingsWindowController.shared.show()
            }

            Divider()

            Button("Check for Updates…") {
                if let url = URL(string: "https://github.com/Kulturban/supernote-obsidian-sync/releases") {
                    NSWorkspace.shared.open(url)
                }
            }

            Divider()

            Button("Status") {
                CommandRunner.shared.runAndShow(["--status"], title: "Status")
            }

            Button("Diagnose") {
                CommandRunner.shared.runAndShow(["--diagnose"], title: "Diagnostics")
            }

            Button("Log") {
                CommandRunner.shared.runSilently(["--open-log"], title: "Open Log")
            }

            Divider()

            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
        }
    }
}

@MainActor
final class CommandRunner {
    static let shared = CommandRunner()

    private let cliPath = "/opt/homebrew/bin/supernote-obsidian-sync"
    private var windowControllers: [OutputWindowController] = []

    private init() {}

    private func initialOutput(for arguments: [String], title: String) -> String {
        let command = "\(cliPath) \(arguments.joined(separator: " "))"

        if arguments.contains("--once") {
            return """
            Sync Now

            Looking for changed Supernote notes…
            This can take a moment if OCR is needed.

            Please wait until the result appears.

            Command:
            \(command)
            """
        }

        if arguments.contains("--diagnose") {
            return """
            Diagnostics

            Checking your setup…
            Please wait.

            Command:
            \(command)
            """
        }

        if arguments.contains("--status") {
            return """
            Status

            Checking current sync status…
            Please wait.

            Command:
            \(command)
            """
        }

        return """
        Running command…

        \(command)
        """
    }

    func runAndShow(_ arguments: [String], title: String) {
        let outputWindow = OutputWindowController.show(
            title: title,
            output: initialOutput(for: arguments, title: title)
        )

        Task {
            let result = await CommandRunner.runCommand(
                executablePath: cliPath,
                arguments: arguments
            )

            await MainActor.run {
                outputWindow.update(text: result.displayText)
            }
        }
    }

    func runSyncNow(model: SettingsViewModel) {
        let shouldOpenPartner = model.openSupernotePartnerBeforeSync
        let partnerApp = model.supernotePartnerApp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Supernote Partner"
            : model.supernotePartnerApp.trimmingCharacters(in: .whitespacesAndNewlines)
        let parsedDelay = Int(model.supernotePartnerSyncDelaySeconds.trimmingCharacters(in: .whitespacesAndNewlines))
        let delaySeconds: Int
        if let parsedDelay,
           parsedDelay > 0,
           !UInt64(parsedDelay).multipliedReportingOverflow(by: 1_000_000_000).overflow {
            delaySeconds = parsedDelay
        } else {
            delaySeconds = 15
        }
        let syncRunningOutput = initialOutput(for: ["--once"], title: "Sync Now")

        let outputWindow = OutputWindowController.show(
            title: "Sync Now",
            output: syncRunningOutput
        )

        Task {
            if shouldOpenPartner {
                await MainActor.run {
                    outputWindow.update(text: """
                    Sync Now

                    Opening Supernote Partner…
                    App/path:
                    \(partnerApp)

                    Waiting \(delaySeconds) second(s) before Supsidian sync starts.
                    """)
                }

                let openResult = await CommandRunner.openApplicationOrPath(partnerApp)
                if !openResult.succeeded {
                    await MainActor.run {
                        outputWindow.update(text: openResult.displayText)
                    }
                    return
                }

                let (sleepNanoseconds, overflow) = UInt64(delaySeconds).multipliedReportingOverflow(by: 1_000_000_000)
                if !overflow && sleepNanoseconds > 0 {
                    do {
                        try await Task.sleep(nanoseconds: sleepNanoseconds)
                    } catch {
                        return
                    }
                }

                guard !Task.isCancelled else { return }

                await MainActor.run {
                    outputWindow.update(text: syncRunningOutput)
                }
            }

            let result = await CommandRunner.runCommand(
                executablePath: cliPath,
                arguments: ["--once"]
            )

            await MainActor.run {
                outputWindow.update(text: result.displayText)
            }
        }
    }

    func runSilently(_ arguments: [String], title: String) {
        Task {
            let result = await CommandRunner.runCommand(
                executablePath: cliPath,
                arguments: arguments
            )

            if !result.succeeded {
                showWindow(title: title, text: result.displayText)
            }
        }
    }

    @discardableResult
    private func showWindow(title: String, text: String) -> OutputWindowController {
        let controller = OutputWindowController(title: title, text: text)
        windowControllers.append(controller)

        controller.onClose = { [weak self, weak controller] in
            guard let controller else { return }
            self?.windowControllers.removeAll { $0 === controller }
        }

        controller.show()
        NSApp.activate(ignoringOtherApps: true)

        return controller
    }

    private func commandDescription(_ arguments: [String]) -> String {
        "\(cliPath) \(arguments.joined(separator: " "))"
    }

    private nonisolated static func openApplicationOrPath(_ appOrPath: String) async -> CommandResult {
        let trimmed = appOrPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let arguments: [String]

        if trimmed.contains("/") || trimmed.hasPrefix("~") {
            let expandedPath = (trimmed as NSString).expandingTildeInPath
            var isDirectory: ObjCBool = false
            let exists = FileManager.default.fileExists(atPath: expandedPath, isDirectory: &isDirectory)

            if exists && isDirectory.boolValue && !expandedPath.lowercased().hasSuffix(".app") {
                arguments = ["-a", expandedPath]
            } else {
                arguments = [expandedPath]
            }
        } else {
            arguments = ["-a", trimmed]
        }

        return await runCommand(
            executablePath: "/usr/bin/open",
            arguments: arguments
        )
    }

    private nonisolated static func stripProgressLines(from output: String) -> String {
        output
            .split(separator: "\n", omittingEmptySubsequences: false)
            .filter { !$0.hasPrefix("SUSPIDIAN_PROGRESS:") }
            .joined(separator: "\n")
    }

    private nonisolated static func runCommand(
        executablePath: String,
        arguments: [String]
    ) async -> CommandResult {
        await Task.detached(priority: .userInitiated) {
            let executableURL = URL(fileURLWithPath: executablePath)

            guard FileManager.default.isExecutableFile(atPath: executablePath) else {
                return CommandResult(
                    succeeded: false,
                    displayText: """
                    Command not found or not executable.

                    Expected CLI path:
                    \(executablePath)

                    Try reinstalling with Homebrew:
                    brew reinstall kulturban/supernote-obsidian-sync/supernote-obsidian-sync
                    """
                )
            }

            let task = Process()
            task.executableURL = executableURL
            task.arguments = arguments

            let outputPipe = Pipe()
            let errorPipe = Pipe()

            task.standardOutput = outputPipe
            task.standardError = errorPipe

            do {
                try task.run()

                let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
                let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
                task.waitUntilExit()

                let rawOutput = String(data: outputData, encoding: .utf8) ?? ""
                let output = stripProgressLines(from: rawOutput)
                let error = String(data: errorData, encoding: .utf8) ?? ""

                if task.terminationStatus == 0 {
                    let text = output.trimmingCharacters(in: .whitespacesAndNewlines)

                    return CommandResult(
                        succeeded: true,
                        displayText: text.isEmpty ? "Done." : output
                    )
                }

                return CommandResult(
                    succeeded: false,
                    displayText: """
                    Command failed.

                    Exit code:
                    \(task.terminationStatus)

                    Command:
                    \(executablePath) \(arguments.joined(separator: " "))

                    Output:
                    \(output)

                    Error:
                    \(error)
                    """
                )
            } catch {
                return CommandResult(
                    succeeded: false,
                    displayText: """
                    Failed to run command.

                    Command:
                    \(executablePath) \(arguments.joined(separator: " "))

                    Error:
                    \(error.localizedDescription)
                    """
                )
            }
        }.value
    }
}

struct CommandResult {
    let succeeded: Bool
    let displayText: String
}

@MainActor
final class OutputWindowController: NSWindowController, NSWindowDelegate {
    private static var openControllers: [OutputWindowController] = []

    static func show(title: String, output: String) -> OutputWindowController {
        let controller = OutputWindowController(title: title, text: output)

        openControllers.append(controller)

        controller.onClose = { [weak controller] in
            guard let controller else { return }
            openControllers.removeAll { $0 === controller }
        }

        controller.showWindow(nil)
        NSApp.activate(ignoringOtherApps: true)

        return controller
    }

    var onClose: (() -> Void)?

    private let textView: NSTextView

    func update(text: String) {
        textView.string = text
    }

    init(title: String, text: String) {
        let scrollView = NSTextView.scrollableTextView()

        guard let textView = scrollView.documentView as? NSTextView else {
            fatalError("Could not create text view")
        }

        self.textView = textView

        textView.string = text
        textView.isEditable = false
        textView.isSelectable = true
        textView.font = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        textView.textContainerInset = NSSize(width: 16, height: 16)

        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = true
        scrollView.autohidesScrollers = false

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 520),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = title
        window.contentView = scrollView
        window.center()

        super.init(window: window)

        window.delegate = self
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func show() {
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        window?.display()
    }

    func updateText(_ text: String) {
        textView.string = text
        textView.scrollToBeginningOfDocument(nil)
        textView.needsDisplay = true

        window?.contentView?.needsDisplay = true
        window?.display()
        window?.makeKeyAndOrderFront(nil)

        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }
}
