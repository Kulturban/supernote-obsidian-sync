import SwiftUI
import ServiceManagement
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

enum OCRProvider: String, CaseIterable, Identifiable {
    case mistral
    case gemini
    case claude
    case openai
    case localOllama = "local_ollama"
    case hybridMarkerOlmocr = "hybrid_marker_olmocr"
    case none = "none"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .mistral:
            return "Mistral"
        case .gemini:
            return "Google Gemini"
        case .claude:
            return "Anthropic Claude"
        case .openai:
            return "OpenAI"
        case .localOllama:
            return "Local Ollama"
        case .hybridMarkerOlmocr:
            return "Hybrid Marker + Ollama — Experimental"
        case .none:
            return "No OCR (PDF Embed Only)"
        }
    }

    var isCloudVLM: Bool {
        switch self {
        case .gemini, .claude, .openai:
            return true
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            return false
        }
    }

    var defaultCloudModel: String {
        switch self {
        case .gemini:
            return "gemini-2.5-flash"
        case .claude:
            return "claude-sonnet-4-5"
        case .openai:
            return "gpt-4.1"
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            return ""
        }
    }

    var suggestedCloudModels: [String] {
        switch self {
        case .gemini:
            return ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
        case .claude:
            return ["claude-sonnet-4-5", "claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"]
        case .openai:
            return ["gpt-4.1", "gpt-4.1-mini", "gpt-4o"]
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            return []
        }
    }

    var apiKeyEnvVarName: String {
        switch self {
        case .mistral:
            return "MISTRAL_API_KEY"
        case .gemini:
            return "GEMINI_API_KEY"
        case .claude:
            return "ANTHROPIC_API_KEY"
        case .openai:
            return "OPENAI_API_KEY"
        case .localOllama, .hybridMarkerOlmocr, .none:
            return ""
        }
    }

    var apiKeyFieldLabel: String {
        switch self {
        case .mistral:
            return "Mistral API key"
        case .gemini:
            return "Gemini API key"
        case .claude:
            return "Anthropic API key"
        case .openai:
            return "OpenAI API key"
        case .localOllama, .hybridMarkerOlmocr, .none:
            return "API key"
        }
    }

    static func normalized(from rawValue: String) -> OCRProvider {
        let cleaned = rawValue.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if ["none", "disabled", "no_ocr", "off", "pdf_only"].contains(cleaned) {
            return .none
        }
        return OCRProvider(rawValue: cleaned) ?? .mistral
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
    var open_supernote_partner_before_sync: Bool
    var supernote_partner_app: String
    var supernote_partner_sync_delay_seconds: Int
    var ocr_provider: String
    var ocr_model: String
    var gemini_api_key: String
    var anthropic_api_key: String
    var openai_api_key: String
    var local_ollama_url: String
    var local_ollama_model: String
    var local_ollama_num_ctx: Int
    var local_ollama_unload_after_note: Bool
    var hybrid_marker_command: String
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
        open_supernote_partner_before_sync: false,
        supernote_partner_app: "Supernote Partner",
        supernote_partner_sync_delay_seconds: 15,
        ocr_provider: OCRProvider.localOllama.rawValue,
        ocr_model: "",
        gemini_api_key: "",
        anthropic_api_key: "",
        openai_api_key: "",
        local_ollama_url: "http://localhost:11434/api/generate",
        local_ollama_model: "richardyoung/olmocr2:7b-q8",
        local_ollama_num_ctx: 8192,
        local_ollama_unload_after_note: true,
        hybrid_marker_command: "marker_single",
        notebooks: []
    )

    enum CodingKeys: String, CodingKey {
        case vault_dir
        case supernote_tool_path
        case check_interval_seconds
        case file_stability_wait_seconds
        case task_marker
        case task_tag
        case custom_ocr_instruction
        case open_requires_obsidian_running
        case open_supernote_partner_before_sync
        case supernote_partner_app
        case supernote_partner_sync_delay_seconds
        case ocr_provider
        case ocr_model
        case gemini_api_key
        case anthropic_api_key
        case openai_api_key
        case local_ollama_url
        case local_ollama_model
        case local_ollama_num_ctx
        case local_ollama_unload_after_note
        case hybrid_marker_command
        case notebooks
    }

    init(
        vault_dir: String,
        supernote_tool_path: String,
        check_interval_seconds: Int,
        file_stability_wait_seconds: Int,
        task_marker: String,
        task_tag: String,
        custom_ocr_instruction: String?,
        open_requires_obsidian_running: Bool,
        open_supernote_partner_before_sync: Bool,
        supernote_partner_app: String,
        supernote_partner_sync_delay_seconds: Int,
        ocr_provider: String,
        ocr_model: String = "",
        gemini_api_key: String = "",
        anthropic_api_key: String = "",
        openai_api_key: String = "",
        local_ollama_url: String,
        local_ollama_model: String,
        local_ollama_num_ctx: Int,
        local_ollama_unload_after_note: Bool,
        hybrid_marker_command: String,
        notebooks: [NotebookConfig]
    ) {
        self.vault_dir = vault_dir
        self.supernote_tool_path = supernote_tool_path
        self.check_interval_seconds = check_interval_seconds
        self.file_stability_wait_seconds = file_stability_wait_seconds
        self.task_marker = task_marker
        self.task_tag = task_tag
        self.custom_ocr_instruction = custom_ocr_instruction
        self.open_requires_obsidian_running = open_requires_obsidian_running
        self.open_supernote_partner_before_sync = open_supernote_partner_before_sync
        self.supernote_partner_app = supernote_partner_app
        self.supernote_partner_sync_delay_seconds = supernote_partner_sync_delay_seconds
        self.ocr_provider = ocr_provider
        self.ocr_model = ocr_model
        self.gemini_api_key = gemini_api_key
        self.anthropic_api_key = anthropic_api_key
        self.openai_api_key = openai_api_key
        self.local_ollama_url = local_ollama_url
        self.local_ollama_model = local_ollama_model
        self.local_ollama_num_ctx = local_ollama_num_ctx
        self.local_ollama_unload_after_note = local_ollama_unload_after_note
        self.hybrid_marker_command = hybrid_marker_command
        self.notebooks = notebooks
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        self.vault_dir = try container.decodeIfPresent(String.self, forKey: .vault_dir) ?? ""
        self.supernote_tool_path = try container.decodeIfPresent(String.self, forKey: .supernote_tool_path) ?? ""
        self.check_interval_seconds = try container.decodeIfPresent(Int.self, forKey: .check_interval_seconds) ?? 60
        self.file_stability_wait_seconds = try container.decodeIfPresent(Int.self, forKey: .file_stability_wait_seconds) ?? 10
        self.task_marker = try container.decodeIfPresent(String.self, forKey: .task_marker) ?? "#"
        self.task_tag = try container.decodeIfPresent(String.self, forKey: .task_tag) ?? "#task"
        self.custom_ocr_instruction = try container.decodeIfPresent(String.self, forKey: .custom_ocr_instruction)
        self.open_requires_obsidian_running = try container.decodeIfPresent(Bool.self, forKey: .open_requires_obsidian_running) ?? true
        self.open_supernote_partner_before_sync = try container.decodeIfPresent(Bool.self, forKey: .open_supernote_partner_before_sync) ?? false
        self.supernote_partner_app = try container.decodeIfPresent(String.self, forKey: .supernote_partner_app) ?? "Supernote Partner"
        self.supernote_partner_sync_delay_seconds = try container.decodeIfPresent(Int.self, forKey: .supernote_partner_sync_delay_seconds) ?? 15
        self.ocr_provider = try container.decodeIfPresent(String.self, forKey: .ocr_provider) ?? OCRProvider.mistral.rawValue
        self.ocr_model = try container.decodeIfPresent(String.self, forKey: .ocr_model) ?? ""
        self.gemini_api_key = try container.decodeIfPresent(String.self, forKey: .gemini_api_key) ?? ""
        self.anthropic_api_key = try container.decodeIfPresent(String.self, forKey: .anthropic_api_key) ?? ""
        self.openai_api_key = try container.decodeIfPresent(String.self, forKey: .openai_api_key) ?? ""
        self.local_ollama_url = try container.decodeIfPresent(String.self, forKey: .local_ollama_url) ?? "http://localhost:11434/api/generate"
        self.local_ollama_model = try container.decodeIfPresent(String.self, forKey: .local_ollama_model) ?? "richardyoung/olmocr2:7b-q8"
        self.local_ollama_num_ctx = try container.decodeIfPresent(Int.self, forKey: .local_ollama_num_ctx) ?? 8192
        self.local_ollama_unload_after_note = try container.decodeIfPresent(Bool.self, forKey: .local_ollama_unload_after_note) ?? true
        self.hybrid_marker_command = try container.decodeIfPresent(String.self, forKey: .hybrid_marker_command) ?? "marker_single"
        self.notebooks = try container.decodeIfPresent([NotebookConfig].self, forKey: .notebooks) ?? []
    }
}

