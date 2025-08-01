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
import webbrowser
import pyperclip
import json
from datetime import datetime
import sqlite3
import browser_cookie3
import tempfile
import shutil
import hashlib
import queue
import ffmpeg
import re
import gettext

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

if getattr(sys, 'frozen', False):
    if platform.system() == "Windows":
        app_data_dir = os.path.join(os.getenv('APPDATA'), 'EnhancedYouTubeDownloader')
    else:
        app_data_dir = os.path.join(os.path.expanduser('~'), '.EnhancedYouTubeDownloader')

    os.makedirs(app_data_dir, exist_ok=True)
    HISTORY_FILE = os.path.join(app_data_dir, 'download_history.json')
    QUEUE_FILE = os.path.join(app_data_dir, 'download_queue.json')
    SETTINGS_FILE = os.path.join(app_data_dir, 'settings.json')
else:
    HISTORY_FILE = os.path.join(BASE_DIR, 'download_history.json')
    QUEUE_FILE = os.path.join(BASE_DIR, 'download_queue.json')
    SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')

FILENAME_TEMPLATES = [
    "%(title)s.%(ext)s",
    "%(uploader)s - %(title)s.%(ext)s",
    "%(uploader)s_%(title)s.%(ext)s",
    "%(title)s [%(id)s].%(ext)s",
    "%(upload_date)s - %(title)s.%(ext)s",
    "%(uploader)s/%(title)s.%(ext)s"
]

DEFAULT_SETTINGS = {
    'theme': 'dark',
    'auto_update': True,
    'check_space': True,
    'min_space_gb': 1,
    'default_format': 'mp4',
    'default_quality': 'best',
    'default_save_path': os.getcwd(),
    'default_threads': os.cpu_count() or 4,
    'notifications': True,
    'hardware_accel': 'auto',
    'filename_template': '%(title)s.%(ext)s',
    'default_language': 'en'
}


class FFmpegProgressParser:
    def __init__(self, total_duration, progress_callback):
        self.total_duration = total_duration
        self.progress_callback = progress_callback
        self.duration_pattern = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2})\.\d{2}")
        self.time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.\d{2}")

    def parse(self, line):
        if "time=" in line:
            time_match = self.time_pattern.search(line)
            if time_match:
                hours, minutes, seconds = map(int, time_match.groups())
                current_time = hours * 3600 + minutes * 60 + seconds
                if self.total_duration > 0:
                    progress = int((current_time / self.total_duration) * 100)
                    self.progress_callback(progress)


class AppSettings:
    def __init__(self):
        self.settings = DEFAULT_SETTINGS.copy()
        self.load_settings()

    def load_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r') as f:
                    loaded_settings = json.load(f)
                    for key in self.settings:
                        if key in loaded_settings:
                            self.settings[key] = loaded_settings[key]
        except Exception as e:
            print(f"Error loading settings: {e}")

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value
        self.save_settings()


class DownloadQueue:
    def __init__(self):
        self.queue = queue.Queue()
        self.current_task = None
        self.paused = False
        self.stop_flag = False
        self.thread = None
        self.load_queue()

    def add_task(self, task):
        self.queue.put(task)
        self.save_queue()

    def get_task(self):
        if not self.queue.empty():
            self.current_task = self.queue.get()
            self.save_queue()
            return self.current_task
        return None

    def clear_queue(self):
        while not self.queue.empty():
            self.queue.get()
        self.current_task = None
        self.save_queue()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def stop(self):
        self.stop_flag = True
        if self.thread and self.thread.is_alive():
            self.thread.join()

    def save_queue(self):
        tasks = []
        if self.current_task:
            tasks.append(self.current_task)
        temp_queue = queue.Queue()
        while not self.queue.empty():
            task = self.queue.get()
            tasks.append(task)
            temp_queue.put(task)
        self.queue = temp_queue

        with open(QUEUE_FILE, 'w') as f:
            json.dump(tasks, f)

    def load_queue(self):
        try:
            if os.path.exists(QUEUE_FILE):
                with open(QUEUE_FILE, 'r') as f:
                    tasks = json.load(f)
                    for task in tasks:
                        self.queue.put(task)
        except Exception as e:
            print(f"Error loading queue: {e}")


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
            subprocess.run(
                [sys.executable, "-m", "pip", "--disable-pip-version-check", "install", "--upgrade", "yt-dlp"],
                check=True, capture_output=True)
            return True
    except Exception as e:
        return False


root = tk.Tk()
root.withdraw()
center_window(root)

app_settings = AppSettings()

THEMES = {
    'dark': {
        'bg': '#1e1e1e',
        'fg': '#ffffff',
        'entry_bg': '#2d2d2d',
        'entry_fg': '#ffffff',
        'text_bg': '#252525',
        'text_fg': '#e0e0e0',
        'button_bg': '#3a3a3a',
        'button_fg': '#ffffff',
        'active_button_bg': '#4a90e2',
        'listbox_bg': '#2d2d2d',
        'listbox_fg': '#ffffff',
        'select_bg': '#4a90e2',
        'error_bg': '#ff6b6b',
        'success_bg': '#8ef58e',
        'label_bg': '#1e1e1e',
        'label_fg': '#ffffff',
        'menu_bg': '#2d2d2d',
        'menu_fg': '#ffffff',
        'menu_active_bg': '#4a90e2',
        'menu_active_fg': '#ffffff',
        'progress_trough': '#252525',
        'progress_bar': '#4a90e2',
        'menu_bg': '#2d2d2d',
        'menu_fg': '#ffffff',
        'menu_active_bg': '#4a90e2',
        'menu_active_fg': '#ffffff',
        'menu_bg': '#ffffff',
        'menu_fg': '#333333',
        'menu_active_bg': '#4a90e2',
        'menu_active_fg': '#ffffff'
    },
    'light': {
        'bg': '#fbfbfb',
        'fg': '#333333',
        'entry_bg': '#ffffff',
        'entry_fg': '#333333',
        'text_bg': '#f0f0f0',
        'text_fg': '#333333',
        'button_bg': '#e0e0e0',
        'button_fg': '#333333',
        'active_button_bg': '#4a90e2',
        'listbox_bg': '#ffffff',
        'listbox_fg': '#333333',
        'select_bg': '#4a90e2',
        'error_bg': '#ff6b6b',
        'success_bg': '#8ef58e',
        'label_bg': '#f5f5f5',
        'label_fg': '#333333',
        'menu_bg': '#ffffff',
        'menu_fg': '#333333',
        'menu_active_bg': '#4a90e2',
        'menu_active_fg': '#ffffff',
        'progress_trough': '#e0e0e0',
        'progress_bar': '#4a90e2'
    }
}

language = app_settings.get("default_language", "en")
locales_dir = os.path.join(BASE_DIR, "locales")

try:
    lang = gettext.translation("messages", locales_dir, languages=[language])
    lang.install()
    _ = lang.gettext
except FileNotFoundError:
    _ = lambda s: s


