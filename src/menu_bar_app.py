import subprocess
import threading
from pathlib import Path

import rumps

from supernote_obsidian_sync import (
    PROJECT_DIR,
    CONFIG_FILE,
    LOG_FILE,
    diagnose,
    scan_once,
    watch_loop,
)


class SupernoteObsidianMenuBarApp(rumps.App):
    def __init__(self):
        super().__init__("SN→Obsidian")

        self.watch_thread = None
        self.is_watching = False

        self.menu = [
            rumps.MenuItem("Sync now", callback=self.sync_now),
            rumps.MenuItem("Start watching", callback=self.start_watching),
            rumps.MenuItem("Stop watching", callback=self.stop_watching),
            None,
            rumps.MenuItem("Run diagnostics", callback=self.run_diagnostics),
            rumps.MenuItem("Open config", callback=self.open_config),
            rumps.MenuItem("Open log", callback=self.open_log),
            rumps.MenuItem("Open project folder", callback=self.open_project_folder),
            None,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

    def notify(self, title, subtitle, message):
        rumps.notification(
            title=title,
            subtitle=subtitle,
            message=message,
        )

    def sync_now(self, _):
        def run():
            try:
                scan_once()
                self.notify(
                    "Supernote → Obsidian",
                    "Sync complete",
                    "Finished checking for new or changed notes.",
                )
            except Exception as e:
                rumps.alert(f"Sync failed:\n\n{e}")

        threading.Thread(target=run, daemon=True).start()

    def start_watching(self, _):
        if self.is_watching:
            rumps.alert("Already watching.")
            return

        self.is_watching = True

        def run():
            try:
                watch_loop()
            except Exception as e:
                self.is_watching = False
                rumps.alert(f"Watcher stopped because of an error:\n\n{e}")

        self.watch_thread = threading.Thread(target=run, daemon=True)
        self.watch_thread.start()

        self.notify(
            "Supernote → Obsidian",
            "Watching started",
            "The app is now checking for new notes automatically.",
        )

    def stop_watching(self, _):
        # In this first simple version, stopping is done by quitting the app.
        # We will improve this in the next step.
        rumps.alert(
            "For now, use Quit to stop watching.\n\n"
            "We will add a cleaner stop function in the next version."
        )

    def run_diagnostics(self, _):
        try:
            result = subprocess.run(
                [
                    str(PROJECT_DIR / ".venv" / "bin" / "python"),
                    str(PROJECT_DIR / "src" / "supernote_obsidian_sync.py"),
                    "--diagnose",
                ],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_DIR),
            )

            output = result.stdout or result.stderr or "No diagnostic output."
            rumps.alert(output[:4000])

        except Exception as e:
            rumps.alert(f"Diagnostics failed:\n\n{e}")

    def open_config(self, _):
        subprocess.run(["open", str(CONFIG_FILE)])

    def open_log(self, _):
        if LOG_FILE.exists():
            subprocess.run(["open", str(LOG_FILE)])
        else:
            rumps.alert(f"Log file does not exist yet:\n\n{LOG_FILE}")

    def open_project_folder(self, _):
        subprocess.run(["open", str(PROJECT_DIR)])

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    SupernoteObsidianMenuBarApp().run()
