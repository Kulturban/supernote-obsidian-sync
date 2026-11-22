//
//  SupernoteObsidianSyncApp.swift
//  SupernoteObsidianSync
//

import SwiftUI
import Combine
import AppKit


struct MenuSetupStatusView: View {
    @StateObject private var model = SettingsViewModel()
    @ObservedObject private var runner = CommandRunner.shared
    private let refreshTimer = Timer.publish(every: 2, on: .main, in: .common).autoconnect()

    var body: some View {
        Group {
            if runner.isSyncing {
                if let fraction = runner.syncFractionCompleted {
                    Text("🔄 Syncing (\(Int((fraction * 100).rounded()))%)")
                } else {
                    Text("🔄 Syncing…")
                }

                if !runner.syncStageSummary.isEmpty {
                    Text(runner.syncStageSummary)
                }

                if !runner.syncContextSummary.isEmpty {
                    Text(runner.syncContextSummary)
                }
            } else if model.setupReady {
                Button("✅ Ready to sync") {
                    SettingsWindowController.shared.showSetup()
                }

                if !runner.lastSyncSummary.isEmpty {
                    if runner.lastSyncFailed {
                        Button(runner.lastSyncSummary) {
                            runner.showLastSyncDetails()
                        }
                    } else {
                        Text(runner.lastSyncSummary)
                    }
                }
            } else {
                Button("⚠️ Not ready to sync — Open Setup…") {
                    SettingsWindowController.shared.showSetup()
                }

                if let step = model.nextSetupStep {
                    Text("Next: \(step.title)")
                }
            }

            Divider()

            Button(runner.isSyncing ? "Sync Now (Running…)" : "Sync Now") {
                let currentModel = SettingsViewModel()

                if currentModel.setupReady {
                    CommandRunner.shared.runSyncNow(model: currentModel)
                } else {
                    SettingsWindowController.shared.showSetup()
                }
            }
            .disabled(runner.isSyncing)

            Menu("Sync Folder") {
                if model.notebooks.isEmpty {
                    Button("No folders configured — Open Settings…") {
                        SettingsWindowController.shared.show()
                    }
                } else {
                    ForEach(model.notebooks) { notebook in
                        let folderName = notebook.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            ? "Unnamed Folder"
                            : notebook.name.trimmingCharacters(in: .whitespacesAndNewlines)
                        let files = noteFiles(for: notebook)

                        Menu(folderName) {
                            Button("Sync Entire Folder") {
                                let currentModel = SettingsViewModel()

                                if currentModel.setupReady {
                                    CommandRunner.shared.runSyncNow(model: currentModel, folderName: folderName)
                                } else {
                                    SettingsWindowController.shared.showSetup()
                                }
                            }
                            .disabled(runner.isSyncing)

                            Divider()

                            if files.isEmpty {
                                Text("No .note files found")
                            } else {
                                ForEach(files, id: \.path) { file in
                                    Button(file.label) {
                                        let currentModel = SettingsViewModel()

                                        if currentModel.setupReady {
                                            CommandRunner.shared.runSyncNow(
                                                model: currentModel,
                                                folderName: folderName,
                                                noteFilePath: file.path
                                            )
                                        } else {
                                            SettingsWindowController.shared.showSetup()
                                        }
                                    }
                                    .disabled(runner.isSyncing)
                                }
                            }
                        }
                    }

                    Divider()

                    Button("Sync All Folders") {
                        let currentModel = SettingsViewModel()

                        if currentModel.setupReady {
                            CommandRunner.shared.runSyncNow(model: currentModel)
                        } else {
                            SettingsWindowController.shared.showSetup()
                        }
                    }
                    .disabled(runner.isSyncing)
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

    private func noteFiles(for notebook: NotebookConfig) -> [(label: String, path: String)] {
        let rawPath = notebook.source_dir.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !rawPath.isEmpty else {
            return []
        }

        let expandedPath = (rawPath as NSString).expandingTildeInPath
        let rootURL = URL(fileURLWithPath: expandedPath, isDirectory: true).standardizedFileURL
        guard FileManager.default.fileExists(atPath: rootURL.path),
              let enumerator = FileManager.default.enumerator(
                  at: rootURL,
                  includingPropertiesForKeys: [.isRegularFileKey],
                  options: [.skipsHiddenFiles]
              )
        else {
            return []
        }

        let rootPrefix = rootURL.path.hasSuffix("/") ? rootURL.path : rootURL.path + "/"
        var results: [(label: String, path: String)] = []

        for case let fileURL as URL in enumerator {
            guard fileURL.pathExtension.lowercased() == "note" else {
                continue
            }
            let standardizedPath = fileURL.standardizedFileURL.path
            let relativeLabel: String
            if standardizedPath.hasPrefix(rootPrefix) {
                relativeLabel = String(standardizedPath.dropFirst(rootPrefix.count))
            } else {
                relativeLabel = fileURL.lastPathComponent
            }
            results.append((label: relativeLabel, path: standardizedPath))
        }

        return results.sorted {
            $0.label.localizedCaseInsensitiveCompare($1.label) == .orderedAscending
        }
    }
}

@main
struct SupernoteObsidianSyncApp: App {
    @StateObject private var runner = CommandRunner.shared

    var body: some Scene {
        MenuBarExtra {
            MenuSetupStatusView()

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
        } label: {
            if runner.isSyncing {
                if let fraction = runner.syncFractionCompleted {
                    Label("Supsidian \(Int((fraction * 100).rounded()))%", systemImage: "arrow.triangle.2.circlepath")
                } else {
                    Label("Supsidian…", systemImage: "arrow.triangle.2.circlepath")
                }
            } else {
                Label("Supsidian", systemImage: "long.text.page.and.pencil")
            }
        }
    }
}

@MainActor
final class CommandRunner: ObservableObject {
    static let shared = CommandRunner()

    @Published var isSyncing = false
    @Published var syncFractionCompleted: Double? = nil
    @Published var syncStageSummary = ""
    @Published var syncContextSummary = ""
    @Published var lastSyncSummary = ""
    @Published var lastSyncFailed = false

    private var lastSyncTitle = "Sync Now"
    private var lastSyncText = ""
    private var windowControllers: [OutputWindowController] = []

    private var cliPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            "\(home)/supernote-obsidian-sync/.venv/bin/supernote-obsidian-sync",
            "/opt/homebrew/bin/supernote-obsidian-sync",
            "/usr/local/bin/supernote-obsidian-sync"
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) }
            ?? "/opt/homebrew/bin/supernote-obsidian-sync"
    }

    private init() {}

    func showLastSyncDetails() {
        guard !lastSyncText.isEmpty else { return }
        _ = OutputWindowController.show(
            title: lastSyncTitle,
            output: lastSyncText,
            reuseExisting: true
        )
    }

    private func initialOutput(for arguments: [String], title: String) -> String {
        let command = "\(cliPath) \(arguments.joined(separator: " "))"

        if arguments.contains("--once") {
            return """
            \(title)

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

    func runSyncNow(
        model: SettingsViewModel,
        folderName: String? = nil,
        noteFilePath: String? = nil
    ) {
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

        let trimmedFolder = folderName?.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedFile = noteFilePath?.trimmingCharacters(in: .whitespacesAndNewlines)
        var syncArguments = ["--once"]
        let windowTitle: String
        let contextSummary: String

        if let trimmedFolder, !trimmedFolder.isEmpty {
            syncArguments.append(contentsOf: ["--folder", trimmedFolder])
        }
        if let trimmedFile, !trimmedFile.isEmpty {
            syncArguments.append(contentsOf: ["--file", trimmedFile])
            let fileLabel = URL(fileURLWithPath: trimmedFile).lastPathComponent
            windowTitle = "Sync File — \(fileLabel)"
            contextSummary = "File: \(fileLabel)"
        } else if let trimmedFolder, !trimmedFolder.isEmpty {
            windowTitle = "Sync Folder — \(trimmedFolder)"
            contextSummary = "Folder: \(trimmedFolder)"
        } else {
            windowTitle = "Sync Now"
            contextSummary = "All configured folders"
        }

        let syncRunningOutput = initialOutput(for: syncArguments, title: windowTitle)
        let progressTracker = SyncProgressTracker(
            command: commandDescription(syncArguments),
            title: windowTitle
        )

        isSyncing = true
        syncFractionCompleted = nil
        syncStageSummary = "Preparing sync…"
        syncContextSummary = contextSummary
        lastSyncTitle = windowTitle
        lastSyncText = syncRunningOutput
        lastSyncFailed = false

        Task {
            if shouldOpenPartner {
                await MainActor.run {
                    self.syncStageSummary = "Opening Supernote Partner and waiting \(delaySeconds)s…"
                }

                let openResult = await CommandRunner.openApplicationOrPath(partnerApp)
                if !openResult.succeeded {
                    await MainActor.run {
                        self.isSyncing = false
                        self.syncFractionCompleted = nil
                        self.syncStageSummary = ""
                        self.lastSyncSummary = "❌ Could not open Supernote Partner — Show Details"
                        self.lastSyncFailed = true
                        self.lastSyncText = openResult.displayText
                        self.showLastSyncDetails()
                    }
                    return
                }

                let (sleepNanoseconds, overflow) = UInt64(delaySeconds).multipliedReportingOverflow(by: 1_000_000_000)
                if !overflow && sleepNanoseconds > 0 {
                    do {
                        try await Task.sleep(nanoseconds: sleepNanoseconds)
                    } catch {
                        await MainActor.run {
                            self.isSyncing = false
                        }
                        return
                    }
                }

                guard !Task.isCancelled else {
                    await MainActor.run {
                        self.isSyncing = false
                    }
                    return
                }

                await MainActor.run {
                    self.syncStageSummary = "Looking for changed Supernote notes…"
                }
            }

            let result = await CommandRunner.runCommand(
                executablePath: cliPath,
                arguments: syncArguments,
                onProgress: { [weak self] event in
                    Task { @MainActor [weak self] in
                        guard let self, !progressTracker.isFinished else { return }
                        let progressText = progressTracker.apply(event)
                        self.syncFractionCompleted = progressTracker.fractionCompleted
                        self.syncStageSummary = progressTracker.currentStageDescription
                        self.syncContextSummary = progressTracker.currentContextSummary
                        self.lastSyncText = progressText
                    }
                }
            )

            await MainActor.run {
                progressTracker.isFinished = true
                self.isSyncing = false
                self.syncFractionCompleted = result.succeeded ? 1.0 : nil
                self.lastSyncText = result.displayText
                self.lastSyncFailed = !result.succeeded

                let summaryLabel: String
                if result.succeeded {
                    if result.displayText.contains("Changes found and synced") {
                        summaryLabel = "✅ Last sync: Changes found and synced"
                    } else if result.displayText.contains("No changes found") {
                        summaryLabel = "✅ Last sync: No changes found"
                    } else {
                        summaryLabel = "✅ Sync completed"
                    }
                } else {
                    summaryLabel = "❌ Last sync failed — Show Details"
                }

                self.lastSyncSummary = summaryLabel
                self.syncStageSummary = summaryLabel

                if !result.succeeded {
                    self.showLastSyncDetails()
                }
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

    private nonisolated static func runCommand(
        executablePath: String,
        arguments: [String],
        onProgress: (@Sendable (SyncProgressEvent) -> Void)? = nil
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

            let stdoutBuffer = StdoutStreamBuffer(onProgress: onProgress)
            let stderrBuffer = DataStreamBuffer()
            let outputHandle = outputPipe.fileHandleForReading
            let errorHandle = errorPipe.fileHandleForReading

            outputHandle.readabilityHandler = { handle in
                let chunk = handle.availableData
                if chunk.isEmpty {
                    handle.readabilityHandler = nil
                } else {
                    stdoutBuffer.append(chunk)
                }
            }

            errorHandle.readabilityHandler = { handle in
                let chunk = handle.availableData
                if chunk.isEmpty {
                    handle.readabilityHandler = nil
                } else {
                    stderrBuffer.append(chunk)
                }
            }

            defer {
                outputHandle.readabilityHandler = nil
                errorHandle.readabilityHandler = nil
            }

            do {
                try task.run()
                task.waitUntilExit()

                outputHandle.readabilityHandler = nil
                errorHandle.readabilityHandler = nil

                let remainingStdout = outputHandle.readDataToEndOfFile()
                let remainingStderr = errorHandle.readDataToEndOfFile()

                let output = stdoutBuffer.finish(remainingChunk: remainingStdout)
                let error = stderrBuffer.finish(remainingChunk: remainingStderr)

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
                outputHandle.readabilityHandler = nil
                errorHandle.readabilityHandler = nil

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

nonisolated struct SyncProgressEvent: Decodable, Sendable {
    let stage: String
    let notebook: String?
    let notebook_index: Int?
    let notebook_count: Int?
    let note: String?
    let note_name: String?
    let provider: String?
    let page: Int?
    let total_pages: Int?
    let changed_index: Int?
    let changed_count: Int?
}

nonisolated final class StdoutStreamBuffer: @unchecked Sendable {
    private static let progressPrefix = "SUSPIDIAN_PROGRESS:"
    private let lock = NSLock()
    private var pendingBytes = Data()
    private var outputLines: [String] = []
    private var hadTrailingNewline = false
    private let onProgress: (@Sendable (SyncProgressEvent) -> Void)?

    nonisolated init(onProgress: (@Sendable (SyncProgressEvent) -> Void)?) {
        self.onProgress = onProgress
    }

    nonisolated func append(_ chunk: Data) {
        guard !chunk.isEmpty else { return }

        var eventsToEmit: [SyncProgressEvent] = []

        lock.lock()
        pendingBytes.append(chunk)

        while let newlineIndex = pendingBytes.firstIndex(of: 0x0A) {
            let lineData = pendingBytes.subdata(in: 0..<newlineIndex)
            pendingBytes.removeSubrange(0...newlineIndex)
            hadTrailingNewline = true

            if let event = processLineData(lineData) {
                eventsToEmit.append(event)
            }
        }
        lock.unlock()

        for event in eventsToEmit {
            onProgress?(event)
        }
    }

    nonisolated func finish(remainingChunk: Data = Data()) -> String {
        var eventsToEmit: [SyncProgressEvent] = []
        let finalOutput: String

        lock.lock()
        if !remainingChunk.isEmpty {
            pendingBytes.append(remainingChunk)
        }

        while let newlineIndex = pendingBytes.firstIndex(of: 0x0A) {
            let lineData = pendingBytes.subdata(in: 0..<newlineIndex)
            pendingBytes.removeSubrange(0...newlineIndex)
            hadTrailingNewline = true

            if let event = processLineData(lineData) {
                eventsToEmit.append(event)
            }
        }

        if !pendingBytes.isEmpty {
            let lineData = pendingBytes
            pendingBytes.removeAll()
            hadTrailingNewline = false

            if let event = processLineData(lineData) {
                eventsToEmit.append(event)
            }
        }

        if outputLines.isEmpty {
            finalOutput = ""
        } else if hadTrailingNewline {
            finalOutput = outputLines.joined(separator: "\n") + "\n"
        } else {
            finalOutput = outputLines.joined(separator: "\n")
        }
        lock.unlock()

        for event in eventsToEmit {
            onProgress?(event)
        }

        return finalOutput
    }

    private nonisolated func processLineData(_ lineData: Data) -> SyncProgressEvent? {
        var line = String(decoding: lineData, as: UTF8.self)
        if line.hasSuffix("\r") {
            line.removeLast()
        }

        if line.hasPrefix(Self.progressPrefix) {
            let jsonText = String(line.dropFirst(Self.progressPrefix.count))
            if let jsonData = jsonText.data(using: .utf8),
               let event = try? JSONDecoder().decode(SyncProgressEvent.self, from: jsonData) {
                return event
            }
            return nil
        }

        outputLines.append(line)
        return nil
    }
}

nonisolated final class DataStreamBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()

    nonisolated init() {}

    nonisolated func append(_ chunk: Data) {
        guard !chunk.isEmpty else { return }
        lock.lock()
        data.append(chunk)
        lock.unlock()
    }

    nonisolated func finish(remainingChunk: Data = Data()) -> String {
        lock.lock()
        if !remainingChunk.isEmpty {
            data.append(remainingChunk)
        }
        let result = String(decoding: data, as: UTF8.self)
        lock.unlock()
        return result
    }
}

@MainActor
final class SyncProgressTracker {
    private let command: String
    private let title: String
    private var notebook: String?
    private var notebookIndex: Int?
    private var notebookCount: Int?
    private var noteName: String?
    private var notePath: String?
    private var provider: String?
    private var page: Int?
    private var totalPages: Int?
    private var changedIndex: Int?
    private var changedCount: Int?
    private var stage: String = "scanning"
    private var stageDescription = "Looking for changed Supernote notes…"
    private var completedNotes: [String] = []
    var isFinished = false

    init(command: String, title: String = "Sync Now") {
        self.command = command
        self.title = title
    }

    var currentStageDescription: String {
        stageDescription
    }

    var currentContextSummary: String {
        var parts: [String] = []
        if let notebook {
            if let notebookIndex, let notebookCount {
                parts.append("Folder: \(notebook) (\(notebookIndex)/\(notebookCount))")
            } else {
                parts.append("Folder: \(notebook)")
            }
        }
        if let noteName {
            parts.append("Note: \(noteName)")
        } else if let notePath {
            parts.append("Note: \(notePath)")
        }
        return parts.joined(separator: "  ·  ")
    }

    var fractionCompleted: Double? {
        let folderCount = max(notebookCount ?? 1, 1)
        let folderIndex = min(max(notebookIndex ?? 1, 1), folderCount)
        let folderBase = Double(folderIndex - 1) / Double(folderCount)
        let folderSpan = 1.0 / Double(folderCount)

        guard let totalPages, totalPages > 0 else {
            if stage == "writing_markdown" {
                return min(max(folderBase + folderSpan * 0.95, 0.0), 1.0)
            }
            if stage == "done" {
                return min(max(folderBase + folderSpan, 0.0), 1.0)
            }
            return nil
        }

        let pageRatio: Double
        if let changedIndex, let changedCount, changedCount > 0 {
            let currentChanged = min(max(changedIndex, 1), changedCount)
            pageRatio = Double(currentChanged) / Double(changedCount)
        } else {
            let currentPage = min(max(page ?? 1, 1), totalPages)
            pageRatio = Double(currentPage) / Double(totalPages)
        }
        let isHybrid = (provider == "hybrid_marker_olmocr")
        let noteFraction: Double

        switch stage {
        case "ocr":
            noteFraction = (isHybrid ? 0.7 : 0.9) * pageRatio
        case "marker":
            noteFraction = 0.7 + 0.25 * pageRatio
        case "visual_fallback":
            noteFraction = 0.95 + 0.04 * pageRatio
        case "writing_markdown":
            noteFraction = 0.99
        case "done":
            noteFraction = 1.0
        default:
            return nil
        }

        return min(max(folderBase + folderSpan * noteFraction, 0.0), 1.0)
    }

    func apply(_ event: SyncProgressEvent) -> String {
        stage = event.stage

        if let notebook = event.notebook, !notebook.isEmpty {
            self.notebook = notebook
        }
        if let notebookIndex = event.notebook_index {
            self.notebookIndex = notebookIndex
        }
        if let notebookCount = event.notebook_count {
            self.notebookCount = notebookCount
        }
        if let noteName = event.note_name, !noteName.isEmpty {
            self.noteName = noteName
        }
        if let notePath = event.note, !notePath.isEmpty {
            self.notePath = notePath
        }
        if let provider = event.provider, !provider.isEmpty {
            self.provider = provider
        }
        if let page = event.page {
            self.page = page
        }
        if let totalPages = event.total_pages {
            self.totalPages = totalPages
        }
        if let changedIndex = event.changed_index {
            self.changedIndex = changedIndex
        }
        if let changedCount = event.changed_count {
            self.changedCount = changedCount
        }

        switch event.stage {
        case "scanning":
            noteName = nil
            notePath = nil
            page = nil
            totalPages = nil
            changedIndex = nil
            changedCount = nil
            if let notebook, let notebookIndex, let notebookCount {
                stageDescription = "Scanning folder \(notebookIndex) of \(notebookCount): \(notebook)…"
            } else if let notebook {
                stageDescription = "Scanning folder: \(notebook)…"
            } else {
                stageDescription = "Scanning Supernote folder…"
            }

        case "processing":
            page = nil
            totalPages = nil
            changedIndex = nil
            changedCount = nil
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Processing note: \(currentNote)…"

        case "converting":
            page = nil
            totalPages = nil
            changedIndex = nil
            changedCount = nil
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Converting \(currentNote) to PDF…"

        case "ocr_start":
            page = nil
            totalPages = nil
            changedIndex = nil
            changedCount = nil
            let activeProvider = provider ?? "configured provider"
            stageDescription = "OCR in progress… (\(activeProvider))"

        case "ocr":
            let activeProvider = provider ?? "local OCR"
            if let page = event.page, let totalPages = event.total_pages {
                if let changedIndex = event.changed_index,
                   let changedCount = event.changed_count,
                   changedCount < totalPages {
                    let changedLabel = changedCount == 1
                        ? "1 changed page"
                        : "changed \(changedIndex) of \(changedCount)"
                    stageDescription = "OCR in progress… (\(activeProvider) — page \(page) of \(totalPages), \(changedLabel))"
                } else {
                    stageDescription = "OCR in progress… (\(activeProvider) — page \(page) of \(totalPages))"
                }
            } else if let page = event.page {
                stageDescription = "OCR in progress… (\(activeProvider) — page \(page))"
            } else {
                stageDescription = "OCR in progress… (\(activeProvider))"
            }

        case "marker":
            if let page = event.page, let totalPages = event.total_pages {
                if let changedIndex = event.changed_index,
                   let changedCount = event.changed_count,
                   changedCount < totalPages {
                    let changedLabel = changedCount == 1
                        ? "1 changed page"
                        : "changed \(changedIndex) of \(changedCount)"
                    stageDescription = "OCR in progress… (Marker layout & visuals — page \(page) of \(totalPages), \(changedLabel))"
                } else {
                    stageDescription = "OCR in progress… (Marker layout & visuals — page \(page) of \(totalPages))"
                }
            } else if let page = event.page {
                stageDescription = "OCR in progress… (Marker layout & visuals — page \(page))"
            } else {
                stageDescription = "OCR in progress… (Marker layout & visuals)"
            }

        case "visual_fallback":
            if let page = event.page, let totalPages = event.total_pages {
                if let changedIndex = event.changed_index,
                   let changedCount = event.changed_count,
                   changedCount < totalPages {
                    let checkLabel = changedCount == 1
                        ? "1 page"
                        : "\(changedIndex) of \(changedCount)"
                    stageDescription = "Checking visuals… (page \(page) of \(totalPages), \(checkLabel))"
                } else {
                    stageDescription = "Checking visuals… (page \(page) of \(totalPages))"
                }
            } else if let page = event.page {
                stageDescription = "Checking visuals… (page \(page))"
            } else {
                stageDescription = "Checking visuals…"
            }

        case "writing_markdown":
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Writing Markdown for \(currentNote)…"

        case "done":
            if let finishedNote = noteName ?? notePath,
               !completedNotes.contains(finishedNote) {
                completedNotes.append(finishedNote)
            }
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Finished note: \(currentNote)"

        default:
            stageDescription = "Sync step: \(event.stage)…"
        }

        return formattedText()
    }

    private func formattedText() -> String {
        var lines: [String] = [title, ""]

        if let notebook {
            if let notebookIndex, let notebookCount {
                lines.append("Folder: \(notebook) (\(notebookIndex) of \(notebookCount))")
            } else {
                lines.append("Folder: \(notebook)")
            }
        }

        if let noteName {
            lines.append("Note:   \(noteName)")
        } else if let notePath {
            lines.append("Note:   \(notePath)")
        }

        lines.append("Status: \(stageDescription)")

        if !completedNotes.isEmpty {
            lines.append("")
            lines.append("Completed in this run (\(completedNotes.count)):")
            for completed in completedNotes {
                lines.append("• \(completed)")
            }
        }

        lines.append("")
        lines.append("Please wait until the final summary appears.")
        lines.append("")
        lines.append("Command:")
        lines.append(command)

        return lines.joined(separator: "\n")
    }
}

struct CommandResult {
    let succeeded: Bool
    let displayText: String
}

@MainActor
final class OutputWindowProgressModel: ObservableObject {
    @Published var isVisible = false
    @Published var isRunning = false
    @Published var fractionCompleted: Double? = nil
    @Published var label = ""
    @Published var context = ""
}

struct OutputWindowProgressHeaderView: View {
    @ObservedObject var model: OutputWindowProgressModel

    var body: some View {
        if model.isVisible {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.label)
                        .font(.headline)
                        .foregroundColor(.primary)
                        .lineLimit(1)
                        .truncationMode(.tail)

                    Spacer()

                    if let fraction = model.fractionCompleted {
                        Text("\(Int((fraction * 100).rounded()))%")
                            .font(.system(.headline, design: .monospaced))
                            .foregroundColor(.accentColor)
                    }
                }

                if !model.context.isEmpty {
                    Text(model.context)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                        .truncationMode(.middle)
                }

                if let fraction = model.fractionCompleted {
                    ProgressView(value: fraction, total: 1.0)
                        .progressViewStyle(.linear)
                } else if model.isRunning {
                    ProgressView()
                        .progressViewStyle(.linear)
                }
            }
            .padding(.horizontal, 18)
            .padding(.top, 14)
            .padding(.bottom, 12)
            .background(Color(nsColor: .controlBackgroundColor))

            Divider()
        }
    }
}

@MainActor
final class OutputWindowController: NSWindowController, NSWindowDelegate {
    private static var openControllers: [OutputWindowController] = []
    private static var sharedSyncController: OutputWindowController?

    static func show(title: String, output: String, reuseExisting: Bool = false) -> OutputWindowController {
        if reuseExisting, let existing = sharedSyncController {
            existing.window?.title = title
            existing.update(text: output)
            existing.bringToFront()
            return existing
        }

        let controller = OutputWindowController(title: title, text: output)

        openControllers.append(controller)
        if reuseExisting {
            sharedSyncController = controller
        }

        controller.onClose = { [weak controller] in
            guard let controller else { return }
            openControllers.removeAll { $0 === controller }
            if sharedSyncController === controller {
                sharedSyncController = nil
            }
        }

        controller.bringToFront()

        return controller
    }

    var onClose: (() -> Void)?

    private let textView: NSTextView
    private let progressModel = OutputWindowProgressModel()

    func update(text: String) {
        textView.string = text
    }

    func updateProgress(isRunning: Bool, fraction: Double?, label: String, context: String = "") {
        progressModel.isVisible = isRunning || fraction != nil || !label.isEmpty
        progressModel.isRunning = isRunning
        progressModel.fractionCompleted = fraction
        progressModel.label = label
        progressModel.context = context
    }

    func bringToFront() {
        guard let window else { return }
        window.level = .normal
        showWindow(nil)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
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
        scrollView.translatesAutoresizingMaskIntoConstraints = false

        let headerHost = NSHostingView(rootView: OutputWindowProgressHeaderView(model: progressModel))
        headerHost.translatesAutoresizingMaskIntoConstraints = false

        let containerView = NSView(frame: NSRect(x: 0, y: 0, width: 780, height: 540))
        containerView.addSubview(headerHost)
        containerView.addSubview(scrollView)

        NSLayoutConstraint.activate([
            headerHost.topAnchor.constraint(equalTo: containerView.topAnchor),
            headerHost.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            headerHost.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),

            scrollView.topAnchor.constraint(equalTo: headerHost.bottomAnchor),
            scrollView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: containerView.bottomAnchor)
        ])

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 780, height: 540),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = title
        window.minSize = NSSize(width: 640, height: 420)
        window.tabbingMode = .disallowed
        window.hidesOnDeactivate = false
        window.isReleasedWhenClosed = false
        window.contentView = containerView
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
