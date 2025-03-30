import tkinter
import tkinter.filedialog
import customtkinter as ctk
from PIL import Image, ImageTk, UnidentifiedImageError, ImageOps
import os
import threading
import queue # For thread-safe communication
import io # For intermediate saving/loading if needed
import sys # To get script directory
import time # For the exit delay (though 'after' is used)

# --- Pygame for Audio ---
try:
    import pygame
    pygame_available = True
except ImportError:
    pygame_available = False
    print("Warning: Pygame not found. Music playback will be disabled.")
    print("Install pygame: pip install pygame")

# --- Constants ---
DEFAULT_BG_COLOR_RGB = (255, 255, 255) # White
DEFAULT_BG_COLOR_RGBA = (255, 255, 255, 0) # Transparent White

# Color codes for visual impact labels
COLOR_GREEN = "#34A853"  # Subtle/Lossless
COLOR_YELLOW = "#FBBC05" # Barely Noticeable
COLOR_ORANGE = "#F29900" # Noticeable
COLOR_RED = "#EA4335"   # Highly Impactful

# Default compression settings
DEFAULT_COMPRESSION_SETTINGS = {
    "enabled": False,
    "strip_metadata": {"enabled": False},
    "optimize": {"enabled": False},
    "jpeg_quality": {"enabled": False, "value": 85},
    "quantize": {"enabled": False, "colors": 256}
}

# --- Music Settings ---
MUSIC_FILENAME = 'music.ogg'
MUSIC_VOLUME = 0.15 # 15% volume

      
# --- Get Base Directory ---
def get_base_dir():
    """ Get the base directory for data files, handling frozen executables. """
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    else:
        # Running as a normal Python script.
        try:
            # __file__ is the path to the current script.
            return os.path.dirname(os.path.abspath(__file__))
        except NameError:
            # Fallback if __file__ is not defined (e.g., interactive interpreter)
            return os.getcwd()

BASE_DIR = get_base_dir()
MUSIC_FILE_PATH = os.path.join(BASE_DIR, MUSIC_FILENAME)

print(f"Attempting to load music from: {MUSIC_FILE_PATH}")
if not os.path.exists(MUSIC_FILE_PATH):
    print(f"!!! CRITICAL ERROR: Music file does NOT exist at expected runtime path: {MUSIC_FILE_PATH}")
# ---------------------------------------------------------------------

# --- Core Image Processing Functions ---
# (apply_compression and make_image_square remain unchanged from the previous version)
def apply_compression(img, settings):
    """Applies selected compression techniques BEFORE padding/saving."""
    if settings.get("quantize", {}).get("enabled"):
        num_colors = settings.get("quantize", {}).get("colors", 256)
        try:
            original_mode = img.mode
            if img.mode not in ('RGB', 'RGBA', 'L', 'P'):
                 img = img.convert('RGBA' if 'A' in original_mode else 'RGB')

            bits_per_channel = max(1, int(num_colors**(1/3)).bit_length())
            if bits_per_channel > 8: bits_per_channel = 8
            # Posterize often gives more predictable results than quantize for this
            img = ImageOps.posterize(img.convert('RGB'), bits_per_channel)

            if 'A' in original_mode:
                 if img.mode != 'RGBA': img = img.convert('RGBA')
            elif img.mode != 'RGB':
                 img = img.convert('RGB')

            print(f"Applied quantization/posterization to ~{num_colors} colors (using {bits_per_channel} bits)")
        except Exception as e:
            print(f"Error during quantization: {e}")
    return img

