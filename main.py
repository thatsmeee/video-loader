import yt_dlp
import tkinter as tk
from tkinter import messagebox, filedialog, simpledialog
import threading
import os
import requests
from tkinter import ttk
import sys
import platform
import time
import subprocess
from packaging import version
from ctypes import windll
import psutil

if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    ffmpeg_dir = os.path.join(BASE_DIR, 'ffmpeg')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ffmpeg_dir = os.path.join(BASE_DIR, 'ffmpeg')

os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']

def optimize_process_priority():
    try:
        if platform.system() == "Windows":
            p = psutil.Process(os.getpid())
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            windll.kernel32.SetPriorityClass(p.pid, 0x00004000)
        else:
            os.nice(10)
            os.system("renice -n 10 -p $$")
    except Exception:
        pass

optimize_process_priority()

def update_yt_dlp():
    try:
        current_version = version.parse(yt_dlp.version.__version__)
        latest_version = version.parse(subprocess.check_output(
            [sys.executable, "-m", "yt_dlp", "--version"],
            stderr=subprocess.PIPE, text=True).strip())

        if latest_version > current_version:
            subprocess.run([sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--upgrade", "yt-dlp"],
                           check=True, capture_output=True)
            return True
    except Exception as e:
        return False

root = tk.Tk()
root.withdraw()

class YTDLPLogger:
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self._lock = threading.Lock()

    def debug(self, msg):
        with self._lock:
            root.after(0, self.log_callback, msg)

    def warning(self, msg):
        with self._lock:
            root.after(0, self.log_callback, f"⚠️ {msg}")

    def error(self, msg):
        with self._lock:
            root.after(0, self.log_callback, f"❌ {msg}")

def download_thread(url, media_type, quality, codec, save_path, threads, log_callback,
                    progress_callback, done_callback, advanced_options=None):
    try:
        if not advanced_options:
            advanced_options = {}

        postprocessors = []
        if media_type in ['mp3', 'ogg', 'wav', 'm4a']:
            ydl_format = 'bestaudio'
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': media_type,
                'preferredquality': advanced_options.get('audio_quality', '192'),
            })
        elif media_type in ['mp4', 'webm', 'mkv']:
            if quality == 'best':
                ydl_format = 'best'
            elif quality.isdigit():
                ydl_format = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
            else:
                ydl_format = 'best'
            postprocessors.append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': media_type,
            })

        ydl_opts = {
            'format': ydl_format,
            'outtmpl': os.path.join(save_path, '%(title)s.%(ext)s'),
            'noplaylist': not advanced_options.get('playlist', False),
            'postprocessors': postprocessors,
            'quiet': True,
            'logger': YTDLPLogger(log_callback),
            'progress_hooks': [lambda d: root.after(0, progress_callback, d)],
            'postprocessor_args': ['-threads', str(threads)],
            'concurrent_fragment_downloads': 8,
            'http_chunk_size': 1048576,
            'retries': 10,
            'fragment_retries': 10,
            'extractor_args': {
                'youtube': {
                    'player_skip': ['js'],
                    'player_client': ['android']
                }
            }
        }

        if advanced_options.get('time_range'):
            start_time, end_time = advanced_options['time_range']

            def time_to_seconds(t):
                if isinstance(t, str):
                    if ':' in t:
                        parts = list(map(int, t.split(':')))
                        if len(parts) == 3:
                            return parts[0] * 3600 + parts[1] * 60 + parts[2]
                        elif len(parts) == 2:
                            return parts[0] * 60 + parts[1]
                    return int(t) if t.isdigit() else 0
                return t

            start_sec = time_to_seconds(start_time)
            end_sec = time_to_seconds(end_time)

            ydl_opts.update({
                    'download_ranges': lambda info, ctx: [{
                    'start_time': start_sec,
                    'end_time': end_sec,
                    'title': 'Clip'
                }],
                'force_keyframes_at_cuts': True,
                'postprocessor_args': ydl_opts.get('postprocessor_args', []) + [
                    '-ss', str(start_sec),
                    '-to', str(end_sec)
                ]
            })

        if advanced_options.get('subtitles'):
            ydl_opts['writesubtitles'] = True
            ydl_opts['subtitlesformat'] = advanced_options.get('subtitle_format', 'srt')
            ydl_opts['subtitleslangs'] = ['all']

        if advanced_options.get('metadata'):
            ydl_opts['writethumbnail'] = True
            ydl_opts['writeinfojson'] = True
            ydl_opts['writedescription'] = True
            ydl_opts['writeannotations'] = True
            ydl_opts['writeautomaticsub'] = True

        if codec:
            if media_type in ['mp3', 'ogg', 'wav', 'm4a']:
                ydl_opts['postprocessor_args'].extend(['-c:a', codec])
            else:
                ydl_opts['postprocessor_args'].extend(['-c:v', codec])

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        root.after(0, done_callback)
        root.after(0, log_callback, "✅ Download complete!")

    except Exception as e:
        root.after(0, log_callback, f"❌ Error: {str(e)}")

