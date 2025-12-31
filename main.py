import os
import threading
import queue
import customtkinter as ctk
from tkinter import filedialog, messagebox
from yt_dlp import YoutubeDL

# -----------------------------
# Paths / config
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FFMPEG_BIN_DIR = os.path.join(
    BASE_DIR,
    "ffmpeg-2025-01-30-git-1911a6ec26-full_build",
    "bin",
)

def _ffmpeg_exists(ffmpeg_dir: str) -> bool:
    # yt-dlp accepts either an ffmpeg executable path or a directory containing it
    # Windows: ffmpeg.exe; *nix: ffmpeg
    win = os.name == "nt"
    exe = "ffmpeg.exe" if win else "ffmpeg"
    return os.path.isdir(ffmpeg_dir) and os.path.isfile(os.path.join(ffmpeg_dir, exe))

# -----------------------------
# Download logic (runs in worker thread)
# -----------------------------
def youtube_to_audio(link: str, download_path: str, ui_queue: queue.Queue):
    """
    Downloads YouTube audio and converts to MP3 using FFmpegExtractAudio.
    Reports progress/status via ui_queue.
    """
    try:
        if not os.path.exists(download_path):
            os.makedirs(download_path, exist_ok=True)

        ffmpeg_ok = _ffmpeg_exists(FFMPEG_BIN_DIR)

        def progress_hook(d):
            # Runs in worker thread; communicate to UI thread via queue
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total and total > 0:
                    pct = (downloaded / total) * 100.0
                    ui_queue.put(("progress", pct))
                    ui_queue.put(("status", f"Downloading… {pct:.1f}%"))
                else:
                    ui_queue.put(("status", "Downloading…"))
            elif d.get("status") == "finished":
                ui_queue.put(("progress", 100.0))
                ui_queue.put(("status", "Download finished. Converting to MP3…"))

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(download_path, "%(title).200s [%(id)s].%(ext)s"),
            "noplaylist": True,               # small safety: avoid accidental playlist downloads
            "restrictfilenames": True,        # avoid problematic chars across OSes
            "windowsfilenames": True,         # extra safety on Windows
            "progress_hooks": [progress_hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
        }

        # If bundled ffmpeg exists, use it; otherwise rely on system PATH.
        if ffmpeg_ok:
            ydl_opts["ffmpeg_location"] = FFMPEG_BIN_DIR
        else:
            ui_queue.put(("status", "FFmpeg not found in project folder. Using system FFmpeg (PATH)…"))

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])

        ui_queue.put(("done", f"MP3 download complete!\nFile saved in:\n{download_path}"))

    except Exception as e:
        ui_queue.put(("error", f"An error occurred:\n{e}"))

# -----------------------------
# UI
# -----------------------------
def browse_folder():
    folder = filedialog.askdirectory(title="Select Download Folder")
    if folder:
        folder_entry.delete(0, ctk.END)
        folder_entry.insert(0, folder)

def set_ui_busy(is_busy: bool):
    state = ctk.DISABLED if is_busy else ctk.NORMAL
    download_button.configure(state=state)
    browse_btn.configure(state=state)
    link_entry.configure(state=state)
    folder_entry.configure(state=state)

def start_download():
    link = link_entry.get().strip()
    if not link:
        messagebox.showerror("Error", "Please enter a YouTube video link.")
        return

    download_folder = folder_entry.get().strip() or os.path.join(BASE_DIR, "downloads")

    # Reset UI indicators
    progress_bar.set(0)
    status_label.configure(text="Starting…")

    set_ui_busy(True)

    # Start worker
    worker = threading.Thread(
        target=youtube_to_audio,
        args=(link, download_folder, ui_queue),
        daemon=True,
    )
    worker.start()

    # Start polling UI queue
    root.after(100, poll_queue)

def poll_queue():
    """
    Pull messages from worker thread and update UI safely.
    """
    try:
        while True:
            msg_type, payload = ui_queue.get_nowait()

            if msg_type == "status":
                status_label.configure(text=str(payload))

            elif msg_type == "progress":
                # customtkinter progress bar expects 0..1
                pct = float(payload)
                progress_bar.set(max(0.0, min(1.0, pct / 100.0)))

            elif msg_type == "done":
                status_label.configure(text="Done.")
                set_ui_busy(False)
                messagebox.showinfo("Success", str(payload))
                return

            elif msg_type == "error":
                status_label.configure(text="Error.")
                set_ui_busy(False)
                messagebox.showerror("Error", str(payload))
                return

    except queue.Empty:
        # Nothing yet; keep polling
        root.after(100, poll_queue)

# -----------------------------
# App setup
# -----------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("YouTube MP3 Converter")

width, height = 520, 240
root.geometry(f"{width}x{height}")  # FIX: remove spaces around 'x'
root.resizable(False, False)

ui_queue = queue.Queue()

# Grid config
root.grid_columnconfigure(1, weight=1)

# YouTube Link input
ctk.CTkLabel(root, text="YouTube Video Link:").grid(row=0, column=0, padx=10, pady=(15, 10), sticky="w")
link_entry = ctk.CTkEntry(root, width=360)
link_entry.grid(row=0, column=1, padx=10, pady=(15, 10), sticky="ew", columnspan=2)

# Download folder selection
ctk.CTkLabel(root, text="Download Folder:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
folder_entry = ctk.CTkEntry(root, width=280)
folder_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

browse_btn = ctk.CTkButton(root, text="Browse", command=browse_folder, width=90)
browse_btn.grid(row=1, column=2, padx=10, pady=10, sticky="e")

# Progress / status
status_label = ctk.CTkLabel(root, text="Idle.", anchor="w")
status_label.grid(row=2, column=0, padx=10, pady=(5, 0), sticky="w", columnspan=3)

progress_bar = ctk.CTkProgressBar(root)
progress_bar.grid(row=3, column=0, padx=10, pady=(10, 10), sticky="ew", columnspan=3)
progress_bar.set(0)

# Download button
download_button = ctk.CTkButton(root, text="Download", command=start_download)
download_button.grid(row=4, column=1, padx=10, pady=(5, 15), sticky="ew")

root.mainloop()
