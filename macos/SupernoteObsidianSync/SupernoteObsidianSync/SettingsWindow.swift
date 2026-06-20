import SwiftUI
import AppKit
import Combine

// MARK: - Models

struct NotebookConfig: Identifiable, Codable {
    var id = UUID()
    var name: String
    var source_dir: String
    var obsidian_note_folder: String
    var attachment_folder: String
    var state_file: String

    enum CodingKeys: String, CodingKey {
        case name
        case source_dir
        case obsidian_note_folder
        case attachment_folder
        case state_file
    }

    init(
        name: String,
        source_dir: String,
        obsidian_note_folder: String,
        attachment_folder: String,
        state_file: String
    ) {
        self.name = name
        self.source_dir = source_dir
        self.obsidian_note_folder = obsidian_note_folder
        self.attachment_folder = attachment_folder
        self.state_file = state_file
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        self.id = UUID()
        self.name = try container.decode(String.self, forKey: .name)
        self.source_dir = try container.decode(String.self, forKey: .source_dir)
        self.obsidian_note_folder = try container.decode(String.self, forKey: .obsidian_note_folder)
        self.attachment_folder = try container.decode(String.self, forKey: .attachment_folder)
        self.state_file = try container.decode(String.self, forKey: .state_file)
    }
}

struct SyncConfig: Codable {
    var vault_dir: String
    var supernote_tool_path: String
    var check_interval_seconds: Int
    var file_stability_wait_seconds: Int
    var task_marker: String
    var task_tag: String
    var custom_ocr_instruction: String?
    var open_requires_obsidian_running: Bool
    var notebooks: [NotebookConfig]

    static let `default` = SyncConfig(
        vault_dir: "",
        supernote_tool_path: "",
        check_interval_seconds: 60,
        file_stability_wait_seconds: 10,
        task_marker: "#",
        task_tag: "#task",
        custom_ocr_instruction: "",
        open_requires_obsidian_running: true,
        notebooks: []
    )
}

enum SettingsSection: String, CaseIterable, Identifiable {
    case setup = "Setup"
    case obsidianSettings = "Obsidian Settings"
    case folders = "Folders"
    case ocrTasks = "OCR & Tasks"
    case advanced = "Advanced"
    case diagnostics = "Diagnostics"

    var id: String { rawValue }

    var icon: String {
        switch self {
        case .setup:
            return "checkmark.seal"
        case .obsidianSettings:
            return "gearshape"
        case .folders:
            return "folder"
        case .ocrTasks:
            return "text.viewfinder"
        case .advanced:
            return "slider.horizontal.3"
        case .diagnostics:
            return "stethoscope"
        }
    }

    var subtitle: String {
        switch self {
        case .setup:
            return "Setup progress"
        case .obsidianSettings:
            return "Vault and converter"
        case .folders:
            return "Supernote → Obsidian"
        case .ocrTasks:
            return "OCR and task conversion"
        case .advanced:
            return "Timing and startup"
        case .diagnostics:
            return "Logs and checks"
        }
    }
}

enum SetupStep: String, CaseIterable, Identifiable {
    case obsidianVault
    case supernoteTool
    case mistralApiKey
    case folders

    var id: String { rawValue }

    var number: Int {
        switch self {
        case .obsidianVault:
            return 1
        case .supernoteTool:
            return 2
        case .mistralApiKey:
            return 3
        case .folders:
            return 4
        }
    }

    var title: String {
        switch self {
        case .obsidianVault:
            return "Choose your Obsidian vault"
        case .supernoteTool:
            return "Connect supernote-tool"
        case .mistralApiKey:
            return "Add your Mistral API key"
        case .folders:
            return "Add a Supernote folder"
        }
    }

    var description: String {
        switch self {
        case .obsidianVault:
            return "The app needs your Obsidian vault so it knows where to save Markdown files and attachments."
        case .supernoteTool:
            return "supernote-tool converts Supernote .note files into PDFs before they are sent to OCR."
        case .mistralApiKey:
            return "Mistral OCR turns handwriting into searchable Markdown text."
        case .folders:
            return "Choose which Supernote folders should sync, and where they should appear in Obsidian."
        }
    }

    var buttonTitle: String {
        switch self {
        case .obsidianVault, .supernoteTool:
            return "Open Obsidian Settings"
        case .mistralApiKey:
            return "Open OCR & Tasks"
        case .folders:
            return "Open Folders"
        }
    }

    var targetSection: SettingsSection {
        switch self {
        case .obsidianVault, .supernoteTool:
            return .obsidianSettings
        case .mistralApiKey:
            return .ocrTasks
        case .folders:
            return .folders
        }
    }

    var icon: String {
        switch self {
        case .obsidianVault:
            return "square.stack.3d.up"
        case .supernoteTool:
            return "wrench.and.screwdriver"
        case .mistralApiKey:
            return "key"
        case .folders:
            return "folder.badge.plus"
        }
    }
}

// MARK: - View Model

// MARK: - View Model

@MainActor
final class SettingsViewModel: ObservableObject {
    var savedSettingsExist: Bool {
        let configURL = FileManager.default
            .homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Supernote Obsidian Sync/config.json")

        return FileManager.default.fileExists(atPath: configURL.path)
    }

