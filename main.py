import os
import threading
import queue
from dataclasses import dataclass

import customtkinter as ctk
from tkinter import filedialog, messagebox
from yt_dlp import YoutubeDL

# -----------------------------
# Paths / config
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# If you bundle ffmpeg, keep it here (directory that contains ffmpeg.exe/ffmpeg and ffprobe.exe/ffprobe)
FFMPEG_BIN_DIR = os.path.join(
    BASE_DIR,
    "ffmpeg-2025-01-30-git-1911a6ec26-full_build",
    "bin",
)

def _bin_exists(bin_dir: str, exe_name: str) -> bool:
    return os.path.isdir(bin_dir) and os.path.isfile(os.path.join(bin_dir, exe_name))

def _ffmpeg_bundle_ok(ffmpeg_dir: str) -> bool:
    win = os.name == "nt"
    ffmpeg_exe = "ffmpeg.exe" if win else "ffmpeg"
    ffprobe_exe = "ffprobe.exe" if win else "ffprobe"
    return _bin_exists(ffmpeg_dir, ffmpeg_exe) and _bin_exists(ffmpeg_dir, ffprobe_exe)

def _safe_mkdir(path: str):
    os.makedirs(path, exist_ok=True)

# -----------------------------
# Download job model
# -----------------------------
@dataclass(frozen=True)
class Job:
    url: str
    out_dir: str
    mode: str              # "audio" | "video"
    mp3_kbps: str          # e.g. "192"
    mp4_height: str        # e.g. "1080" or "best"

# -----------------------------
# yt-dlp worker
# -----------------------------
def download_worker(job: Job, ui_q: queue.Queue):
    """
    Downloads either:
      - audio -> mp3 with chosen bitrate
      - video -> mp4 with chosen max resolution (height)
    Uses bundled ffmpeg if present; otherwise relies on system PATH.
    Reports progress/status via ui_q.
    """
    try:
        _safe_mkdir(job.out_dir)

        ffmpeg_ok = _ffmpeg_bundle_ok(FFMPEG_BIN_DIR)

        def progress_hook(d):
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes", 0)
                if total and total > 0:
                    pct = (downloaded / total) * 100.0
                    ui_q.put(("progress", pct))
                    ui_q.put(("status", f"Downloading… {pct:.1f}%"))
                else:
                    ui_q.put(("status", "Downloading…"))
            elif status == "finished":
                ui_q.put(("progress", 100.0))
                ui_q.put(("status", "Download finished. Processing with FFmpeg…"))

        # Common output template (safe across OS)
        outtmpl = os.path.join(job.out_dir, "%(title).200s [%(id)s].%(ext)s")

        ydl_opts = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "restrictfilenames": True,
            "windowsfilenames": True,
            "progress_hooks": [progress_hook],

            # More robust networking defaults
            "retries": 5,
            "fragment_retries": 5,
            "consoletitle": False,
            "nocheckcertificate": False,
        }

        if ffmpeg_ok:
            # yt-dlp accepts a directory containing ffmpeg/ffprobe
            ydl_opts["ffmpeg_location"] = FFMPEG_BIN_DIR
        else:
            ui_q.put(("status", "Bundled FFmpeg not found. Using system FFmpeg (PATH)…"))

        if job.mode == "audio":
            # Best audio, then convert to mp3 at chosen bitrate
            ydl_opts.update({
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        # For mp3 this is kbps. (yt-dlp passes this to ffmpeg as -b:a)
                        "preferredquality": job.mp3_kbps,
                    }
                ],
            })

        elif job.mode == "video":
            # MP4 output with max chosen height.
            #
            # Strategy:
            # 1) Prefer MP4 video + M4A audio (fastest path: "stream copy" for merge)
            # 2) If not available, fall back to best and then force mp4 container.
            #
            # height filter: bestvideo[height<=?]
            if job.mp4_height == "best":
                fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
                label = "Downloading MP4 (best available)…"
            else:
                h = job.mp4_height
                fmt = (
                    f"bestvideo[ext=mp4][height<={h}]+bestaudio[ext=m4a]"
                    f"/bestvideo[height<={h}]+bestaudio"
                    f"/best[height<={h}]"
                    f"/best"
                )
                label = f"Downloading MP4 (≤{h}p)…"

            ui_q.put(("status", label))

            ydl_opts.update({
                "format": fmt,
                "merge_output_format": "mp4",  # forces mp4 container after merge
                # If some sites deliver webm, merge_output_format ensures mp4 output.
                # NOTE: true re-encode is not forced; it will re-mux when possible.
                "postprocessors": [
                    # If merge already yields mp4, this is basically a no-op.
                    # If not, it converts container to mp4.
                    {"key": "FFmpegVideoConvertor", "preferedformat": "mp4"},
                ],
            })
        else:
            raise ValueError("Invalid mode. Expected 'audio' or 'video'.")

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([job.url])

        ui_q.put(("done", f"Complete!\nSaved in:\n{job.out_dir}"))

    except Exception as e:
        ui_q.put(("error", f"An error occurred:\n{e}"))