if not getattr(sys, 'frozen', False):
    update_thread = threading.Thread(target=update_yt_dlp, daemon=True)
    update_thread.start()


root.deiconify()
root.title("Enhanced YouTube Downloader")
script_dir = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(script_dir, "footage.ico")
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"⚠️ Failed to set icon: {e}")

root.geometry("750x750")
root.configure(bg="#0b1a2f")
root.resizable(False, False)

save_path = tk.StringVar(value=os.getcwd())

main_frame = tk.Frame(root, bg="#0b1a2f")
search_frame = tk.Frame(root, bg="#0b1a2f")
advanced_frame = tk.Frame(root, bg="#0b1a2f")
history_frame = tk.Frame(root, bg="#0b1a2f")

for frame in (main_frame, search_frame, advanced_frame, history_frame):
    frame.place(relwidth=1, relheight=1)

def show_frame(f):
    f.tkraise()

def choose_folder():
    folder = filedialog.askdirectory()
    if folder:
        save_path.set(folder)

def log_to_output(msg):
    output_text.config(state=tk.NORMAL)
    output_text.insert(tk.END, msg + "\n")
    output_text.see(tk.END)
    output_text.config(state=tk.DISABLED)

def format_speed(speed):
    if speed is None:
        return "N/A"
    speed = float(speed)
    if speed > 1024 * 1024:
        return f"{speed / (1024 * 1024):.2f} MB/s"
    elif speed > 1024:
        return f"{speed / 1024:.2f} KB/s"
    else:
        return f"{speed:.2f} B/s"

last_update_time = 0
last_downloaded = 0

def update_progress(data):
    global last_update_time, last_downloaded

    if data.get('status') == 'downloading':
        current_time = time.time()
        elapsed = current_time - last_update_time if last_update_time and (current_time - last_update_time) > 0.001 else 0.001
        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes') or data.get('total_bytes_estimate')

        if total:
            percent = int(downloaded / total * 100)
            progress_var.set(percent)
            speed = (downloaded - last_downloaded) / elapsed if last_downloaded and elapsed > 0 else 0
            speed_label.config(text=f"Speed: {format_speed(speed)}")
            progress_label.config(text=f"{percent}%")

        last_update_time = current_time
        last_downloaded = downloaded

    elif data.get('status') == 'finished':
        progress_var.set(100)
        speed_label.config(text="Speed: Completed")
        progress_label.config(text="100%")

def on_download_complete():
    complete_label.place(relx=0.5, rely=0.96, anchor="s")
    root.after(3000, lambda: complete_label.place_forget())

