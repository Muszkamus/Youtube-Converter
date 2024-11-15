import os
from yt_dlp import YoutubeDL # pip install yt-dlp

def youtube_to_mp3(link, download_path="downloads"):
    try:
        # Ensure the download directory exists
        if not os.path.exists(download_path):
            os.makedirs(download_path) # Creates directory in the project

        # Specify options for audio-only download
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s')
        }

        with YoutubeDL(ydl_opts) as ydl:
            print("Downloading and converting to MP3...")
            ydl.download([link])
        print("MP3 download complete!")
    except Exception as e:
        print(f"An error occurred: {e}")

# Input YouTube link
link = input("Enter the YouTube video link: ")
default_path = "downloads" 
youtube_to_mp3(link, default_path)


# If "ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install or provide the path using --ffmpeg-location"
# Install the modules from: https://ffmpeg.org/download.html
# Add bin to PATH: e.g., (C:\ffmpeg\bin)