    @Published var vaultDir = ""
    @Published var supernoteToolPath = ""
    @Published var checkIntervalSeconds = "60"
    @Published var fileStabilityWaitSeconds = "10"
    @Published var taskMarker = "#"
    @Published var taskTag = "#task"
    @Published var customOcrInstruction = ""
    @Published var openRequiresObsidianRunning = true
    @Published var mistralApiKey = ""
    @Published var notebooks: [NotebookConfig] = []
    @Published var statusMessage = ""
    @Published var startAtLoginEnabled = false
    @Published var selectedSection: SettingsSection = .setup

    private let appSupportDir: URL
    private let configURL: URL
    private let envURL: URL

    private var launchAgentURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library")
            .appendingPathComponent("LaunchAgents")
            .appendingPathComponent("com.kulturban.supernote-obsidian-sync.plist")
    }

    init() {
        let home = FileManager.default.homeDirectoryForCurrentUser

        self.appSupportDir = home
            .appendingPathComponent("Library")
            .appendingPathComponent("Application Support")
            .appendingPathComponent("Supernote Obsidian Sync")

        self.configURL = appSupportDir.appendingPathComponent("config.json")
        self.envURL = appSupportDir.appendingPathComponent(".env")

        load()
    }

    // MARK: Load / Save

    func load() {
        do {
            try FileManager.default.createDirectory(
                at: appSupportDir,
                withIntermediateDirectories: true
            )

            let config: SyncConfig

            if FileManager.default.fileExists(atPath: configURL.path) {
                let data = try Data(contentsOf: configURL)
                config = try JSONDecoder().decode(SyncConfig.self, from: data)
            } else {
                config = .default
            }

            apply(config)
            mistralApiKey = loadEnvValue(for: "MISTRAL_API_KEY") ?? ""
            refreshStartAtLoginStatus()
            statusMessage = "Settings loaded."
        } catch {
            statusMessage = "❌ Failed to load settings: \(error.localizedDescription)"
        }
    }

    func save() {
        do {
            try FileManager.default.createDirectory(
                at: appSupportDir,
                withIntermediateDirectories: true
            )

            let config = SyncConfig(
                vault_dir: vaultDir,
                supernote_tool_path: supernoteToolPath,
                check_interval_seconds: Int(checkIntervalSeconds) ?? 60,
                file_stability_wait_seconds: Int(fileStabilityWaitSeconds) ?? 10,
                task_marker: taskMarker,
                task_tag: taskTag,
                custom_ocr_instruction: customOcrInstruction,
                open_requires_obsidian_running: openRequiresObsidianRunning,
                notebooks: notebooks
            )

            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

            let data = try encoder.encode(config)
            try data.write(to: configURL)

            let envText = "MISTRAL_API_KEY=\(mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines))\n"
            try envText.write(to: envURL, atomically: true, encoding: .utf8)

            if let nextStep = nextSetupStep {
                statusMessage = "✅ Settings saved. Continue setup: \(nextStep.title)."
            } else {
                statusMessage = "✅ Settings saved. Sync is ready."
            }
        } catch {
            statusMessage = "❌ Failed to save settings: \(error.localizedDescription)"
        }
    }

    private func apply(_ config: SyncConfig) {
        vaultDir = config.vault_dir
        supernoteToolPath = config.supernote_tool_path
        checkIntervalSeconds = String(config.check_interval_seconds)
        fileStabilityWaitSeconds = String(config.file_stability_wait_seconds)
        taskMarker = config.task_marker
        taskTag = config.task_tag
        customOcrInstruction = config.custom_ocr_instruction ?? ""
        openRequiresObsidianRunning = config.open_requires_obsidian_running
        notebooks = config.notebooks
    }

    // MARK: Validation

    func validateSettings() -> [String] {
        var errors: [String] = []

        let trimmedKey = mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines)

        if trimmedKey.isEmpty {
            errors.append("Mistral AI API key is missing.")
        } else if trimmedKey.contains(" ") || trimmedKey.count < 20 {
            errors.append("Mistral AI API key does not look valid.")
        }

        if vaultDir.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            errors.append("Obsidian vault folder is missing.")
        } else if !isValidDirectory(vaultDir) {
            errors.append("Obsidian vault folder does not exist.")
        }

        if supernoteToolPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            errors.append("supernote-tool path is missing.")
        } else if !FileManager.default.isExecutableFile(atPath: supernoteToolPath) {
            errors.append("supernote-tool path is not valid or not executable.")
        }

        if notebooks.isEmpty {
            errors.append("At least one Supernote folder must be configured.")
        }

        for notebook in notebooks {
            if notebook.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("A synced folder has no name.")
            }

            if notebook.source_dir.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Supernote source folder is missing for \(notebook.name).")
            } else if !isValidDirectory(notebook.source_dir) {
                errors.append("Supernote source folder does not exist for \(notebook.name).")
            }

            if notebook.obsidian_note_folder.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Obsidian output folder is missing for \(notebook.name).")
            }

            if notebook.attachment_folder.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Attachment folder is missing for \(notebook.name).")
            }

            if notebook.state_file.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("State file is missing for \(notebook.name).")
            }
        }

        return errors
    }

    var setupItems: [(String, Bool, String, SettingsSection)] {
        [
            (
                "Obsidian vault",
                isSetupStepComplete(.obsidianVault),
                vaultDir.isEmpty ? "Missing" : vaultDir,
                .obsidianSettings
            ),
            (
                "supernote-tool",
                isSetupStepComplete(.supernoteTool),
                supernoteToolPath.isEmpty ? "Missing" : supernoteToolPath,
                .obsidianSettings
            ),
            (
                "Mistral API key",
                isSetupStepComplete(.mistralApiKey),
                mistralApiKey.isEmpty ? "Missing" : "Set",
                .ocrTasks
            ),
            (
                "Synced folders",
                isSetupStepComplete(.folders),
                "\(notebooks.count) configured",
                .folders
            )
        ]
    }

    var setupReady: Bool {
        nextSetupStep == nil
    }

    var completedSetupCount: Int {
        SetupStep.allCases.filter { isSetupStepComplete($0) }.count
    }

    var nextSetupStep: SetupStep? {
        for step in SetupStep.allCases {
            if !isSetupStepComplete(step) {
                return step
            }
        }

        return nil
    }

    func isSetupStepComplete(_ step: SetupStep) -> Bool {
        switch step {
        case .obsidianVault:
            return isValidDirectory(vaultDir)
        case .supernoteTool:
            return FileManager.default.isExecutableFile(atPath: supernoteToolPath)
        case .mistralApiKey:
            return !mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .folders:
            return !notebooks.isEmpty
        }
    }

    private func isValidDirectory(_ path: String) -> Bool {
        guard !path.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }

        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory)
        return exists && isDirectory.boolValue
    }

    // MARK: Startup

    func refreshStartAtLoginStatus() {
        startAtLoginEnabled = FileManager.default.fileExists(atPath: launchAgentURL.path)
    }

    func setStartAtLogin(_ enabled: Bool) {
        startAtLoginEnabled = enabled

        if enabled {
            CommandRunner.shared.runAndShow(["--install-agent"], title: "Install Start at Login")
            statusMessage = "Installing Start at Login…"
        } else {
            CommandRunner.shared.runAndShow(["--uninstall-agent"], title: "Remove Start at Login")
            statusMessage = "Removing Start at Login…"
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
            self.refreshStartAtLoginStatus()
        }
    }

    // MARK: Folder / File Choosers

    func chooseVaultFolder() {
        chooseFolder(title: "Choose Obsidian Vault") { url in
            if self.isInsideSupernotePartnerFolder(url.path) {
                self.statusMessage = "❌ This looks like the Supernote Partner folder. Please choose your Obsidian vault instead."
                return
            }

            self.vaultDir = url.path
        }
    }

    func chooseSupernoteTool() {
        chooseFile(title: "Choose supernote-tool") { url in
            self.supernoteToolPath = url.path
        }
    }

    func addNotebook() {
        chooseFolder(
            title: "Choose Supernote Folder",
            initialDirectory: suggestedSupernotePartnerFolderURL()
        ) { url in
            let folderName = url.lastPathComponent
            let safeName = folderName.isEmpty ? "Supernote" : folderName
            let stateName = "processed_\(Self.slugify(safeName)).json"

            let notebook = NotebookConfig(
                name: safeName,
                source_dir: url.path,
                obsidian_note_folder: safeName,
                attachment_folder: "Attachments/Supernote/\(safeName)",
                state_file: stateName
            )

            self.notebooks.append(notebook)
            self.statusMessage = "Added folder: \(safeName)"
        }
    }

    func removeNotebook(_ notebook: NotebookConfig) {
        notebooks.removeAll { $0.id == notebook.id }
        statusMessage = "Removed folder."
    }

    func chooseSupernoteFolder(for notebook: NotebookConfig) {
        guard let index = notebooks.firstIndex(where: { $0.id == notebook.id }) else {
            return
        }

        chooseFolder(
            title: "Choose Supernote Folder",
            initialDirectory: suggestedSupernotePartnerFolderURL()
        ) { url in
            self.notebooks[index].source_dir = url.path

            if self.notebooks[index].name.isEmpty {
                self.notebooks[index].name = url.lastPathComponent
            }
        }
    }

    func chooseObsidianFolder(for notebook: NotebookConfig) {
        guard let index = notebooks.firstIndex(where: { $0.id == notebook.id }) else {
            return
        }

        chooseFolder(
            title: "Choose Obsidian Folder inside Vault",
            initialDirectory: obsidianVaultURL()
        ) { url in
            self.notebooks[index].obsidian_note_folder = self.relativeToVault(url: url)
        }
    }

    func chooseAttachmentFolder(for notebook: NotebookConfig) {
        guard let index = notebooks.firstIndex(where: { $0.id == notebook.id }) else {
            return
        }

        chooseFolder(
            title: "Choose Attachment Folder inside Vault",
            initialDirectory: obsidianVaultURL()
        ) { url in
            self.notebooks[index].attachment_folder = self.relativeToVault(url: url)
        }
    }

    private func chooseFolder(
        title: String,
        initialDirectory: URL? = nil,
        completion: (URL) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.title = title
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        panel.directoryURL = initialDirectory

        if panel.runModal() == .OK, let url = panel.url {
            completion(normalizeSupernoteFolder(url))
        }
    }

    private func obsidianVaultURL() -> URL? {
        guard !vaultDir.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }

        return URL(fileURLWithPath: vaultDir)
    }

    private func suggestedSupernotePartnerFolderURL() -> URL {
        let home = FileManager.default.homeDirectoryForCurrentUser

        let candidates = [
            home
                .appendingPathComponent("Library")
                .appendingPathComponent("Containers")
                .appendingPathComponent("com.ratta.supernote")
                .appendingPathComponent("Data")
                .appendingPathComponent("Documents"),

            home
                .appendingPathComponent("Library")
                .appendingPathComponent("Containers")
                .appendingPathComponent("com.ratta.supernote.mac")
                .appendingPathComponent("Data")
                .appendingPathComponent("Documents"),

            home
                .appendingPathComponent("Library")
                .appendingPathComponent("Containers")
                .appendingPathComponent("Supernote Partner")
                .appendingPathComponent("Data")
                .appendingPathComponent("Documents"),

            home
                .appendingPathComponent("Library")
                .appendingPathComponent("Application Support")
                .appendingPathComponent("Supernote Partner"),

            home
                .appendingPathComponent("Library")
                .appendingPathComponent("Application Support")
                .appendingPathComponent("com.ratta.supernote")
        ]

        for candidate in candidates {
            if containsSupernoteNotes(candidate) {
                return candidate
            }
        }

        for candidate in candidates {
            if isDirectory(candidate) {
                return candidate
            }
        }

        return home
    }

    private func containsSupernoteNotes(_ url: URL) -> Bool {
        guard isDirectory(url) else {
            return false
        }

        guard let enumerator = FileManager.default.enumerator(
            at: url,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ) else {
            return false
        }

        for case let fileURL as URL in enumerator {
            if fileURL.pathExtension.lowercased() == "note" {
                return true
            }
        }

        return false
    }

    private func isDirectory(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        let exists = FileManager.default.fileExists(
            atPath: url.path,
            isDirectory: &isDirectory
        )

        return exists && isDirectory.boolValue
    }

    private func chooseFile(title: String, completion: (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.title = title
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false

        if panel.runModal() == .OK, let url = panel.url {
            completion(url)
        }
    }

    private func relativeToVault(url: URL) -> String {
        guard !vaultDir.isEmpty else {
            return url.path
        }

        let vaultPath = URL(fileURLWithPath: vaultDir).standardizedFileURL.path
        let chosenPath = url.standardizedFileURL.path

        if chosenPath == vaultPath {
            return ""
        }

        if chosenPath.hasPrefix(vaultPath + "/") {
            return String(chosenPath.dropFirst(vaultPath.count + 1))
        }

        return chosenPath
    }



    private func isInsideSupernotePartnerFolder(_ path: String) -> Bool {
        path.contains("/Library/Containers/com.ratta.supernote/")
    }

    private func normalizeSupernoteFolder(_ url: URL) -> URL {
        // If the user chooses .../Supernote, use .../Supernote/Note automatically.
        if url.lastPathComponent == "Supernote" {
            let noteURL = url.appendingPathComponent("Note")
            var isDirectory: ObjCBool = false

            if FileManager.default.fileExists(atPath: noteURL.path, isDirectory: &isDirectory),
               isDirectory.boolValue {
                return noteURL
            }
        }

        return url
    }

    var suggestedSupernoteFolderPath: String {
        if let url = findDefaultSupernoteNoteFolder() {
            return url.path
        }

        return "Default Supernote Partner folder not found yet. Open Supernote Partner and sync once."
    }

    private func findDefaultSupernoteNoteFolder() -> URL? {
        let home = FileManager.default.homeDirectoryForCurrentUser

        let supernoteBase = home
            .appendingPathComponent("Library")
            .appendingPathComponent("Containers")
            .appendingPathComponent("com.ratta.supernote")
            .appendingPathComponent("Data")
            .appendingPathComponent("Library")
            .appendingPathComponent("Application Support")
            .appendingPathComponent("com.ratta.supernote")

        guard let userFolders = try? FileManager.default.contentsOfDirectory(
            at: supernoteBase,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        ) else {
            return nil
        }

        let candidates = userFolders
            .map {
                $0
                    .appendingPathComponent("Supernote")
                    .appendingPathComponent("Note")
            }
            .filter { url in
                var isDirectory: ObjCBool = false
                return FileManager.default.fileExists(atPath: url.path, isDirectory: &isDirectory)
                    && isDirectory.boolValue
            }

        return candidates.sorted { $0.path < $1.path }.first
    }

    private func chooseSupernoteFolder(title: String, completion: (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.title = title
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false

        if let defaultFolder = findDefaultSupernoteNoteFolder() {
            panel.directoryURL = defaultFolder
        }

        if panel.runModal() == .OK, let url = panel.url {
            completion(url)
        }
    }

    // MARK: External Help

    func openMistralApiKeyPage() {
        if let url = URL(string: "https://admin.mistral.ai/organization/api-keys") {
            NSWorkspace.shared.open(url)
        }
    }

    func openSupernoteToolHelp() {
        if let url = URL(string: "https://github.com/jya-dev/supernote-tool") {
            NSWorkspace.shared.open(url)
        }
    }

    func autoDetectSupernoteTool() {
        let candidates = [
            "/opt/homebrew/bin/supernote-tool",
            "/usr/local/bin/supernote-tool",
            "\(FileManager.default.homeDirectoryForCurrentUser.path)/supernote-obsidian-sync/.venv/bin/supernote-tool"
        ]

        for candidate in candidates {
            if FileManager.default.isExecutableFile(atPath: candidate) {
                supernoteToolPath = candidate
                statusMessage = "✅ supernote-tool found."
                return
            }
        }

        if let detected = runWhich("supernote-tool") {
            supernoteToolPath = detected
            statusMessage = "✅ supernote-tool found."
            return
        }

        statusMessage = "❌ supernote-tool not found. Use Get supernote-tool for Obsidian or Choose…"
    }

    // MARK: Utility

    private func loadEnvValue(for key: String) -> String? {
        guard FileManager.default.fileExists(atPath: envURL.path),
              let text = try? String(contentsOf: envURL, encoding: .utf8)
        else {
            return nil
        }

        for line in text.components(separatedBy: .newlines) {
            if line.hasPrefix("\(key)=") {
                return String(line.dropFirst(key.count + 1))
            }
        }

        return nil
    }

    private func runWhich(_ command: String) -> String? {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/which")
        task.arguments = [command]

        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = Pipe()

        do {
            try task.run()
            task.waitUntilExit()

            guard task.terminationStatus == 0 else {
                return nil
            }

            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines)

            return output?.isEmpty == false ? output : nil
        } catch {
            return nil
        }
    }

    private static func slugify(_ value: String) -> String {
        let lowered = value.lowercased()
        let mapped = lowered.map { character -> Character in
            character.isLetter || character.isNumber ? character : "_"
        }

        return String(mapped)
            .split(separator: "_")
            .joined(separator: "_")
    }
}