def apply_theme_recursively(widget, theme):
    cls = widget.winfo_class()

    common_cfg = {}
    if cls in ("Frame", "LabelFrame", "Toplevel"):
        common_cfg["bg"] = theme["bg"]
    elif cls == "Label":
        common_cfg["bg"] = theme["label_bg"]
        common_cfg["fg"] = theme["label_fg"]
    elif cls == "Button":
        text = widget.cget("text") if hasattr(widget, "cget") else ""

        buttons_with_custom_colors = {
            "📌 Download": {"bg": "#1e6aa6", "fg": "white"},
            "🔎 Search": {"bg": "#1e6aa6", "fg": "white"},
            "🎞 Media Converter": {"bg": "#1e6aa6", "fg": "white"},
            "✂ Video trim": {"bg": "#1e6aa6", "fg": "white"},
            "🔊 Audio Extractor": {"bg": "#1e6aa6", "fg": "white"},
            "🔀 Merge Videos": {"bg": "#1e6aa6", "fg": "white"},
            "🔄 Convert video": {"bg": "#1e6aa6", "fg": "white"},
            "✂️ Trim": {"bg": "#1e6aa6", "fg": "white"},
            "🎵 Extract Audio": {"bg": "#1e6aa6", "fg": "white"},
            "➕ Add Files": {"bg": "#3a3a3a", "fg": "white"},
            "🗑 Clear": {"bg": "#d94c4c", "fg": "white"},
            "Clear": {"bg": "#d94c4c", "fg": "white"},
            "🗑 Clear History": {"bg": "#d94c4c", "fg": "white"},
            "🔄 Repeat Download": {"bg": "#1e6aa6", "fg": "white"},
            "🗑 Clear": {"bg": "#f43535", "fg": "white"},
            "▶️ Start": {"bg": "#1e6aa6", "fg": "white"},
            "📌 Скачать": {"bg": "#1e6aa6", "fg": "white"},
            "🔎 Поиск": {"bg": "#1e6aa6", "fg": "white"},
            "🎞 Медиа конвертер": {"bg": "#1e6aa6", "fg": "white"},
            "✂ Видеообрезка": {"bg": "#1e6aa6", "fg": "white"},
            "🔊 Извлечение аудио": {"bg": "#1e6aa6", "fg": "white"},
            "🔀 Объединение видео": {"bg": "#1e6aa6", "fg": "white"},
            "🔄 Конвертировать видео": {"bg": "#1e6aa6", "fg": "white"},
            "✂️ Обрезка": {"bg": "#1e6aa6", "fg": "white"},
            "🎵 Извлечь аудио": {"bg": "#1e6aa6", "fg": "white"},
            "➕ Добавить файлы": {"bg": "#3a3a3a", "fg": "white"},
            "🗑 Очистить": {"bg": "#d94c4c", "fg": "white"},
            "Очистить": {"bg": "#d94c4c", "fg": "white"},
            "🗑 Очистить историю": {"bg": "#d94c4c", "fg": "white"},
            "🔄 Повторить загрузку": {"bg": "#1e6aa6", "fg": "white"},
            "🗑 Очистить": {"bg": "#f43535", "fg": "white"},
            "▶️ Начать": {"bg": "#1e6aa6", "fg": "white"},
            "📌 Завантажити": {"bg": "#1e6aa6", "fg": "white"},
            "🔎 Пошук": {"bg": "#1e6aa6", "fg": "white"},
            "🎞 Медіаконвертер": {"bg": "#1e6aa6", "fg": "white"},
            "✂ Відеообрізання": {"bg": "#1e6aa6", "fg": "white"},
            "🔊 Витягти аудіо": {"bg": "#1e6aa6", "fg": "white"},
            "🔀 Об'єднання відео": {"bg": "#1e6aa6", "fg": "white"},
            "🔄 Конвертувати відео": {"bg": "#1e6aa6", "fg": "white"},
            "✂️ Обрізка": {"bg": "#1e6aa6", "fg": "white"},
            "🎵 Витягти аудіо": {"bg": "#1e6aa6", "fg": "white"},
            "➕ Додати файли": {"bg": "#3a3a3a", "fg": "white"},
            "🗑 Очистити": {"bg": "#d94c4c", "fg": "white"},
            "Очистити": {"bg": "#d94c4c", "fg": "white"},
            "🗑 Очистити історію": {"bg": "#d94c4c", "fg": "white"},
            "🔄 Повторити завантаження": {"bg": "#1e6aa6", "fg": "white"},
            "🗑 Очистити": {"bg": "#f43535", "fg": "white"},
            "▶️ Почати": {"bg": "#1e6aa6", "fg": "white"}
        }

        if text in buttons_with_custom_colors:
            custom = buttons_with_custom_colors[text]
            common_cfg["bg"] = custom["bg"]
            common_cfg["fg"] = custom["fg"]
            common_cfg["activebackground"] = custom["bg"]
        else:
            common_cfg["bg"] = theme["button_bg"]
            common_cfg["fg"] = theme["button_fg"]
            common_cfg["activebackground"] = theme["active_button_bg"]


    elif cls == "Entry":
        common_cfg["bg"] = theme["entry_bg"]
        common_cfg["fg"] = theme["entry_fg"]
        common_cfg["insertbackground"] = theme["fg"]
    elif cls == "Text":
        common_cfg["bg"] = theme["text_bg"]
        common_cfg["fg"] = theme["text_fg"]
    elif cls == "Listbox":
        common_cfg["bg"] = theme["listbox_bg"]
        common_cfg["fg"] = theme["listbox_fg"]
        common_cfg["selectbackground"] = theme["select_bg"]
    elif cls == "Menu":
        widget.config(
            bg=theme['menu_bg'],
            fg=theme['menu_fg'],
            activebackground=theme['menu_active_bg'],
            activeforeground=theme['menu_active_fg'],
            selectcolor=theme['menu_bg']
        )

        try:
            widget['menu'].config(
                bg=theme['menu_bg'],
                fg=theme['menu_fg'],
                activebackground=theme['menu_active_bg'],
                activeforeground=theme['menu_active_fg'],
                selectcolor=theme['menu_bg']
            )
        except Exception:
            pass
    elif cls in ("Checkbutton", "Radiobutton"):
        common_cfg["bg"] = theme["bg"]
        common_cfg["fg"] = theme["fg"]
        common_cfg["activebackground"] = theme["active_button_bg"]
    elif isinstance(widget, tk.OptionMenu):
        widget.config(
            bg=theme['button_bg'],
            fg=theme['button_fg'],
            activebackground=theme['active_button_bg'],
            highlightthickness=0,
            relief="flat"
        )
        widget['menu'].config(
            bg=theme['menu_bg'],
            fg=theme['menu_fg'],
            activebackground=theme['menu_active_bg'],
            activeforeground=theme['menu_active_fg']
        )
    elif cls == "Scale":
        common_cfg["bg"] = theme["bg"]
        common_cfg["fg"] = theme["fg"]
        common_cfg["troughcolor"] = theme["progress_trough"]
        common_cfg["highlightbackground"] = theme["bg"]
        common_cfg["activebackground"] = theme["active_button_bg"]
    elif cls == "OptionMenu":
        common_cfg["bg"] = theme["button_bg"]
        common_cfg["fg"] = theme["button_fg"]
        common_cfg["activebackground"] = theme["active_button_bg"]
        try:
            widget["menu"].configure(
                bg=theme["menu_bg"],
                fg=theme["menu_fg"],
                activebackground=theme["menu_active_bg"],
                activeforeground=theme["menu_active_fg"]
            )
        except Exception:
            pass

    try:
        widget.configure(**common_cfg)
    except Exception:
        pass

    if isinstance(widget, ttk.Progressbar):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            "TProgressbar",
            troughcolor=theme['progress_trough'],
            background=theme['progress_bar']
        )

    for child in widget.winfo_children():
        apply_theme_recursively(child, theme)


def apply_theme_to_new_toplevel(toplevel, theme):
    toplevel.configure(bg=theme["bg"])
    apply_theme_recursively(toplevel, theme)


def apply_theme(theme_name):
    theme = THEMES[theme_name]
    root.configure(bg=theme['bg'])
    apply_theme_recursively(root, theme)

    style = ttk.Style()
    style.theme_use('clam')
    style.configure(
        "TProgressbar",
        thickness=12,
        troughcolor=theme['progress_trough'],
        background=theme['progress_bar'],
        bordercolor=theme['bg'],
        relief="flat",
        padding=0,
        borderwidth=0
    )

    style.configure(
        "TMenubar",
        background=theme['menu_bg'],
        foreground=theme['menu_fg'],
        relief="flat"
    )

    menubar.config(
        bg=theme['menu_bg'],
        fg=theme['menu_fg'],
        activebackground=theme['menu_active_bg'],
        activeforeground=theme['menu_active_fg']
    )

    for child in menubar.winfo_children():
        child.config(
            bg=theme['menu_bg'],
            fg=theme['menu_fg'],
            activebackground=theme['menu_active_bg'],
            activeforeground=theme['menu_active_fg'],
            selectcolor=theme['menu_bg']
        )

    try:
        if platform.system() == "Windows":
            menubar.config(
                bg='SystemMenu',
                fg='SystemMenuText',
                activebackground='SystemHighlight',
                activeforeground='SystemHighlightText',
                selectcolor='SystemMenu'
            )
        else:
            menubar.config(
                bg=theme['menu_bg'],
                fg=theme['menu_fg'],
                activebackground=theme['menu_active_bg'],
                activeforeground=theme['menu_active_fg'],
                selectcolor=theme['menu_bg']
            )
    except Exception as e:
        print(f"Error applying menu theme: {e}")

    app_settings.set('theme', theme_name)


def apply_theme_to_widget(widget, theme):
    widget_type = widget.winfo_class()

    if widget_type == 'TFrame':
        widget.configure(bg=theme['bg'])
    elif widget_type == 'TLabel':
        widget.configure(bg=theme['bg'], fg=theme['fg'])
    elif widget_type == 'TEntry':
        widget.configure(bg=theme['entry_bg'], fg=theme['entry_fg'],
                         insertbackground=theme['fg'])
    elif widget_type == 'TButton':
        widget.configure(bg=theme['button_bg'], fg=theme['button_fg'])
    elif widget_type == 'TText':
        widget.configure(bg=theme['text_bg'], fg=theme['text_fg'])
    elif widget_type == 'Listbox':
        widget.configure(bg=theme['listbox_bg'], fg=theme['listbox_fg'],
                         selectbackground=theme['select_bg'])
    elif widget_type == 'Menu':
        widget.configure(bg=theme['bg'], fg=theme['fg'])

    for child in widget.winfo_children():
        apply_theme_to_widget(child, theme)


class YTDLPLogger:
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self._lock = threading.Lock()

    def debug(self, msg):
        pass

    def warning(self, msg):
        with self._lock:
            root.after(0, self.log_callback, msg)

    def error(self, msg):
        with self._lock:
            root.after(0, self.log_callback, f"❌ {msg}")


def save_to_history(url, media_type, quality, codec, save_path, threads, advanced_options):
    try:
        history = load_history()

        entry = {
            'url': url,
            'media_type': media_type,
            'quality': quality,
            'codec': codec if codec else '',
            'save_path': save_path,
            'threads': threads if threads else 4,
            'advanced_options': advanced_options if advanced_options else {},
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        history.append(entry)

        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)

    except Exception as e:
        print(f"Error saving history: {e}")


def load_history():
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def clear_history():
    try:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
        update_history_list()
    except Exception as e:
        messagebox.showerror("Error", f"Failed to clear history: {e}")


def get_cookies_from_browser(browser_name, domain="youtube.com"):
    try:
        if browser_name == "chrome":
            cj = browser_cookie3.chrome(domain_name=domain)
        elif browser_name == "firefox":
            cj = browser_cookie3.firefox(domain_name=domain)
        elif browser_name == "edge":
            cj = browser_cookie3.edge(domain_name=domain)
        elif browser_name == "opera":
            cj = browser_cookie3.opera(domain_name=domain)
        else:
            return None

        temp_dir = tempfile.mkdtemp()
        cookies_file = os.path.join(temp_dir, 'cookies.txt')

        with open(cookies_file, 'w') as f:
            for cookie in cj:
                if domain in cookie.domain:
                    f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t{'TRUE' if cookie.secure else 'FALSE'}\t"
                            f"{int(cookie.expires) if cookie.expires else 0}\t{cookie.name}\t{cookie.value}\n")

        return cookies_file
    except Exception as e:
        print(f"Error getting cookies from {browser_name}: {e}")
        return None


def get_cookies_from_file(file_path):
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            if not lines:
                return None

        temp_dir = tempfile.mkdtemp()
        cookies_file = os.path.join(temp_dir, 'cookies.txt')
        shutil.copyfile(file_path, cookies_file)
        return cookies_file
    except Exception as e:
        print(f"Error processing cookies file: {e}")
        return None


def check_disk_space(path, min_space_gb=1):
    try:
        usage = shutil.disk_usage(path)
        free_space_gb = usage.free / (1024 ** 3)
        if free_space_gb < min_space_gb:
            return False, free_space_gb
        return True, free_space_gb
    except Exception as e:
        print(f"Error checking disk space: {e}")
        return True, 0


def get_hardware_acceleration_methods():
    methods = ['auto']
    try:
        if platform.system() == "Windows":
            methods.extend(['cuda', 'dxva2', 'qsv'])
        elif platform.system() == "Linux":
            methods.extend(['vaapi', 'vdpau'])
        elif platform.system() == "Darwin":
            methods.append('videotoolbox')
    except:
        pass
    return methods


def optimize_conversion_settings(format_type, hw_accel='auto'):
    settings = {
        'threads': os.cpu_count() or 4,
        'preset': 'fast',
        'crf': '23',
        'hwaccel': hw_accel
    }

    if format_type in ['mp4', 'mkv']:
        settings.update({
            'vcodec': 'h264',
            'acodec': 'aac',
            'movflags': '+faststart'
        })
    elif format_type == 'webm':
        settings.update({
            'vcodec': 'libvpx-vp9',
            'acodec': 'libopus',
            'deadline': 'realtime'
        })
    elif format_type in ['mp3', 'ogg', 'wav', 'm4a', 'flac', 'aac']:
        settings.update({
            'acodec': {
                'mp3': 'libmp3lame',
                'ogg': 'libvorbis',
                'wav': 'pcm_s16le',
                'm4a': 'aac',
                'flac': 'flac',
                'aac': 'aac'
            }.get(format_type, 'copy')
        })
        settings.pop('vcodec', None)
        settings.pop('hwaccel', None)

    return settings


