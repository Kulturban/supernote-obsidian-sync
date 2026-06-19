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

    // Direct Homebrew Cellar path for now.
    // Later we can make this auto-detect /opt/homebrew/bin, /usr/local/bin, etc.
    private let cliPath = "/opt/homebrew/Cellar/supernote-obsidian-sync/0.5.0/bin/supernote-obsidian-sync"

    private var outputWindow: NSWindow?

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

        // Run through zsh so macOS can execute the Homebrew CLI more reliably.
        task.executableURL = URL(fileURLWithPath: "/bin/zsh")
        task.arguments = ["-lc", "\(cliPath) \(arguments.joined(separator: " "))"]

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
        let textView = NSTextView(frame: NSRect(x: 0, y: 0, width: 760, height: 520))
        textView.string = text
        textView.isEditable = false
        textView.font = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        textView.textContainerInset = NSSize(width: 16, height: 16)

        let scrollView = NSScrollView(frame: NSRect(x: 0, y: 0, width: 760, height: 520))
        scrollView.documentView = textView
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = true

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 520),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = title
        window.contentView = scrollView
        window.center()
        window.makeKeyAndOrderFront(nil)

        NSApp.activate(ignoringOtherApps: true)

        self.outputWindow = window
    }
}
