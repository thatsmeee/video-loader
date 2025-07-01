import yt_dlp
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
import os
import requests
from tkinter import ttk
import sys
import platform

if getattr(sys, 'frozen', False):
    ffmpeg_dir = os.path.join(sys._MEIPASS, 'ffmpeg')
else:
    ffmpeg_dir = os.path.join(os.path.dirname(__file__), 'ffmpeg')

os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ['PATH']

if platform.system() == "Windows":
    import psutil
    p = psutil.Process(os.getpid())
    p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
else:
    os.nice(10)

class YTDLPLogger:
    def __init__(self, log_callback):
        self.log_callback = log_callback

    def debug(self, msg):
        self.log_callback(msg)

    def warning(self, msg):
        self.log_callback("⚠️ " + msg)

    def error(self, msg):
        self.log_callback("❌ " + msg)

def download_thread(url, media_type, quality, codec, save_path, threads, log_callback, progress_callback, done_callback):
    try:
        if media_type in ['mp3', 'ogg', 'wav', 'm4a']:
            ydl_format = 'bestaudio'
            postprocessors = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': media_type,
                'preferredquality': '192',
            }]
        elif media_type in ['mp4', 'webm', 'mkv']:
            if quality == 'best':
                ydl_format = 'best'
            elif quality.isdigit():
                ydl_format = f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]'
            else:
                ydl_format = 'best'
            postprocessors = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': media_type,
            }]
        else:
            log_callback(f"Неподдерживаемый формат: {media_type}")
            return

        ydl_opts = {
            'format': ydl_format,
            'outtmpl': os.path.join(save_path, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'postprocessors': postprocessors,
            'quiet': True,
            'logger': YTDLPLogger(log_callback),
            'progress_hooks': [lambda d: progress_callback(d)]
        }

        if codec:
            ydl_opts['postprocessor_args'] = [
                '-c:a' if media_type in ['mp3', 'ogg', 'wav', 'm4a'] else '-c:v', codec,
                '-threads', str(threads)
            ]
        else:
            ydl_opts['postprocessor_args'] = ['-threads', str(threads)]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        done_callback()
        log_callback("✅ Загрузка завершена!")

    except Exception as e:
        log_callback(f"❌ Ошибка: {e}")

root = tk.Tk()
root.title("")
script_dir = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(script_dir, "footage.ico")
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"⚠️ Не удалось установить иконку: {e}")

root.geometry("700x600")
root.configure(bg="#0b1a2f")
root.resizable(False, False)

save_path = tk.StringVar(value=os.getcwd())

main_frame = tk.Frame(root, bg="#0b1a2f")
search_frame = tk.Frame(root, bg="#0b1a2f")

for frame in (main_frame, search_frame):
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

def update_progress(data):
    if data.get('status') == 'downloading':
        total = data.get('total_bytes') or data.get('total_bytes_estimate')
        downloaded = data.get('downloaded_bytes', 0)
        if total:
            percent = int(downloaded / total * 100)
            progress_var.set(percent)
    elif data.get('status') == 'finished':
        progress_var.set(100)

def on_download_complete():
    complete_label.place(relx=0.5, rely=0.96, anchor="s")
    root.after(3000, lambda: complete_label.place_forget())

def start_download():
    url = url_entry.get().strip()
    media_type = format_var.get().strip()
    quality = quality_entry.get().strip()
    codec = codec_entry.get().strip() or None
    folder = save_path.get()
    threads = threads_slider.get()

    if not url or not media_type or not quality or not folder:
        messagebox.showerror("Ошибка", "Заполни все поля и выбери папку.")
        return

    output_text.config(state=tk.NORMAL)
    output_text.delete(1.0, tk.END)
    output_text.config(state=tk.DISABLED)
    progress_var.set(0)

    threading.Thread(target=download_thread, args=(url, media_type, quality, codec, folder,
                                                   threads, log_to_output, update_progress, on_download_complete)).start()

label_style = {"bg": "#0b1a2f", "fg": "#ffffff", "font": ("Segoe UI", 10)}
entry_style = {"bg": "#1b2b45", "fg": "#ffffff", "insertbackground": "white", "relief": "flat", "font": ("Segoe UI", 10)}

tk.Button(main_frame, text="Проверить доступна ли информация с сайта к скачиванию", command=lambda: show_frame(search_frame),
          bg="#1e3c60", fg="white", relief="flat", font=("Segoe UI", 9))\
    .pack(padx=20, pady=15, fill="x", expand=True)

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
add_form_row(form_frame, "🔗 Ссылка на видео файл:", url_entry)

