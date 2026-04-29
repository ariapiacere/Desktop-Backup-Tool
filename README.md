🗂 Desktop Backup Tool

A simple but powerful Windows tool to automatically organize recent files from your Desktop into a structured backup folder.

Built with Python, featuring both a modern Tkinter GUI and CLI mode.

✨ Features
📂 Automatically detects Desktop location (including OneDrive)
🗃 Organizes files into categories (images, documents, videos, etc.)
⏱ Filters files by recent activity (configurable time window)
🚫 Skips unwanted files (shortcuts, system files, ignored extensions)
⚙️ Fully configurable via config.json
🔍 Dry-run mode (preview before moving)
📋 Logging system (backup_log.txt)
🖥 GUI (Tkinter) + CLI support
📦 How It Works
Scans your Desktop
Selects files that are recently modified or created
Moves them into a backup folder like:
D:\04.29.26_backup\
 ├── images\
 ├── documents\
 ├── videos\
 └── others\
 
Reuses the same folder if run multiple times in one day

🚀 Usage

🔹 GUI Mode (default)
python desktop_backup.py

Launches the graphical interface.

🔹 CLI Mode
python desktop_backup.py --cli

Runs in terminal with interactive prompts.


⚙️ Configuration

Settings are stored in:

config.json
Example:
{
  "time_window_hours": 24,
  "destination_drive": "D",
  "excluded_folders": ["node_modules", ".git"],
  "ignored_extensions": [".tmp", ".log", ".lnk"],
  "dry_run": false,
  "logging_enabled": true
}
📋 Log File

Logs are saved to: backup_log.txt

Includes:

Files moved
Skipped files
Errors

🧠 Requirements
 Windows 10 / 11
 Python 3.x
 Tkinter (usually included with Python)
 
📁 Project Structure
desktop-backup/
 ├── desktop_backup.py
 ├── config.json
 ├── backup_log.txt
 └── README.md



Built as a personal productivity tool to keep Desktop clean and organized.

📜 License

Free to use and modify.
