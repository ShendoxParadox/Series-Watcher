import os
import re
import json
import vlc
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from urllib.parse import quote
from PIL import Image, ImageTk

# Constants
LAST_POSITION_FILE = 'last_position.json'
CHECK_INTERVAL = 250  # Interval to check the video time (in milliseconds)
SAVE_INTERVAL = 5000  # Interval to save the video position (in milliseconds)
THRESHOLD = 1.5  # Threshold in seconds to trigger the next episode
IMAGE_FILE_EXTENSIONS = ['png', 'jpg', 'jpeg']  # Supported image file extensions
IMAGE_MAX_SIZE = (400, 300)  # Maximum size for the displayed image
SUBTITLE_UPDATE_RETRY_INTERVAL = 1000  # Interval to retry fetching subtitles (in milliseconds)
SUBTITLE_UPDATE_RETRY_COUNT = 5  # Number of times to retry fetching subtitles

# Regular expression for episode detection
EPISODE_REGEX = re.compile(r'[eE](\d{2})')
THEME = 'clam'
# ('clam', 'alt', 'default', 'classic')


def get_and_rename_series_structure(base_path):
    series_structure = {}
    for season in sorted(os.listdir(base_path)):
        season_path = os.path.join(base_path, season)
        if os.path.isdir(season_path):
            episodes = sorted(os.listdir(season_path))
            renamed_episodes = []
            episode_count = 1
            for episode in episodes:
                match = EPISODE_REGEX.search(episode)
                if match:
                    new_episode_name = f"e{episode_count:02d}"  # Remove the extension
                    new_episode_path = os.path.join(season_path, new_episode_name)
                    old_episode_path = os.path.join(season_path, episode)
                    os.rename(old_episode_path, new_episode_path)
                    renamed_episodes.append(new_episode_name)
                    episode_count += 1
                else:
                    renamed_episodes.append(episode)
            series_structure[season] = renamed_episodes
    return series_structure



def save_last_position(series_index, season, episode, time, root_path):
    data = load_json()
    data[series_index] = {'season': season, 'episode': episode, 'time': time, 'root_path': root_path}
    with open(LAST_POSITION_FILE, 'w') as f:
        json.dump(data, f)

