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
from PIL import Image, ImageTk
from PIL.Image import Resampling
from io import BytesIO


if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
    ffmpeg_dir = os.path.join(BASE_DIR, 'ffmpeg', 'bin')
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    ffmpeg_dir = os.path.join(BASE_DIR, 'ffmpeg', 'bin')

ffmpeg_path = os.path.join(ffmpeg_dir, 'ffmpeg.exe')
if not os.path.isfile(ffmpeg_path):
    messagebox.showerror("FFmpeg Missing", f"Не найден ffmpeg.exe по пути:\n{ffmpeg_path}")
    sys.exit(1)

os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']


def center_window(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    x = (screen_width // 2) - (width * 2)
    y = (screen_height // 2) - (height * 2)

    window.geometry(f'+{x}+{y}')

def center_window_preview(window):
    window.update_idletasks()
    width = window.winfo_width()
    height = window.winfo_height()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)

    window.geometry(f'+{x}+{y}')

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
center_window(root)

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
tools_frame = tk.Frame(root, bg="#0b1a2f")
tools_convert_frame = tk.Frame(root, bg="#0b1a2f")
tools_trim_frame = tk.Frame(root, bg="#0b1a2f")
tools_merge_frame = tk.Frame(root, bg="#0b1a2f")

for f in (tools_frame, tools_convert_frame, tools_trim_frame, tools_merge_frame):
    f.place(relwidth=1, relheight=1)

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


def preview_video():
    url = url_entry.get().strip()
    if not url:
        messagebox.showerror("Error", "Please enter a video URL to preview")
        return

    # Создаем новое окно для превью
    preview_window = tk.Toplevel(root)
    preview_window.title("Video Preview")
    preview_window.geometry("400x500")
    preview_window.resizable(False, False)
    preview_window.configure(bg="#0b1a2f")
    center_window_preview(preview_window)

    # Виджеты для нового окна
    thumbnail_label = tk.Label(preview_window, bg="#0b1a2f")
    thumbnail_label.pack(pady=10)

    video_info_label = tk.Label(
        preview_window,
        bg="#0b1a2f",
        fg="white",
        font=("Segoe UI", 10),
        justify="left",
        wraplength=380
    )
    video_info_label.pack(pady=5, padx=10, fill="x")

    loading_label = tk.Label(
        preview_window,
        text="🔄 Loading video info...",
        bg="#0b1a2f",
        fg="white",
        font=("Segoe UI", 10)
    )
    loading_label.pack(pady=10)

    def update_ui(info_text, image=None):
        loading_label.pack_forget()
        if image:
            thumbnail_label.config(image=image)
            thumbnail_label.image = image
        video_info_label.config(text=info_text)

    def fetch_info():
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'force_generic_extractor': True,
                'socket_timeout': 10,
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_client': ['android']
                    }
                }
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                preview_window.after(0, lambda: update_ui("❌ Failed to get video info"))
                return

            # Формируем информацию о видео
            title = info.get('title', 'Unknown title')
            uploader = info.get('uploader', 'Unknown author')
            duration = info.get('duration', 0)
            duration_str = time.strftime("%H:%M:%S", time.gmtime(duration)) if duration else "Live stream"

            info_text = f"🎬 Title: {title}\n👤 Author: {uploader}\n⏱ Duration: {duration_str}"

            # Пробуем получить миниатюру
            thumbnail_url = None
            if 'thumbnail' in info:
                thumbnail_url = info['thumbnail']
            elif 'thumbnails' in info and info['thumbnails']:
                thumbnail_url = info['thumbnails'][-1]['url']

            if thumbnail_url:
                try:
                    response = requests.get(thumbnail_url, timeout=10)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content))
                        img = img.resize((380, 220), Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        preview_window.after(0, lambda: update_ui(info_text, photo))
                        return
                except Exception as e:
                    print(f"Thumbnail error: {e}")

            # Если миниатюра не загрузилась, показываем только информацию
            preview_window.after(0, lambda: update_ui(info_text))

        except yt_dlp.utils.DownloadError as e:
            preview_window.after(0, lambda: update_ui(f"❌ Download Error: {str(e)}"))
        except Exception as e:
            preview_window.after(0, lambda: update_ui(f"❌ Unexpected error: {str(e)}"))

    # Запускаем в отдельном потоке
    threading.Thread(target=fetch_info, daemon=True).start()

    # Кнопка закрытия
    close_button = tk.Button(
        preview_window,
        text="Close Preview",
        command=preview_window.destroy,
        bg="#1e3c60",
        fg="white",
        relief="flat",
        font=("Segoe UI", 10)
    )
    close_button.pack(pady=10, ipadx=20, ipady=5)




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

tk.Button(button_frame, text="🎬 Tools", command=lambda: show_frame(tools_frame),
          bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 11)).pack(side=tk.LEFT, padx=(10, 0))

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