def make_image_square(image_path, output_folder, compression_settings):
    """Converts an image to a 1:1 aspect ratio by padding, applying compression."""
    try:
        img = Image.open(image_path)
        original_format = img.format

        if compression_settings.get("enabled", False):
            img = apply_compression(img, compression_settings)

        width, height = img.size
        max_dim = max(width, height)

        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            mode = 'RGBA'
            bg_color = DEFAULT_BG_COLOR_RGBA
            if img.mode != 'RGBA': img = img.convert('RGBA')
        else:
            if img.mode != 'RGB': img = img.convert('RGB')
            mode = 'RGB'
            bg_color = DEFAULT_BG_COLOR_RGB

        new_img = Image.new(mode, (max_dim, max_dim), bg_color)
        paste_x = (max_dim - width) // 2
        paste_y = (max_dim - height) // 2
        new_img.paste(img, (paste_x, paste_y), img if mode == 'RGBA' else None)

        base_name = os.path.basename(image_path)
        name, ext = os.path.splitext(base_name)
        output_ext = '.png' if mode == 'RGBA' else ext.lower()
        if output_ext not in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
             output_ext = '.png'

        output_filename = f"{name}_square{output_ext}"
        output_path = os.path.join(output_folder, output_filename)

        save_options = {}
        is_jpeg_output = output_ext in ['.jpg', '.jpeg']

        if compression_settings.get("enabled", False):
            # Strip metadata: Pillow usually does this unless told otherwise??? Explicit is complex.
            if compression_settings.get("strip_metadata", {}).get("enabled"):
                 print("Stripping metadata (Pillow default behavior)")

            if compression_settings.get("optimize", {}).get("enabled"):
                save_options['optimize'] = True
                print("Applying save optimization")

            if is_jpeg_output and compression_settings.get("jpeg_quality", {}).get("enabled"):
                quality = compression_settings.get("jpeg_quality", {}).get("value", 85)
                save_options['quality'] = quality
                print(f"Applying JPEG quality: {quality}")
            elif not is_jpeg_output and compression_settings.get("jpeg_quality", {}).get("enabled"):
                 print("Skipping JPEG quality: Output is not JPEG.")

        new_img.save(output_path, **save_options)
        img.close()
        new_img.close()
        return output_path

    except UnidentifiedImageError: print(f"Error: Cannot identify image file: {image_path}"); return None
    except FileNotFoundError: print(f"Error: Input file not found: {image_path}"); return None
    except PermissionError: print(f"Error: Permission denied for file: {image_path} or folder: {output_folder}"); return None
    except ValueError as ve: print(f"Error processing {image_path} (ValueError): {ve}"); return None
    except Exception as e: print(f"Error processing {image_path}: {e}"); return None


# --- GUI Application Class ---

class ImageSquarifierApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Texture Fixer for Tower Unite")
        # Height for shit
        self.geometry("600x780")
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        self.input_files = []
        self.output_folder = ""
        self.processing_thread = None
        self.stop_processing_flag = False
        self.update_queue = queue.Queue()
        self.compression_settings = DEFAULT_COMPRESSION_SETTINGS.copy()
        self.compression_widgets = {}
        self.music_playing = False
        self.music_loaded = False
        self.exit_splash = None # To hold reference to the exit window

        # --- Initialize Pygame Mixer ---
        self.initialize_audio()

        # --- Configure grid layout ---
        self.grid_columnconfigure(0, weight=1)
        # Added row 0 for music control, shifted others down
        self.grid_rowconfigure(0, weight=0) # Music Row
        self.grid_rowconfigure(1, weight=0) # Input Row
        self.grid_rowconfigure(2, weight=0) # Output Row
        self.grid_rowconfigure(3, weight=0) # Compression Toggle Row
        self.grid_rowconfigure(4, weight=0) # Convert Button Row
        self.grid_rowconfigure(5, weight=1) # Compression Frame Row (expands vertically if needed)
        self.grid_rowconfigure(6, weight=1) # Status Frame Row (expands vertically)


        # MUSIC CONTROL
        self.music_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.music_frame.grid(row=0, column=0, padx=20, pady=(10, 0), sticky="ew")
        self.music_frame.grid_columnconfigure(0, weight=1) # Allow label to expand

        self.mute_button = ctk.CTkButton(
            self.music_frame,
            text="Mute Music",
            command=self.toggle_mute,
            width=120
        )
        # right button???
        self.mute_button.grid(row=0, column=1, padx=10, pady=5, sticky="e")

        self.music_status_label = ctk.CTkLabel(self.music_frame, text="", text_color="gray", anchor="w")
        self.music_status_label.grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        self.update_music_status_ui() # Set initial text/state

        # input select
        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.grid(row=1, column=0, padx=20, pady=(10, 10), sticky="ew") # Adjusted row
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.select_files_button = ctk.CTkButton(self.input_frame, text="Select Image Files", command=self.select_files)
        self.select_files_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.input_label = ctk.CTkLabel(self.input_frame, text="No files selected.", text_color="gray", anchor="w")
        self.input_label.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")

        # input select 2
        self.output_frame = ctk.CTkFrame(self)
        self.output_frame.grid(row=2, column=0, padx=20, pady=10, sticky="ew") # Adjusted row
        self.output_frame.grid_columnconfigure(0, weight=1)
        self.select_output_button = ctk.CTkButton(self.output_frame, text="Select Output Folder", command=self.select_output_folder)
        self.select_output_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.output_label = ctk.CTkLabel(self.output_frame, text="No output folder selected.", text_color="gray", anchor="w")
        self.output_label.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="ew")

        # input select 3
        self.compression_toggle_checkbox = ctk.CTkCheckBox(
            self,
            text="Make My Textures Take Up Less Space! (Optional Compression)",
            command=self.toggle_compression_frame,
            variable=ctk.BooleanVar(value=self.compression_settings["enabled"]),
            onvalue=True, offvalue=False
        )
        self.compression_toggle_checkbox.grid(row=3, column=0, padx=20, pady=(10, 5), sticky="w") # Adjusted row

        # ACTION
        self.convert_button = ctk.CTkButton(self, text="Convert to Square", command=self.start_conversion, state="disabled")
        self.convert_button.grid(row=4, column=0, padx=20, pady=10, sticky="ew") # Adjusted row

        # compression thingy
        self.compression_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.compression_frame.grid_columnconfigure(0, weight=1)
        self.create_compression_widgets(self.compression_frame)
        

        # status area
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.grid(row=6, column=0, padx=20, pady=(10, 20), sticky="nsew") # Adjusted row
        self.status_frame.grid_columnconfigure(0, weight=1)
        self.status_frame.grid_rowconfigure(0, weight=1)

        self.status_textbox = ctk.CTkTextbox(self.status_frame, height=100, state="disabled", wrap="word")
        self.status_textbox.grid(row=0, column=0, padx=10, pady=(10, 5), sticky="nsew")
        self._add_status("Ready. Select images and an output folder.")

        self.progress_bar = ctk.CTkProgressBar(self.status_frame, orientation="horizontal")
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, padx=10, pady=(5, 10), sticky="ew")

        # --- Initialize Compression Frame Visibility ---
        self.toggle_compression_frame() # Set initial state based on checkbox

        # --- Start Queue Checking ---
        self.after(100, self.process_queue)

        # --- Override Close Button Behavior ---
        self.protocol("WM_DELETE_WINDOW", self.on_closing)


    # --- Audio Methods ---
    def initialize_audio(self):
        """Initializes pygame mixer and loads music."""
        if not pygame_available:
            self.music_loaded = False
            return

        try:
            pygame.mixer.init()
            if os.path.exists(MUSIC_FILE_PATH):
                pygame.mixer.music.load(MUSIC_FILE_PATH)
                pygame.mixer.music.set_volume(MUSIC_VOLUME)
                pygame.mixer.music.play(loops=-1) # Play indefinitely
                self.music_playing = True
                self.music_loaded = True
                print(f"Music loaded and playing: {MUSIC_FILENAME}")
            else:
                print(f"Error: Music file not found at: {MUSIC_FILE_PATH}")
                self.music_loaded = False
        except Exception as e:
            print(f"Error initializing audio or playing music: {e}")
            self.music_loaded = False
            self.music_playing = False
            if pygame.mixer.get_init(): # Quit mixer if init succeeded but load/play failed
                pygame.mixer.quit()

    def toggle_mute(self):
        """Toggles music mute state."""
        if not self.music_loaded or not pygame.mixer.get_init():
            return # Do nothing if music isn't loaded/working

        if self.music_playing:
            pygame.mixer.music.pause()
            self.music_playing = False
        else:
            pygame.mixer.music.unpause()
            self.music_playing = True

        self.update_music_status_ui()

    def update_music_status_ui(self):
        """Updates the mute button text and status label."""
        if not self.music_loaded:
            self.mute_button.configure(text="No Music", state="disabled")
            self.music_status_label.configure(text="Audio disabled or file not found.")
        elif self.music_playing:
            self.mute_button.configure(text="Mute Music", state="normal")
            self.music_status_label.configure(text=f"Made by Bear/Tovia")
        else:
            self.mute_button.configure(text="Unmute", state="normal")
            self.music_status_label.configure(text="Music Muted")

    # --- Compression Widget Creation --- all this shit was done with ai cause uhhhhh fuck if i know how to do it
    # (create_compression_widgets remains unchanged from previous version)
    def create_compression_widgets(self, parent_frame):
        """Creates the widgets for individual compression options."""
        self.compression_widgets = {} # Reset dict
        current_row = 0

        # --- Option 1: Strip Metadata ---
        key = "strip_metadata"
        frame = ctk.CTkFrame(parent_frame)
        frame.grid(row=current_row, column=0, padx=5, pady=5, sticky="ew")
        frame.grid_columnconfigure(1, weight=1) # Allow label to take space

        var = ctk.BooleanVar(value=self.compression_settings[key]["enabled"])
        cb = ctk.CTkCheckBox(frame, text="", variable=var, command=lambda k=key, v=var: self.update_compression_setting(k, "enabled", v.get()), width=20)
        cb.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        label = ctk.CTkLabel(frame, text="Strip Metadata (Removes EXIF, etc.)", text_color=COLOR_GREEN, anchor="w")
        label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.compression_widgets[key] = {'frame': frame, 'var': var, 'checkbox': cb, 'label': label}
        current_row += 1

        # --- Option 2: Optimize (Pillow Built-in) ---
        key = "optimize"
        frame = ctk.CTkFrame(parent_frame)
        frame.grid(row=current_row, column=0, padx=5, pady=5, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)

        var = ctk.BooleanVar(value=self.compression_settings[key]["enabled"])
        cb = ctk.CTkCheckBox(frame, text="", variable=var, command=lambda k=key, v=var: self.update_compression_setting(k, "enabled", v.get()), width=20)
        cb.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        label = ctk.CTkLabel(frame, text="Optimize (Lossless/Minor Lossy)", text_color=COLOR_GREEN, anchor="w")
        label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.compression_widgets[key] = {'frame': frame, 'var': var, 'checkbox': cb, 'label': label}
        current_row += 1

        # --- Option 3: JPEG Quality ---
        key = "jpeg_quality"
        main_frame = ctk.CTkFrame(parent_frame) # Main frame for this option
        main_frame.grid(row=current_row, column=0, padx=5, pady=5, sticky="ew")
        main_frame.grid_columnconfigure(1, weight=1)

        # Top part (checkbox, label, settings toggle)
        top_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1) # Label expands

        var = ctk.BooleanVar(value=self.compression_settings[key]["enabled"])
        cb = ctk.CTkCheckBox(top_frame, text="", variable=var, command=lambda k=key, v=var: self.toggle_compression_option_params(k, v.get()), width=20)
        cb.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        label = ctk.CTkLabel(top_frame, text="JPEG Quality (Requires JPEG Output)", text_color=COLOR_YELLOW, anchor="w")
        label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        settings_button = ctk.CTkButton(top_frame, text="▼ Settings", width=80, command=lambda k=key: self.toggle_settings_visibility(k))
        settings_button.grid(row=0, column=2, padx=10, pady=5)

        # Parameter Frame (initially maybe hidden)
        param_frame = ctk.CTkFrame(main_frame) # Separate frame for params
        param_frame.grid_columnconfigure(1, weight=1)

        quality_label = ctk.CTkLabel(param_frame, text="Quality (1-100):", anchor="w")
        quality_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        quality_value = ctk.IntVar(value=self.compression_settings[key]["value"])
        quality_slider = ctk.CTkSlider(param_frame, from_=1, to=100, number_of_steps=99, variable=quality_value, command=lambda val, k=key, p="value": self.update_compression_setting(k, p, int(val)))
        quality_slider.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        quality_display = ctk.CTkLabel(param_frame, textvariable=quality_value, width=35) # Display current value
        quality_display.grid(row=0, column=2, padx=10, pady=5)

        self.compression_widgets[key] = {
            'frame': main_frame, 'var': var, 'checkbox': cb, 'label': label,
            'settings_button': settings_button, 'param_frame': param_frame,
            'param_visible': False, # State track for param visibility
            'quality_slider': quality_slider, 'quality_value': quality_value,
            'quality_display': quality_display
        }
        self.toggle_compression_option_params(key, var.get()) # Enable/disable controls
        self.toggle_settings_visibility(key, show=False) # Hide params initially
        current_row += 1

        # --- Option 4: Quantize/Posterize (Color Reduction) ---
        key = "quantize"
        main_frame = ctk.CTkFrame(parent_frame)
        main_frame.grid(row=current_row, column=0, padx=5, pady=5, sticky="ew")
        main_frame.grid_columnconfigure(1, weight=1)

        top_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        top_frame.grid(row=0, column=0, sticky="ew")
        top_frame.grid_columnconfigure(1, weight=1)

        var = ctk.BooleanVar(value=self.compression_settings[key]["enabled"])
        cb = ctk.CTkCheckBox(top_frame, text="", variable=var, command=lambda k=key, v=var: self.toggle_compression_option_params(k, v.get()), width=20)
        cb.grid(row=0, column=0, padx=(10, 5), pady=5, sticky="w")
        label = ctk.CTkLabel(top_frame, text="Reduce Colors (Posterize)", text_color=COLOR_ORANGE, anchor="w")
        label.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        settings_button = ctk.CTkButton(top_frame, text="▼ Settings", width=80, command=lambda k=key: self.toggle_settings_visibility(k))
        settings_button.grid(row=0, column=2, padx=10, pady=5)

        param_frame = ctk.CTkFrame(main_frame)
        param_frame.grid_columnconfigure(1, weight=1)

        colors_label = ctk.CTkLabel(param_frame, text="Max Colors (~):", anchor="w")
        colors_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        colors_value = ctk.IntVar(value=self.compression_settings[key]["colors"])
        colors_slider = ctk.CTkSlider(param_frame, from_=2, to=256, number_of_steps=254, variable=colors_value, command=lambda val, k=key, p="colors": self.update_compression_setting(k, p, int(val)))
        colors_slider.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        colors_display = ctk.CTkLabel(param_frame, textvariable=colors_value, width=35)
        colors_display.grid(row=0, column=2, padx=10, pady=5)

        self.compression_widgets[key] = {
            'frame': main_frame, 'var': var, 'checkbox': cb, 'label': label,
            'settings_button': settings_button, 'param_frame': param_frame,
            'param_visible': False,
            'colors_slider': colors_slider, 'colors_value': colors_value,
            'colors_display': colors_display
        }
        self.toggle_compression_option_params(key, var.get())
        self.toggle_settings_visibility(key, show=False)
        current_row += 1


    # --- GUI Methods ---
    # (toggle_compression_frame, update_compression_setting,
    # toggle_compression_option_params, toggle_settings_visibility,
    # select_files, select_output_folder, check_conversion_ready,
    # start_conversion, _add_status, _update_progress, _clear_status,
    # process_queue remain unchanged from previous version)

    def toggle_compression_frame(self):
        """Shows or hides the compression options frame based on the main checkbox."""
        is_enabled = self.compression_toggle_checkbox.get()
        self.compression_settings["enabled"] = is_enabled
        if is_enabled:
            # Place it in grid (Adjusted row index)
            self.compression_frame.grid(row=5, column=0, padx=20, pady=5, sticky="nsew")
        else:
            self.compression_frame.grid_remove()

    def update_compression_setting(self, key, param, value):
        """Updates a specific compression setting value."""
        if key in self.compression_settings:
            if param in self.compression_settings[key]:
                self.compression_settings[key][param] = value
            else:
                self.compression_settings[key]["enabled"] = value

    def toggle_compression_option_params(self, key, is_enabled):
         """Enables/disables parameter controls when an option is checked/unchecked."""
         self.update_compression_setting(key, "enabled", is_enabled)
         widgets = self.compression_widgets.get(key, {})
         param_state = "normal" if is_enabled else "disabled"

         if 'settings_button' in widgets:
             widgets['settings_button'].configure(state=param_state)
             if not is_enabled and widgets.get('param_visible'):
                 self.toggle_settings_visibility(key, show=False)

         if 'quality_slider' in widgets: widgets['quality_slider'].configure(state=param_state)
         if 'colors_slider' in widgets: widgets['colors_slider'].configure(state=param_state)

    def toggle_settings_visibility(self, key, show=None):
        """Toggles the visibility of the parameter sub-frame for a compression option."""
        widgets = self.compression_widgets.get(key)
        if not widgets or 'param_frame' not in widgets: return

        param_frame = widgets['param_frame']
        is_currently_visible = widgets.get('param_visible', False)
        should_show = not is_currently_visible if show is None else show

        if should_show:
            param_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))
            widgets['settings_button'].configure(text="▲ Settings")
            widgets['param_visible'] = True
        else:
            param_frame.grid_remove()
            widgets['settings_button'].configure(text="▼ Settings")
            widgets['param_visible'] = False

    def select_files(self):
        filetypes = [("Image Files", "*.png *.jpg *.jpeg *.gif *.bmp *.tiff *.webp"), ("All Files", "*.*")]
        files = tkinter.filedialog.askopenfilenames(title="Select Image Files", filetypes=filetypes)
        if files:
            self.input_files = list(files)
            num_files = len(self.input_files)
            self.input_label.configure(text=f"{num_files} file{'s' if num_files != 1 else ''} selected.", text_color="white")
            self._add_status(f"Selected {num_files} image file{'s' if num_files != 1 else ''}.")
        else:
            self.input_files = []
            self.input_label.configure(text="No files selected.", text_color="gray")
            self._add_status("File selection cancelled.")
        self.check_conversion_ready()

    def select_output_folder(self):
        folder = tkinter.filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_folder = folder
            self.output_label.configure(text=folder, text_color="white")
            self._add_status(f"Output folder set to: {folder}")
        else:
            self._add_status("Output folder selection cancelled.")
        self.check_conversion_ready()

    def check_conversion_ready(self):
        if self.input_files and self.output_folder:
            self.convert_button.configure(state="normal")
        else:
            self.convert_button.configure(state="disabled")

    def start_conversion(self):
        if not self.input_files or not self.output_folder:
            self._add_status("Error: Please select input files and an output folder first.", error=True); return
        if self.processing_thread and self.processing_thread.is_alive():
             self._add_status("Warning: Processing is already running.", error=True); return

        self._set_controls_enabled(False)
        self.progress_bar.set(0)
        self._clear_status()
        self._add_status("Starting conversion...")
        if self.compression_settings["enabled"]:
             self._add_status("Compression options are ENABLED.")
             for key, settings in self.compression_settings.items():
                 if key != "enabled" and isinstance(settings, dict) and settings.get("enabled"):
                      params = ", ".join(f"{p}={v}" for p, v in settings.items() if p != "enabled")
                      self._add_status(f"  - Applying: {key.replace('_',' ').title()}" + (f" ({params})" if params else ""))
        else: self._add_status("Compression options are disabled.")

        self.stop_processing_flag = False
        current_compression_settings = self.compression_settings.copy()

        self.processing_thread = threading.Thread(
            target=self._conversion_worker,
            args=(list(self.input_files), self.output_folder, self.update_queue, current_compression_settings),
            daemon=True
        )
        self.processing_thread.start()

    def _set_controls_enabled(self, enabled: bool):
        """Enable or disable main control widgets."""
        state = "normal" if enabled else "disabled"
        self.select_files_button.configure(state=state)
        self.select_output_button.configure(state=state)
        self.compression_toggle_checkbox.configure(state=state)

        # Mute button state depends on music loaded status as well
        if self.music_loaded:
            self.mute_button.configure(state=state)
        else:
            self.mute_button.configure(state="disabled") # Always disabled if no music

        # Compression options
        for key, widgets in self.compression_widgets.items():
             master_widget_state = "disabled"
             if enabled:
                 option_enabled = self.compression_settings.get(key, {}).get("enabled", False)
                 master_widget_state = "normal"
                 param_widget_state = "normal" if option_enabled else "disabled"
             else: param_widget_state = "disabled"

             if 'checkbox' in widgets: widgets['checkbox'].configure(state=master_widget_state)
             if 'settings_button' in widgets: widgets['settings_button'].configure(state=param_widget_state)
             if 'quality_slider' in widgets: widgets['quality_slider'].configure(state=param_widget_state)
             if 'colors_slider' in widgets: widgets['colors_slider'].configure(state=param_widget_state)

        # Convert button
        self.convert_button.configure(state="disabled")
        if enabled: self.check_conversion_ready()

    def _add_status(self, message: str, error: bool = False):
        self.status_textbox.configure(state="normal")
        prefix = "ERROR: " if error else ""
        self.status_textbox.insert("end", f"{prefix}{message}\n")
        self.status_textbox.configure(state="disabled")
        self.status_textbox.see("end")

    def _update_progress(self, value: float):
        self.progress_bar.set(value)

    def _clear_status(self):
        self.status_textbox.configure(state="normal")
        self.status_textbox.delete("1.0", "end")
        self.status_textbox.configure(state="disabled")

    def process_queue(self):
        try:
            while True:
                message = self.update_queue.get_nowait()
                msg_type = message.get("type")
                data = message.get("data")
                if msg_type == "status": self._add_status(data["message"], error=data.get("error", False))
                elif msg_type == "progress": self._update_progress(data)
                elif msg_type == "done": self._add_status("Conversion finished."); self._set_controls_enabled(True)
                elif msg_type == "enable_controls": self._set_controls_enabled(True)
        except queue.Empty: pass
        finally: self.after(100, self.process_queue)

    # EXIT
    def on_closing(self):
        """Handles the event when the user clicks the close button."""
        if self.exit_splash: # Prevent opening multiple splashes
            return

        # Stop music if playing
        if self.music_loaded and pygame.mixer.get_init():
            pygame.mixer.music.stop()

        # Hide the main window immediately
        self.withdraw()

        # Create the splash screen
        self.exit_splash = ctk.CTkToplevel(self)
        self.exit_splash.overrideredirect(True) # Remove window decorations
        self.exit_splash.attributes("-topmost", True) # Keep it on top

        splash_width = 350
        splash_height = 120

        # Calculate center position add center to monitor so it looks nice
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x_pos = (screen_width // 2) - (splash_width // 2)
        y_pos = (screen_height // 2) - (splash_height // 2)

        self.exit_splash.geometry(f"{splash_width}x{splash_height}+{x_pos}+{y_pos}")

        # Add content to splash screen
        # For "glow": Using white text on the default dark background of CTkToplevel
        # A true glow is complex; this provides high contrast.
        font_large = ctk.CTkFont(size=18, weight="bold")
        font_small = ctk.CTkFont(size=10)

        label_main = ctk.CTkLabel(
            self.exit_splash,
            text="Created with love, by Bear + Tovia",
            font=font_large,
            text_color="#FFFFFF" # Bright white text
        )
        label_main.pack(pady=(25, 5), padx=20) # Add padding

        label_sub = ctk.CTkLabel(
            self.exit_splash,
            text="now get creating, friend, dont procrastinate.",
            font=font_small,
            text_color="#CCCCCC" # Slightly dimmer white/gray
        )
        label_sub.pack(pady=(0, 20), padx=20)

        # Schedule the closing of the splash and the app
        self.exit_splash.after(2500, self.quit_app) # 2.5 seconds

    def quit_app(self):
        """Destroys the splash screen and the main application."""
        if self.exit_splash:
            self.exit_splash.destroy()
        if pygame_available and pygame.mixer.get_init():
            pygame.mixer.quit() # Clean up pygame mixer
        self.destroy() # Destroy the main CTk window and exit mainloop


    # workerthread function
    @staticmethod
    def _conversion_worker(input_files, output_folder, update_queue, compression_settings):
        total_files = len(input_files)
        success_count = 0; error_count = 0
        for i, file_path in enumerate(input_files):
            filename = os.path.basename(file_path)
            update_queue.put({"type": "status", "data": {"message": f"Processing ({i+1}/{total_files}): {filename}"}})
            output_path = make_image_square(file_path, output_folder, compression_settings)
            if output_path: success_count += 1
            else:
                error_count += 1
                # Error message printed in make_image_square, signal failure here
                update_queue.put({"type": "status", "data": {"message": f"Failed conversion: {filename}", "error": True}})
            progress = (i + 1) / total_files
            update_queue.put({"type": "progress", "data": progress})
        final_message = f"Completed. {success_count} succeeded, {error_count} failed."
        update_queue.put({"type": "status", "data": {"message": final_message, "error": error_count > 0}})
        update_queue.put({"type": "done"})


# --- Main Execution ---
if __name__ == "__main__":
    app = ImageSquarifierApp()
    try:
        app.mainloop()
    finally:
        if pygame_available and pygame.mixer.get_init():
            pygame.mixer.quit()