format_var = tk.StringVar(value="mp4")
format_entry = tk.Entry(form_frame, textvariable=format_var, **entry_style)
add_form_row(form_frame, "🎞 Формат (mp3, mp4, ogg т.д.):", format_entry)

quality_entry = tk.Entry(form_frame, **entry_style)
quality_entry.insert(0, "best")
add_form_row(form_frame, "🧩 Качество (worst/best, 360/720/1800 т.д.):", quality_entry)

codec_entry = tk.Entry(form_frame, **entry_style)
add_form_row(form_frame, "📦 Кодек (opus, vp9 и т.д.) (не обязательно):", codec_entry)

dir_frame = tk.Frame(form_frame, bg="#0b1a2f")
dir_entry = tk.Entry(dir_frame, textvariable=save_path, **entry_style)
dir_entry.pack(side=tk.LEFT, expand=True, fill="x", padx=(0, 5))
tk.Button(dir_frame, text="📁", command=choose_folder, bg="#1e3c60", fg="white", relief="flat").pack(side=tk.LEFT)
add_form_row(form_frame, "💿 Директория сохранения:", dir_frame)

threads_frame = tk.Frame(form_frame, bg="#0b1a2f")
threads_label = tk.Label(threads_frame, text="🎚 Количество потоков FFmpeg:", **label_style)
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

tk.Button(main_frame, text="📌 Скачать", command=start_download, bg="#1e6aa6", fg="white",
          font=("Segoe UI", 11, "bold"), relief="flat", padx=10, pady=5)\
    .pack(padx=20, pady=15, fill="x", expand=True)

tk.Label(main_frame, text="📜 Лог процесса:", **label_style).pack(anchor="w", padx=20, pady=(10, 0))
output_text = tk.Text(main_frame, height=10, bg="#11213a", fg="#cceeff", relief="flat", font=("Consolas", 9), wrap="word")
output_text.config(state=tk.DISABLED)
output_text.pack(padx=20, pady=(5, 10), fill="both", expand=True)

progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(main_frame, variable=progress_var, maximum=100)
style = ttk.Style()
style.theme_use('clam')
style.configure("TProgressbar", thickness=12, troughcolor="#1a2e45", background="#3ca3ff", bordercolor="#0b1a2f", relief="flat")
progress_bar.pack(padx=20, pady=(0, 10), fill="x")

complete_label = tk.Label(main_frame, text="✅ Загрузка завершена!", bg="#0b1a2f", fg="#8ef58e", font=("Segoe UI", 12, "bold"))

search_input = tk.StringVar()
search_results = tk.StringVar()

def search_sites():
    try:
        url = "https://raw.githubusercontent.com/thatsmeee/video-loader/main/allowed-list.md"
        response = requests.get(url)
        lines = response.text.splitlines()
        query = search_input.get().lower()
        matches = [line for line in lines if query in line.lower()]
        result_text = "\n".join(matches) if matches else "Ничего не найдено."
        search_results.set(result_text)
    except Exception as e:
        search_results.set(f"Ошибка: {e}")

search_frame_inner = tk.Frame(search_frame, bg="#0b1a2f")
search_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    search_frame_inner,
    text="Поиск поддерживаемых сайтов",
    bg="#0b1a2f",
    fg="white",
    relief="flat",
    font=("Segoe UI", 10, "bold"),
    anchor="w",
    justify="left"
).pack(padx=30, pady=(20, 10), fill="x")

search_entry = tk.Entry(search_frame_inner, textvariable=search_input, **entry_style)
search_entry.pack(padx=30, pady=(0, 10), fill="x")

tk.Button(search_frame_inner, text="🔎 Найти", command=search_sites,
          bg="#1e6aa6", fg="white", relief="flat",
          font=("Segoe UI", 10, "bold")).pack(padx=30, pady=(0, 20), fill="x")

tk.Label(search_frame_inner, text="📄 Результаты:", **label_style).pack(anchor="w", padx=30, pady=(0, 5))

search_output = tk.Message(search_frame_inner, textvariable=search_results,
                           bg="#11213a", fg="#cceeff", width=640,
                           font=("Consolas", 9))
search_output.pack(padx=30, pady=(0, 20), fill="both", expand=True)

tk.Button(search_frame_inner, text="📦 На главную", command=lambda: show_frame(main_frame),
          bg="#1e3c60", fg="white", relief="flat",
          font=("Segoe UI", 10)).pack(padx=30, pady=(0, 30), fill="x")

show_frame(main_frame)
root.mainloop()