tk.Button(form_frame, text="Preview", command=preview_video,
          bg="#1e6aa6", fg="white", relief="flat").grid(row=add_form_row.row, column=1, sticky="ew", pady=5)
add_form_row.row += 1

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

thumbnail_label = tk.Label(main_frame, bg="#0b1a2f")
thumbnail_label.pack(padx=20, pady=(5, 0))

video_info_label = tk.Label(main_frame, text="", bg="#0b1a2f", fg="white", font=("Segoe UI", 10), justify="left")
video_info_label.pack(padx=20, pady=(3, 5), anchor="w")

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
).pack(padx=30, pady=(20, 10), fill="x", anchor="w")

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
    query = search_input.get().strip()
    if not query:
        search_results.set("Please enter a search query.")
        return

    try:
        url = "https://raw.githubusercontent.com/thatsmeee/video-loader/main/allowed-list.md"
        response = requests.get(url)
        response.raise_for_status() # Raise an exception for bad status codes
        lines = response.text.splitlines()
        query_lower = query.lower()
        matches = [line for line in lines if query_lower in line.lower()]
        result_text = "\n".join(matches) if matches else "No results found."
        search_results.set(result_text)
    except requests.exceptions.RequestException as e:
        search_results.set(f"Error fetching data: {e}. Please check your internet connection.")
    except Exception as e:
        search_results.set(f"An unexpected error occurred: {e}")

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
).pack(padx=30, pady=(20, 10), fill="x", anchor="w")

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

tk.Label(tools_frame,
    text="🎬 Tools",
    bg="#0b1a2f",
    fg="white",
    justify="left",
    font=("Segoe UI", 14, "bold"),
    anchor="w"
).pack(pady=(30, 20), padx=30, anchor="w")

tk.Button(tools_frame, text="🎞 Media Converter", command=lambda: show_frame(tools_convert_frame),
    bg="#1e6aa6", fg="white", relief="flat", font=("Segoe UI", 11)).pack(padx=40, pady=10, fill="x")

tk.Button(tools_frame, text="✂️ Video trim (without recoding)", command=lambda: show_frame(tools_trim_frame),
    bg="#1e6aa6", fg="white", relief="flat", font=("Segoe UI", 11)).pack(padx=40, pady=10, fill="x")

tk.Button(tools_frame, text="⬅️ Back", command=lambda: show_frame(main_frame),
    bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 11)).pack(padx=40, pady=10, fill="x")

tk.Label(tools_convert_frame,
    text="🎞 Media Converter",
    bg="#0b1a2f",
    fg="white",
    font=("Segoe UI", 14, "bold"),
    anchor="w",
    justify="left"
).pack(pady=20, padx=30, anchor="w")

tk.Label(tools_convert_frame, text="Enter output format (e.g., mp4, mkv, avi):", bg="#0b1a2f", fg="white", font=("Segoe UI", 10)).pack(padx=40, anchor="w")
convert_format_var = tk.StringVar(value="mp4")
tk.Entry(tools_convert_frame, textvariable=convert_format_var, **entry_style).pack(padx=40, pady=5, fill="x")

