//
//  SupernoteObsidianSyncApp.swift
//  SupernoteObsidianSync
//

import SwiftUI
import AppKit

@main
struct SupernoteObsidianSyncApp: App {
    var body: some Scene {
        MenuBarExtra("Supernote Sync", systemImage: "note.text") {
            Button("Status") {
                CommandRunner.shared.runAndShow(["--status"], title: "Status")
            }

            Button("Run Sync Now") {
                CommandRunner.shared.runAndShow(["--once"], title: "Sync Result")
            }

            Button("Diagnose") {
                CommandRunner.shared.runAndShow(["--diagnose"], title: "Diagnostics")
            }

            Divider()

            Button("Open Settings") {
                CommandRunner.shared.runSilently(["--open-settings"])
            }

            Button("Open Log") {
                CommandRunner.shared.runSilently(["--open-log"])
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

    func runSilently(_ arguments: [String]) {
        _ = runCommand(arguments)
    }

    func runAndShow(_ arguments: [String], title: String) {
        let output = runCommand(arguments)
        showWindow(title: title, text: output)
    }

    private func runCommand(_ arguments: [String]) -> String {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/zsh")

        let quotedCLI = shellQuote(cliPath)
        let quotedArguments = arguments.map { shellQuote($0) }.joined(separator: " ")
        task.arguments = ["-lc", "\(quotedCLI) \(quotedArguments)"]

        let outputPipe = Pipe()
        let errorPipe = Pipe()

        task.standardOutput = outputPipe
        task.standardError = errorPipe

        do {
            try task.run()
            task.waitUntilExit()

            let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

            let output = String(data: outputData, encoding: .utf8) ?? ""
            let error = String(data: errorData, encoding: .utf8) ?? ""

            if task.terminationStatus == 0 {
                return output.isEmpty ? "Done." : output
            } else {
                return """
                Command failed.

                Exit code: \(task.terminationStatus)

                Command:
                \(cliPath) \(arguments.joined(separator: " "))

                Output:
                \(output)

                Error:
                \(error)
                """
            }
        } catch {
            return """
            Failed to run command.

            Command:
            \(cliPath) \(arguments.joined(separator: " "))

            Error:
            \(error)
            """
        }
    }

    private func showWindow(title: String, text: String) {
        let controller = OutputWindowController(title: title, text: text)
        windowControllers.append(controller)

        controller.onClose = { [weak self, weak controller] in
            guard let controller else { return }
            self?.windowControllers.removeAll { $0 === controller }
        }

        controller.showWindow(nil)
        controller.window?.makeKeyAndOrderFront(nil)
        controller.window?.display()
        NSApp.activate(ignoringOtherApps: true)
    }

    private func shellQuote(_ value: String) -> String {
        return "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }
}

final class OutputWindowController: NSWindowController, NSWindowDelegate {
    var onClose: (() -> Void)?

    private let textView: NSTextView

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

        DispatchQueue.main.async {
            self.textView.string = text
            self.textView.needsDisplay = true
            scrollView.needsDisplay = true
            window.contentView?.needsDisplay = true
            window.makeKeyAndOrderFront(nil)
            window.display()
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func windowWillClose(_ notification: Notification) {
        onClose?()
    }
}