def start_download():
    global last_update_time, last_downloaded
    last_update_time = 0
    last_downloaded = 0

    url = url_entry.get().strip()
    media_type = format_var.get().strip()
    quality = quality_entry.get().strip()
    codec = codec_entry.get().strip() or None
    folder = save_path.get()
    threads = threads_slider.get()

    advanced_options = {}
    if hasattr(advanced_frame, 'playlist_var'):
        advanced_options['playlist'] = advanced_frame.playlist_var.get()
    if hasattr(advanced_frame, 'subtitles_var'):
        advanced_options['subtitles'] = advanced_frame.subtitles_var.get()
    if hasattr(advanced_frame, 'subtitle_format_var'):
        advanced_options['subtitle_format'] = advanced_frame.subtitle_format_var.get()
    if hasattr(advanced_frame, 'metadata_var'):
        advanced_options['metadata'] = advanced_frame.metadata_var.get()
    if hasattr(advanced_frame, 'audio_quality_var'):
        advanced_options['audio_quality'] = advanced_frame.audio_quality_var.get()
    if hasattr(advanced_frame, 'time_start_var') and hasattr(advanced_frame, 'time_end_var'):
        start = advanced_frame.time_start_var.get()
        end = advanced_frame.time_end_var.get()
        if start and end:
            advanced_options['time_range'] = (start, end)
        elif start or end:
            log_to_output("⚠️ Choose start and end of the video")
            return

    if not url or not media_type or not folder:
        messagebox.showerror("Error", "Please fill all required fields and select a folder.")
        return

    output_text.config(state=tk.NORMAL)
    output_text.delete(1.0, tk.END)
    output_text.config(state=tk.DISABLED)
    progress_var.set(0)
    speed_label.config(text="Speed: -")
    progress_label.config(text="0%")

    threading.Thread(
        target=download_thread,
        args=(url, media_type, quality, codec, folder, threads, log_to_output,
              update_progress, on_download_complete, advanced_options),
        daemon=True
    ).start()

label_style = {"bg": "#0b1a2f", "fg": "#ffffff", "font": ("Segoe UI", 10)}
entry_style = {"bg": "#1b2b45", "fg": "#ffffff", "insertbackground": "white", "relief": "flat",
               "font": ("Segoe UI", 10)}

button_frame = tk.Frame(main_frame, bg="#0b1a2f")
button_frame.pack(padx=20, pady=(15, 10), fill="x", expand=True)

tk.Button(button_frame, text="⚙️ Advanced options",
          command=lambda: show_frame(advanced_frame),
          bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 11)
          ).pack(side=tk.LEFT, expand=True, fill="x")

tk.Button(button_frame, text="🔍",
          command=lambda: show_frame(search_frame),
          bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 11),
          width=3).pack(side=tk.LEFT, padx=(10, 0))

form_frame = tk.Frame(main_frame, bg="#0b1a2f")
form_frame.pack(padx=20, pady=10, anchor="w", fill="x")

def add_form_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_form_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_form_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_form_row.row += 1

add_form_row.row = 0

url_entry = tk.Entry(form_frame, **entry_style)
add_form_row(form_frame, "🔗 Video URL:", url_entry)

format_var = tk.StringVar(value="mp4")
format_entry = tk.Entry(form_frame, textvariable=format_var, **entry_style)
add_form_row(form_frame, "🎞 Format (mp3, mp4, ogg etc.):", format_entry)

quality_entry = tk.Entry(form_frame, **entry_style)
quality_entry.insert(0, "best")
add_form_row(form_frame, "🧩 Quality (worst/best, 360/720/1800 etc.):", quality_entry)

codec_entry = tk.Entry(form_frame, **entry_style)
add_form_row(form_frame, "📦 Codec (opus, vp9 etc.) (optional):", codec_entry)