// MARK: - Main Settings Window

struct SettingsView: View {
    @ObservedObject var model: SettingsViewModel

    var body: some View {
        HStack(spacing: 0) {
            sidebar

            Divider()

            detailView
        }
        .frame(width: 980, height: 720)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 18) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Supernote Sync")
                    .font(.title2)
                    .bold()

                Text("Settings")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 16)
            .padding(.top, 20)

            VStack(spacing: 6) {
                ForEach(SettingsSection.allCases) { section in
                    sidebarItem(section)
                }
            }
            .padding(.horizontal, 10)

            Spacer()

            setupMiniStatus
                .padding(.horizontal, 12)
                .padding(.bottom, 14)
        }
        .frame(width: 235)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private func sidebarItem(_ section: SettingsSection) -> some View {
        Button {
            model.selectedSection = section
        } label: {
            HStack(spacing: 10) {
                Image(systemName: section.icon)
                    .frame(width: 20)

                VStack(alignment: .leading, spacing: 2) {
                    Text(section.rawValue)
                        .font(.headline)

                    Text(section.subtitle)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                Spacer()
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 9)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(model.selectedSection == section ? Color.accentColor.opacity(0.16) : Color.clear)
            )
        }
        .buttonStyle(.plain)
    }

    private var setupMiniStatus: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: model.setupReady ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .foregroundColor(model.setupReady ? .green : .orange)

                Text(model.setupReady ? "Ready to sync" : "Setup incomplete")
                    .font(.headline)
            }

            Text(model.setupReady ? "All required settings look good." : "Some required settings need attention.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color(nsColor: .windowBackgroundColor))
        )
    }

    private var detailView: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    pageHeader

                    switch model.selectedSection {
                    case .setup:
                        setupPage
                    case .obsidianSettings:
                        obsidianSettingsPage
                    case .folders:
                        foldersPage
                    case .ocrTasks:
                        ocrTasksPage
                    case .advanced:
                        advancedPage
                    case .diagnostics:
                        diagnosticsPage
                    }
                }
                .padding(28)
            }

            Divider()

            bottomBar
        }
    }

    private var pageHeader: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(model.selectedSection.rawValue)
                .font(.largeTitle)
                .bold()

            Text(model.selectedSection.subtitle)
                .font(.callout)
                .foregroundColor(.secondary)
        }
    }

    // MARK: Pages

    private var setupPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: model.setupReady ? "Setup Complete" : "First-Time Setup",
                description: model.setupReady
                    ? "Everything required is configured. Future changes can be made in the other settings sections."
                    : "Complete one step at a time. When a step is finished, the next card appears automatically."
            ) {
                VStack(alignment: .leading, spacing: 16) {
                    setupStepDots

                    if let step = model.nextSetupStep {
                        HStack(spacing: 10) {
                            Image(systemName: step.icon)
                                .foregroundColor(.accentColor)

                            Text("Step \(step.number) of \(SetupStep.allCases.count)")
                                .font(.headline)

                            Spacer()
                        }

                        Text(step.title)
                            .font(.title2)
                            .bold()

                        Text(step.description)
                            .font(.footnote)
                            .foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    } else {
                        HStack(spacing: 10) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundColor(.green)

                            Text("Ready to sync")
                                .font(.title2)
                                .bold()
                        }

                        Text("All required setup steps are complete. You can now run sync or start the watcher from the menu bar.")
                            .font(.footnote)
                            .foregroundColor(.secondary)

                        Button("Run Diagnose") {
                            if model.savedSettingsExist {
                                CommandRunner.shared.runAndShow(["--diagnose"], title: "Diagnostics")
                            } else {
                                model.statusMessage = "Save settings first to enable diagnostics."
                            }
                        }
                        .disabled(!model.savedSettingsExist)
                    }
                }
            }

            if let step = model.nextSetupStep {
                setupStepCard(step)
            }
        }
    }

    private var setupStepDots: some View {
        HStack(spacing: 8) {
            ForEach(SetupStep.allCases) { step in
                Circle()
                    .fill(model.isSetupStepComplete(step) ? Color.green : (model.nextSetupStep == step ? Color.accentColor : Color.secondary.opacity(0.25)))
                    .frame(width: model.nextSetupStep == step ? 11 : 8, height: model.nextSetupStep == step ? 11 : 8)
                    .animation(.easeInOut(duration: 0.18), value: model.nextSetupStep?.id)
            }
        }
    }

    @ViewBuilder
    private func setupStepCard(_ step: SetupStep) -> some View {
        switch step {
        case .obsidianVault:
            SettingsCard(
                title: "Choose your Obsidian vault",
                description: "Select the root folder of your Obsidian vault. Synced Markdown files and attachments will be saved inside this vault."
            ) {
                SettingField(
                    title: "Vault folder",
                    text: $model.vaultDir,
                    buttonTitle: "Choose…",
                    action: model.chooseVaultFolder
                )

                Text("After choosing a valid vault folder, the next setup step will appear automatically.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }

        case .supernoteTool:
            SettingsCard(
                title: "Connect supernote-tool",
                description: "supernote-tool converts Supernote .note files into PDFs before OCR. The app cannot process notes without it."
            ) {
                SettingField(
                    title: "supernote-tool path",
                    text: $model.supernoteToolPath,
                    buttonTitle: "Choose…",
                    action: model.chooseSupernoteTool
                )

                HStack {
                    Button("Auto-detect") {
                        model.autoDetectSupernoteTool()
                    }

                    Button("Get supernote-tool for Obsidian") {
                        model.openSupernoteToolHelp()
                    }
                }

                Text("After a valid executable path is found, the next setup step will appear automatically.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }

        case .mistralApiKey:
            SettingsCard(
                title: "Add your Mistral API key",
                description: "Mistral OCR turns your handwritten Supernote notes into searchable Markdown text."
            ) {
                SecureField("API key", text: $model.mistralApiKey)
                    .textFieldStyle(.roundedBorder)

                Button("Get a Mistral API key") {
                    model.openMistralApiKeyPage()
                }

                Text("After entering an API key, the final setup step will appear automatically.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }

        case .folders:
            SettingsCard(
                title: "Add a Supernote folder",
                description: "Choose which Supernote folder should sync, and where it should appear in Obsidian."
            ) {
                if model.notebooks.isEmpty {
                    EmptyStateView(
                        icon: "folder.badge.plus",
                        title: "No folders configured",
                        message: "Add at least one Supernote folder to finish setup."
                    )
                }

                ForEach(model.notebooks) { notebook in
                    notebookCard(notebook)
                }

                Text("Suggested Supernote Partner folder:")
                    .font(.footnote)
                    .foregroundColor(.secondary)

                Text(model.suggestedSupernoteFolderPath)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                    .truncationMode(.middle)

                Button("+ Add Supernote Folder") {
                    model.addNotebook()
                }

                Text("After adding at least one folder, setup is complete.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }
        }
    }

    private var obsidianSettingsPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Obsidian Vault",
                description: "Choose the root folder of your Obsidian vault. All synced Markdown files and attachments will be saved relative to this folder."
            ) {
                SettingField(
                    title: "Vault folder",
                    text: $model.vaultDir,
                    buttonTitle: "Choose…",
                    action: model.chooseVaultFolder
                )
            }

            SettingsCard(
                title: "supernote-tool",
                description: "Required to convert Supernote .note files into PDFs before OCR. Without this tool, the sync app cannot process your notes."
            ) {
                SettingField(
                    title: "supernote-tool path",
                    text: $model.supernoteToolPath,
                    buttonTitle: "Choose…",
                    action: model.chooseSupernoteTool
                )

                HStack {
                    Button("Auto-detect") {
                        model.autoDetectSupernoteTool()
                    }

                    Button("Get supernote-tool for Obsidian") {
                        model.openSupernoteToolHelp()
                    }
                }
            }
        }
    }

    private var foldersPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Synced Supernote Folders",
                description: "Add each Supernote folder you want to sync. For every source folder, choose where Markdown files and attachments should go inside your Obsidian vault."
            ) {
                if model.notebooks.isEmpty {
                    EmptyStateView(
                        icon: "folder.badge.plus",
                        title: "No folders configured",
                        message: "Add a Supernote folder to start syncing it to Obsidian."
                    )
                }

                ForEach(model.notebooks) { notebook in
                    notebookCard(notebook)
                }

                Button("+ Add Supernote Folder") {
                    model.addNotebook()
                }
            }
        }
    }

    private var ocrTasksPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Mistral OCR",
                description: "Supernote notes are converted to PDF and sent to Mistral OCR. The returned text is saved as searchable Markdown in Obsidian."
            ) {
                SecureField("API key", text: $model.mistralApiKey)
                    .textFieldStyle(.roundedBorder)

                Button("Get a Mistral API key") {
                    model.openMistralApiKeyPage()
                }
            }

            SettingsCard(
                title: "Custom OCR Instruction",
                description: "Optional. Add a short instruction for how Mistral should render your notes."
            ) {
                VStack(alignment: .leading, spacing: 8) {
                    TextEditor(text: $model.customOcrInstruction)
                        .font(.system(.body, design: .default))
                        .frame(minHeight: 110)
                        .padding(6)
                        .overlay(
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(Color.secondary.opacity(0.25))
                        )

                    Text("Leave empty for the default faithful OCR behavior. Bad instructions can reduce OCR quality.")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    Text("Example: Preserve headings and bullet lists. Keep diagrams as images. Do not summarize. Keep the original wording as faithfully as possible.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            SettingsCard(
                title: "Task Conversion",
                description: "Turn handwritten or OCR-detected task lines into Obsidian-compatible checkboxes."
            ) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Example")
                        .font(.headline)

                    CodeBlock("# Buy milk")

                    Text("becomes")
                        .foregroundColor(.secondary)

                    CodeBlock("- [ ] #task Buy milk")

                    Text("Write the task marker at the beginning of a line in Supernote. During sync, that line becomes a checkbox task in Obsidian.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }

            SettingsCard(
                title: "Task Settings",
                description: "Customize how handwritten task lines are detected and tagged."
            ) {
                SettingField(
                    title: "Task marker",
                    text: $model.taskMarker
                )

                Text("The marker that tells the sync app: this line should become a task. Default: #")
                    .font(.footnote)    
                    .foregroundColor(.secondary)

                SettingField(
                    title: "Task tag",
                    text: $model.taskTag
                )

                Text("The tag added to converted tasks. Default: #task")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }
        }
    }

    private var advancedPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Advanced",
                description: "Optional safety settings for manual syncing."
            ) {
                VStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .center) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("File stability wait")
                                .font(.headline)

                            Text("Wait a few seconds before processing files so Supernote Partner has time to finish syncing.")
                                .font(.footnote)
                                .foregroundColor(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }

                        Spacer()

                        HStack(spacing: 8) {
                            TextField("10", text: $model.fileStabilityWaitSeconds)
                                .textFieldStyle(.roundedBorder)
                                .frame(width: 70)

                            Text("seconds")
                                .foregroundColor(.secondary)
                        }
                        .frame(width: 170, alignment: .trailing)
                    }

                    Divider()

                    Toggle(
                        "Require Obsidian to be running before syncing",
                        isOn: $model.openRequiresObsidianRunning
                    )

                    Text("Recommended: keep this enabled, so notes are only written while Obsidian is available.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            SettingsCard(
                title: "Manual Sync Mode",
                description: "This app now syncs only when you choose Sync Now from the menu bar."
            ) {
                VStack(alignment: .leading, spacing: 8) {
                    Label("No background watcher is shown in the release UI.", systemImage: "checkmark.circle")
                    Label("No start-at-login setup is needed.", systemImage: "checkmark.circle")
                    Label("Check interval is hidden because it is only used for background watching.", systemImage: "checkmark.circle")
                }
                .foregroundColor(.secondary)
            }
        }
    }

    private var diagnosticsPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Diagnostics",
                description: "Run checks, open logs, and troubleshoot your setup."
            ) {
                HStack {
                    Button("Run Diagnose") {
                        if model.savedSettingsExist {
                                CommandRunner.shared.runAndShow(["--diagnose"], title: "Diagnostics")
                            } else {
                                model.statusMessage = "Save settings first to enable diagnostics."
                            }
                    }

                    Button("Open Settings Folder") {
                        CommandRunner.shared.runSilently(["--open-settings"], title: "Open Settings")
                    }

                    Button("Open Log File") {
                        CommandRunner.shared.runSilently(["--open-log"], title: "Open Log")
                    }
                }
            }

            SettingsCard(
                title: "Useful Commands",
                description: "These actions use the same command-line backend as the menu bar app."
            ) {
                VStack(alignment: .leading, spacing: 10) {
                    CommandInfoRow(
                        title: "Run Diagnose",
                        description: "Checks your config, folders, API key, and supernote-tool installation."
                    )

                    CommandInfoRow(
                        title: "Open Settings Folder",
                        description: "Opens the macOS Application Support folder where config.json, .env, state files, and logs are stored."
                    )

                    CommandInfoRow(
                        title: "Open Log File",
                        description: "Shows the sync log for troubleshooting OCR, PDF conversion, and folder problems."
                    )
                }
            }
        }
    }

    // MARK: Components inside main view

    private func notebookCard(_ notebook: NotebookConfig) -> some View {
        guard let index = model.notebooks.firstIndex(where: { $0.id == notebook.id }) else {
            return AnyView(EmptyView())
        }

        return AnyView(
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(model.notebooks[index].name.isEmpty ? "Unnamed Folder" : model.notebooks[index].name)
                            .font(.title3)
                            .bold()

                        Text("Supernote folder → Obsidian folder")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }

                    Spacer()

                    Button("Remove") {
                        model.removeNotebook(notebook)
                    }
                }

                Divider()

                SettingField(
                    title: "Name",
                    text: $model.notebooks[index].name
                )

                SettingField(
                    title: "Supernote folder",
                    text: $model.notebooks[index].source_dir,
                    buttonTitle: "Choose…",
                    action: { model.chooseSupernoteFolder(for: notebook) }
                )

                SettingField(
                    title: "Obsidian Markdown folder inside vault",
                    text: $model.notebooks[index].obsidian_note_folder,
                    buttonTitle: "Choose…",
                    action: { model.chooseObsidianFolder(for: notebook) }
                )

                SettingField(
                    title: "Obsidian attachment folder inside vault",
                    text: $model.notebooks[index].attachment_folder,
                    buttonTitle: "Choose…",
                    action: { model.chooseAttachmentFolder(for: notebook) }
                )

                SettingField(
                    title: "State file",
                    text: $model.notebooks[index].state_file
                )
            }
            .padding(14)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
        )
    }

    private var bottomBar: some View {
        HStack(alignment: .center, spacing: 12) {
            ScrollView {
                Text(model.statusMessage)
                    .font(.footnote)
                    .foregroundColor(model.statusMessage.hasPrefix("❌") ? .red : .secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            .frame(maxHeight: 70)

            Spacer()

            Button("Quit Settings") {


                SettingsWindowController.shared.close()


            }



            Button("Save Settings") {


                model.save()


            }


            .keyboardShortcut(.defaultAction)
        }
        .padding(12)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

// MARK: - Reusable UI Components

// MARK: - Reusable UI Components

struct SettingsCard<Content: View>: View {
    let title: String
    let description: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 5) {
                Text(title)
                    .font(.title3)
                    .bold()

                Text(description)
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            content
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 18)
                .fill(Color(nsColor: .textBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color.primary.opacity(0.06), lineWidth: 1)
        )
    }
}

struct SettingField: View {
    let title: String
    @Binding var text: String
    var buttonTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.headline)

            HStack {
                TextField("", text: $text)
                    .textFieldStyle(.roundedBorder)

                if let buttonTitle, let action {
                    Button(buttonTitle, action: action)
                }
            }
        }
    }
}