def convert_video():
    infile = filedialog.askopenfilename(title="Select video")
    if not infile:
        return

    fmt = convert_format_var.get().strip().lower()
    if not fmt:
        messagebox.showerror("Format Error", "Please enter a valid output format (e.g., mp4, mkv).")
        return

    base_filename = os.path.splitext(os.path.basename(infile))[0]
    default_outfile = os.path.join(os.path.dirname(infile), f"{base_filename}.{fmt}")

    outfile = filedialog.asksaveasfilename(
        title="Save converted video as",
        defaultextension=f".{fmt}",
        initialfile=f"{base_filename}.{fmt}",
        filetypes=[(f"{fmt.upper()} files", f"*.{fmt}"), ("All files", "*.*")]
    )

    if not outfile:
        return

    threading.Thread(target=lambda: subprocess.run([
        ffmpeg_path, '-y', '-i', infile, outfile
    ], check=True)).start()

tk.Button(tools_convert_frame, text="🔄 Convert video", command=convert_video,
    bg="#1e6aa6", fg="white", relief="flat", font=("Segoe UI", 11)).pack(padx=40, pady=10, fill="x")

tk.Button(tools_convert_frame, text="⬅️ Back", command=lambda: show_frame(tools_frame),
    bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 10)).pack(padx=40, pady=(30, 0), fill="x")

tk.Label(tools_trim_frame,
    text="✂ Video trimming",
    bg="#0b1a2f",
    fg="white",
    font=("Segoe UI", 14, "bold"),
    anchor="w",
    justify="left"
).pack(pady=20, padx=30, anchor="w")

tk.Label(tools_trim_frame, text="Start time (format HH:MM:SS or seconds):", bg="#0b1a2f", fg="white", font=("Segoe UI", 10)).pack(padx=40, anchor="w")
trim_start_var = tk.StringVar()
tk.Entry(tools_trim_frame, textvariable=trim_start_var, **entry_style).pack(padx=40, pady=5, fill="x")

tk.Label(tools_trim_frame, text="End time (format HH:MM:SS or seconds):", bg="#0b1a2f", fg="white", font=("Segoe UI", 10)).pack(padx=40, anchor="w")
trim_end_var = tk.StringVar()
tk.Entry(tools_trim_frame, textvariable=trim_end_var, **entry_style).pack(padx=40, pady=5, fill="x")

def trim_video():
    infile = filedialog.askopenfilename(title="Select video")
    if not infile:
        return

    fmt = convert_format_var.get().strip().lower() or "mp4"
    base_filename = os.path.splitext(os.path.basename(infile))[0]
    default_outfile = os.path.join(os.path.dirname(infile), f"{base_filename}_trimmed.{fmt}")

    outfile = filedialog.asksaveasfilename(
        title="Save trimmed video as",
        defaultextension=f".{fmt}",
        initialfile=f"{base_filename}_trimmed.{fmt}",
        filetypes=[(f"{fmt.upper()} files", f"*.{fmt}"), ("All files", "*.*")]
    )
    if not outfile:
        return

    start = trim_start_var.get().strip()
    end = trim_end_var.get().strip()

    if not start or not end:
        messagebox.showerror("Error", "Please specify both start and end time.")
        return

    threading.Thread(target=lambda: subprocess.run([
        ffmpeg_path, '-y', '-ss', start, '-to', end, '-i', infile, '-c', 'copy', outfile
    ], check=True)).start()

tk.Button(tools_trim_frame, text="✂️ Trim", command=trim_video,
    bg="#1e6aa6", fg="white", relief="flat", font=("Segoe UI", 11)).pack(padx=40, pady=10, fill="x")

tk.Button(tools_trim_frame, text="⬅️ Back", command=lambda: show_frame(tools_frame),
    bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 10)).pack(padx=40, pady=(30, 0), fill="x")

tk.Label(tools_merge_frame,
    text="🔀 Video Merger",
    bg="#0b1a2f",
    fg="white",
    font=("Segoe UI", 14, "bold"),
    anchor="w",
    justify="left"
).pack(pady=20, padx=30, anchor="w")

tk.Label(tools_merge_frame, text="This feature will be available in the next version",
         bg="#0b1a2f", fg="white", font=("Segoe UI", 10)).pack(padx=40, pady=20)

tk.Button(tools_merge_frame, text="⬅️ Back", command=lambda: show_frame(tools_frame),
    bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 10)).pack(padx=40, pady=(30, 0), fill="x")

show_frame(main_frame)
root.mainloop()