def download_thread_wrapper(download_queue):
    while not download_queue.stop_flag:
        if download_queue.paused:
            time.sleep(1)
            continue

        task = download_queue.get_task()
        if not task:
            break

        try:
            url = task['url']
            media_type = task['media_type']
            quality = task['quality']
            codec = task.get('codec')
            save_path = task['save_path']
            threads = task.get('threads', 4)
            advanced_options = task.get('advanced_options', {})

            if queue_listbox.size() > 0:
                root.after(0, lambda: queue_listbox.itemconfig(0, {'bg': '#3ca3ff'}))

            download_thread(
                url, media_type, quality, codec, save_path, threads,
                show_toast, update_progress,
                lambda: on_download_complete(download_queue),
                advanced_options
            )

            if queue_listbox.size() > 0:
                root.after(0, lambda: queue_listbox.itemconfig(0, {'bg': '#8ef58e'}))

        except Exception as e:
            if queue_listbox.size() > 0:
                root.after(0, lambda: queue_listbox.itemconfig(0, {'bg': '#ff6b6b'}))
            show_toast(f"Error processing task: {str(e)}", error=True)

    show_toast("Queue processing finished")
    root.after(0, update_queue_buttons_state)


def download_thread(url, media_type, quality, codec, save_path, threads, toast_callback,
                    progress_callback, done_callback, advanced_options=None):
    try:
        if not advanced_options:
            advanced_options = {}

        if app_settings.get('check_space', True):
            min_space = app_settings.get('min_space_gb', 1)
            enough_space, free_space = check_disk_space(save_path, min_space)
            if not enough_space:
                root.after(0, lambda: messagebox.showwarning(
                    "Low Disk Space",
                    f"Warning! Only {free_space:.2f} GB free space left on target drive.\n"
                    "Download may fail if there's not enough space for the video."
                ))

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

            postprocessor_args = [
                '-threads', str(threads),
                '-preset', 'fast',
                '-crf', '23'
            ]

            hw_accel = advanced_options.get('hw_accel', app_settings.get('hardware_accel', 'auto'))
            if hw_accel != 'auto':
                postprocessor_args.extend(['-hwaccel', hw_accel])

            postprocessors.append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': media_type,
            })

        filename_template = advanced_options.get('filename_template',
                                                 app_settings.get('filename_template', '%(title)s.%(ext)s'))

        ydl_opts = {
            'format': ydl_format,
            'outtmpl': os.path.join(save_path, filename_template),
            'noplaylist': not advanced_options.get('playlist', False),
            'postprocessors': postprocessors,
            'quiet': True,
            'logger': YTDLPLogger(toast_callback),
            'progress_hooks': [lambda d: root.after(0, progress_callback, d)],
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

        if media_type in ['mp4', 'webm', 'mkv']:
            ydl_opts['postprocessor_args'] = postprocessor_args

        if advanced_options.get('proxy'):
            proxy = advanced_options['proxy'].strip()
            if proxy:
                ydl_opts['proxy'] = proxy
                toast_callback(f"Using proxy: {proxy}")

        if advanced_options.get('cookies_file'):
            cookies_file = advanced_options['cookies_file']
            if cookies_file and os.path.exists(cookies_file):
                ydl_opts['cookiefile'] = cookies_file
                toast_callback("Using cookies for authentication")

        if advanced_options.get('subtitles'):
            ydl_opts.update({
                'writesubtitles': True,
                'subtitlesformat': advanced_options.get('subtitle_format', 'srt'),
                'subtitleslangs': ['all'],
                'writeautomaticsub': True,
                'allsubtitles': True,
                'postprocessors': postprocessors + [{
                    'key': 'FFmpegSubtitlesConvertor',
                    'format': advanced_options.get('subtitle_format', 'srt')
                }]
            })

        if advanced_options.get('metadata'):
            ydl_opts['writethumbnail'] = True
            ydl_opts['writeinfojson'] = True
            ydl_opts['writedescription'] = True
            ydl_opts['writeannotations'] = True
            ydl_opts['writeautomaticsub'] = True

        if codec:
            if media_type in ['mp3', 'ogg', 'wav', 'm4a']:
                if 'postprocessor_args' not in ydl_opts:
                    ydl_opts['postprocessor_args'] = []
                ydl_opts['postprocessor_args'].extend(['-c:a', codec])
            else:
                if 'postprocessor_args' not in ydl_opts:
                    ydl_opts['postprocessor_args'] = []
                ydl_opts['postprocessor_args'].extend(['-c:v', codec])

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')

            template = advanced_options.get('filename_template',
                                            app_settings.get('filename_template', '%(title)s.%(ext)s'))
            out_filename = ydl.prepare_filename(info)
            out_path = os.path.join(save_path, out_filename)

            root.last_downloaded_file = out_path

            ydl.download([url])

        if advanced_options.get('cookies_file'):
            temp_dir = os.path.dirname(advanced_options['cookies_file'])
            if os.path.exists(temp_dir) and temp_dir.startswith(tempfile.gettempdir()):
                try:
                    shutil.rmtree(temp_dir)
                except Exception as e:
                    toast_callback(f"Failed to clean up cookies temp files: {e}", warning=True)

        save_to_history(url, media_type, quality, codec, save_path, threads, advanced_options)
        update_history_list()

        root.after(0, done_callback)
        show_toast(f"Download complete: {title}", success=True)

    except Exception as e:
        show_toast(f"Error: {str(e)}", error=True)


def on_download_complete(download_queue):
    if app_settings.get('notifications', True):
        complete_label.place(relx=0.5, rely=0.96, anchor="s")
        root.after(3000, lambda: complete_label.place_forget())
    if download_queue.current_task:
        download_queue.current_task = None
        download_queue.save_queue()
    update_queue_list()


def add_to_queue():
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
            show_toast("Choose start and end of the video", warning=True)
            return
    if hasattr(security_frame, 'proxy_var'):
        proxy = security_frame.proxy_var.get().strip()
        if proxy:
            advanced_options['proxy'] = proxy
    if hasattr(security_frame, 'cookies_file'):
        cookies_file = security_frame.cookies_file
        if cookies_file and os.path.exists(cookies_file):
            advanced_options['cookies_file'] = cookies_file
    if hasattr(advanced_frame, 'filename_template_var'):
        advanced_options['filename_template'] = advanced_frame.filename_template_var.get()
    if hasattr(advanced_frame, 'hw_accel_var'):
        advanced_options['hw_accel'] = advanced_frame.hw_accel_var.get()

    if not url or not media_type or not folder:
        messagebox.showerror("Error", "Please fill all required fields and select a folder.")
        return

    task = {
        'url': url,
        'media_type': media_type,
        'quality': quality,
        'codec': codec,
        'save_path': folder,
        'threads': threads,
        'advanced_options': advanced_options,
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    download_queue.add_task(task)
    show_toast(f"Added to queue: {url}")
    update_queue_list()
    update_queue_buttons_state()


def start_queue():
    if not download_queue.thread or not download_queue.thread.is_alive():
        download_queue.stop_flag = False
        download_queue.paused = False
        download_queue.thread = threading.Thread(
            target=download_thread_wrapper,
            args=(download_queue,),
            daemon=True
        )
        download_queue.thread.start()
        show_toast("Queue processing started")
    else:
        download_queue.resume()
        show_toast("Queue resumed")

    update_queue_buttons_state()


def pause_queue():
    download_queue.pause()
    show_toast("Queue paused")
    update_queue_buttons_state()


def stop_queue():
    download_queue.stop()
    show_toast("Queue stopped")
    update_queue_buttons_state()


def clear_queue():
    download_queue.clear_queue()
    show_toast("Queue cleared")
    update_queue_list()
    update_queue_buttons_state()


def update_queue_list():
    queue_listbox.delete(0, tk.END)

    if download_queue.current_task:
        url = download_queue.current_task.get('url', '')
        media_type = download_queue.current_task.get('media_type', '')
        queue_listbox.insert(tk.END, f"🔄 {url} ({media_type})")
        queue_listbox.itemconfig(0, {'bg': '#3ca3ff'})

    temp_queue = queue.Queue()
    while not download_queue.queue.empty():
        task = download_queue.queue.get()
        url = task.get('url', '')
        media_type = task.get('media_type', '')
        queue_listbox.insert(tk.END, f"⏳ {url} ({media_type})")
        temp_queue.put(task)
    download_queue.queue = temp_queue


def update_queue_buttons_state():
    is_processing = download_queue.thread and download_queue.thread.is_alive()
    is_paused = download_queue.paused
    has_tasks = not download_queue.queue.empty() or download_queue.current_task

    if is_processing:
        if is_paused:
            queue_start_button.config(state=tk.NORMAL)
            queue_pause_button.config(state=tk.DISABLED)
            queue_stop_button.config(state=tk.NORMAL)
        else:
            queue_start_button.config(state=tk.DISABLED)
            queue_pause_button.config(state=tk.NORMAL)
            queue_stop_button.config(state=tk.NORMAL)
    else:
        queue_start_button.config(state=tk.NORMAL if has_tasks else tk.DISABLED)
        queue_pause_button.config(state=tk.DISABLED)
        queue_stop_button.config(state=tk.DISABLED)

    queue_clear_button.config(state=tk.NORMAL if has_tasks else tk.DISABLED)


def repeat_download(entry):
    def set_values():
        try:
            url_entry.delete(0, tk.END)
            url_entry.insert(0, entry.get('url', ''))

            format_var.set(entry.get('media_type', 'mp4'))

            quality_entry.delete(0, tk.END)
            quality_entry.insert(0, entry.get('quality', 'best'))

            codec_entry.delete(0, tk.END)
            codec_entry.insert(0, entry.get('codec', ''))

            save_path.set(entry.get('save_path', os.getcwd()))

            threads = entry.get('threads', os.cpu_count() or 4)
            threads_slider.set(min(max(threads, 1), os.cpu_count() or 4))

            adv_options = entry.get('advanced_options', {})

            if hasattr(advanced_frame, 'playlist_var'):
                advanced_frame.playlist_var.set(adv_options.get('playlist', False))
            if hasattr(advanced_frame, 'subtitles_var'):
                advanced_frame.subtitles_var.set(adv_options.get('subtitles', False))
            if hasattr(advanced_frame, 'subtitle_format_var'):
                advanced_frame.subtitle_format_var.set(adv_options.get('subtitle_format', 'srt'))
            if hasattr(advanced_frame, 'metadata_var'):
                advanced_frame.metadata_var.set(adv_options.get('metadata', False))
            if hasattr(advanced_frame, 'audio_quality_var'):
                advanced_frame.audio_quality_var.set(adv_options.get('audio_quality', '192'))
            if hasattr(advanced_frame, 'time_start_var') and hasattr(advanced_frame, 'time_end_var'):
                time_range = adv_options.get('time_range', ('', ''))
                advanced_frame.time_start_var.set(time_range[0] if time_range else '')
                advanced_frame.time_end_var.set(time_range[1] if time_range else '')
            if hasattr(security_frame, 'proxy_var'):
                security_frame.proxy_var.set(adv_options.get('proxy', ''))
            if hasattr(security_frame, 'cookies_file'):
                pass
            if hasattr(advanced_frame, 'filename_template_var'):
                advanced_frame.filename_template_var.set(adv_options.get('filename_template', '%(title)s.%(ext)s'))
            if hasattr(advanced_frame, 'hw_accel_var'):
                advanced_frame.hw_accel_var.set(adv_options.get('hw_accel', 'auto'))

            show_frame(main_frame)
            show_toast(f"Loaded settings from history: {entry.get('timestamp', '')}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load history entry: {str(e)}")
            show_toast(f"Error loading history: {str(e)}", error=True)

    root.after(0, set_values)


def update_history_list():
    history = load_history()
    history_listbox.delete(0, tk.END)

    for entry in reversed(history):
        timestamp = entry.get('timestamp', '')
        url = entry.get('url', '')
        media_type = entry.get('media_type', '')
        history_listbox.insert(0, f"{timestamp} - {url} ({media_type})")


def show_toast(message, success=False, error=False, warning=False):
    if not (success or error):
        return

    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    toast.geometry("300x60+{}+{}".format(
        root.winfo_x() + root.winfo_width() - 320,
        root.winfo_y() + root.winfo_height() - 80
    ))

    bg_color = "#4CAF50" if success else "#F44336" if error else "#2196F3"

    toast_frame = tk.Frame(toast, bg=bg_color)
    toast_frame.pack(fill="both", expand=True)

    label = tk.Label(
        toast_frame,
        text=message,
        fg="white",
        bg=bg_color,
        font=("Segoe UI", 10),
        wraplength=280,
        justify="left"
    )
    label.pack(pady=10, padx=10)

    toast.after(3000, toast.destroy)


if not getattr(sys, 'frozen', False) and app_settings.get('auto_update', True):
    update_thread = threading.Thread(target=update_yt_dlp, daemon=True)
    update_thread.start()

root.deiconify()
root.title("Enhanced YouTube Downloader")
script_dir = os.path.dirname(os.path.abspath(__file__))
icon_path = os.path.join(BASE_DIR, "footage.ico")
if os.path.exists(icon_path):
    try:
        root.iconbitmap(icon_path)
    except Exception as e:
        print(f"⚠️ Failed to set icon: {e}")

root.geometry("750x650")
root.resizable(False, False)

save_path = tk.StringVar(value=app_settings.get('default_save_path', os.getcwd()))

download_queue = DownloadQueue()

main_frame = tk.Frame(root)
search_frame = tk.Frame(root)
advanced_frame = tk.Frame(root)
history_frame = tk.Frame(root)
tools_frame = tk.Frame(root)
security_frame = tk.Frame(root)
tools_convert_frame = tk.Frame(root)
tools_trim_frame = tk.Frame(root)
tools_merge_frame = tk.Frame(root)
tools_extract_frame = tk.Frame(root)
queue_frame = tk.Frame(root)
help_frame = tk.Frame(root)
settings_frame = tk.Frame(root)

for f in (tools_frame, tools_convert_frame, tools_trim_frame, tools_merge_frame,
          tools_extract_frame, security_frame, queue_frame, help_frame, settings_frame):
    f.place(relwidth=1, relheight=1)

for frame in (main_frame, search_frame, advanced_frame, history_frame):
    frame.place(relwidth=1, relheight=1)


def show_frame(f):
    f.tkraise()
    if f == history_frame:
        update_history_list()
    elif f == queue_frame:
        update_queue_list()
        update_queue_buttons_state()


def choose_folder():
    folder = filedialog.askdirectory()
    if folder:
        save_path.set(folder)
        if app_settings.get('check_space', True):
            min_space = app_settings.get('min_space_gb', 1)
            enough_space, free_space = check_disk_space(folder, min_space)
            if not enough_space:
                messagebox.showwarning(
                    "Low Disk Space",
                    f"Warning! Only {free_space:.2f} GB free space left on target drive.\n"
                    "Downloads may fail if there's not enough space."
                )


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
        elapsed = current_time - last_update_time if last_update_time and (
                current_time - last_update_time) > 0.001 else 0.001
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


def paste_from_clipboard():
    try:
        clipboard_content = pyperclip.paste()
        if clipboard_content.startswith(('http://', 'https://')):
            url_entry.delete(0, tk.END)
            url_entry.insert(0, clipboard_content)
        else:
            messagebox.showwarning("Invalid URL", "Clipboard doesn't contain a valid URL")
    except Exception as e:
        messagebox.showerror("Clipboard Error", f"Failed to access clipboard: {str(e)}")


def preview_video():
    url = url_entry.get().strip()
    if not url:
        messagebox.showerror("Error", "Please enter a video URL to preview")
        return

    preview_window = tk.Toplevel(root)
    preview_window.title("Video Preview")
    preview_window.geometry("400x500")
    preview_window.resizable(False, False)
    center_window_preview(preview_window)

    thumbnail_label = tk.Label(preview_window)
    thumbnail_label.pack(pady=10)

    video_info_label = tk.Label(
        preview_window,
        font=("Segoe UI", 10),
        justify="left",
        wraplength=380
    )
    video_info_label.pack(pady=5, padx=28, fill="x")

    loading_label = tk.Label(
        preview_window,
        text="🔄 Loading video info...",
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
                },
                'noplaylist': True,
                'simulate': True,
                'forceurl': True,
                'forcetitle': True,
                'forceduration': True,
                'forcethumbnail': True
            }

            if hasattr(security_frame, 'proxy_var'):
                proxy = security_frame.proxy_var.get().strip()
                if proxy:
                    ydl_opts['proxy'] = proxy

            if hasattr(security_frame, 'cookies_file'):
                cookies_file = security_frame.cookies_file
                if cookies_file and os.path.exists(cookies_file):
                    ydl_opts['cookiefile'] = cookies_file

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            if not info:
                preview_window.after(0, lambda: update_ui("❌ Failed to get video info"))
                return

            title = info.get('title', 'Unknown title')
            uploader = info.get('uploader', 'Unknown author')
            duration = info.get('duration', 0)
            duration_str = time.strftime("%H:%M:%S", time.gmtime(duration)) if duration else "Live stream"

            info_text = f"🎬 Title: {title}\n👤 Author: {uploader}\n⏱ Duration: {duration_str}"

            thumbnail_url = None
            if 'thumbnail' in info:
                thumbnail_url = info['thumbnail']
            elif 'thumbnails' in info and info['thumbnails']:
                thumbnails = sorted(info['thumbnails'], key=lambda x: x.get('width', 0), reverse=True)
                thumbnail_url = thumbnails[0]['url'] if thumbnails else None

            if thumbnail_url:
                try:
                    proxies = None
                    if hasattr(security_frame, 'proxy_var'):
                        proxy = security_frame.proxy_var.get().strip()
                        if proxy:
                            proxies = {
                                'http': proxy,
                                'https': proxy
                            }

                    response = requests.get(thumbnail_url, timeout=10, proxies=proxies)
                    if response.status_code == 200:
                        img = Image.open(BytesIO(response.content))
                        img = img.resize((380, 220), Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        preview_window.after(0, lambda: update_ui(info_text, photo))
                        return
                except Exception as e:
                    print(f"Thumbnail error: {e}")

            preview_window.after(0, lambda: update_ui(info_text))

        except yt_dlp.utils.DownloadError as e:
            preview_window.after(0, lambda: update_ui(f"❌ Download Error: {str(e)}"))
        except Exception as e:
            preview_window.after(0, lambda: update_ui(f"❌ Unexpected error: {str(e)}"))

    threading.Thread(target=fetch_info, daemon=True).start()

    close_button = tk.Button(
        preview_window,
        text="Close Preview",
        command=preview_window.destroy,
        relief="flat",
        font=("Segoe UI", 10)
    )
    close_button.pack(pady=10, ipadx=20, ipady=5)

    theme = THEMES[app_settings.get('theme', 'dark')]
    preview_window.configure(bg=theme['bg'])
    thumbnail_label.configure(bg=theme['bg'])
    video_info_label.configure(bg=theme['bg'], fg=theme['fg'])
    loading_label.configure(bg=theme['bg'], fg=theme['fg'])
    close_button.configure(bg=theme['button_bg'], fg=theme['button_fg'])


def import_cookies_from_browser(browser_name):
    try:
        site = security_frame.cookie_site_var.get().strip()
        if not site:
            raise ValueError("No domain specified")
        cookies_file = get_cookies_from_browser(browser_name, domain=site)
        if cookies_file:
            security_frame.cookies_file = cookies_file
            show_toast(f"Successfully imported cookies from {browser_name.capitalize()} for domain: {site}",
                       success=True)
            messagebox.showinfo("Success", f"Cookies imported from {browser_name.capitalize()}")
        else:
            show_toast(f"Failed to import cookies from {browser_name.capitalize()}", error=True)
            messagebox.showerror("Error", f"Failed to import cookies from {browser_name.capitalize()}")
    except Exception as e:
        show_toast(f"Error importing cookies: {str(e)}", error=True)
        messagebox.showerror("Error", f"Failed to import cookies: {str(e)}")


def import_cookies_from_file():
    file_path = filedialog.askopenfilename(
        title="Select cookies file",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
    )
    if file_path:
        try:
            cookies_file = get_cookies_from_file(file_path)
            if cookies_file:
                security_frame.cookies_file = cookies_file
                show_toast("Successfully imported cookies from file", success=True)
                messagebox.showinfo("Success", "Cookies imported from file")
            else:
                show_toast("Invalid cookies file format", error=True)
                messagebox.showerror("Error", "Invalid cookies file format")
        except Exception as e:
            show_toast(f"Error importing cookies: {str(e)}", error=True)
            messagebox.showerror("Error", f"Failed to import cookies: {str(e)}")


def clear_cookies():
    if hasattr(security_frame, 'cookies_file'):
        temp_dir = os.path.dirname(security_frame.cookies_file)
        if os.path.exists(temp_dir) and temp_dir.startswith(tempfile.gettempdir()):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                show_toast(f"Failed to clean up cookies temp files: {e}", warning=True)
        security_frame.cookies_file = None
        show_toast("Cookies cleared", success=True)
        messagebox.showinfo("Success", "Cookies cleared")


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
            show_toast("Choose start and end of the video", warning=True)
            return
    if hasattr(security_frame, 'proxy_var'):
        proxy = security_frame.proxy_var.get().strip()
        if proxy:
            advanced_options['proxy'] = proxy
    if hasattr(security_frame, 'cookies_file'):
        cookies_file = security_frame.cookies_file
        if cookies_file and os.path.exists(cookies_file):
            advanced_options['cookies_file'] = cookies_file
    if hasattr(advanced_frame, 'filename_template_var'):
        advanced_options['filename_template'] = advanced_frame.filename_template_var.get()
    if hasattr(advanced_frame, 'hw_accel_var'):
        advanced_options['hw_accel'] = advanced_frame.hw_accel_var.get()

    if not url or not media_type or not folder:
        messagebox.showerror("Error", "Please fill all required fields and select a folder.")
        return

    progress_var.set(0)
    speed_label.config(text="Speed: -")
    progress_label.config(text="0%")

    threading.Thread(
        target=download_thread,
        args=(url, media_type, quality, codec, folder, threads, show_toast,
              update_progress, lambda: on_download_complete(download_queue), advanced_options),
        daemon=True
    ).start()


menubar = tk.Menu(root)
root.config(menu=menubar)

if platform.system() == "Windows":
    menubar.config(
        bg='SystemMenu',
        fg='SystemMenuText',
        activebackground='SystemHighlight',
        activeforeground='SystemHighlightText',
        selectcolor='SystemMenu'
    )

file_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="File", menu=file_menu)
file_menu.add_command(label="Exit", command=root.quit)

settings_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Settings", menu=settings_menu)
settings_menu.add_command(label="Settings", command=lambda: show_frame(settings_frame))
# settings_menu.add_separator()
# settings_menu.add_command(label="Dark Theme", command=lambda: apply_theme('dark'))
# settings_menu.add_command(label="Light Theme", command=lambda: apply_theme('light'))

help_menu = tk.Menu(menubar, tearoff=0)
menubar.add_cascade(label="Help", menu=help_menu)
help_menu.add_command(label="Help", command=lambda: show_frame(help_frame))
help_menu.add_command(label="About",
                      command=lambda: messagebox.showinfo("About", "Enhanced YouTube Downloader\nVersion 1.5.1"))

label_style = {"font": ("Segoe UI", 10)}
entry_style = {"insertbackground": "white", "relief": "flat", "font": ("Segoe UI", 10)}

button_frame = tk.Frame(main_frame)
button_frame.pack(padx=28, pady=(15, 10), fill="x", expand=True)

tk.Button(button_frame, text=_("🔧 Advanced"),
          command=lambda: show_frame(advanced_frame),
          relief="flat", font=("Segoe UI", 10)
          ).pack(side=tk.LEFT, expand=False, fill="x")

tk.Button(button_frame, text=_("🔍 Search"),
          command=lambda: show_frame(search_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=False, padx=(10, 0))

tk.Button(button_frame, text=_("🎬 Tools"), command=lambda: show_frame(tools_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=False, padx=(10, 0))

tk.Button(button_frame, text=_("⚙️ Security"), command=lambda: show_frame(security_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=False, padx=(10, 0))

tk.Button(button_frame, text=_("⏳ History"), command=lambda: show_frame(history_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=False, padx=(10, 0))

tk.Button(button_frame, text=_("📜 Queue"), command=lambda: show_frame(queue_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=False, padx=(10, 0))

tk.Button(button_frame, text=_("ℹ"), command=lambda: show_frame(help_frame),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.RIGHT, expand=False, padx=(10, 0))

form_frame = tk.Frame(main_frame)
form_frame.pack(padx=28, pady=10, anchor="w", fill="x")


def add_form_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_form_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_form_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_form_row.row += 1


add_form_row.row = 0

url_frame = tk.Frame(form_frame)
url_entry = tk.Entry(url_frame, **entry_style)
url_entry.pack(side=tk.LEFT, expand=True, fill="x")

url_entry.bind("<Button-3>", lambda e: paste_from_clipboard())

tk.Button(url_frame, text="📋", command=paste_from_clipboard,
          relief="flat", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(5, 0))
add_form_row(form_frame, _("🔗 Video URL:"), url_frame)

tk.Button(form_frame, text="Preview", command=preview_video,
          relief="flat").grid(row=add_form_row.row, column=1, sticky="ew", pady=5)
add_form_row.row += 1

format_var = tk.StringVar(value=app_settings.get('default_format', 'mp4'))
format_entry = tk.Entry(form_frame, textvariable=format_var, **entry_style)
add_form_row(form_frame, _("🎞 Format (mp3, mp4, ogg etc.):"), format_entry)

quality_entry = tk.Entry(form_frame, **entry_style)
quality_entry.insert(0, app_settings.get('default_quality', 'best'))
add_form_row(form_frame, _("🧩 Quality (worst/best, 360/720/1800 etc.):"), quality_entry)

codec_entry = tk.Entry(form_frame, **entry_style)
add_form_row(form_frame, _("📦 Codec (opus, vp9 etc.) (optional):"), codec_entry)

dir_frame = tk.Frame(form_frame)
dir_entry = tk.Entry(dir_frame, textvariable=save_path, **entry_style)
dir_entry.pack(side=tk.LEFT, expand=True, fill="x", padx=(0, 5))
tk.Button(dir_frame, text="📁", font=("Segoe UI", 7, "bold"), command=choose_folder,
          relief="flat").pack(side=tk.LEFT)
add_form_row(form_frame, _("💿 Save directory:"), dir_frame)

threads_frame = tk.Frame(form_frame)
threads_label = tk.Label(threads_frame, text=_("🎚 FFmpeg threads:"), **label_style)
threads_label.pack(side=tk.LEFT, padx=(0, 10))

threads_slider = tk.Scale(
    threads_frame,
    from_=1,
    to=os.cpu_count() or 4,
    orient=tk.HORIZONTAL,
    highlightthickness=0,
    troughcolor="#1b2b45",
    activebackground="#1e6aa6",
    sliderrelief="flat"
)
threads_slider.set(app_settings.get('default_threads', os.cpu_count() or 4))
threads_slider.pack(side=tk.LEFT, expand=True, fill="x")
add_form_row(form_frame, "", threads_frame)

buttons_frame = tk.Frame(main_frame)
buttons_frame.pack(padx=28, pady=0, fill="x", expand=True)

download_button = tk.Button(buttons_frame, text=_("📌 Download"), command=start_download,
                            font=("Segoe UI", 11, "bold"), relief="flat")
download_button.pack(side=tk.LEFT, expand=True, fill="x", padx=(0, 5))
download_button.config(bg="#358ff4", fg="white")

tk.Button(buttons_frame, text=_("➕ Add to Queue"), command=add_to_queue,
          font=("Segoe UI", 11), relief="flat", bg="#3a3a3a").pack(side=tk.LEFT, expand=True, fill="x")

"""tk.Label(main_frame, text="📜 Process log:", **label_style).pack(anchor="w", padx=28, pady=(10, 0))
output_text = tk.Text(main_frame, height=7, wrap="word",
                      font=("Consolas", 9))
output_text.config(state=tk.DISABLED)
output_text.pack(padx=28, pady=(5, 10), fill="both", expand=True)
"""
progress_container = tk.Frame(main_frame)
progress_container.pack(padx=28, pady=(0, 0), fill="x")

style = ttk.Style()
style.theme_use('clam')
style.layout(
    "TProgressbar",
    [('Horizontal.Progressbar.trough',
      {'children': [('Horizontal.Progressbar.pbar', {'side': 'left', 'sticky': 'ns'})],
       'sticky': 'nswe'})]
)

progress_var = tk.IntVar()
progress_bar = ttk.Progressbar(
    progress_container,
    variable=progress_var,
    maximum=100,
    style="TProgressbar"
)
progress_bar.pack(fill="x", pady=0)

progress_frame = tk.Frame(progress_container)
progress_frame.pack(fill="x", pady=0)

progress_label = tk.Label(
    progress_frame,
    text="0%",
    font=("Segoe UI", 10)
)
progress_label.pack(side=tk.LEFT)

speed_label = tk.Label(
    progress_frame,
    text="Speed: -",
    font=("Segoe UI", 10)
)
speed_label.pack(side=tk.RIGHT)

thumbnail_label = tk.Label(main_frame)
thumbnail_label.pack(padx=28, pady=(0, 0))

video_info_label = tk.Label(main_frame, text="", font=("Segoe UI", 10), justify="left")
video_info_label.pack(padx=28, pady=(3, 5), anchor="w")

complete_label = tk.Label(main_frame, text=_("✅ Download complete!"),
                          font=("Segoe UI", 12, "bold"))

advanced_frame_inner = tk.Frame(advanced_frame)
advanced_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    advanced_frame_inner,
    text=_("🔧 Advanced Options"),
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

advanced_form_frame = tk.Frame(advanced_frame_inner)
advanced_form_frame.pack(padx=28, pady=10, anchor="w", fill="x")


def add_advanced_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_advanced_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_advanced_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_advanced_row.row += 1


add_advanced_row.row = 0

advanced_frame.playlist_var = tk.BooleanVar()
playlist_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.playlist_var,
                                activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, _("📋 Download entire playlist:"), playlist_check)

advanced_frame.subtitles_var = tk.BooleanVar()
subtitles_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.subtitles_var,
                                 activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, _("📝 Download subtitles:"), subtitles_check)

advanced_frame.subtitle_format_var = tk.StringVar(value="srt")
subtitle_format_menu = tk.OptionMenu(advanced_form_frame, advanced_frame.subtitle_format_var, "srt", "vtt", "ass",
                                     "lrc")
subtitle_format_menu.config(highlightthickness=0)
subtitle_format_menu['menu'].config()

add_advanced_row(advanced_form_frame, _("📄 Subtitle format:"), subtitle_format_menu)

advanced_frame.metadata_var = tk.BooleanVar()
metadata_check = tk.Checkbutton(advanced_form_frame, variable=advanced_frame.metadata_var,
                                activebackground="#0b1a2f")
add_advanced_row(advanced_form_frame, _("📊 Download metadata (description, tags, etc.):"), metadata_check)

advanced_frame.audio_quality_var = tk.StringVar(value="192")
audio_quality_menu = tk.OptionMenu(advanced_form_frame, advanced_frame.audio_quality_var, "128", "192", "256", "320")
audio_quality_menu.config(highlightthickness=0)
audio_quality_menu['menu'].config()
add_advanced_row(advanced_form_frame, _("🔊 Audio quality (kbps):"), audio_quality_menu)

advanced_frame.time_start_var = tk.StringVar()
time_start_entry = tk.Entry(advanced_form_frame, textvariable=advanced_frame.time_start_var, **entry_style)
add_advanced_row(advanced_form_frame, _("⏱ Start time (HH:MM:SS):"), time_start_entry)

advanced_frame.time_end_var = tk.StringVar()
time_end_entry = tk.Entry(advanced_form_frame, textvariable=advanced_frame.time_end_var, **entry_style)
add_advanced_row(advanced_form_frame, _("⏱ End time (HH:MM:SS):"), time_end_entry)

advanced_frame.filename_template_var = tk.StringVar(value=app_settings.get('filename_template', '%(title)s.%(ext)s'))
filename_template_menu = tk.OptionMenu(
    advanced_form_frame,
    advanced_frame.filename_template_var,
    *FILENAME_TEMPLATES
)
filename_template_menu.config(highlightthickness=0)
filename_template_menu['menu'].config()
add_advanced_row(advanced_form_frame, "", filename_template_menu)

hw_accel_methods = get_hardware_acceleration_methods()
advanced_frame.hw_accel_var = tk.StringVar(value=app_settings.get('hardware_accel', 'auto'))
hw_accel_menu = tk.OptionMenu(
    advanced_form_frame,
    advanced_frame.hw_accel_var,
    *hw_accel_methods
)
hw_accel_menu.config(highlightthickness=0)
hw_accel_menu['menu'].config()
add_advanced_row(advanced_form_frame, _("⚡ Hardware acceleration:"), hw_accel_menu)

tk.Button(advanced_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat",
          font=("Segoe UI", 10)).pack(padx=28, pady=20, fill="x")

security_frame_inner = tk.Frame(security_frame)
security_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    security_frame_inner,
    text=_("⚙️ Security Settings"),
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

security_form_frame = tk.Frame(security_frame_inner)
security_form_frame.pack(padx=28, pady=10, anchor="w", fill="x")


def add_security_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_security_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_security_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_security_row.row += 1


add_security_row.row = 0

security_frame.proxy_var = tk.StringVar()
security_frame.cookie_site_var = tk.StringVar(value="youtube.com")
cookie_site_entry = tk.Entry(security_form_frame, textvariable=security_frame.cookie_site_var, **entry_style)
add_security_row(security_form_frame, _("🌐 Cookie domain (e.g., youtube.com):"), cookie_site_entry)
proxy_entry = tk.Entry(security_form_frame, textvariable=security_frame.proxy_var, **entry_style)
add_security_row(security_form_frame, _("🔌 Proxy (e.g., http://user:pass@ip:port):"), proxy_entry)

tk.Label(security_form_frame, text=_("🍪 Cookies:"), **label_style).grid(row=add_security_row.row, column=0, sticky="w",
                                                                        padx=(0, 10), pady=5)
add_security_row.row += 1

cookies_buttons_frame = tk.Frame(security_form_frame)
cookies_buttons_frame.grid(row=add_security_row.row, column=0, columnspan=2, sticky="ew", pady=5)
add_security_row.row += 1

tk.Button(cookies_buttons_frame, text=_("Chrome"), command=lambda: import_cookies_from_browser("chrome"),
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(cookies_buttons_frame, text=_("Firefox"), command=lambda: import_cookies_from_browser("firefox"),
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(cookies_buttons_frame, text=_("Edge"), command=lambda: import_cookies_from_browser("edge"),
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(cookies_buttons_frame, text=_("Opera"), command=lambda: import_cookies_from_browser("opera"),
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(cookies_buttons_frame, text=_("From File"), command=import_cookies_from_file,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(cookies_buttons_frame, text=_("Clear"), command=clear_cookies,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(security_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat",
          font=("Segoe UI", 10)).pack(padx=28, pady=20, fill="x")

queue_frame_inner = tk.Frame(queue_frame)
queue_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    queue_frame_inner,
    text=_("📜 Download Queue"),
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

queue_listbox = tk.Listbox(
    queue_frame_inner,
    font=("Segoe UI", 9),
    height=15
)
queue_listbox.pack(padx=28, pady=10, fill="both", expand=True)

queue_buttons_frame = tk.Frame(queue_frame_inner)
queue_buttons_frame.pack(padx=28, pady=5, fill="x")

queue_start_button = tk.Button(
    queue_buttons_frame,
    text=_("▶ Start"),
    command=start_queue,
    relief="flat",
    font=("Segoe UI", 10)
)
queue_start_button.pack(side=tk.LEFT, expand=True, fill="x", padx=2)

queue_pause_button = tk.Button(
    queue_buttons_frame,
    text=_("⏸ Pause"),
    command=pause_queue,
    relief="flat",
    font=("Segoe UI", 10)
)
queue_pause_button.pack(side=tk.LEFT, expand=True, fill="x", padx=2)

queue_stop_button = tk.Button(
    queue_buttons_frame,
    text=_("⏹ Stop"),
    command=stop_queue,
    relief="flat",
    font=("Segoe UI", 10)
)
queue_stop_button.pack(side=tk.LEFT, expand=True, fill="x", padx=2)

queue_clear_button = tk.Button(
    queue_buttons_frame,
    text=_("🗑 Clear"),
    command=clear_queue,
    relief="flat",
    font=("Segoe UI", 10)
)
queue_clear_button.pack(side=tk.LEFT, expand=True, fill="x", padx=2)
queue_clear_button.config(bg="#f43535", fg="white")

tk.Button(queue_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat",
          font=("Segoe UI", 10)).pack(padx=28, pady=20, fill="x")

search_input = tk.StringVar()
search_results = tk.StringVar()


def search_sites():
    query = search_input.get().strip()
    if not query:
        search_results.set("Please enter a search query.")
        return

    try:
        url = "https://raw.githubusercontent.com/thatsmeee/video-loader/main/allowed-list.md"

        proxies = None
        if hasattr(advanced_frame, 'proxy_var'):
            proxy = advanced_frame.proxy_var.get().strip()
            if proxy:
                proxies = {
                    'http': proxy,
                    'https': proxy
                }

        response = requests.get(url, proxies=proxies)
        response.raise_for_status()
        lines = response.text.splitlines()
        query_lower = query.lower()
        matches = [line for line in lines if query_lower in line.lower()]
        result_text = "\n".join(matches) if matches else "No results found."
        search_results.set(result_text)
    except requests.exceptions.RequestException as e:
        search_results.set(f"Error fetching data: {e}. Please check your internet connection.")
    except Exception as e:
        search_results.set(f"An unexpected error occurred: {e}")


search_frame_inner = tk.Frame(search_frame)
search_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    search_frame_inner,
    text=_("Search supported websites"),
    relief="flat",
    font=("Segoe UI", 10, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

search_entry = tk.Entry(search_frame_inner, textvariable=search_input, **entry_style)
search_entry.pack(padx=28, pady=(0, 10), fill="x")

tk.Button(search_frame_inner, text=_("🔎 Search"), command=search_sites,
          relief="flat",
          font=("Segoe UI", 10, "bold")).pack(padx=28, pady=(0, 20), fill="x")

tk.Label(search_frame_inner, text=_("📄 Results:"), **label_style).pack(anchor="w", padx=28, pady=(0, 5))

search_output = tk.Label(
    search_frame_inner,
    textvariable=search_results,
    font=("Consolas", 7),
    wraplength=600,
    anchor="w",
    justify="left",
    height=34
)
search_output.pack(padx=28, pady=(0, 10), fill="x")

tk.Button(search_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat",
          font=("Segoe UI", 10)).pack(padx=28, pady=(0, 30), fill="x")

history_frame_inner = tk.Frame(history_frame)
history_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    history_frame_inner,
    text=_("⏳ Download History"),
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

history_listbox = tk.Listbox(
    history_frame_inner,
    font=("Segoe UI", 9),
    height=15
)
history_listbox.pack(padx=28, pady=10, fill="both", expand=True)

history_buttons_frame = tk.Frame(history_frame_inner)
history_buttons_frame.pack(padx=28, pady=5, fill="x")

tk.Button(history_buttons_frame, text=_("🔄 Repeat Download"),
          command=lambda: repeat_selected_download(),
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=True, fill="x",
                                                     padx=5)

tk.Button(history_buttons_frame, text=_("🗑 Clear History"),
          command=clear_history,
          relief="flat", font=("Segoe UI", 10)).pack(side=tk.LEFT, expand=True, fill="x",
                                                     padx=5)


def repeat_selected_download():
    selection = history_listbox.curselection()
    if not selection:
        messagebox.showwarning("No Selection", "Please select an item from history")
        return

    history = load_history()
    index = len(history) - 1 - selection[0]
    entry = history[index]
    repeat_download(entry)


tk.Button(history_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat",
          font=("Segoe UI", 10)).pack(padx=28, pady=20, fill="x")

tk.Label(tools_frame,
         text=_("🎬 Tools"),
         justify="left",
         font=("Segoe UI", 12, "bold"),
         anchor="w"
         ).pack(pady=(30, 20), padx=28, anchor="w")

tk.Button(tools_frame, text=_("🎞 Media Converter"), command=lambda: show_frame(tools_convert_frame),
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_frame, text=_("✂ Video trim"), command=lambda: show_frame(tools_trim_frame),
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_frame, text=_("🔊 Audio Extractor"), command=lambda: show_frame(tools_extract_frame),
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_frame, text=_("🔀 Merge Videos"), command=lambda: show_frame(tools_merge_frame),
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_frame, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Label(tools_extract_frame,
         text=_("🔊 Audio Extractor"),
         font=("Segoe UI", 14, "bold"),
         anchor="w",
         justify="left"
         ).pack(pady=20, padx=28, anchor="w")

tk.Label(tools_extract_frame,
         text=_("Output audio format:"),
         font=("Segoe UI", 10)
         ).pack(padx=28, anchor="w")

audio_format_var = tk.StringVar(value="mp3")
audio_format_menu = tk.OptionMenu(
    tools_extract_frame,
    audio_format_var,
    "mp3", "wav", "ogg", "m4a", "flac", "aac"
)
audio_format_menu.config(
    highlightthickness=0,
    font=("Segoe UI", 10)
)
audio_format_menu['menu'].config(
    font=("Segoe UI", 10)
)
audio_format_menu.pack(padx=28, pady=5, fill="x")

tk.Label(tools_extract_frame,
         text="Audio quality (kbps):",
         font=("Segoe UI", 10)
         ).pack(padx=28, anchor="w")

audio_quality_var = tk.StringVar(value="192")
audio_quality_menu = tk.OptionMenu(
    tools_extract_frame,
    audio_quality_var,
    "64", "128", "192", "256", "320"
)
audio_quality_menu.config(
    highlightthickness=0,
    font=("Segoe UI", 10)
)
audio_quality_menu['menu'].config(
    font=("Segoe UI", 10)
)
audio_quality_menu.pack(padx=28, pady=5, fill="x")


def run_audio_extraction():
    video_file = filedialog.askopenfilename(
        title="Select video file",
        filetypes=[("Video files", "*.mp4;*.mkv;*.avi;*.mov;*.flv;*.webm"), ("All files", "*.*")]
    )
    if not video_file:
        return

    progress_window = tk.Toplevel(root)
    progress_window.title("Extracting Audio")
    progress_window.geometry("400x150")
    center_window_preview(progress_window)

    tk.Label(progress_window, text="Extracting audio...", font=("Segoe UI", 10)).pack(pady=10)

    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(
        progress_window,
        variable=progress_var,
        maximum=100,
        style="TProgressbar"
    )
    progress_bar.pack(fill="x", padx=20, pady=10)

    status_label = tk.Label(progress_window, text="0%", font=("Segoe UI", 10))
    status_label.pack()

    def update_progress(percent):
        progress_var.set(percent)
        status_label.config(text=f"{percent}%")
        if percent >= 100:
            progress_window.destroy()
            messagebox.showinfo("Success", "Audio extraction completed successfully!")

    base_name = os.path.splitext(os.path.basename(video_file))[0]
    audio_format = audio_format_var.get()

    output_file = filedialog.asksaveasfilename(
        title="Save audio file",
        initialfile=f"{base_name}.{audio_format}",
        defaultextension=f".{audio_format}",
        filetypes=[(f"{audio_format.upper()} files", f"*.{audio_format}"), ("All files", "*.*")]
    )

    if not output_file:
        progress_window.destroy()
        return

    def extract_audio_thread():
        try:
            duration = get_video_duration(video_file)
            quality = audio_quality_var.get()

            codec_map = {
                "mp3": "libmp3lame",
                "wav": "pcm_s16le",
                "ogg": "libvorbis",
                "m4a": "aac",
                "flac": "flac",
                "aac": "aac"
            }

            cmd = [
                ffmpeg_path,
                '-y',
                '-i', video_file,
                '-vn',
                '-acodec', codec_map[audio_format],
                '-b:a', f"{quality}k",
                '-progress', 'pipe:1',
                output_file
            ]

            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True
            )

            for line in process.stderr:
                if 'time=' in line:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.\d{2}', line)
                    if time_match and duration > 0:
                        h, m, s = map(int, time_match.groups())
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / duration) * 100)
                        root.after(0, update_progress, percent)

            process.wait()
            root.after(0, lambda: update_progress(100))

        except Exception as e:
            root.after(0, progress_window.destroy)
            root.after(0, lambda: messagebox.showerror("Error", f"An error occurred: {str(e)}"))

    threading.Thread(target=extract_audio_thread, daemon=True).start()


tk.Button(
    tools_extract_frame,
    text=_("🎵 Extract Audio"),
    command=run_audio_extraction,
    relief="flat",
    font=("Segoe UI", 11)
).pack(padx=28, pady=20, fill="x")

tk.Button(
    tools_extract_frame,
    text=_("⬅ Back"),
    command=lambda: show_frame(tools_frame),
    relief="flat",
    font=("Segoe UI", 10)
).pack(padx=28, pady=(30, 0), fill="x")

tk.Label(tools_convert_frame,
         text=_("🎞 Media Converter"),
         font=("Segoe UI", 12, "bold"),
         anchor="w",
         justify="left"
         ).pack(pady=20, padx=28, anchor="w")

tk.Label(tools_convert_frame, text=_("Enter output format (e.g., mp4, mkv, avi):"),
         font=("Segoe UI", 10)).pack(padx=28, anchor="w")
convert_format_var = tk.StringVar(value="mp4")
tk.Entry(tools_convert_frame, textvariable=convert_format_var, **entry_style).pack(padx=28, pady=5, fill="x")


def get_video_duration(file_path):
    try:
        result = subprocess.run(
            [ffmpeg_path, '-i', file_path],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True
        )

        for line in result.stderr.split('\n'):
            if 'Duration:' in line:
                time_str = line.split('Duration:')[1].split(',')[0].strip()
                h, m, s = time_str.split(':')
                return int(h) * 3600 + int(m) * 60 + float(s)
        return 0
    except Exception:
        return 0


def convert_video():
    infile = filedialog.askopenfilename(title="Select video")
    if not infile:
        return

    progress_window = tk.Toplevel(root)
    progress_window.title("Converting Video")
    progress_window.geometry("400x150")
    center_window_preview(progress_window)

    tk.Label(progress_window, text="Converting video...", font=("Segoe UI", 10)).pack(pady=10)

    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(
        progress_window,
        variable=progress_var,
        maximum=100,
        style="TProgressbar"
    )
    progress_bar.pack(fill="x", padx=20, pady=10)

    status_label = tk.Label(progress_window, text="0%", font=("Segoe UI", 10))
    status_label.pack()

    def update_progress(percent):
        progress_var.set(percent)
        status_label.config(text=f"{percent}%")
        if percent >= 100:
            progress_window.destroy()
            messagebox.showinfo("Success", "Video converted successfully!")

    fmt = convert_format_var.get().strip().lower()
    if not fmt:
        progress_window.destroy()
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
        progress_window.destroy()
        return

    def convert_thread():
        try:
            duration = get_video_duration(infile)

            cmd = [
                ffmpeg_path,
                '-y',
                '-i', infile,
                '-progress', 'pipe:1',
                outfile
            ]

            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True
            )

            for line in process.stderr:
                if 'time=' in line:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.\d{2}', line)
                    if time_match and duration > 0:
                        h, m, s = map(int, time_match.groups())
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / duration) * 100)
                        root.after(0, update_progress, percent)

            process.wait()
            root.after(0, lambda: update_progress(100))

        except Exception as e:
            root.after(0, progress_window.destroy)
            root.after(0, lambda: messagebox.showerror("Error", f"An error occurred: {str(e)}"))

    threading.Thread(target=convert_thread, daemon=True).start()


tk.Button(tools_convert_frame, text=_("🔄 Convert video"), command=convert_video,
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_convert_frame, text=_("⬅ Back"), command=lambda: show_frame(tools_frame),
          relief="flat", font=("Segoe UI", 10)).pack(padx=28, pady=(30, 0), fill="x")

tk.Label(tools_trim_frame,
         text=_("✂ Video trimming"),
         font=("Segoe UI", 14, "bold"),
         anchor="w",
         justify="left"
         ).pack(pady=20, padx=28, anchor="w")

tk.Label(tools_trim_frame, text=_("Start time (format HH:MM:SS or seconds):"),
         font=("Segoe UI", 10)).pack(padx=28, anchor="w")
trim_start_var = tk.StringVar()
tk.Entry(tools_trim_frame, textvariable=trim_start_var, **entry_style).pack(padx=28, pady=5, fill="x")

tk.Label(tools_trim_frame, text=_("End time (format HH:MM:SS or seconds):"),
         font=("Segoe UI", 10)).pack(padx=28, anchor="w")
trim_end_var = tk.StringVar()
tk.Entry(tools_trim_frame, textvariable=trim_end_var, **entry_style).pack(padx=28, pady=5, fill="x")


def trim_video():
    infile = filedialog.askopenfilename(title="Select video")
    if not infile:
        return

    progress_window = tk.Toplevel(root)
    progress_window.title("Trimming Video")
    progress_window.geometry("400x150")
    center_window_preview(progress_window)

    tk.Label(progress_window, text="Trimming video...", font=("Segoe UI", 10)).pack(pady=10)

    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(
        progress_window,
        variable=progress_var,
        maximum=100,
        style="TProgressbar"
    )
    progress_bar.pack(fill="x", padx=20, pady=10)

    status_label = tk.Label(progress_window, text="0%", font=("Segoe UI", 10))
    status_label.pack()

    def update_progress(percent):
        progress_var.set(percent)
        status_label.config(text=f"{percent}%")
        if percent >= 100:
            progress_window.destroy()
            messagebox.showinfo("Success", "Video trimmed successfully!")

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
        progress_window.destroy()
        return

    start = trim_start_var.get().strip()
    end = trim_end_var.get().strip()

    if not start or not end:
        progress_window.destroy()
        messagebox.showerror("Error", "Please specify both start and end time.")
        return

    def trim_thread():
        try:
            duration = get_video_duration(infile)

            cmd = [
                ffmpeg_path,
                '-y',
                '-ss', start,
                '-to', end,
                '-i', infile,
                '-c', 'copy',
                '-progress', 'pipe:1',
                outfile
            ]

            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )

            for line in process.stderr:
                if 'time=' in line:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.\d{2}', line)
                    if time_match and duration > 0:
                        h, m, s = map(int, time_match.groups())
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / duration) * 100)
                        root.after(0, update_progress, percent)

            process.wait()
            root.after(0, lambda: update_progress(100))

        except Exception as e:
            root.after(0, progress_window.destroy)
            root.after(0, lambda: messagebox.showerror("Error", f"Failed to trim video: {str(e)}"))

    threading.Thread(target=trim_thread, daemon=True).start()


tk.Button(tools_trim_frame, text=_("✂ Trim"), command=trim_video,
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=10, fill="x")

tk.Button(tools_trim_frame, text=_("⬅️ Back"), command=lambda: show_frame(tools_frame),
          relief="flat", font=("Segoe UI", 10)).pack(padx=28, pady=(30, 0), fill="x")

tk.Label(tools_merge_frame,
         text=_("🔀 Video Merger"),
         font=("Segoe UI", 14, "bold"),
         anchor="w",
         justify="left"
         ).pack(pady=20, padx=28, anchor="w")

tk.Label(tools_merge_frame,
         text=_("Select multiple video files to merge (same codec recommended):"),
         font=("Segoe UI", 10)
         ).pack(padx=28, anchor="w")

merge_files = []


def add_merge_files():
    files = filedialog.askopenfilenames(
        title="Select video files to merge",
        filetypes=[("Video files", "*.mp4;*.mkv;*.avi;*.mov;*.flv;*.webm"), ("All files", "*.*")]
    )
    if files:
        merge_files.extend(files)
        update_merge_list()


def update_merge_list():
    merge_listbox.delete(0, tk.END)
    for i, file in enumerate(merge_files, 1):
        merge_listbox.insert(tk.END, f"{i}. {os.path.basename(file)}")


def remove_selected_file():
    selection = merge_listbox.curselection()
    if selection:
        merge_files.pop(selection[0])
        update_merge_list()


def clear_merge_list():
    merge_files.clear()
    update_merge_list()


def move_file_up():
    selection = merge_listbox.curselection()
    if selection and selection[0] > 0:
        index = selection[0]
        merge_files[index], merge_files[index - 1] = merge_files[index - 1], merge_files[index]
        update_merge_list()
        merge_listbox.select_set(index - 1)


def move_file_down():
    selection = merge_listbox.curselection()
    if selection and selection[0] < len(merge_files) - 1:
        index = selection[0]
        merge_files[index], merge_files[index + 1] = merge_files[index + 1], merge_files[index]
        update_merge_list()
        merge_listbox.select_set(index + 1)


merge_listbox = tk.Listbox(
    tools_merge_frame,
    font=("Segoe UI", 9),
    height=8
)
merge_listbox.pack(padx=28, pady=10, fill="x")

merge_buttons_frame = tk.Frame(tools_merge_frame)
merge_buttons_frame.pack(padx=28, pady=5, fill="x")

tk.Button(merge_buttons_frame, text=_("➕ Add Files"), command=add_merge_files,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(merge_buttons_frame, text=_("➖ Remove"), command=remove_selected_file,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(merge_buttons_frame, text=_("🔼 Up"), command=move_file_up,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(merge_buttons_frame, text=_("🔽 Down"), command=move_file_down,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Button(merge_buttons_frame, text=_("🗑 Clear"), command=clear_merge_list,
          relief="flat", font=("Segoe UI", 9)).pack(side=tk.LEFT, expand=True, fill="x",
                                                    padx=2)

tk.Label(tools_merge_frame,
         text=_("Output format:"),
         font=("Segoe UI", 10)
         ).pack(padx=28, anchor="w")

merge_format_var = tk.StringVar(value="mp4")
merge_format_menu = tk.OptionMenu(
    tools_merge_frame,
    merge_format_var,
    "mp4", "mkv", "avi", "mov", "webm"
)
merge_format_menu.config(
    highlightthickness=0,
    font=("Segoe UI", 10)
)
merge_format_menu['menu'].config(
    font=("Segoe UI", 10)
)
merge_format_menu.pack(padx=28, pady=5, fill="x")


def merge_videos():
    if len(merge_files) < 2:
        messagebox.showerror("Error", "Please select at least 2 video files to merge")
        return

    progress_window = tk.Toplevel(root)
    progress_window.title("Merging Videos")
    progress_window.geometry("400x150")
    center_window_preview(progress_window)

    tk.Label(progress_window, text="Merging videos...", font=("Segoe UI", 10)).pack(pady=10)

    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(
        progress_window,
        variable=progress_var,
        maximum=100,
        style="TProgressbar"
    )
    progress_bar.pack(fill="x", padx=20, pady=10)

    status_label = tk.Label(progress_window, text="0%", font=("Segoe UI", 10))
    status_label.pack()

    def update_progress(percent):
        progress_var.set(percent)
        status_label.config(text=f"{percent}%")
        if percent >= 100:
            progress_window.destroy()
            messagebox.showinfo("Success", "Videos merged successfully!")

    list_file = os.path.join(os.path.dirname(merge_files[0]), "ffmpeg_concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for file in merge_files:
            f.write(f"file '{file}'\n")

    output_format = merge_format_var.get()
    output_file = filedialog.asksaveasfilename(
        title="Save merged video as",
        defaultextension=f".{output_format}",
        filetypes=[(f"{output_format.upper()} files", f"*.{output_format}"), ("All files", "*.*")]
    )

    if not output_file:
        progress_window.destroy()
        return

    def merge_thread():
        try:
            total_duration = 0
            for file in merge_files:
                duration = get_video_duration(file)
                if duration > 0:
                    total_duration += duration

            cmd = [
                ffmpeg_path,
                '-f', 'concat',
                '-safe', '0',
                '-i', list_file,
                '-c', 'copy',
                '-progress', 'pipe:1',
                output_file
            ]

            process = subprocess.Popen(
                cmd,
                stderr=subprocess.PIPE,
                stdout=subprocess.PIPE,
                universal_newlines=True
            )

            for line in process.stderr:
                if 'time=' in line:
                    time_match = re.search(r'time=(\d{2}):(\d{2}):(\d{2})\.\d{2}', line)
                    if time_match and total_duration > 0:
                        h, m, s = map(int, time_match.groups())
                        current_time = h * 3600 + m * 60 + s
                        percent = int((current_time / total_duration) * 100)
                        root.after(0, update_progress, percent)

            process.wait()
            os.remove(list_file)
            root.after(0, lambda: update_progress(100))

        except Exception as e:
            root.after(0, progress_window.destroy)
            root.after(0, lambda: messagebox.showerror("Error", f"Failed to merge videos: {str(e)}"))

    threading.Thread(target=merge_thread, daemon=True).start()


tk.Button(tools_merge_frame, text="🔀 Merge Videos", command=merge_videos,
          relief="flat", font=("Segoe UI", 11)).pack(padx=28, pady=20, fill="x")

tk.Button(tools_merge_frame, text="⬅️ Back", command=lambda: show_frame(tools_frame),
          relief="flat", font=("Segoe UI", 10)).pack(padx=28, pady=(30, 0), fill="x")

help_frame_inner = tk.Frame(help_frame)
help_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    help_frame_inner,
    text=_("📚 Usage manual"),
    relief="flat",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

text_frame = tk.Frame(help_frame_inner)
text_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

scrollbar = tk.Scrollbar(text_frame)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

help_text = tk.Text(
    text_frame,
    font=("Segoe UI", 10),
    wrap=tk.WORD,
    yscrollcommand=scrollbar.set
)
help_text.pack(fill=tk.BOTH, expand=True)
scrollbar.config(command=help_text.yview)

help_content = """
    📚 Enhanced YouTube Downloader - Help

    🔹 Main features:
    1. Paste the video URL in the "Video URL" field
    2. Select the format (mp4, mp3, etc.)
    3. Specify the quality (for example: best, 720, 480)
    4. Select the folder to save
    5. Click "Download"

    🔹 Additional features:
    - Convert video to other formats
    - Trim video by time
    - Extract audio from video
    - Merge multiple videos
    - Download queue with control (pause/cancel)
    - Optimize CPU/GPU usage during conversion

    🔹 Hot keys:
    - Ctrl+V: Paste URL from clipboard
    - F1: Open this help
    - Ctrl+Q: Quickly view videos

    🔹 Supported sites:
    - YouTube, Vimeo, Dailymotion
    - Facebook, Twitter, Instagram
    - And many more (see Search tab)

    For more help visit:
    https://github.com/thatsmeee/video-loader
"""

help_text.insert(tk.END, help_content)
help_text.config(state=tk.DISABLED)

tk.Button(
    help_frame_inner,
    text=_("⬅ Back"),
    command=lambda: show_frame(main_frame),
    relief="flat",
    font=("Segoe UI", 10)
).pack(padx=28, pady=20, fill="x")

settings_frame_inner = tk.Frame(settings_frame)
settings_frame_inner.place(relwidth=1, relheight=1)

tk.Label(
    settings_frame_inner,
    text="⚙️ Settings",
    font=("Segoe UI", 12, "bold"),
    anchor="w",
    justify="left"
).pack(padx=28, pady=(20, 10), fill="x", anchor="w")

settings_form_frame = tk.Frame(settings_frame_inner)
settings_form_frame.pack(padx=28, pady=10, anchor="w", fill="x")


def add_settings_row(master, label_text, widget):
    label = tk.Label(master, text=label_text, **label_style)
    label.grid(row=add_settings_row.row, column=0, sticky="w", padx=(0, 10), pady=5)
    widget.grid(row=add_settings_row.row, column=1, sticky="ew", pady=5)
    master.grid_columnconfigure(1, weight=1)
    add_settings_row.row += 1


add_settings_row.row = 0

theme_var = tk.StringVar(value=app_settings.get('theme', 'dark'))
tk.Label(settings_form_frame, text="Theme:", **label_style).grid(row=add_settings_row.row, column=0, sticky="w",
                                                                 padx=(0, 10), pady=5)
theme_frame = tk.Frame(settings_form_frame)
theme_frame.grid(row=add_settings_row.row, column=1, sticky="ew", pady=5)
add_settings_row.row += 1

tk.Radiobutton(
    theme_frame,
    text="Dark",
    variable=theme_var,
    value="dark",
    command=lambda: apply_theme('dark'),
    selectcolor="black",
    **label_style,
).pack(side=tk.LEFT, padx=5)

tk.Radiobutton(
    theme_frame,
    text="Light",
    variable=theme_var,
    value="light",
    command=lambda: apply_theme('light'),
    **label_style
).pack(side=tk.LEFT, padx=5)

tk.Label(
    settings_form_frame,
    text=_("🌍 Language Selection"),
    font=("Segoe UI", 12, "bold"),
    anchor="w", justify="left"
).grid(row=add_settings_row.row, column=0, sticky="w", padx=5, pady=(20, 10))

add_settings_row.row += 1

tk.Label(settings_form_frame, text="Select language:", font=("Segoe UI", 10)).grid(
    row=add_settings_row.row, column=0, sticky="w", padx=(5, 10), pady=5
)

lang_var = tk.StringVar(value=app_settings.get("default_language", "uk"))

available_languages = {
    "uk": "Ukrainian",
    "en": "English",
    "ru": "Russian"
}


def change_language(lang_code):
    app_settings.set("default_language", lang_code)
    show_toast("Language changed to" + f": {available_languages[lang_code]}")
    messagebox.showinfo("Info", "Please restart the application to apply the language.")


lang_menu = tk.OptionMenu(
    settings_form_frame,
    lang_var,
    *available_languages.values(),
    command=lambda selected_name: change_language(
        [code for code, name in available_languages.items() if name == selected_name][0]
    )
)
lang_menu.grid(row=add_settings_row.row, column=1, sticky="w", pady=5)
add_settings_row.row += 1

filename_template_menu.config(highlightthickness=0)
filename_template_menu.grid(row=add_settings_row.row, column=1, sticky="ew", pady=5)
add_settings_row.row += 1

tk.Button(settings_frame_inner, text=_("⬅ Back"), command=lambda: show_frame(main_frame),
          relief="flat", font=("Segoe UI", 10)).pack(padx=28, pady=20, fill="x")

update_history_list()
show_frame(main_frame)

apply_theme(app_settings.get('theme', 'dark'))


def on_focus_in(event):
    try:
        clipboard_text = root.clipboard_get()
        if clipboard_text.startswith(('http://', 'https://')):
            url_entry.delete(0, tk.END)
            url_entry.insert(0, clipboard_text)
    except tk.TclError:
        pass


root.bind("<F1>", lambda e: show_frame(help_frame))
root.bind("<Control-q>", lambda e: preview_video())

url_entry.bind("<FocusIn>", on_focus_in)
root.mainloop()