def load_last_position():
    try:
        with open(LAST_POSITION_FILE, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return [{}, {}, {}]  # Default to three empty series



def reset_last_position():
    with open(LAST_POSITION_FILE, 'w') as f:
        json.dump([{}, {}, {}], f)


def delete_last_position():
    if os.path.exists(LAST_POSITION_FILE):
        os.remove(LAST_POSITION_FILE)
        messagebox.showinfo("File Deleted", "last_position.json has been deleted.")
    else:
        messagebox.showinfo("File Not Found", "last_position.json does not exist.")


def find_image_file(base_path):
    for ext in IMAGE_FILE_EXTENSIONS:
        img_path = os.path.join(base_path, f'img.{ext}')
        if os.path.exists(img_path):
            return img_path
    return None


def load_json():
    try:
        with open(LAST_POSITION_FILE, 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        return [{}, {}, {}]


class VideoPlayer:
    def __init__(self, series_index):
        self.series_index = series_index
        self.player = vlc.MediaPlayer()
        self.current_season = 's01'
        self.current_episode = 'e01'
        self.current_time = 0  # Track the current playback time in seconds
        self.series_structure = {}
        self.skip_seconds = 30  # Default skip time in seconds
        self.root = None  # Tkinter root for scheduling checks
        self.update_callback = None  # Callback function to update the UI
        self.base_path = None
        self.subtitle_retry_count = 0

    def set_series_structure(self, structure):
        self.series_structure = structure

    def set_update_callback(self, callback):
        self.update_callback = callback

    def set_base_path(self, path):
        self.base_path = path

    def play_episode(self, season, episode, time=0):
        path = os.path.join(self.base_path, season, episode)
        media = vlc.Media(f'file://{quote(path)}')
        self.player.set_media(media)
        self.player.play()
        self.player.set_time(int(time * 1000))  # Set the playback time in milliseconds
        save_last_position(self.series_index, season, episode, time, self.base_path)
        self.schedule_check()
        self.schedule_save_position()
        self.update_playback_bar()
        self.subtitle_retry_count = 0
        self.schedule_subtitle_update()  # Schedule subtitle tracks update

    def pause(self):
        self.player.pause()
        self.save_position()

    def stop(self):
        self.player.stop()
        self.save_position()

    def fast_forward(self):
        current_time = self.player.get_time()
        self.player.set_time(current_time + self.skip_seconds * 1000)  # Convert seconds to milliseconds

    def rewind(self):
        current_time = self.player.get_time()
        self.player.set_time(max(0, current_time - self.skip_seconds * 1000))  # Convert seconds to milliseconds

    def next_episode(self):
        episodes = self.series_structure[self.current_season]
        current_index = episodes.index(self.current_episode)
        if current_index + 1 < len(episodes):
            self.current_episode = episodes[current_index + 1]
        else:
            seasons = sorted(self.series_structure.keys())
            current_season_index = seasons.index(self.current_season)
            if current_season_index + 1 < len(seasons):
                self.current_season = seasons[current_season_index + 1]
                self.current_episode = self.series_structure[self.current_season][0]
            else:
                messagebox.showinfo("End of Series", "End of series reached.")
                return
        self.play_episode(self.current_season, self.current_episode)
        if self.update_callback:
            self.update_callback()

    def previous_episode(self):
        episodes = self.series_structure[self.current_season]
        current_index = episodes.index(self.current_episode)
        if current_index - 1 >= 0:
            self.current_episode = episodes[current_index - 1]
        else:
            seasons = sorted(self.series_structure.keys())
            current_season_index = seasons.index(self.current_season)
            if current_season_index - 1 >= 0:
                self.current_season = seasons[current_season_index - 1]
                self.current_episode = self.series_structure[self.current_season][-1]
            else:
                messagebox.showinfo("Start of Series", "You are at the first episode.")
                return
        self.play_episode(self.current_season, self.current_episode)
        if self.update_callback:
            self.update_callback()

    def set_skip_seconds(self, seconds):
        try:
            self.skip_seconds = int(seconds)
        except ValueError:
            messagebox.showerror("Invalid Input", "Please enter a valid number of seconds.")

    def schedule_check(self):
        if self.root is not None:
            self.root.after(CHECK_INTERVAL, self.check_episode_end)

    def check_episode_end(self):
        if self.player.is_playing():
            current_time = self.player.get_time() / 1000  # Convert to seconds
            total_time = self.player.get_length() / 1000  # Convert to seconds
            self.current_time = current_time
            if total_time - current_time <= THRESHOLD:
                self.next_episode()
            else:
                self.schedule_check()

    def schedule_save_position(self):
        if self.root is not None:
            self.root.after(SAVE_INTERVAL, self.save_position_periodically)

    def save_position_periodically(self):
        if self.player.is_playing():
            self.save_position()
        self.schedule_save_position()

    def save_position(self):
        self.current_time = self.player.get_time() / 1000  # Convert to seconds
        save_last_position(self.series_index, self.current_season, self.current_episode, self.current_time, self.base_path)

    def update_playback_bar(self):
        if self.root and self.update_callback:
            self.update_callback()
        self.root.after(CHECK_INTERVAL, self.update_playback_bar)

    def schedule_subtitle_update(self):
        if self.subtitle_retry_count < SUBTITLE_UPDATE_RETRY_COUNT:
            self.root.after(SUBTITLE_UPDATE_RETRY_INTERVAL, self.update_subtitle_tracks)

    def get_subtitle_tracks(self):
        root.after(1000)
        track_description = self.player.video_get_spu_description()
        if track_description:
            return track_description
        return []

    def set_subtitle_track(self, track_id):
        self.player.video_set_spu(track_id)

    def update_subtitle_tracks(self):
        subtitles = self.get_subtitle_tracks()
        if subtitles or self.subtitle_retry_count >= SUBTITLE_UPDATE_RETRY_COUNT:
            if self.update_callback:
                self.update_callback()
        else:
            self.subtitle_retry_count += 1
            self.schedule_subtitle_update()


class VideoPlayerApp:
    def __init__(self, root, series_index):
        self.root = root
        self.series_index = series_index
        self.root.title(f"Video Player - Series {series_index + 1}")
        self.player = VideoPlayer(series_index)
        self.player.root = root  # Pass Tkinter root to the player for scheduling
        self.player.set_update_callback(self.update_playback_bar)  # Set callback to update label and progress bar

        self.style = ttk.Style()
        self.style.theme_use(THEME)  # Apply the theme globally
        # Set global background color
        self.root.configure(background="#2E2E2E")

        # Configure ttk styles to match the background color
        self.style.configure("TLabel", background="#2E2E2E", foreground="white")
        self.style.configure("TFrame", background="#2E2E2E")
        # self.style.configure("TButton", background="#4CAF50", foreground="white")
        self.style.map("TButton",
                       background=[("active", "#45a049")],
                       foreground=[("active", "white")])
        
        self.style.configure("TProgressbar", troughcolor="#3E3E3E", background="#4CAF50")


        last_position = load_last_position()[series_index]
        if last_position:
            last_season, last_episode, last_time, last_base_path = last_position['season'], last_position['episode'], last_position['time'], last_position['root_path']
            if last_base_path:
                self.player.set_base_path(last_base_path)
                self.series_structure = get_and_rename_series_structure(last_base_path)
                self.player.set_series_structure(self.series_structure)
            self.player.current_season = last_season
            self.player.current_episode = last_episode
            self.player.current_time = last_time

        self.style = ttk.Style()
        self.style.configure("TLabel", padding=6, font=("Helvetica", 12))
        self.style.configure("TButton", padding=6, font=("Helvetica", 12))

        self.label = ttk.Label(root, text=f"Current Episode: {self.player.current_season} {self.player.current_episode}")
        self.label.pack(pady=(10, 0))

        self.progress = ttk.Progressbar(root, orient="horizontal", length=400, mode="determinate")
        self.progress.pack(pady=(0, 10))

        self.image_label = ttk.Label(root)
        self.image_label.pack(pady=(0, 10))
        self.load_image()

        self.browse_button = ttk.Button(root, text="Browse", command=self.browse_folder)
        self.browse_button.pack(pady=5)

        self.play_button = ttk.Button(root, text="Continue", command=self.play)
        self.play_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.pause_button = ttk.Button(root, text="Pause", command=self.pause)
        self.pause_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.next_button = ttk.Button(root, text="Next", command=self.next_episode)
        self.next_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.previous_button = ttk.Button(root, text="Previous", command=self.previous_episode)
        self.previous_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.fast_forward_button = ttk.Button(root, text="Fast Forward", command=self.fast_forward)
        self.fast_forward_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.rewind_button = ttk.Button(root, text="Rewind", command=self.rewind)
        self.rewind_button.pack(side=tk.LEFT, padx=5, pady=5)

        self.skip_entry_label = ttk.Label(root, text="Enter skip time in seconds:")
        self.skip_entry_label.pack(pady=(10, 0))

        self.skip_entry = ttk.Entry(root)
        self.skip_entry.pack(pady=(0, 10))

        self.set_skip_button = ttk.Button(root, text="Set Skip Time", command=self.set_skip_seconds)
        self.set_skip_button.pack()

        self.subtitle_label = ttk.Label(root, text="Select Subtitle:")
        self.subtitle_label.pack(pady=(10, 0))

        self.subtitle_combobox = ttk.Combobox(root, state="readonly")
        self.subtitle_combobox.pack(pady=(0, 10))
        self.subtitle_combobox.bind("<<ComboboxSelected>>", self.subtitle_selected)

        self.delete_button = ttk.Button(root, text="Delete Last Position", command=self.delete_last_position)
        self.delete_button.pack(pady=5)

    def play(self):
        self.player.play_episode(self.player.current_season, self.player.current_episode, self.player.current_time)
        self.update_label()
        self.update_subtitle_combobox()

    def pause(self):
        self.player.pause()

    def next_episode(self):
        self.player.next_episode()
        self.update_label()
        self.update_subtitle_combobox()

    def previous_episode(self):
        self.player.previous_episode()
        self.update_label()
        self.update_subtitle_combobox()

    def fast_forward(self):
        self.player.fast_forward()

    def rewind(self):
        self.player.rewind()

    def set_skip_seconds(self):
        skip_seconds = self.skip_entry.get()
        self.player.set_skip_seconds(skip_seconds)

    def update_label(self):
        text = f"Current Episode: {self.player.current_season} {self.player.current_episode}"
        self.label.config(text=text)

    def update_playback_bar(self):
        current_time = self.player.player.get_time() / 1000  # Convert to seconds
        total_time = self.player.player.get_length() / 1000  # Convert to seconds
        if total_time > 0:
            self.progress["value"] = (current_time / total_time) * 100
        else:
            self.progress["value"] = 0
        self.update_label()

    def load_image(self):
        if self.player.base_path:
            img_path = find_image_file(self.player.base_path)
            if img_path:
                image = Image.open(img_path)
                image.thumbnail(IMAGE_MAX_SIZE, Image.ANTIALIAS)  # Preserve aspect ratio
                photo = ImageTk.PhotoImage(image)
                self.image_label.config(image=photo)
                self.image_label.image = photo  # Keep a reference to avoid garbage collection


    def browse_folder(self):
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            # Update only the current series info
            data = load_last_position()
            data[self.series_index] = {'season': 's01', 'episode': 'e01', 'time': 0, 'root_path': folder_selected}
            with open(LAST_POSITION_FILE, 'w') as f:
                json.dump(data, f)
            
            self.player.set_base_path(folder_selected)
            self.series_structure = get_and_rename_series_structure(folder_selected)
            self.player.set_series_structure(self.series_structure)
            self.load_image()
            self.update_label()


    def update_subtitle_combobox(self):
        subtitles = self.player.get_subtitle_tracks()
        subtitle_list = [sub[1] for sub in subtitles]  # Extract the name from the tuple
        self.subtitle_combobox['values'] = subtitle_list
        if subtitles:
            self.subtitle_combobox.current(0)

    def subtitle_selected(self, event):
        selected_index = self.subtitle_combobox.current()
        subtitles = self.player.get_subtitle_tracks()
        if selected_index >= 0 and selected_index < len(subtitles):
            track_id = subtitles[selected_index][0]  # Extract the ID from the tuple
            self.player.set_subtitle_track(track_id)

    def delete_last_position(self):
        delete_last_position()


class HomePage:
    def __init__(self, root):
        self.root = root
        self.root.title("Series Watcher")
        self.series_data = load_last_position()
        self.frames = []
        self.images = []
        self.setup_ui()

    def setup_ui(self):
        self.style = ttk.Style()
        self.style.theme_use(THEME)  # Apply the theme globally
        self.root.configure(background="#2E2E2E")
        self.style.configure("TLabel", padding=6, font=("Helvetica", 14))
        self.style.configure("TButton", padding=6, font=("Helvetica", 12))

        self.style.configure("TLabel", background="#2E2E2E", foreground="white")
        self.style.configure("TFrame", background="#2E2E2E")
        # self.style.configure("TButton", background="#4CAF50", foreground="white")
        self.style.map("TButton",
                       background=[("active", "#45a049")],
                       foreground=[("active", "white")])
        
        # self.style.configure("TProgressbar", troughcolor="#3E3E3E", background="#4CAF50")


        ttk.Label(self.root, text="Select a Series to Watch").pack(pady=20)

        self.frame_container = ttk.Frame(self.root)
        self.frame_container.pack(pady=20)

        for i in range(3):
            frame = ttk.Frame(self.frame_container)
            frame.grid(row=0, column=i, padx=10)
            self.frames.append(frame)
            self.setup_series_slot(i)

    def setup_series_slot(self, index):
        series_info = self.series_data[index]
        image_label = ttk.Label(self.frames[index])
        image_label.pack()

        if 'root_path' in series_info:
            img_path = find_image_file(series_info['root_path'])
            if img_path:
                image = Image.open(img_path)
                image.thumbnail(IMAGE_MAX_SIZE, Image.ANTIALIAS)  # Preserve aspect ratio
                photo = ImageTk.PhotoImage(image)
                image_label.config(image=photo)
                image_label.image = photo  # Keep a reference to avoid garbage collection

        ttk.Button(self.frames[index], text=f"Series {index + 1}", command=lambda idx=index: self.open_series(idx)).pack(pady=10)

    def open_series(self, series_index):
        self.root.destroy()
        new_root = tk.Tk()
        VideoPlayerApp(new_root, series_index)
        new_root.mainloop()


if __name__ == '__main__':
    root = tk.Tk()
    HomePage(root)
    root.mainloop()