# -----------------------------
# UI helpers
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
    audio_radio.configure(state=state)
    video_radio.configure(state=state)
    mp3_menu.configure(state=state)
    mp4_menu.configure(state=state)

def update_mode_controls():
    mode = mode_var.get()
    if mode == "audio":
        mp3_menu.configure(state=ctk.NORMAL)
        mp4_menu.configure(state=ctk.DISABLED)
        mp4_label.configure(text="MP4 Quality (disabled)")
        mp3_label.configure(text="MP3 Quality (kbps)")
    else:
        mp3_menu.configure(state=ctk.DISABLED)
        mp4_menu.configure(state=ctk.NORMAL)
        mp4_label.configure(text="MP4 Quality (max height)")
        mp3_label.configure(text="MP3 Quality (disabled)")

def start_download():
    url = link_entry.get().strip()
    if not url:
        messagebox.showerror("Error", "Please enter a YouTube video link.")
        return

    out_dir = folder_entry.get().strip() or os.path.join(BASE_DIR, "downloads")

    # Reset UI
    progress_bar.set(0)
    status_label.configure(text="Starting…")
    set_ui_busy(True)

    job = Job(
        url=url,
        out_dir=out_dir,
        mode=mode_var.get(),
        mp3_kbps=mp3_quality_var.get(),
        mp4_height=mp4_quality_var.get(),
    )

    worker = threading.Thread(
        target=download_worker,
        args=(job, ui_queue),
        daemon=True,
    )
    worker.start()

    root.after(100, poll_queue)

def poll_queue():
    try:
        while True:
            msg_type, payload = ui_queue.get_nowait()

            if msg_type == "status":
                status_label.configure(text=str(payload))

            elif msg_type == "progress":
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
        root.after(100, poll_queue)

# -----------------------------
# App setup
# -----------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

root = ctk.CTk()
root.title("YouTube Converter (MP3 / MP4)")

width, height = 620, 330
root.geometry(f"{width}x{height}")
root.resizable(False, False)

ui_queue = queue.Queue()

# Grid config
root.grid_columnconfigure(1, weight=1)

# YouTube Link input
ctk.CTkLabel(root, text="YouTube Link:").grid(row=0, column=0, padx=10, pady=(15, 10), sticky="w")
link_entry = ctk.CTkEntry(root)
link_entry.grid(row=0, column=1, padx=10, pady=(15, 10), sticky="ew", columnspan=2)

# Download folder
ctk.CTkLabel(root, text="Download Folder:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
folder_entry = ctk.CTkEntry(root)
folder_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")

browse_btn = ctk.CTkButton(root, text="Browse", command=browse_folder, width=110)
browse_btn.grid(row=1, column=2, padx=10, pady=10, sticky="e")

# Mode: Audio vs Video
ctk.CTkLabel(root, text="Mode:").grid(row=2, column=0, padx=10, pady=(5, 5), sticky="w")

mode_var = ctk.StringVar(value="audio")
audio_radio = ctk.CTkRadioButton(root, text="MP3 (audio)", variable=mode_var, value="audio", command=update_mode_controls)
video_radio = ctk.CTkRadioButton(root, text="MP4 (video)", variable=mode_var, value="video", command=update_mode_controls)
audio_radio.grid(row=2, column=1, padx=10, pady=(5, 5), sticky="w")
video_radio.grid(row=2, column=2, padx=10, pady=(5, 5), sticky="w")

# Quality controls
mp3_label = ctk.CTkLabel(root, text="MP3 Quality (kbps)")
mp3_label.grid(row=3, column=0, padx=10, pady=(5, 5), sticky="w")

mp3_quality_var = ctk.StringVar(value="192")
mp3_menu = ctk.CTkOptionMenu(root, variable=mp3_quality_var, values=["128", "192", "256", "320"])
mp3_menu.grid(row=3, column=1, padx=10, pady=(5, 5), sticky="w")

mp4_label = ctk.CTkLabel(root, text="MP4 Quality (max height)")
mp4_label.grid(row=4, column=0, padx=10, pady=(5, 5), sticky="w")

mp4_quality_var = ctk.StringVar(value="1080")
mp4_menu = ctk.CTkOptionMenu(root, variable=mp4_quality_var, values=["best", "2160", "1440", "1080", "720", "480", "360"])
mp4_menu.grid(row=4, column=1, padx=10, pady=(5, 5), sticky="w")

# Status + progress
status_label = ctk.CTkLabel(root, text="Idle.", anchor="w")
status_label.grid(row=5, column=0, padx=10, pady=(10, 0), sticky="w", columnspan=3)

progress_bar = ctk.CTkProgressBar(root)
progress_bar.grid(row=6, column=0, padx=10, pady=(10, 10), sticky="ew", columnspan=3)
progress_bar.set(0)

# Download button
download_button = ctk.CTkButton(root, text="Download", command=start_download)
download_button.grid(row=7, column=1, padx=10, pady=(5, 15), sticky="ew")

# Initial enable/disable based on mode
update_mode_controls()

root.mainloop()