struct SetupStepRow: View {
    let step: SetupStep
    let done: Bool
    let isCurrent: Bool
    let action: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 10) {
            Image(systemName: done ? "checkmark.circle.fill" : (isCurrent ? "exclamationmark.circle.fill" : "circle"))
                .foregroundColor(done ? .green : (isCurrent ? .orange : .secondary))
                .font(.system(size: 16, weight: .semibold))

            VStack(alignment: .leading, spacing: 2) {
                Text(step.title)
                    .font(.headline)

                Text(done ? "Done" : (isCurrent ? "Needs attention" : "Waiting"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            if !done {
                Button("Open", action: action)
            }
        }
        .padding(.vertical, 4)
    }
}

struct StatusRow: View {
    let title: String
    let ok: Bool
    let detail: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundColor(ok ? .green : .red)
                .font(.system(size: 15, weight: .semibold))

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.headline)

                Text(detail)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(2)
                    .truncationMode(.middle)
            }

            Spacer()

            if let actionTitle, let action {
                Button(actionTitle, action: action)
            }
        }
    }
}

struct CommandInfoRow: View {
    let title: String
    let description: String

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title)
                .font(.headline)

            Text(description)
                .font(.footnote)
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 4)
    }
}

struct EmptyStateView: View {
    let icon: String
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 32))
                .foregroundColor(.secondary)

            Text(title)
                .font(.headline)

            Text(message)
                .font(.footnote)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(24)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color(nsColor: .controlBackgroundColor))
        )
    }
}

struct CodeBlock: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.system(.body, design: .monospaced))
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
    }
}

// MARK: - Window Controller

@MainActor
final class SettingsWindowController: NSWindowController, NSWindowDelegate {
    static let shared = SettingsWindowController()

    private let model = SettingsViewModel()

    private init() {
        let view = SettingsView(model: model)
        let hostingView = NSHostingView(rootView: view)

        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 980, height: 720),
            styleMask: [.titled, .closable, .resizable, .miniaturizable],
            backing: .buffered,
            defer: false
        )

        window.title = "Supernote Obsidian Sync Settings"
        window.contentView = hostingView
        window.center()

        super.init(window: window)

        window.delegate = self
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func show() {
        window?.makeKeyAndOrderFront(nil)
        window?.display()
        NSApp.activate(ignoringOtherApps: true)
    }

    func showSetup() {
        model.load()
        model.selectedSection = .setup
        show()
    }
}