enum SettingsSection: String, CaseIterable, Identifiable {
    case setup = "Setup"
    case obsidianSettings = "Obsidian Settings"
    case folders = "Folders"
    case ocrTasks = "OCR & Tasks"
    case advanced = "Advanced"
    case diagnostics = "About & Diagnose"

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
    case ocrProvider
    case folders

    var id: String { rawValue }

    var number: Int {
        switch self {
        case .obsidianVault:
            return 1
        case .supernoteTool:
            return 2
        case .ocrProvider:
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
        case .ocrProvider:
            return "Choose OCR provider"
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
        case .ocrProvider:
            return "Choose how Supsidian should turn handwriting into searchable Markdown text."
        case .folders:
            return "Choose which Supernote folders should sync, and where they should appear in Obsidian."
        }
    }

    var buttonTitle: String {
        switch self {
        case .obsidianVault, .supernoteTool:
            return "Open Obsidian Settings"
        case .ocrProvider:
            return "Open OCR & Tasks"
        case .folders:
            return "Open Folders"
        }
    }

    var targetSection: SettingsSection {
        switch self {
        case .obsidianVault, .supernoteTool:
            return .obsidianSettings
        case .ocrProvider:
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
        case .ocrProvider:
            return "text.viewfinder"
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
    @Published var openSupernotePartnerBeforeSync = false
    @Published var supernotePartnerApp = "Supernote Partner"
    @Published var supernotePartnerSyncDelaySeconds = "15"
    @Published var ocrProvider = OCRProvider.localOllama.rawValue
    @Published var ocrModel = ""
    @Published var geminiApiKey = ""
    @Published var anthropicApiKey = ""
    @Published var openaiApiKey = ""
    @Published var showCloudApiKey = false
    @Published var isTestingCloudConnection = false
    @Published var cloudConnectionTestMessage = ""
    @Published var cloudConnectionTestSucceeded: Bool? = nil
    @Published var localOllamaURL = "http://localhost:11434/api/generate"
    @Published var localOllamaModel = "richardyoung/olmocr2:7b-q8"
    @Published var localOllamaNumCtx = "8192"
    @Published var localOllamaUnloadAfterNote = true
    @Published var hybridMarkerCommand = "marker_single"
    @Published var mistralApiKey = ""
    @Published var notebooks: [NotebookConfig] = []
    @Published var statusMessage = ""
    @Published var localOCRStatusMessage = ""
    @Published var isRunningLocalOCRCommand = false
    @Published var isInstallingOllamaModel = false
    @Published var ollamaInstallProgress: Double? = nil
    @Published var startAtLoginEnabled = false
    @Published var selectedSection: SettingsSection = .setup

    private let appSupportDir: URL
    private let configURL: URL
    private let envURL: URL

    private var launchAgentURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library")
            .appendingPathComponent("LaunchAgents")
            .appendingPathComponent("com.kulturban.supsidian.login.plist")
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
                open_supernote_partner_before_sync: openSupernotePartnerBeforeSync,
                supernote_partner_app: supernotePartnerApp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "Supernote Partner"
                    : supernotePartnerApp.trimmingCharacters(in: .whitespacesAndNewlines),
                supernote_partner_sync_delay_seconds: parsedSupernotePartnerSyncDelaySeconds ?? 15,
                ocr_provider: selectedOCRProvider.rawValue,
                ocr_model: ocrModel.trimmingCharacters(in: .whitespacesAndNewlines),
                gemini_api_key: geminiApiKey.trimmingCharacters(in: .whitespacesAndNewlines),
                anthropic_api_key: anthropicApiKey.trimmingCharacters(in: .whitespacesAndNewlines),
                openai_api_key: openaiApiKey.trimmingCharacters(in: .whitespacesAndNewlines),
                local_ollama_url: localOllamaURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "http://localhost:11434/api/generate"
                    : localOllamaURL.trimmingCharacters(in: .whitespacesAndNewlines),
                local_ollama_model: localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "richardyoung/olmocr2:7b-q8"
                    : localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines),
                local_ollama_num_ctx: parsedLocalOllamaNumCtx ?? 8192,
                local_ollama_unload_after_note: localOllamaUnloadAfterNote,
                hybrid_marker_command: hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? "marker_single"
                    : hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines),
                notebooks: notebooks
            )

            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]

            let data = try encoder.encode(config)
            try data.write(to: configURL, options: [.atomic])
            try FileManager.default.setAttributes(
                [.posixPermissions: 0o600],
                ofItemAtPath: configURL.path
            )

            let trimmedMistralKey = mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
            if selectedOCRProvider == .mistral || !trimmedMistralKey.isEmpty {
                let envText = "MISTRAL_API_KEY=\(trimmedMistralKey)\n"
                try envText.write(to: envURL, atomically: true, encoding: .utf8)
                try FileManager.default.setAttributes(
                    [.posixPermissions: 0o600],
                    ofItemAtPath: envURL.path
                )
            }

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
        let trimmedPartnerApp = config.supernote_partner_app.trimmingCharacters(in: .whitespacesAndNewlines)
        openSupernotePartnerBeforeSync = config.open_supernote_partner_before_sync
        supernotePartnerApp = trimmedPartnerApp.isEmpty ? "Supernote Partner" : trimmedPartnerApp
        supernotePartnerSyncDelaySeconds = String(
            config.supernote_partner_sync_delay_seconds > 0
                && !UInt64(config.supernote_partner_sync_delay_seconds).multipliedReportingOverflow(by: 1_000_000_000).overflow
                ? config.supernote_partner_sync_delay_seconds
                : 15
        )
        ocrProvider = OCRProvider.normalized(from: config.ocr_provider).rawValue
        ocrModel = config.ocr_model
        geminiApiKey = config.gemini_api_key
        anthropicApiKey = config.anthropic_api_key
        openaiApiKey = config.openai_api_key
        localOllamaURL = config.local_ollama_url.isEmpty ? "http://localhost:11434/api/generate" : config.local_ollama_url
        localOllamaModel = config.local_ollama_model.isEmpty ? "richardyoung/olmocr2:7b-q8" : config.local_ollama_model
        localOllamaNumCtx = String(config.local_ollama_num_ctx > 0 ? config.local_ollama_num_ctx : 8192)
        localOllamaUnloadAfterNote = config.local_ollama_unload_after_note
        hybridMarkerCommand = config.hybrid_marker_command.isEmpty ? "marker_single" : config.hybrid_marker_command
        notebooks = config.notebooks
    }

    // MARK: Validation

    func validateSettings() -> [String] {
        var errors: [String] = []

        switch selectedOCRProvider {
        case .mistral:
            let trimmedKey = mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines)

            if trimmedKey.isEmpty {
                errors.append("Mistral AI API key is missing.")
            } else if trimmedKey.contains(" ") || trimmedKey.count < 20 {
                errors.append("Mistral AI API key does not look valid.")
            }
        case .gemini, .claude, .openai:
            let resolvedKey = resolvedCloudApiKey(for: selectedOCRProvider)
            if resolvedKey.isEmpty {
                errors.append("\(selectedOCRProvider.displayName) API key is missing (enter it in settings or set \(selectedOCRProvider.apiKeyEnvVarName)).")
            } else if resolvedKey.contains(" ") {
                errors.append("\(selectedOCRProvider.displayName) API key does not look valid.")
            }
        case .localOllama, .hybridMarkerOlmocr:
            if localOllamaURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Ollama URL is missing.")
            }

            if localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Ollama model is missing.")
            }

            if (parsedLocalOllamaNumCtx ?? 0) <= 0 {
                errors.append("Ollama context size must be a positive number.")
            }

            if selectedOCRProvider == .hybridMarkerOlmocr &&
                hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Marker command is missing.")
            }
        case .none:
            break
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

        if openSupernotePartnerBeforeSync {
            if supernotePartnerApp.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                errors.append("Supernote Partner app name/path is missing.")
            }

            if parsedSupernotePartnerSyncDelaySeconds == nil {
                errors.append("Supernote Partner sync delay must be a positive number.")
            }
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
                "OCR provider",
                isSetupStepComplete(.ocrProvider),
                selectedOCRProvider.displayName,
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
        case .ocrProvider:
            switch selectedOCRProvider {
            case .mistral:
                return !mistralApiKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .gemini, .claude, .openai:
                return !resolvedCloudApiKey(for: selectedOCRProvider).isEmpty
            case .localOllama:
                return !localOllamaURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && !localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && (parsedLocalOllamaNumCtx ?? 0) > 0
            case .hybridMarkerOlmocr:
                return !localOllamaURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && !localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    && (parsedLocalOllamaNumCtx ?? 0) > 0
                    && !hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .none:
                return true
            }
        case .folders:
            return !notebooks.isEmpty
        }
    }

    var selectedOCRProvider: OCRProvider {
        get {
            OCRProvider.normalized(from: ocrProvider)
        }
        set {
            let previous = OCRProvider.normalized(from: ocrProvider)
            ocrProvider = newValue.rawValue
            if previous != newValue {
                cloudConnectionTestMessage = ""
                cloudConnectionTestSucceeded = nil
                let trimmedModel = ocrModel.trimmingCharacters(in: .whitespacesAndNewlines)
                if previous.isCloudVLM && newValue.isCloudVLM && !trimmedModel.isEmpty {
                    let previousDefaults = Set([previous.defaultCloudModel] + previous.suggestedCloudModels)
                    if previousDefaults.contains(trimmedModel) {
                        ocrModel = ""
                    }
                }
            }
        }
    }

    // MARK: Cloud VLM Helpers & Connection Test

    func effectiveCloudModel(for provider: OCRProvider) -> String {
        let trimmed = ocrModel.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? provider.defaultCloudModel : trimmed
    }

    func configuredCloudApiKey(for provider: OCRProvider) -> String {
        switch provider {
        case .gemini:
            return geminiApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        case .claude:
            return anthropicApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        case .openai:
            return openaiApiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            return ""
        }
    }

    func environmentCloudApiKey(for provider: OCRProvider) -> String? {
        let envVar = provider.apiKeyEnvVarName
        guard !envVar.isEmpty else {
            return nil
        }

        if let processValue = ProcessInfo.processInfo.environment[envVar]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !processValue.isEmpty {
            return processValue
        }

        if let envFileValue = loadEnvValue(for: envVar)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !envFileValue.isEmpty {
            return envFileValue
        }

        return nil
    }

    func resolvedCloudApiKey(for provider: OCRProvider) -> String {
        let configured = configuredCloudApiKey(for: provider)
        if !configured.isEmpty {
            return configured
        }
        return environmentCloudApiKey(for: provider) ?? ""
    }

    func hasCloudApiKeyFromEnvironmentOnly(for provider: OCRProvider) -> Bool {
        configuredCloudApiKey(for: provider).isEmpty && environmentCloudApiKey(for: provider) != nil
    }

    func testCloudProviderConnection() async {
        let provider = selectedOCRProvider
        guard provider.isCloudVLM else {
            return
        }

        let apiKey = resolvedCloudApiKey(for: provider)
        let model = effectiveCloudModel(for: provider)

        guard !apiKey.isEmpty else {
            cloudConnectionTestSucceeded = false
            cloudConnectionTestMessage = "❌ \(provider.displayName) API key is missing. Enter a key above or set \(provider.apiKeyEnvVarName)."
            return
        }

        isTestingCloudConnection = true
        cloudConnectionTestSucceeded = nil
        cloudConnectionTestMessage = "Testing connection to \(provider.displayName) (\(model))…"
        defer { isTestingCloudConnection = false }

        do {
            let request = try buildCloudConnectionTestRequest(
                provider: provider,
                model: model,
                apiKey: apiKey
            )
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let httpResponse = response as? HTTPURLResponse else {
                cloudConnectionTestSucceeded = false
                cloudConnectionTestMessage = "❌ Unexpected non-HTTP response from \(provider.displayName)."
                return
            }

            if (200...299).contains(httpResponse.statusCode) {
                cloudConnectionTestSucceeded = true
                cloudConnectionTestMessage = "✅ Connected to \(provider.displayName) — model '\(model)' is ready."
            } else {
                let detail = Self.extractAPIErrorMessage(from: data)
                cloudConnectionTestSucceeded = false
                switch httpResponse.statusCode {
                case 401, 403:
                    cloudConnectionTestMessage = "❌ Invalid API key or insufficient permissions (HTTP \(httpResponse.statusCode)): \(detail)"
                case 404:
                    cloudConnectionTestMessage = "❌ Model '\(model)' not found (HTTP 404): \(detail)"
                case 429:
                    cloudConnectionTestMessage = "❌ Rate limit or quota exceeded (HTTP 429): \(detail)"
                default:
                    cloudConnectionTestMessage = "❌ Connection failed (HTTP \(httpResponse.statusCode)): \(detail)"
                }
            }
        } catch {
            cloudConnectionTestSucceeded = false
            cloudConnectionTestMessage = "❌ Connection error: \(error.localizedDescription)"
        }
    }

    private func buildCloudConnectionTestRequest(
        provider: OCRProvider,
        model: String,
        apiKey: String
    ) throws -> URLRequest {
        let encodedModel = model.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? model
        let urlString: String

        switch provider {
        case .gemini:
            urlString = "https://generativelanguage.googleapis.com/v1beta/models/\(encodedModel)"
        case .claude:
            urlString = "https://api.anthropic.com/v1/models/\(encodedModel)"
        case .openai:
            urlString = "https://api.openai.com/v1/models/\(encodedModel)"
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            throw URLError(.unsupportedURL)
        }

        guard let url = URL(string: urlString) else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.timeoutInterval = 20

        switch provider {
        case .gemini:
            request.setValue(apiKey, forHTTPHeaderField: "x-goog-api-key")
        case .claude:
            request.setValue(apiKey, forHTTPHeaderField: "x-api-key")
            request.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        case .openai:
            request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            break
        }

        return request
    }

    private static func extractAPIErrorMessage(from data: Data) -> String {
        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
            if let errorObj = json["error"] as? [String: Any],
               let message = errorObj["message"] as? String,
               !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return message.trimmingCharacters(in: .whitespacesAndNewlines)
            }
            if let message = json["message"] as? String,
               !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return message.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }

        let rawText = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if rawText.isEmpty {
            return "No additional details returned."
        }
        return String(rawText.prefix(240))
    }

    private var parsedLocalOllamaNumCtx: Int? {
        Int(localOllamaNumCtx.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    private var parsedSupernotePartnerSyncDelaySeconds: Int? {
        guard let value = Int(supernotePartnerSyncDelaySeconds.trimmingCharacters(in: .whitespacesAndNewlines)),
              value > 0,
              !UInt64(value).multipliedReportingOverflow(by: 1_000_000_000).overflow
        else {
            return nil
        }

        return value
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
        if #available(macOS 13.0, *) {
            startAtLoginEnabled = SMAppService.mainApp.status == .enabled
        } else {
            startAtLoginEnabled = FileManager.default.fileExists(atPath: launchAgentURL.path)
        }
    }

    func setStartAtLogin(_ enabled: Bool) {
        if #available(macOS 13.0, *) {
            do {
                if enabled {
                    try SMAppService.mainApp.register()
                    startAtLoginEnabled = true
                    statusMessage = "✅ Supsidian will open at login."
                } else {
                    try SMAppService.mainApp.unregister()
                    startAtLoginEnabled = false
                    statusMessage = "✅ Supsidian will not open at login."
                }
            } catch {
                refreshStartAtLoginStatus()
                statusMessage = "❌ Failed to update login setting: \(error.localizedDescription)"
            }

            return
        }

        // Fallback for older macOS versions.
        do {
            let launchAgentsDir = launchAgentURL.deletingLastPathComponent()

            try FileManager.default.createDirectory(
                at: launchAgentsDir,
                withIntermediateDirectories: true
            )

            if enabled {
                let plist = """
                <?xml version="1.0" encoding="UTF-8"?>
                <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
                <plist version="1.0">
                <dict>
                    <key>Label</key>
                    <string>com.kulturban.supsidian.login</string>

                    <key>ProgramArguments</key>
                    <array>
                        <string>/Applications/Supsidian.app/Contents/MacOS/Supsidian</string>
                    </array>

                    <key>RunAtLoad</key>
                    <true/>
                </dict>
                </plist>
                """

                try plist.write(to: launchAgentURL, atomically: true, encoding: .utf8)
                startAtLoginEnabled = true
                statusMessage = "✅ Supsidian will open at login."
            } else {
                if FileManager.default.fileExists(atPath: launchAgentURL.path) {
                    try FileManager.default.removeItem(at: launchAgentURL)
                }

                startAtLoginEnabled = false
                statusMessage = "✅ Supsidian will not open at login."
            }
        } catch {
            refreshStartAtLoginStatus()
            statusMessage = "❌ Failed to update login setting: \(error.localizedDescription)"
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

    func openOllamaDownloadPage() {
        if let url = URL(string: "https://ollama.com/download") {
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

    func checkLocalOCRDependencies() async {
        guard !isRunningLocalOCRCommand else { return }

        isRunningLocalOCRCommand = true
        localOCRStatusMessage = "Checking local OCR setup…"
        defer {
            isRunningLocalOCRCommand = false
        }

        let model = localOllamaModelName

        guard let ollamaPath = resolveExecutable("ollama") else {
            localOCRStatusMessage = """
            ❌ Ollama not found.
            Install Ollama first, then run: ollama pull \(model)
            """
            return
        }

        var lines = ["✅ Ollama found: \(ollamaPath)"]

        let listResult = await runProcessCapture(
            executable: ollamaPath,
            arguments: ["list"]
        )

        if listResult.exitCode == 0 {
            if listResult.output.contains(model) {
                lines.append("✅ Ollama model installed: \(model)")
            } else {
                lines.append("❌ Ollama model missing: \(model)")
                lines.append("Run: ollama pull \(model)")
            }
        } else {
            lines.append("❌ Could not list Ollama models.")
            lines.append(listResult.output.isEmpty ? "Make sure Ollama is running." : listResult.output)
        }

        if selectedOCRProvider == .hybridMarkerOlmocr {
            let markerCommand = hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "marker_single"
                : hybridMarkerCommand.trimmingCharacters(in: .whitespacesAndNewlines)

            if let markerPath = resolveExecutable(markerCommand) {
                lines.append("✅ Marker command found: \(markerPath)")
            } else {
                lines.append("❌ Marker command not found: \(markerCommand)")
                lines.append("Use an absolute hybrid_marker_command path if the app cannot find marker_single.")
            }
        }

        localOCRStatusMessage = lines.joined(separator: "\n")
    }

    func installOllamaModel() async {
        guard !isRunningLocalOCRCommand else { return }

        let model = localOllamaModelName

        guard let ollamaPath = resolveExecutable("ollama") else {
            localOCRStatusMessage = """
            ❌ Ollama was not found.
            Install Ollama first, then try again.
            """
            return
        }

        isRunningLocalOCRCommand = true
        isInstallingOllamaModel = true
        ollamaInstallProgress = nil
        localOCRStatusMessage = "Installing Ollama model… This can take a while.\n\(model)"

        final class PullStateGuard: @unchecked Sendable {
            private let lock = NSLock()
            private var finished = false

            nonisolated init() {}

            nonisolated var isFinished: Bool {
                lock.lock()
                defer { lock.unlock() }
                return finished
            }

            nonisolated func markFinished() {
                lock.lock()
                finished = true
                lock.unlock()
            }
        }

        let stateGuard = PullStateGuard()

        let result = await runProcessCapture(
            executable: ollamaPath,
            arguments: ["pull", model],
            onOutputChunk: { [weak self] recentChunk in
                guard !stateGuard.isFinished,
                      let snapshot = Self.parseOllamaPullProgress(from: recentChunk)
                else {
                    return
                }

                Task { @MainActor [weak self] in
                    guard let self, !stateGuard.isFinished else { return }
                    if let fraction = snapshot.fractionCompleted {
                        if let current = self.ollamaInstallProgress {
                            self.ollamaInstallProgress = max(current, fraction)
                        } else {
                            self.ollamaInstallProgress = fraction
                        }
                    }
                    if !snapshot.statusLine.isEmpty {
                        self.localOCRStatusMessage = "Installing Ollama model: \(model)\n\(snapshot.statusLine)"
                    }
                }
            }
        )

        stateGuard.markFinished()
        isInstallingOllamaModel = false
        isRunningLocalOCRCommand = false

        if result.exitCode == 0 {
            ollamaInstallProgress = 1.0
            localOCRStatusMessage = "✅ Ollama model installed: \(model)"
        } else {
            ollamaInstallProgress = nil
            let cleanOutput = Self.stripANSIEscapeCodes(from: result.output)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            localOCRStatusMessage = """
            ❌ Failed to install Ollama model: \(model)
            \(cleanOutput)
            """
        }
    }

    func installMarker() async {
        guard !isRunningLocalOCRCommand else { return }

        isRunningLocalOCRCommand = true
        defer {
            isRunningLocalOCRCommand = false
        }

        let projectDirectory = markerProjectDirectory
        let markerVenvDirectory = "\(projectDirectory)/.venv-marker-ocr"
        let venvPython = "\(markerVenvDirectory)/bin/python"
        let markerPath = "\(markerVenvDirectory)/bin/marker_single"

        let pythonCandidates = [
            "/opt/homebrew/bin/python3.12",
            "/usr/local/bin/python3.12"
        ]

        let pythonPath = pythonCandidates.first {
            FileManager.default.isExecutableFile(atPath: $0)
        } ?? runWhich("python3.12")

        guard let pythonPath else {
            localOCRStatusMessage = "❌ Python 3.12 was not found. Install it first with: brew install python@3.12"
            return
        }

        localOCRStatusMessage = """
        Installing Marker into local project environment…
        \(markerVenvDirectory)
        """

        let venvResult = await runProcessCapture(
            executable: pythonPath,
            arguments: ["-m", "venv", markerVenvDirectory]
        )
        guard venvResult.exitCode == 0 else {
            localOCRStatusMessage = """
            ❌ Failed to create Marker Python environment.
            \(venvResult.output)
            """
            return
        }

        localOCRStatusMessage = "Upgrading pip in Marker environment…"
        let pipUpgradeResult = await runProcessCapture(
            executable: venvPython,
            arguments: ["-m", "pip", "install", "--upgrade", "pip"]
        )
        guard pipUpgradeResult.exitCode == 0 else {
            localOCRStatusMessage = """
            ❌ Failed to upgrade pip in Marker environment.
            \(pipUpgradeResult.output)
            """
            return
        }

        localOCRStatusMessage = "Installing Marker… This can take a while."
        let markerInstallResult = await runProcessCapture(
            executable: venvPython,
            arguments: ["-m", "pip", "install", "marker-pdf"]
        )
        guard markerInstallResult.exitCode == 0 else {
            localOCRStatusMessage = """
            ❌ Failed to install Marker.
            \(markerInstallResult.output)
            """
            return
        }

        if FileManager.default.isExecutableFile(atPath: markerPath) {
            hybridMarkerCommand = markerPath
            localOCRStatusMessage = "✅ Marker installed. Marker command set to: \(markerPath)"
        } else {
            localOCRStatusMessage = """
            Marker install finished, but marker_single was not found at:
            \(markerPath)

            \(markerInstallResult.output)
            """
        }
    }

    // MARK: Utility

    var localOllamaModelName: String {
        let trimmed = localOllamaModel.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "richardyoung/olmocr2:7b-q8" : trimmed
    }

    private var markerProjectDirectory: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("supernote-obsidian-sync")
            .path
    }

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

    private func resolveExecutable(_ command: String) -> String? {
        let trimmed = command.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return nil
        }

        if trimmed.hasPrefix("/"),
           FileManager.default.isExecutableFile(atPath: trimmed) {
            return trimmed
        }

        if let detected = runWhich(trimmed) {
            return detected
        }

        let commandName = URL(fileURLWithPath: trimmed).lastPathComponent
        let candidates = [
            "/opt/homebrew/bin/\(commandName)",
            "/usr/local/bin/\(commandName)",
            "/usr/bin/\(commandName)",
            "/bin/\(commandName)"
        ]

        return candidates.first {
            FileManager.default.isExecutableFile(atPath: $0)
        }
    }

    private nonisolated func runProcessCapture(
        executable: String,
        arguments: [String],
        onOutputChunk: (@Sendable (String) -> Void)? = nil
    ) async -> (exitCode: Int32, output: String) {
        await Task.detached(priority: .userInitiated) {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: executable)
            task.arguments = arguments

            let outputPipe = Pipe()
            let errorPipe = Pipe()
            task.standardOutput = outputPipe
            task.standardError = errorPipe

            let stdoutCollector = ProcessChunkCollector(onOutputChunk: onOutputChunk)
            let stderrCollector = ProcessChunkCollector(onOutputChunk: onOutputChunk)
            let outputHandle = outputPipe.fileHandleForReading
            let errorHandle = errorPipe.fileHandleForReading

            outputHandle.readabilityHandler = { handle in
                let chunk = handle.availableData
                if chunk.isEmpty {
                    handle.readabilityHandler = nil
                } else {
                    stdoutCollector.append(chunk)
                }
            }

            errorHandle.readabilityHandler = { handle in
                let chunk = handle.availableData
                if chunk.isEmpty {
                    handle.readabilityHandler = nil
                } else {
                    stderrCollector.append(chunk)
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

                let remainingOut = outputHandle.readDataToEndOfFile()
                let remainingErr = errorHandle.readDataToEndOfFile()

                let output = stdoutCollector.finish(remainingChunk: remainingOut)
                let error = stderrCollector.finish(remainingChunk: remainingErr)
                let combined = [output, error]
                    .joined(separator: "\n")
                    .trimmingCharacters(in: .whitespacesAndNewlines)

                if combined.count > 3000 {
                    return (task.terminationStatus, String(combined.suffix(3000)))
                }

                return (task.terminationStatus, combined)
            } catch {
                outputHandle.readabilityHandler = nil
                errorHandle.readabilityHandler = nil
                return (-1, error.localizedDescription)
            }
        }.value
    }

    nonisolated static func stripANSIEscapeCodes(from text: String) -> String {
        var result = text
        let patterns = [
            "\\u{001B}\\[[0-9;?]*[ -/]*[@-~]",
            "\\u{001B}\\][^\\u{0007}\\u{001B}]*(?:\\u{0007}|\\u{001B}\\\\)",
            "\\u{001B}[@-Z\\\\-_]"
        ]
        for pattern in patterns {
            if let regex = try? NSRegularExpression(pattern: pattern) {
                let range = NSRange(result.startIndex..<result.endIndex, in: result)
                result = regex.stringByReplacingMatches(in: result, range: range, withTemplate: "")
            }
        }
        return result
    }

    nonisolated static func parseOllamaPullProgress(
        from rawChunk: String
    ) -> (fractionCompleted: Double?, statusLine: String)? {
        // Turn cursor-positioning CSI sequences into carriage returns so line updates split cleanly.
        var normalized = rawChunk
        if let cursorRegex = try? NSRegularExpression(pattern: "\\u{001B}\\[[0-9;]*[GKJ]") {
            let range = NSRange(normalized.startIndex..<normalized.endIndex, in: normalized)
            normalized = cursorRegex.stringByReplacingMatches(in: normalized, range: range, withTemplate: "\r")
        }

        let stripped = stripANSIEscapeCodes(from: normalized)
        let rawSegments = stripped.components(separatedBy: CharacterSet(charactersIn: "\r\n"))

        var latestStatusLine = ""
        var latestFraction: Double? = nil
        let percentRegex = try? NSRegularExpression(pattern: "(?:^|\\s)(\\d{1,3})\\s*%")
        let barRegex = try? NSRegularExpression(pattern: "(?:▕[^▏]*▏|\\[[=#>\\s.-]+\\]|[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏])")
        let spaceRegex = try? NSRegularExpression(pattern: "\\s{2,}")

        for segment in rawSegments {
            var cleaned = segment
            if let barRegex {
                let range = NSRange(cleaned.startIndex..<cleaned.endIndex, in: cleaned)
                cleaned = barRegex.stringByReplacingMatches(in: cleaned, range: range, withTemplate: " ")
            }
            if let spaceRegex {
                let range = NSRange(cleaned.startIndex..<cleaned.endIndex, in: cleaned)
                cleaned = spaceRegex.stringByReplacingMatches(in: cleaned, range: range, withTemplate: " ")
            }
            cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !cleaned.isEmpty else { continue }

            latestStatusLine = cleaned

            if let percentRegex {
                let range = NSRange(cleaned.startIndex..<cleaned.endIndex, in: cleaned)
                let matches = percentRegex.matches(in: cleaned, range: range)
                if let lastMatch = matches.last,
                   lastMatch.numberOfRanges > 1,
                   let valueRange = Range(lastMatch.range(at: 1), in: cleaned),
                   let percentValue = Int(cleaned[valueRange]) {
                    let clamped = min(max(percentValue, 0), 100)
                    latestFraction = Double(clamped) / 100.0
                }
            }

            let lower = cleaned.lowercased()
            if lower.contains("verifying sha256")
                || lower.contains("writing manifest")
                || lower == "success" {
                latestFraction = 1.0
            } else if lower.contains("pulling manifest") && latestFraction == nil {
                latestFraction = 0.0
            }
        }

        guard !latestStatusLine.isEmpty || latestFraction != nil else {
            return nil
        }

        return (latestFraction, latestStatusLine)
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
                Text("Supsidian")
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
        let isSelected = model.selectedSection == section

        return HStack(spacing: 10) {
            Image(systemName: section.icon)
                .frame(width: 20)
                .foregroundColor(isSelected ? .accentColor : .primary)

            VStack(alignment: .leading, spacing: 2) {
                Text(section.rawValue)
                    .font(.headline)
                    .foregroundColor(.primary)

                Text(section.subtitle)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(isSelected ? Color.accentColor.opacity(0.16) : Color.clear)
        )
        .onTapGesture {
            model.selectedSection = section
        }
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

        case .ocrProvider:
            SettingsCard(
                title: "Choose OCR provider",
                description: "Choose how Supsidian should turn your handwritten Supernote notes into searchable Markdown text."
            ) {
                ocrProviderSettingsContent(showCustomInstruction: false)

                Text("After the selected OCR provider has its required fields, the final setup step will appear automatically.")
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

    @ViewBuilder
    private func ocrProviderSettingsContent(showCustomInstruction: Bool) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            Picker(
                "OCR provider",
                selection: Binding(
                    get: { model.selectedOCRProvider },
                    set: { model.selectedOCRProvider = $0 }
                )
            ) {
                ForEach(OCRProvider.allCases) { provider in
                    Text(provider.displayName).tag(provider)
                }
            }
            .pickerStyle(.menu)

            Divider()

            switch model.selectedOCRProvider {
            case .mistral:
                VStack(alignment: .leading, spacing: 12) {
                    providerExplanation([
                        "Cloud OCR.",
                        "Easiest setup if you already have a Mistral API key.",
                        "Sends note/PDF content to Mistral’s OCR API.",
                        "Good general quality.",
                        "API usage/costs may apply.",
                        "Requires MISTRAL_API_KEY."
                    ])

                    SecureField("Mistral API key", text: $model.mistralApiKey)
                        .textFieldStyle(.roundedBorder)

                    Button("Get a Mistral API key") {
                        model.openMistralApiKeyPage()
                    }

                    if showCustomInstruction {
                        customOCRInstructionEditor
                    }
                }

            case .gemini, .claude, .openai:
                cloudVLMProviderSettingsView(
                    for: model.selectedOCRProvider,
                    showCustomInstruction: showCustomInstruction
                )

            case .localOllama:
                VStack(alignment: .leading, spacing: 12) {
                    providerExplanation([
                        "Local OCR on this Mac using Ollama.",
                        "Requires Ollama running locally.",
                        "Requires model \(model.localOllamaModelName).",
                        "Does not send note pages to cloud APIs.",
                        "Heavier/slower than cloud OCR.",
                        "Good for private/local handwriting OCR."
                    ])

                    SettingField(title: "Ollama URL", text: $model.localOllamaURL)
                    localOllamaModelPickerField
                    SettingField(title: "Context size", text: $model.localOllamaNumCtx)
                    Toggle("Unload Ollama model after each note", isOn: $model.localOllamaUnloadAfterNote)
                    Text("Recommended for 16 GB Macs to free memory after each processed note. Disable for faster batch processing.")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    Text("Requires Ollama and:\nollama pull \(model.localOllamaModelName)")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.secondary)

                    localOCRActionButtons()
                }

            case .hybridMarkerOlmocr:
                VStack(alignment: .leading, spacing: 12) {
                    providerExplanation(
                        [
                            "Experimental advanced mode.",
                            "Uses Ollama for local OCR (with sequential RAM unload before Marker on 16 GB Macs).",
                            "Uses Marker to extract layout, visuals, tables, and diagrams (plus Qwen3-VL sketch fallback when Marker finds none).",
                            "Best for visual notes with drawings or structure.",
                            "Hardest to install.",
                            "marker_single may need an absolute path."
                        ],
                        color: .orange
                    )

                    SettingField(title: "Ollama URL", text: $model.localOllamaURL)
                    localOllamaModelPickerField
                    SettingField(title: "Context size", text: $model.localOllamaNumCtx)
                    Toggle("Unload Ollama model after each note", isOn: $model.localOllamaUnloadAfterNote)
                    Text("Recommended for 16 GB Macs to free memory before Marker runs and after each processed note.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                    SettingField(title: "Marker command", text: $model.hybridMarkerCommand)

                    Text("Experimental. Requires Marker/marker_single. If Supsidian app or LaunchAgent cannot find marker_single, use an absolute path.")
                        .font(.footnote)
                        .foregroundColor(.orange)

                    Text("Hybrid Marker uses a low-memory profile by default for 16 GB Macs.")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    Text("Also requires Ollama and:\nollama pull \(model.localOllamaModelName)")
                        .font(.system(.caption, design: .monospaced))
                        .foregroundColor(.secondary)

                    Text("Marker is not installed silently. The Install Marker button creates a local project environment and installs Marker there. If the app cannot find marker_single, use an absolute path.")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    markerInstallationHelp()

                    Button("Install Marker") {
                        Task {
                            await model.installMarker()
                        }
                    }
                    .disabled(model.isRunningLocalOCRCommand)

                    localOCRActionButtons()
                }

            case .none:
                VStack(alignment: .leading, spacing: 12) {
                    providerExplanation([
                        "OCR disabled.",
                        "Converts each Supernote .note file into a PDF attachment.",
                        "Automatically creates a companion Markdown note with frontmatter and a ![[<Note>.pdf]] embed.",
                        "Preserves existing manually edited Markdown notes.",
                        "Does not require a Mistral API key, Ollama, or Marker."
                    ])
                }
            }
        }
    }

    private var localOllamaModelPickerField: some View {
        VStack(alignment: .leading, spacing: 6) {
            SettingField(title: "Ollama model", text: $model.localOllamaModel)

            HStack(spacing: 6) {
                Text("Quick select:")
                    .font(.caption)
                    .foregroundColor(.secondary)

                Button("qwen3-vl:8b (Recommended — 16 GB)") {
                    model.localOllamaModel = "qwen3-vl:8b"
                }
                .buttonStyle(.bordered)
                .controlSize(.small)

                Button("richardyoung/olmocr2:7b-q8") {
                    model.localOllamaModel = "richardyoung/olmocr2:7b-q8"
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
    }

    private var customOCRInstructionEditor: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()

            Text("Custom OCR Instruction")
                .font(.headline)

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

    private func cloudApiKeyBinding(for provider: OCRProvider) -> Binding<String> {
        switch provider {
        case .gemini:
            return $model.geminiApiKey
        case .claude:
            return $model.anthropicApiKey
        case .openai:
            return $model.openaiApiKey
        case .mistral, .localOllama, .hybridMarkerOlmocr, .none:
            return $model.mistralApiKey
        }
    }

    @ViewBuilder
    private func cloudVLMProviderSettingsView(
        for provider: OCRProvider,
        showCustomInstruction: Bool
    ) -> some View {
        let keyBinding = cloudApiKeyBinding(for: provider)

        VStack(alignment: .leading, spacing: 12) {
            providerExplanation([
                "Cloud VLM OCR with high-accuracy handwriting recognition.",
                "Detects hand-drawn sketches and diagrams via bounding boxes and crops them locally with Pillow.",
                "Caches unchanged pages per provider and model so only modified pages are reprocessed.",
                "Sends rendered note page images to \(provider.displayName). API usage/costs may apply.",
                "Requires \(provider.apiKeyFieldLabel) (or environment variable \(provider.apiKeyEnvVarName))."
            ])

            VStack(alignment: .leading, spacing: 6) {
                Text(provider.apiKeyFieldLabel)
                    .font(.subheadline)
                    .fontWeight(.medium)

                HStack(spacing: 8) {
                    if model.showCloudApiKey {
                        TextField(provider.apiKeyFieldLabel, text: keyBinding)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))
                    } else {
                        SecureField(provider.apiKeyFieldLabel, text: keyBinding)
                            .textFieldStyle(.roundedBorder)
                    }

                    Button {
                        model.showCloudApiKey.toggle()
                    } label: {
                        Image(systemName: model.showCloudApiKey ? "eye.slash" : "eye")
                    }
                    .buttonStyle(.borderless)
                    .help(model.showCloudApiKey ? "Hide API key" : "Show API key")
                }

                if model.hasCloudApiKeyFromEnvironmentOnly(for: provider) {
                    Text("Detected \(provider.apiKeyEnvVarName) in environment / .env. Leave empty to use it, or enter a key here to override.")
                        .font(.footnote)
                        .foregroundColor(.green)
                } else {
                    Text("Stored locally in config.json with restricted permissions (0600). Fallback: \(provider.apiKeyEnvVarName).")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                Text("Model")
                    .font(.subheadline)
                    .fontWeight(.medium)

                TextField(
                    "Default: \(provider.defaultCloudModel)",
                    text: $model.ocrModel
                )
                .textFieldStyle(.roundedBorder)
                .font(.system(.body, design: .monospaced))

                HStack(spacing: 6) {
                    Text("Common models:")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    ForEach(provider.suggestedCloudModels, id: \.self) { suggested in
                        Button(suggested) {
                            model.ocrModel = suggested
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }

                Text("Leave empty to use the default model (\(provider.defaultCloudModel)).")
                    .font(.footnote)
                    .foregroundColor(.secondary)
            }

            HStack(spacing: 10) {
                Button("Test Connection") {
                    Task {
                        await model.testCloudProviderConnection()
                    }
                }
                .disabled(model.isTestingCloudConnection)

                if model.isTestingCloudConnection {
                    ProgressView()
                        .controlSize(.small)
                }
            }

            if !model.cloudConnectionTestMessage.isEmpty {
                Text(model.cloudConnectionTestMessage)
                    .font(.footnote)
                    .foregroundColor(
                        model.cloudConnectionTestSucceeded == true
                            ? .green
                            : (model.cloudConnectionTestSucceeded == false ? .red : .secondary)
                    )
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.secondary.opacity(0.08))
                    .cornerRadius(8)
            }

            if showCustomInstruction {
                customOCRInstructionEditor
            }
        }
    }

    private func providerExplanation(_ lines: [String], color: Color = .secondary) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(lines, id: \.self) { line in
                Text("• \(line)")
                    .font(.footnote)
                    .foregroundColor(color)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func markerInstallationHelp() -> some View {
        DisclosureGroup("Marker installation help") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Marker is used only in Hybrid mode. It helps Supsidian extract layout, visuals, tables, and diagrams from the generated PDF.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Marker is not installed automatically yet because it needs a Python environment and can be sensitive to Python versions and PATH.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Recommended manual install for now:")
                    .font(.headline)

                VStack(alignment: .leading, spacing: 6) {
                    Text("1. Open Terminal.")
                    Text("2. Go to your Supsidian project folder:")
                    commandSnippet("cd ~/supernote-obsidian-sync")
                    Text("3. If python3.12 is missing, install it first:")
                    commandSnippet("brew install python@3.12")
                    Text("4. Create a separate Marker Python environment:")
                    commandSnippet("/opt/homebrew/bin/python3.12 -m venv .venv-marker-ocr")
                    Text("5. Activate it:")
                    commandSnippet("source .venv-marker-ocr/bin/activate")
                    Text("6. Install Marker:")
                    commandSnippet("python -m pip install --upgrade pip\npython -m pip install marker-pdf")
                    Text("7. Use this marker command path in Supsidian:")
                    commandSnippet("~/supernote-obsidian-sync/.venv-marker-ocr/bin/marker_single")
                    Text("If this path does not work in the app, replace ~ with your full home folder path.")
                    Text("8. Then click “Check Local OCR Setup”.")
                }
                .font(.footnote)
                .foregroundColor(.secondary)

                Text("If Supsidian cannot find marker_single, an absolute path is safer than just marker_single. Marker is experimental and optional; Local Ollama mode works without Marker.")
                    .font(.footnote)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.top, 8)
        }
    }

    private func commandSnippet(_ text: String) -> some View {
        Text(text)
            .font(.system(.caption, design: .monospaced))
            .foregroundColor(.secondary)
            .textSelection(.enabled)
            .padding(8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(nsColor: .controlBackgroundColor))
            )
    }

    private func localOCRActionButtons() -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Button("Check Local OCR Setup") {
                    Task {
                        await model.checkLocalOCRDependencies()
                    }
                }
                .disabled(model.isRunningLocalOCRCommand)

                Button("Install Ollama model") {
                    Task {
                        await model.installOllamaModel()
                    }
                }
                .disabled(model.isRunningLocalOCRCommand)

                Button("Open Ollama Download") {
                    model.openOllamaDownloadPage()
                }
            }

            if model.isInstallingOllamaModel {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Downloading & installing Ollama model…")
                            .font(.footnote)
                            .foregroundColor(.secondary)

                        Spacer()

                        if let progress = model.ollamaInstallProgress {
                            Text("\(Int((progress * 100).rounded()))%")
                                .font(.system(.footnote, design: .monospaced))
                                .foregroundColor(.secondary)
                        }
                    }

                    if let progress = model.ollamaInstallProgress {
                        ProgressView(value: progress, total: 1.0)
                            .progressViewStyle(.linear)
                    } else {
                        ProgressView()
                            .progressViewStyle(.linear)
                    }
                }
            } else if model.isRunningLocalOCRCommand {
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)

                    Text("Working…")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }

            if !model.localOCRStatusMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                Text(model.localOCRStatusMessage)
                    .font(.system(.caption, design: .monospaced))
                    .foregroundColor(.secondary)
                    .textSelection(.enabled)
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color(nsColor: .controlBackgroundColor))
                    )
            }
        }
    }

    private var ocrTasksPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "OCR Provider",
                description: "Choose between cloud OCR and local OCR providers. Provider-specific settings are saved to config.json."
            ) {
                ocrProviderSettingsContent(showCustomInstruction: true)
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

    private var appVersionString: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "unknown"
        return "Version \(version) (Build \(build))"
    }

    private var advancedPage: some View {
        VStack(alignment: .leading, spacing: 18) {
            SettingsCard(
                title: "Open Supsidian at login",
                description: "Supsidian will appear in the menu bar after login. Syncing still happens manually with Sync Now."
            ) {
                HStack {
                    Spacer()

                    Toggle(
                        "",
                        isOn: Binding(
                            get: { model.startAtLoginEnabled },
                            set: { model.setStartAtLogin($0) }
                        )
                    )
                    .toggleStyle(.switch)
                    .labelsHidden()
                }
            }

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
                        "Open Supernote Partner before Sync Now",
                        isOn: $model.openSupernotePartnerBeforeSync
                    )

                    Text("Optional: open Supernote Partner first, wait briefly for it to sync notes locally, then run Supsidian.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    if model.openSupernotePartnerBeforeSync {
                        SettingField(
                            title: "Supernote Partner app name or path",
                            text: $model.supernotePartnerApp
                        )

                        HStack(alignment: .center) {
                            Text("Delay before Supsidian sync")
                                .font(.headline)

                            Spacer()

                            HStack(spacing: 8) {
                                TextField("15", text: $model.supernotePartnerSyncDelaySeconds)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 70)

                                Text("seconds")
                                    .foregroundColor(.secondary)
                            }
                            .frame(width: 170, alignment: .trailing)
                        }
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
                title: "Supsidian",
                description: appVersionString
            ) {
                VStack(alignment: .leading, spacing: 6) {
                    Text("Supernote → Obsidian Sync")
                        .font(.headline)

                    Text("Menu bar app for syncing Supernote notes to Obsidian.")
                        .font(.footnote)
                        .foregroundColor(.secondary)

                    Text("Command-line tool: supernote-obsidian-sync")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

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

        window.title = "Supsidian Settings"
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

nonisolated final class ProcessChunkCollector: @unchecked Sendable {
    private let lock = NSLock()
    private var collectedData = Data()
    private let maxStoredBytes = 32_768
    private let recentWindowBytes = 2_048
    private let onOutputChunk: (@Sendable (String) -> Void)?

    nonisolated init(onOutputChunk: (@Sendable (String) -> Void)?) {
        self.onOutputChunk = onOutputChunk
    }

    nonisolated func append(_ chunk: Data) {
        guard !chunk.isEmpty else { return }

        let recentText: String
        lock.lock()
        collectedData.append(chunk)
        if collectedData.count > maxStoredBytes {
            collectedData.removeFirst(collectedData.count - maxStoredBytes)
        }
        let windowData = collectedData.suffix(recentWindowBytes)
        recentText = String(decoding: windowData, as: UTF8.self)
        lock.unlock()

        onOutputChunk?(recentText)
    }

    nonisolated func finish(remainingChunk: Data = Data()) -> String {
        let finalText: String
        var trailingWindowText: String?

        lock.lock()
        if !remainingChunk.isEmpty {
            collectedData.append(remainingChunk)
            if collectedData.count > maxStoredBytes {
                collectedData.removeFirst(collectedData.count - maxStoredBytes)
            }
            let windowData = collectedData.suffix(recentWindowBytes)
            trailingWindowText = String(decoding: windowData, as: UTF8.self)
        }
        finalText = String(decoding: collectedData, as: UTF8.self)
        lock.unlock()

        if let trailingWindowText {
            onOutputChunk?(trailingWindowText)
        }

        return finalText
    }
}