dir_frame = tk.Frame(form_frame, bg="#0b1a2f")
dir_entry = tk.Entry(dir_frame, textvariable=save_path, **entry_style)
dir_entry.pack(side=tk.LEFT, expand=True, fill="x", padx=(0, 5))
tk.Button(dir_frame, text="📁", command=choose_folder, bg="#1e3c60", fg="white", relief="flat").pack(side=tk.LEFT)
add_form_row(form_frame, "💿 Save directory:", dir_frame)

threads_frame = tk.Frame(form_frame, bg="#0b1a2f")
threads_label = tk.Label(threads_frame, text="🎚 FFmpeg threads:", **label_style)
threads_label.pack(side=tk.LEFT, padx=(0, 10))

threads_slider = tk.Scale(
    threads_frame,
    from_=1,
    to=os.cpu_count() or 4,
    orient=tk.HORIZONTAL,
    bg="#0b1a2f",
    fg="white",
    highlightthickness=0,
    troughcolor="#1b2b45",
    activebackground="#1e6aa6",
    sliderrelief="flat"
)
threads_slider.set(os.cpu_count() or 4)
threads_slider.pack(side=tk.LEFT, expand=True, fill="x")
add_form_row(form_frame, "", threads_frame)

tk.Button(main_frame, text="📌 Download", command=start_download, bg="#1e6aa6", fg="white",
          font=("Segoe UI", 11, "bold"), relief="flat", padx=10, pady=5) \
    .pack(padx=20, pady=15, fill="x", expand=True)

tk.Label(main_frame, text="📜 Process log:", **label_style).pack(anchor="w", padx=20, pady=(10, 0))
output_text = tk.Text(main_frame, height=10, bg="#11213a", fg="#cceeff", relief="flat", font=("Consolas", 9),
                      wrap="word")
output_text.config(state=tk.DISABLED)
output_text.pack(padx=20, pady=(5, 10), fill="both", expand=True)

progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(main_frame, variable=progress_var, maximum=100)
style = ttk.Style()
style.theme_use('clam')
style.configure("TProgressbar", thickness=12, troughcolor="#1a2e45", background="#3ca3ff", bordercolor="#0b1a2f",
                relief="flat")
progress_bar.pack(padx=20, pady=(0, 5), fill="x")

progress_frame = tk.Frame(main_frame, bg="#0b1a2f")
progress_frame.pack(padx=20, pady=(0, 10), fill="x")

progress_label = tk.Label(progress_frame, text="0%", bg="#0b1a2f", fg="#ffffff", font=("Segoe UI", 10))
progress_label.pack(side=tk.LEFT)

speed_label = tk.Label(progress_frame, text="Speed: -", bg="#0b1a2f", fg="#ffffff", font=("Segoe UI", 10))
speed_label.pack(side=tk.RIGHT)

complete_label = tk.Label(main_frame, text="✅ Download complete!", bg="#0b1a2f", fg="#8ef58e",
                          font=("Segoe UI", 12, "bold"))

advanced_frame_inner = tk.Frame(advanced_frame, bg="#0b1a2f")
advanced_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    advanced_frame_inner,
    text="⚙️ Advanced Options",
    bg="#0b1a2f",
    fg="white",
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=30, pady=(20, 10), fill="x")

advanced_form_frame = tk.Frame(advanced_frame_inner, bg="#0b1a2f")
advanced_form_frame.pack(padx=20, pady=10, anchor="w", fill="x")

def add_advanced_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_advanced_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_advanced_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_advanced_row.row += 1

add_advanced_row.row = 0

advanced_frame.playlist_var = tk.BooleanVar()
playlist_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.playlist_var, bg="#0b1a2f",
                                activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, "📋 Download entire playlist:", playlist_check)

advanced_frame.subtitles_var = tk.BooleanVar()
subtitles_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.subtitles_var, bg="#0b1a2f",
                                 activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, "📝 Download subtitles:", subtitles_check)

advanced_frame.subtitle_format_var = tk.StringVar(value="srt")
subtitle_format_menu = tk.OptionMenu(advanced_form_frame, advanced_frame.subtitle_format_var, "srt", "vtt", "ass",
                                     "lrc")
