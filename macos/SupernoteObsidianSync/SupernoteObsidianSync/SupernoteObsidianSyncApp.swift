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

            Divider()

            Button("Sync Now") {
                let currentModel = SettingsViewModel()

                if currentModel.setupReady {
                    CommandRunner.shared.runSyncNow(model: currentModel)
                } else {
                    SettingsWindowController.shared.showSetup()
                }
            }

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

                        Button(folderName) {
                            let currentModel = SettingsViewModel()

                            if currentModel.setupReady {
                                CommandRunner.shared.runSyncNow(model: currentModel, folderName: folderName)
                            } else {
                                SettingsWindowController.shared.showSetup()
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

    func runSyncNow(model: SettingsViewModel, folderName: String? = nil) {
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
        let syncArguments: [String]
        let windowTitle: String
        if let trimmedFolder, !trimmedFolder.isEmpty {
            syncArguments = ["--once", "--folder", trimmedFolder]
            windowTitle = "Sync Folder — \(trimmedFolder)"
        } else {
            syncArguments = ["--once"]
            windowTitle = "Sync Now"
        }

        let syncRunningOutput = initialOutput(for: syncArguments, title: windowTitle)
        let progressTracker = SyncProgressTracker(
            command: commandDescription(syncArguments),
            title: windowTitle
        )

        let outputWindow = OutputWindowController.show(
            title: windowTitle,
            output: syncRunningOutput
        )
        outputWindow.updateProgress(
            isRunning: true,
            fraction: nil,
            label: "Preparing sync…"
        )

        Task {
            if shouldOpenPartner {
                await MainActor.run {
                    outputWindow.updateProgress(
                        isRunning: true,
                        fraction: nil,
                        label: "Opening Supernote Partner and waiting \(delaySeconds)s…"
                    )
                    outputWindow.update(text: """
                    \(windowTitle)

                    Opening Supernote Partner…
                    App/path:
                    \(partnerApp)

                    Waiting \(delaySeconds) second(s) before Supsidian sync starts.
                    """)
                }

                let openResult = await CommandRunner.openApplicationOrPath(partnerApp)
                if !openResult.succeeded {
                    await MainActor.run {
                        outputWindow.updateProgress(
                            isRunning: false,
                            fraction: nil,
                            label: "Could not open Supernote Partner"
                        )
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
                    outputWindow.updateProgress(
                        isRunning: true,
                        fraction: nil,
                        label: "Looking for changed Supernote notes…"
                    )
                    outputWindow.update(text: syncRunningOutput)
                }
            }

            let result = await CommandRunner.runCommand(
                executablePath: cliPath,
                arguments: syncArguments,
                onProgress: { event in
                    Task { @MainActor in
                        guard !progressTracker.isFinished else { return }
                        let progressText = progressTracker.apply(event)
                        outputWindow.updateProgress(
                            isRunning: true,
                            fraction: progressTracker.fractionCompleted,
                            label: progressTracker.currentStageDescription
                        )
                        outputWindow.update(text: progressText)
                    }
                }
            )

            await MainActor.run {
                progressTracker.isFinished = true
                outputWindow.updateProgress(
                    isRunning: false,
                    fraction: result.succeeded ? 1.0 : nil,
                    label: result.succeeded ? "Sync completed" : "Sync failed"
                )
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

        let currentPage = min(max(page ?? 1, 1), totalPages)
        let pageRatio = Double(currentPage) / Double(totalPages)
        let isHybrid = (provider == "hybrid_marker_olmocr")
        let noteFraction: Double

        switch stage {
        case "ocr":
            noteFraction = (isHybrid ? 0.7 : 0.9) * pageRatio
        case "marker":
            noteFraction = 0.7 + 0.25 * pageRatio
        case "writing_markdown":
            noteFraction = 0.95
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

        switch event.stage {
        case "scanning":
            noteName = nil
            notePath = nil
            page = nil
            totalPages = nil
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
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Processing note: \(currentNote)…"

        case "converting":
            page = nil
            totalPages = nil
            let currentNote = noteName ?? notePath ?? "note"
            stageDescription = "Converting \(currentNote) to PDF…"

        case "ocr_start":
            page = nil
            totalPages = nil
            let activeProvider = provider ?? "configured provider"
            stageDescription = "OCR in progress… (\(activeProvider))"

        case "ocr":
            let activeProvider = provider ?? "local OCR"
            if let page = event.page, let totalPages = event.total_pages {
                stageDescription = "OCR in progress… (\(activeProvider) — page \(page) of \(totalPages))"
            } else if let page = event.page {
                stageDescription = "OCR in progress… (\(activeProvider) — page \(page))"
            } else {
                stageDescription = "OCR in progress… (\(activeProvider))"
            }

        case "marker":
            if let page = event.page, let totalPages = event.total_pages {
                stageDescription = "OCR in progress… (Marker layout & visuals — page \(page) of \(totalPages))"
            } else if let page = event.page {
                stageDescription = "OCR in progress… (Marker layout & visuals — page \(page))"
            } else {
                stageDescription = "OCR in progress… (Marker layout & visuals)"
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
}

struct OutputWindowProgressHeaderView: View {
    @ObservedObject var model: OutputWindowProgressModel

    var body: some View {
        if model.isVisible {
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(model.label)
                        .font(.footnote)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                        .truncationMode(.tail)

                    Spacer()

                    if let fraction = model.fractionCompleted {
                        Text("\(Int((fraction * 100).rounded()))%")
                            .font(.system(.footnote, design: .monospaced))
                            .foregroundColor(.secondary)
                    }
                }

                if let fraction = model.fractionCompleted {
                    ProgressView(value: fraction, total: 1.0)
                        .progressViewStyle(.linear)
                } else if model.isRunning {
                    ProgressView()
                        .progressViewStyle(.linear)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 8)
            .background(Color(nsColor: .windowBackgroundColor))

            Divider()
        }
    }
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
    private let progressModel = OutputWindowProgressModel()

    func update(text: String) {
        textView.string = text
    }

    func updateProgress(isRunning: Bool, fraction: Double?, label: String) {
        progressModel.isVisible = isRunning || fraction != nil
        progressModel.isRunning = isRunning
        progressModel.fractionCompleted = fraction
        progressModel.label = label
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

        let containerView = NSView(frame: NSRect(x: 0, y: 0, width: 760, height: 520))
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
            contentRect: NSRect(x: 0, y: 0, width: 760, height: 520),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = title
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