subtitle_format_menu.config(bg="#1b2b45", fg="white", relief="flat", highlightthickness=0)
subtitle_format_menu['menu'].config(bg="#1b2b45", fg="white")
add_advanced_row(advanced_form_frame, "📄 Subtitle format:", subtitle_format_menu)

advanced_frame.metadata_var = tk.BooleanVar()
metadata_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.metadata_var, bg="#0b1a2f",
                                activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, "📊 Download metadata (description, tags, etc.):", metadata_check)

advanced_frame.audio_quality_var = tk.StringVar(value="192")
audio_quality_menu = tk.OptionMenu(advanced_form_frame, advanced_frame.audio_quality_var, "128", "192", "256", "320")
audio_quality_menu.config(bg="#1b2b45", fg="white", relief="flat", highlightthickness=0)
audio_quality_menu['menu'].config(bg="#1b2b45", fg="white")
add_advanced_row(advanced_form_frame, "🔊 Audio quality (kbps):", audio_quality_menu)

advanced_frame.time_start_var = tk.StringVar()
time_start_entry = tk.Entry(advanced_form_frame, textvariable=advanced_frame.time_start_var, **entry_style)
add_advanced_row(advanced_form_frame, "⏱ Start time (HH:MM:SS):", time_start_entry)

advanced_frame.time_end_var = tk.StringVar()
time_end_entry = tk.Entry(advanced_form_frame, textvariable=advanced_frame.time_end_var, **entry_style)
add_advanced_row(advanced_form_frame, "⏱ End time (HH:MM:SS):", time_end_entry)

tk.Button(advanced_frame_inner, text="⬅️ Back to main", command=lambda: show_frame(main_frame),
          bg="#1e3c60", fg="white", relief="flat",
          font=("Segoe UI", 10)).pack(padx=30, pady=20, fill="x")

search_input = tk.StringVar()
search_results = tk.StringVar()

def search_sites():
    try:
        url = "https://raw.githubusercontent.com/thatsmeee/video-loader/main/allowed-list.md"
        response = requests.get(url)
        lines = response.text.splitlines()
        query = search_input.get().lower()
        matches = [line for line in lines if query in line.lower()]
        result_text = "\n".join(matches) if matches else "No results found."
        search_results.set(result_text)
    except Exception as e:
        search_results.set(f"Error: {e}")

search_frame_inner = tk.Frame(search_frame, bg="#0b1a2f")
search_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    search_frame_inner,
    text="Search supported websites",
    bg="#0b1a2f",
    fg="white",
    relief="flat",
    font=("Segoe UI", 10, "bold"),
    anchor="w",
    justify="left"
).pack(padx=30, pady=(20, 10), fill="x")

search_entry = tk.Entry(search_frame_inner, textvariable=search_input, **entry_style)
search_entry.pack(padx=30, pady=(0, 10), fill="x")

tk.Button(search_frame_inner, text="🔎 Search", command=search_sites,
          bg="#1e6aa6", fg="white", relief="flat",
          font=("Segoe UI", 10, "bold")).pack(padx=30, pady=(0, 20), fill="x")

tk.Label(search_frame_inner, text="📄 Results:", **label_style).pack(anchor="w", padx=30, pady=(0, 5))

search_output = tk.Message(search_frame_inner, textvariable=search_results,
                           bg="#11213a", fg="#cceeff", width=640,
                           font=("Consolas", 9))
search_output.pack(padx=30, pady=(0, 20), fill="both", expand=True)

tk.Button(search_frame_inner, text="⬅️ Back to main", command=lambda: show_frame(main_frame),
          bg="#1e3c60", fg="white", relief="flat",
          font=("Segoe UI", 10)).pack(padx=30, pady=(0, 30), fill="x")

show_frame(main_frame)
root.mainloop()

