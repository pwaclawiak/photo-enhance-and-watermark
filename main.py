import os
import sys
import time
import threading
import json
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageEnhance, ImageOps, ImageStat, ImageFilter

class Tooltip:
    """A simple tooltip class for Tkinter widgets"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tipwindow = None
        widget.bind("<Enter>", self.enter)
        widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        x, y, cx, cy = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 20
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        # Use tk.Label but with explicit colors to override macOS dark mode, and use padx/pady instead of padding
        label = tk.Label(tw, text=self.text, justify=tk.LEFT,
                      bg="#f9f9f9", fg="#000000", relief=tk.SOLID, borderwidth=1,
                      font=("tahoma", "9", "normal"), padx=6, pady=4)
        label.pack(ipadx=1)

    def leave(self, event=None):
        if self.tipwindow:
            self.tipwindow.destroy()
            self.tipwindow = None


class WatermarkApp:
    def __init__(self, root, debug_mode=False):
        self.root = root
        self.debug_mode = debug_mode
        self.root.title(f"Batch Watermark Pro{' [DEBUG MODE]' if self.debug_mode else ''}")
        self.root.geometry("1000x750")
        self.root.minsize(800, 550)

        # State variables
        self.input_paths = []
        self.watermark_path = ""
        self.output_dir = ""
        self.preview_image_orig = None
        self.watermark_image_orig = None
        self.tk_preview_image = None
        self.cached_base_thumb = None
        
        # Caching and Lazy Loading
        self.cached_previews = {}  # index -> PIL Image
        self.preview_cache_lock = threading.Lock()
        self.last_preview_size = (0, 0)
        self._preview_timer = None
        self._resize_timer = None
        
        # Gallery variables
        self.thumbnails = []
        self.thumb_rects = []
        self.enhance_states = []   # tk.BooleanVar for each image
        self.current_preview_index = 0
        self._drag_start_x = 0
        
        # Incremental Loading tracking
        self._load_job_id = None
        self._load_index = 0
        self._x_offset = 10
        self.thumbnails_loaded = False
        
        # Processing Thread State
        self.is_processing = False
        self.cancel_processing = False
        
        self.valid_extensions = ('.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff')
        
        self.load_config()

        self.setup_ui()
        
        # Global Keyboard Bindings
        self.root.bind("<Left>", self._on_key_left)
        self.root.bind("<Right>", self._on_key_right)
        self.root.bind("<space>", self._on_key_space)
        
        # Start background caching thread
        self.cache_thread = threading.Thread(target=self._preview_caching_worker, daemon=True)
        self.cache_thread.start()

    def load_config(self):
        self.config_file = "watermark_config.json"
        
        # Default config data
        self.config_data = {
            "watermark_path": "",
            "output_dir": "",
            "scale": 15.0,
            "opacity": 100.0,
            "margin": 30,
            "position": "Bottom-Left",
            "use_sharpen": True
        }
        
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    self.config_data.update(config)
                    self.watermark_path = self.config_data.get("watermark_path", "")
                    self.output_dir = self.config_data.get("output_dir", "")
                    if self.watermark_path and os.path.exists(self.watermark_path):
                        self.watermark_image_orig = Image.open(self.watermark_path).convert("RGBA")
            except Exception as e:
                print(f"Error loading config: {e}")

    def save_config(self):
        config = {
            "watermark_path": self.watermark_path,
            "output_dir": self.output_dir
        }
        
        if hasattr(self, 'scale_var'):
            config["scale"] = self.scale_var.get()
            config["opacity"] = self.opacity_var.get()
            config["margin"] = self.margin_var.get()
            config["position"] = self.position_var.get()
            config["use_sharpen"] = self.opt_sharpen.get()
            
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f)
        except Exception as e:
            print(f"Error saving config: {e}")

    def setup_ui(self):
        # Configure grid
        self.root.columnconfigure(0, weight=1, minsize=370) # Controls panel
        self.root.columnconfigure(1, weight=3) # Preview panel
        self.root.rowconfigure(0, weight=1)

        # --- Left Panel (Controls) ---
        control_frame = ttk.Frame(self.root, padding="15")
        control_frame.grid(row=0, column=0, sticky="nsew")

        # Step 1: Input Selection
        ttk.Label(control_frame, text="Step 1: Select Images", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        btn_frame1 = ttk.Frame(control_frame)
        btn_frame1.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame1, text="Select Folder", command=self.load_folder).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame1, text="Select Files", command=self.load_files).pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.lbl_input_status = ttk.Label(control_frame, text="No images selected", foreground="gray")
        self.lbl_input_status.pack(anchor="w", pady=(0, 15))

        # Step 2: Watermark Selection
        ttk.Label(control_frame, text="Step 2: Select Watermark", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        ttk.Button(control_frame, text="Browse Logo / Watermark", command=self.load_watermark).pack(fill="x")
        wm_text = os.path.basename(self.watermark_path) if self.watermark_path else "No watermark selected"
        wm_color = "green" if self.watermark_path else "gray"
        self.lbl_wm_status = ttk.Label(control_frame, text=wm_text, foreground=wm_color, wraplength=300)
        self.lbl_wm_status.pack(anchor="w", pady=(0, 15))

        # Step 3: Output Folder
        ttk.Label(control_frame, text="Step 3: Select Output Folder", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        ttk.Button(control_frame, text="Browse Output Folder", command=self.load_output_dir).pack(fill="x")
        out_text = self.output_dir if self.output_dir else "No output folder selected"
        out_color = "green" if self.output_dir else "gray"
        self.lbl_out_status = ttk.Label(control_frame, text=out_text, foreground=out_color, wraplength=300)
        self.lbl_out_status.pack(anchor="w", pady=(0, 15))

        # Step 4: Adjustments
        ttk.Label(control_frame, text="Step 4: Enhancements & Settings", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 10))
        
        # Heavy Enhancement Toggles
        enh_frame1 = ttk.Frame(control_frame)
        enh_frame1.pack(fill="x", pady=(0, 15))
        self.opt_sharpen = tk.BooleanVar(value=self.config_data.get("use_sharpen", True))
        ttk.Checkbutton(enh_frame1, text="Advanced Crisp Sharpening", variable=self.opt_sharpen, command=lambda: [self.save_config(), self.schedule_preview_update()]).pack(side="left")
        lbl_info1 = ttk.Label(enh_frame1, text=" ⓘ ", foreground="#0066cc", cursor="hand2", font=("Arial", 10, "bold"))
        lbl_info1.pack(side="left")
        Tooltip(lbl_info1, "Applies an Unsharp Mask filter to make details pop.\nDisable this if your photos are already perfectly sharp\nor if it exaggerates camera grain.")
        
        # Scale
        scale_header = ttk.Frame(control_frame)
        scale_header.pack(fill="x")
        ttk.Label(scale_header, text="Watermark Size (%):").pack(side="left")
        
        self.scale_var = tk.DoubleVar(value=self.config_data.get("scale", 15.0))
        self.lbl_scale_val = ttk.Label(scale_header, text=f"{self.scale_var.get():.0f}% (Default: 15)", foreground="#0066cc")
        self.lbl_scale_val.pack(side="right")
        
        scale_slider = ttk.Scale(control_frame, from_=5.0, to=100.0, variable=self.scale_var, command=lambda v: self.on_slider_move(v, 'scale'))
        scale_slider.pack(fill="x", pady=(0, 10))

        # Opacity
        opacity_header = ttk.Frame(control_frame)
        opacity_header.pack(fill="x")
        ttk.Label(opacity_header, text="Watermark Opacity (%):").pack(side="left")
        
        self.opacity_var = tk.DoubleVar(value=self.config_data.get("opacity", 100.0))
        self.lbl_opacity_val = ttk.Label(opacity_header, text=f"{self.opacity_var.get():.0f}% (Default: 100)", foreground="#0066cc")
        self.lbl_opacity_val.pack(side="right")
        
        opacity_slider = ttk.Scale(control_frame, from_=10.0, to=100.0, variable=self.opacity_var, command=lambda v: self.on_slider_move(v, 'opacity'))
        opacity_slider.pack(fill="x", pady=(0, 10))

        # Margin
        margin_header = ttk.Frame(control_frame)
        margin_header.pack(fill="x")
        ttk.Label(margin_header, text="Margin (pixels):").pack(side="left")
        
        self.margin_var = tk.IntVar(value=self.config_data.get("margin", 30))
        self.lbl_margin_val = ttk.Label(margin_header, text=f"{self.margin_var.get()} px (Default: 30)", foreground="#0066cc")
        self.lbl_margin_val.pack(side="right")
        
        margin_slider = ttk.Scale(control_frame, from_=0, to=200, variable=self.margin_var, command=lambda v: self.on_slider_move(v, 'margin'))
        margin_slider.pack(fill="x", pady=(0, 10))

        # Position
        ttk.Label(control_frame, text="Position:").pack(anchor="w")
        self.position_var = tk.StringVar(value=self.config_data.get("position", "Bottom-Left"))
        positions = ["Bottom-Left", "Bottom-Right", "Top-Left", "Top-Right", "Center"]
        pos_combo = ttk.Combobox(control_frame, textvariable=self.position_var, values=positions, state="readonly")
        pos_combo.pack(fill="x", pady=(0, 15))
        pos_combo.bind("<<ComboboxSelected>>", lambda e: [self.save_config(), self.schedule_preview_update()])

        # Step 5: Process
        ttk.Label(control_frame, text="Step 5: Run", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        self.btn_process = ttk.Button(control_frame, text="PROCESS IMAGES (4K Max)", command=self.process_images, style="Accent.TButton")
        self.btn_process.pack(fill="x", pady=(0, 10))
        
        # Hidden Progress Area (Starts hidden)
        self.progress_frame = ttk.Frame(control_frame)
        self.lbl_progress_text = ttk.Label(self.progress_frame, text="0/0 pictures done", font=("Arial", 9))
        self.lbl_progress_text.pack(anchor="e")
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(self.progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", ipady=2)
        self.progress_frame.pack_forget()

        # --- Right Panel (Preview) ---
        preview_frame = ttk.Frame(self.root, padding="15", relief="groove", borderwidth=1)
        preview_frame.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)

        ttk.Label(preview_frame, text="Live Preview", font=("Arial", 14, "bold")).grid(row=0, column=0, pady=(0, 10))
        
        # Anti-Stutter Container: Prevents the UI from collapsing/jumping when the image is swapping
        self.preview_img_container = tk.Frame(preview_frame, bg="#e0e0e0")
        self.preview_img_container.grid(row=1, column=0, sticky="nsew")
        self.preview_img_container.grid_propagate(False)
        self.preview_img_container.pack_propagate(False)

        self.lbl_preview = ttk.Label(self.preview_img_container, text="Load images to see preview...", background="#e0e0e0", justify="center")
        self.lbl_preview.place(relx=0.5, rely=0.5, anchor="center")

        # --- Thumbnail Gallery ---
        self.gallery_frame = ttk.Frame(preview_frame)
        self.gallery_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.gallery_frame.columnconfigure(1, weight=1)
        
        # Left Panel for Gallery Controls
        self.gal_ctrl_frame = ttk.Frame(self.gallery_frame)
        self.gal_ctrl_frame.grid(row=0, column=0, sticky="ns", padx=(0, 10))
        
        ttk.Frame(self.gal_ctrl_frame).pack(expand=True) # Top spacer
        
        ttk.Label(self.gal_ctrl_frame, text="Enhance", font=("Arial", 11, "bold")).pack(anchor="center", pady=(0, 2))
        
        btn_row = ttk.Frame(self.gal_ctrl_frame)
        btn_row.pack(anchor="center")
        ttk.Button(btn_row, text="All", width=4, command=self.check_all_enhance, takefocus=False).pack(side="left", padx=1)
        ttk.Button(btn_row, text="None", width=4, command=self.uncheck_all_enhance, takefocus=False).pack(side="left", padx=1)
        
        ttk.Frame(self.gal_ctrl_frame).pack(expand=True) # Bottom spacer

        # Right Panel for Gallery Canvas
        self.gal_canvas = tk.Canvas(self.gallery_frame, height=75, bg="#e0e0e0", highlightthickness=0)
        self.gal_canvas.grid(row=0, column=1, sticky="nsew", padx=5)
        
        self.gal_scrollbar = ttk.Scrollbar(self.gallery_frame, orient="horizontal", command=self.gal_canvas.xview)
        self.gal_scrollbar.grid(row=1, column=1, sticky="ew", pady=(2, 0))
        self.gal_canvas.configure(xscrollcommand=self.gal_scrollbar.set)
        
        self.gal_canvas.bind("<ButtonPress-1>", self.on_gal_press)
        self.gal_canvas.bind("<B1-Motion>", self.on_gal_drag)
        self.gal_canvas.bind("<MouseWheel>", self._on_mousewheel)  # Windows / Mac
        self.gal_canvas.bind("<Button-4>", self._on_mousewheel)    # Linux Scroll Up
        self.gal_canvas.bind("<Button-5>", self._on_mousewheel)    # Linux Scroll Down
        
        # Configure the STOP button style
        style = ttk.Style(self.root)
        style.configure("Stop.TButton", foreground="red", font=("Arial", 11, "bold"))

    def check_all_enhance(self):
        """Checks all enhance checkboxes."""
        for state in self.enhance_states:
            state.set(True)
        self.schedule_preview_update()

    def uncheck_all_enhance(self):
        """Unchecks all enhance checkboxes."""
        for state in self.enhance_states:
            state.set(False)
        self.schedule_preview_update()

    def load_folder(self):
        folder = filedialog.askdirectory(title="Select Folder containing Images")
        if folder:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(self.valid_extensions)]
            self._handle_input_files(files)

    def load_files(self):
        filetypes = (("Image files", "*.jpg *.jpeg *.png *.bmp *.webp *.tiff"), ("All files", "*.*"))
        files = filedialog.askopenfilenames(title="Select Images", filetypes=filetypes)
        if files:
            self._handle_input_files(files)

    def _handle_input_files(self, files):
        self.input_paths = [f for f in files if f.lower().endswith(self.valid_extensions)]
        
        # Cancel any ongoing load jobs
        if self._load_job_id:
            self.root.after_cancel(self._load_job_id)
            self._load_job_id = None
            
        if not self.input_paths:
            self.lbl_input_status.config(text="No valid images found.", foreground="red")
            self.gal_canvas.delete("all")
            self.lbl_preview.config(image="", text="Load images to see preview...")
            return

        self.lbl_input_status.config(text=f"Loading 0 / {len(self.input_paths)} images...", foreground="blue")
        self.lbl_preview.config(text="Starting load...", image="")
        self.root.update_idletasks()
        
        # Reset cache and state
        self.gal_canvas.delete("all")
        with self.preview_cache_lock:
            self.cached_previews.clear()
        self.thumbnails = []
        self.thumb_rects = []
        self.enhance_states = []
        
        self._load_index = 0
        self._x_offset = 10
        self.thumbnails_loaded = False
        self.btn_process.config(state="disabled") # Disable processing while loading
        
        # Start incremental load
        self._load_next_thumbnail()

    def _load_next_thumbnail(self):
        """Asynchronously loads images one by one to prevent GUI freezing."""
        if self._load_index >= len(self.input_paths):
            # All done loading
            self.lbl_input_status.config(text=f"Selected {len(self.input_paths)} images", foreground="green")
            self.btn_process.config(state="normal")
            self.thumbnails_loaded = True
            return

        i = self._load_index
        path = self.input_paths[i]
        
        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img)
            
            if i == 0:
                # Generate high-res preview first
                preview_w = self.preview_img_container.winfo_width()
                preview_h = self.preview_img_container.winfo_height()
                if preview_w < 10 or preview_h < 10:
                    preview_w, preview_h = 800, 600
                
                hr_img = img.copy().convert("RGBA")
                hr_img.thumbnail((preview_w, preview_h), getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS))
                with self.preview_cache_lock:
                    self.cached_previews[0] = hr_img
            
            # Generate small thumbnail
            thumb_img = img.copy()
            thumb_img.thumbnail((60, 60))
            tk_img = ImageTk.PhotoImage(thumb_img)
            self.thumbnails.append(tk_img)
            
            # Add to Canvas
            self.enhance_states.append(tk.BooleanVar(value=False))
            
            rect_id = self.gal_canvas.create_rectangle(
                self._x_offset - 4, 34 - thumb_img.height//2 - 4, 
                self._x_offset + thumb_img.width + 4, 34 + thumb_img.height//2 + 4, 
                outline="#e0e0e0", width=3
            )
            self.thumb_rects.append(rect_id)
            
            img_id = self.gal_canvas.create_image(self._x_offset, 34, anchor="w", image=tk_img)
            
            # Checkbox moved to top right corner of the thumbnail with 3px padding and stripped background
            chk = tk.Checkbutton(self.gal_canvas, variable=self.enhance_states[i], command=self.schedule_preview_update,
                                 bg="#e0e0e0", activebackground="#e0e0e0", bd=0, highlightthickness=0, padx=0, pady=0, takefocus=False)
            self.gal_canvas.create_window(self._x_offset + thumb_img.width - 3, 34 - thumb_img.height//2 + 3, window=chk, anchor="ne")
            
            for item_id in (img_id, rect_id):
                self.gal_canvas.tag_bind(item_id, "<ButtonPress-1>", self.on_gal_press)
                self.gal_canvas.tag_bind(item_id, "<B1-Motion>", self.on_gal_drag)
                self.gal_canvas.tag_bind(item_id, "<ButtonRelease-1>", lambda e, idx=i: self.on_thumb_click(e, idx))
            
            self._x_offset += thumb_img.width + 15
            self.gal_canvas.configure(scrollregion=(0, 0, self._x_offset, 75))
            
            if i == 0:
                self.select_preview_image(0)
                
        except Exception as e:
            print(f"Thumbnail error for {path}: {e}")
            self.thumb_rects.append(None)
            self.enhance_states.append(tk.BooleanVar(value=False))
            
        self._load_index += 1
        self.lbl_input_status.config(text=f"Loading {self._load_index} / {len(self.input_paths)} images...", foreground="blue")
        
        self._load_job_id = self.root.after(5, self._load_next_thumbnail)

    def load_watermark(self):
        filetypes = (("PNG files", "*.png"), ("All image files", "*.jpg *.jpeg *.png *.bmp"))
        path = filedialog.askopenfilename(title="Select Watermark Logo", filetypes=filetypes)
        if path:
            self.watermark_path = path
            try:
                self.watermark_image_orig = Image.open(self.watermark_path).convert("RGBA")
                self.lbl_wm_status.config(text=os.path.basename(path), foreground="green")
                self.save_config()
                self.schedule_preview_update()
            except Exception as e:
                messagebox.showerror("Error", f"Could not open watermark image:\n{e}")

    def load_output_dir(self):
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_dir = folder
            self.lbl_out_status.config(text=folder, foreground="green")
            self.save_config()

    def _preview_caching_worker(self):
        """Background thread that prepares high-res previews for fast switching."""
        while True:
            time.sleep(0.05)
            if not getattr(self, 'thumbnails_loaded', False) or not self.input_paths:
                continue
                
            try:
                preview_w = self.preview_img_container.winfo_width()
                preview_h = self.preview_img_container.winfo_height()
            except:
                continue
                
            if preview_w < 10 or preview_h < 10:
                continue
                
            target_idx = self.current_preview_index
            start = max(0, target_idx - 9)
            end = min(len(self.input_paths), target_idx + 10)
            wanted_indices = list(range(start, end))
            
            # Sort by distance to current index so nearest are generated first
            wanted_indices.sort(key=lambda x: abs(x - target_idx))
            
            to_cache = None
            with self.preview_cache_lock:
                for idx in wanted_indices:
                    if idx not in self.cached_previews:
                        to_cache = idx
                        break
                        
            if to_cache is not None:
                try:
                    img = Image.open(self.input_paths[to_cache])
                    img = ImageOps.exif_transpose(img).convert("RGBA")
                    img.thumbnail((preview_w, preview_h), getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS))
                    with self.preview_cache_lock:
                        self.cached_previews[to_cache] = img
                except Exception as e:
                    print(f"Error background caching {to_cache}: {e}")
                    with self.preview_cache_lock:
                        self.cached_previews[to_cache] = Image.new("RGBA", (preview_w, preview_h))
            else:
                # Cleanup phase
                with self.preview_cache_lock:
                    if len(self.cached_previews) > 20:
                        keys_to_delete = [k for k in self.cached_previews.keys() if k not in wanted_indices]
                        for k in keys_to_delete:
                            del self.cached_previews[k]
                time.sleep(0.1)

    def select_preview_image(self, index):
        if not self.input_paths or index >= len(self.input_paths):
            return
            
        self.current_preview_index = index
        self.root.focus_set() # Clear keyboard focus from buttons/thumbnails to prevent spacebar bugs
        
        # Update highlights
        for i, rect_id in enumerate(self.thumb_rects):
            if rect_id is not None:
                color = "#0078D7" if i == index else "#e0e0e0"
                self.gal_canvas.itemconfig(rect_id, outline=color)
        
        # Pull from cache if available, otherwise generate
        self.generate_base_thumbnail()

    def _on_mousewheel(self, event):
        """Scrolls the gallery canvas using mouse wheel or trackpad."""
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            self.gal_canvas.xview_scroll(-1, "units")
        elif event.num == 5 or getattr(event, 'delta', 0) < 0:
            self.gal_canvas.xview_scroll(1, "units")

    def _on_key_left(self, event):
        if self.input_paths and self.current_preview_index > 0:
            self.select_preview_image(self.current_preview_index - 1)
            
    def _on_key_right(self, event):
        if self.input_paths and self.current_preview_index < len(self.input_paths) - 1:
            self.select_preview_image(self.current_preview_index + 1)
            
    def _on_key_space(self, event):
        # Ignore spacebar if user is interacting with a dropdown/combobox
        if isinstance(event.widget, ttk.Combobox):
            return
            
        if self.input_paths and self.current_preview_index < len(self.enhance_states):
            current = self.enhance_states[self.current_preview_index].get()
            self.enhance_states[self.current_preview_index].set(not current)
            self.schedule_preview_update()
            
            # Force focus back to main root to prevent double toggling if a checkbox was clicked recently
            self.root.focus_set()
            return "break" # Prevent spacebar from triggering other focused UI elements

    def scroll_gallery(self, direction):
        self.gal_canvas.xview_scroll(direction, "units")

    def on_gal_press(self, event):
        self._drag_start_x = event.x
        self.gal_canvas.scan_mark(event.x, 0)
        
    def on_gal_drag(self, event):
        self.gal_canvas.scan_dragto(event.x, 0, gain=1)
        
    def on_thumb_click(self, event, index):
        # Only register as a click if the mouse didn't drag more than 5 pixels
        if abs(event.x - self._drag_start_x) < 5:
            self.select_preview_image(index)

    def auto_enhance_image(self, img, use_sharpen=True, debug_dir=None, base_filename=""):
        """
        Advanced, pure PIL-based enhancement pipeline.
        Replicates OpenCV results mathematically without the heavy dependencies.
        """
        
        # Work on RGB to avoid alpha channel issues during enhancement
        has_alpha = img.mode == 'RGBA'
        if has_alpha:
            alpha = img.split()[3]
            img = img.convert('RGB')
            
        def save_debug_step(current_img, step_name):
            """Helper to save intermediate pipeline steps when in debug mode."""
            if debug_dir and base_filename:
                name, ext = os.path.splitext(base_filename)
                out_path = os.path.join(debug_dir, f"{name}_{step_name}{ext}")
                
                # Re-apply alpha channel safely if the original image had transparency
                if has_alpha:
                    temp_img = current_img.copy()
                    temp_img.putalpha(alpha)
                else:
                    temp_img = current_img
                    
                if ext.lower() in ('.jpg', '.jpeg'):
                    temp_img = temp_img.convert("RGB")
                    temp_img.save(out_path, quality=95)
                else:
                    temp_img.save(out_path)
            
        # Analyze overall brightness (mean) and contrast (stddev)
        grayscale = img.convert("L")
        stat = ImageStat.Stat(grayscale)
        mean_lum = stat.mean[0]
        stddev = stat.stddev[0]
        print(mean_lum, stddev)
            
        # --- 1. Beta Addition/Subtraction (Global Brightness) ---
        target_lum = 100
        target_stddev = 50
        factor = target_lum / max(mean_lum, 1)
        
        if abs(factor - 1.0) >= 0.1 and stddev < 50:
            img = ImageEnhance.Brightness(img).enhance(factor)
        save_debug_step(img, "01_beta")

        # --- 2. Alpha Gain (Contrast) ---
        # Check if contrast is low using standard deviation
        # Increased threshold from 50 to 65 to catch more flat/foggy images
        if stddev < target_stddev:
            # Apply alpha gain to boost contrast
            alpha_gain = 1.1
            img = ImageEnhance.Contrast(img).enhance(alpha_gain)
        save_debug_step(img, "02_alpha")
            
        # --- 3. Slight Gamma Adjustment ---
        # Nonlinear brightening to retain highlight detail while boosting shadows
        # Gamma gets an additional 10% boost (from 0.95 -> 0.85) if beta was triggered
        gamma = 0.95
        img = img.point(lambda i: min(255, int(255 * ((i / 255.0) ** gamma))))
        save_debug_step(img, "03_gamma")
            
        # --- 4. HSV Colorspace Adjustments ---
        # Increase color values (Saturation) by 10% and Value (brightness) by 5%
        hsv = img.convert("HSV")
        h, s, v = hsv.split()
        
        # Boost Saturation (S) by 10%
        s = s.point(lambda i: min(255, int(i * 1.10)))
        # Boost Value (V) without shifting saturation by 10%
        v = v.point(lambda i: min(255, int(i * 1.10)))
        
        img = Image.merge("HSV", (h, s, v)).convert("RGB")
        save_debug_step(img, "04_hsv")
        
        # 5. Advanced Crisp Sharpening
        if use_sharpen:
            # CRITICAL FIX: A 2px radius on a small preview creates massive, distorted halos.
            # We dynamically scale the radius down proportionally to the image width.
            base_radius = 2.0
            dynamic_radius = max(0.4, base_radius * (img.width / 3840.0))
            img = img.filter(ImageFilter.UnsharpMask(radius=dynamic_radius, percent=150, threshold=2))

        if has_alpha:
            img.putalpha(alpha)
            
        return img

    def apply_watermark(self, base_image, watermark_img, scale_factor, opacity, margin, position):
        """Core logic applied to both the preview thumbnail and final high-res output"""
        base_w, base_h = base_image.size
        
        # Scale watermark
        wm_w_orig, wm_h_orig = watermark_img.size
        new_wm_w = max(1, int(base_w * scale_factor))
        new_wm_h = max(1, int(new_wm_w * (wm_h_orig / wm_w_orig)))
        
        wm_resized = watermark_img.resize((new_wm_w, new_wm_h), getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS))
        
        # Apply Opacity
        if opacity < 1.0:
            r, g, b, a = wm_resized.split()
            a = ImageEnhance.Brightness(a).enhance(opacity)
            wm_resized = Image.merge("RGBA", (r, g, b, a))
            
        # Calculate Position
        x, y = margin, margin
        if position == "Bottom-Left":
            y = base_h - new_wm_h - margin
        elif position == "Bottom-Right":
            x = base_w - new_wm_w - margin
            y = base_h - new_wm_h - margin
        elif position == "Top-Right":
            x = base_w - new_wm_w - margin
        elif position == "Center":
            x = (base_w - new_wm_w) // 2
            y = (base_h - new_wm_h) // 2

        # Create a copy so we don't modify the original reference
        result = base_image.copy()
        
        # Paste using the alpha channel as a mask
        result.paste(wm_resized, (x, y), wm_resized)
        return result

    def on_slider_move(self, val, slider_type):
        """Update the label text instantly, but debounce the heavy image processing."""
        if slider_type == 'scale':
            self.lbl_scale_val.config(text=f"{float(val):.0f}% (Default: 15)")
        elif slider_type == 'opacity':
            self.lbl_opacity_val.config(text=f"{float(val):.0f}% (Default: 100)")
        elif slider_type == 'margin':
            self.lbl_margin_val.config(text=f"{float(val):.0f} px (Default: 30)")
            
        self.save_config()
        self.schedule_preview_update()

    def schedule_preview_update(self):
        """Debounce the preview update to avoid lagging when sliding quickly."""
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(100, self.update_preview)

    def on_resize(self, event):
        """Handle window resizing, debouncing the thumbnail regeneration."""
        if event.widget == self.preview_img_container:
            if self._resize_timer:
                self.root.after_cancel(self._resize_timer)
            self._resize_timer = self.root.after(200, self.generate_base_thumbnail)

    def generate_base_thumbnail(self):
        """Pre-calculates the base thumbnail so we don't resize the massive original image on every slider tick."""
        if not self.input_paths:
            return

        preview_w = self.preview_img_container.winfo_width()
        preview_h = self.preview_img_container.winfo_height()
        
        if preview_w < 10 or preview_h < 10:
            preview_w, preview_h = 600, 400

        # Invalidate cache if window size changed significantly
        if self.last_preview_size != (preview_w, preview_h):
            with self.preview_cache_lock:
                self.cached_previews.clear()
            self.last_preview_size = (preview_w, preview_h)

        idx = self.current_preview_index
        
        with self.preview_cache_lock:
            cached_img = self.cached_previews.get(idx)
            
        if cached_img:
            # Pull from our new background lazy-loaded cache
            self.cached_base_thumb = cached_img
        else:
            # Generate it synchronously because user clicked it right now
            try:
                img = Image.open(self.input_paths[idx])
                img = ImageOps.exif_transpose(img).convert("RGBA")
                img.thumbnail((preview_w, preview_h), getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS))
                with self.preview_cache_lock:
                    self.cached_previews[idx] = img
                self.cached_base_thumb = img
            except Exception as e:
                print(f"Error caching {idx}: {e}")
                return
            
        self.update_preview()

    def update_preview(self):
        if not self.cached_base_thumb:
            return

        # Create a copy of the pre-calculated thumbnail
        base_thumb = self.cached_base_thumb.copy()
        
        # Apply Auto-Enhance if selected FOR THIS SPECIFIC IMAGE
        if self.enhance_states[self.current_preview_index].get():
            base_thumb = self.auto_enhance_image(
                base_thumb, 
                use_sharpen=self.opt_sharpen.get()
            )
        
        # Apply Watermark if a watermark image is loaded
        if self.watermark_image_orig:
            # Read UI values
            scale = self.scale_var.get() / 100.0
            opacity = self.opacity_var.get() / 100.0
            position = self.position_var.get()
            
            # Margin scaling for preview: 
            # The physical margin on a thumbnail needs to be proportionally smaller to look accurate
            try:
                orig_img = Image.open(self.input_paths[self.current_preview_index])
                orig_w = orig_img.size[0]
            except:
                orig_w = base_thumb.size[0] * 5 # Fallback
                
            thumb_w = base_thumb.size[0]
            preview_margin = int(self.margin_var.get() * (thumb_w / orig_w))

            # Apply watermark to the thumbnail
            base_thumb = self.apply_watermark(
                base_thumb, 
                self.watermark_image_orig, 
                scale, 
                opacity, 
                preview_margin, 
                position
            )

        # Convert to Tkinter image and display
        self.tk_preview_image = ImageTk.PhotoImage(base_thumb)
        self.lbl_preview.config(image=self.tk_preview_image, text="", background="")

    def process_images(self):
        if not self.input_paths:
            messagebox.showwarning("Missing Input", "Please select input images or a folder first.")
            return
            
        has_watermark = self.watermark_image_orig is not None
        any_enhanced = any(state.get() for state in self.enhance_states)
        
        if not has_watermark and not any_enhanced:
            messagebox.showwarning("Nothing to do", "Please select a watermark image or choose at least one image to enhance.")
            return
            
        if not has_watermark and any_enhanced:
            if not messagebox.askyesno("No Watermark", "You haven't selected a watermark.\n\nAre you sure you want to process the images applying ONLY the enhancements?"):
                return
                
        if not self.output_dir:
            messagebox.showwarning("Missing Output", "Please select an output folder.")
            return

        self.is_processing = True
        self.cancel_processing = False
        self.btn_process.config(text="STOP PROCESSING", command=self.stop_processing, style="Stop.TButton")
        
        # Reveal and reset the progress bar and text
        self.progress_frame.pack(fill="x", pady=(5, 0))
        self.progress_var.set(0)
        total = len(self.input_paths)
        self.lbl_progress_text.config(text=f"0/{total} pictures done")
        self.root.update()

        # Start worker thread
        threading.Thread(target=self._process_worker, daemon=True).start()

    def stop_processing(self):
        if messagebox.askyesno("Stop", "Are you sure you want to stop the image generation process?"):
            self.cancel_processing = True
            self.lbl_progress_text.config(text="Stopping...")

    def _process_worker(self):
        total = len(self.input_paths)
        success = 0

        scale = self.scale_var.get() / 100.0
        opacity = self.opacity_var.get() / 100.0
        margin = self.margin_var.get()
        position = self.position_var.get()
        use_sharpen = self.opt_sharpen.get()

        # Create timestamped subfolder
        # Formatting as YYYY-MM-DD HH-MM-SS to prevent OS file path errors with colons
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        current_run_out_dir = os.path.join(self.output_dir, timestamp)
        try:
            os.makedirs(current_run_out_dir, exist_ok=True)
        except Exception as e:
            print(f"Failed to create timestamp directory: {e}")
            self.root.after(0, self._process_complete, 0, total)
            return

        for i, filepath in enumerate(self.input_paths):
            if self.cancel_processing:
                break
                
            try:
                # Use exif_transpose to fix orientation issues
                img = Image.open(filepath)
                img = ImageOps.exif_transpose(img)
                base_img = img.convert("RGBA")
                
                filename = os.path.basename(filepath)
                
                # --- 4K Downscaling ---
                # Scale image down to a max bounding box of 3840x3840 (covering 4K portrait and landscape)
                base_img.thumbnail((3840, 3840), getattr(Image.Resampling, 'LANCZOS', Image.LANCZOS))
                
                # Apply Auto-Enhance if selected FOR THIS IMAGE
                if i < len(self.enhance_states) and self.enhance_states[i].get():
                    debug_dir = current_run_out_dir if self.debug_mode else None
                    base_img = self.auto_enhance_image(base_img, use_sharpen=use_sharpen, debug_dir=debug_dir, base_filename=filename)
                    
                if self.watermark_image_orig:
                    result = self.apply_watermark(base_img, self.watermark_image_orig, scale, opacity, margin, position)
                else:
                    result = base_img.copy()
                
                out_path = os.path.join(current_run_out_dir, filename)
                
                # Convert back to RGB if saving as JPEG, otherwise keep RGBA (e.g., for PNG)
                ext = os.path.splitext(filename)[1].lower()
                if ext in ('.jpg', '.jpeg'):
                    result = result.convert("RGB")
                    result.save(out_path, quality=95)
                else:
                    result.save(out_path)
                    
                success += 1
            except Exception as e:
                print(f"Failed to process {filepath}: {e}")

            # Safely update UI from thread
            self.root.after(0, self._update_progress_ui, i + 1, total)

        # Job is done (or cancelled)
        self.root.after(0, self._process_complete, success, total)

    def _update_progress_ui(self, current, total):
        if not self.cancel_processing:
            self.progress_var.set((current / total) * 100)
            self.lbl_progress_text.config(text=f"{current}/{total} pictures done")

    def _process_complete(self, success, total):
        self.is_processing = False
        self.btn_process.config(text="PROCESS IMAGES (4K Max)", command=self.process_images, style="Accent.TButton")
        self.progress_frame.pack_forget() # Hide the bar again when finished
        
        if self.cancel_processing:
            messagebox.showinfo("Stopped", f"Processing stopped. {success} images completed.")
        else:
            messagebox.showinfo("Complete", f"Successfully watermarked {success} out of {total} images!")


if __name__ == "__main__":
    debug_mode = "--debug" in sys.argv or "-d" in sys.argv
    
    root = tk.Tk()
    
    # Optional: Basic styling to make standard Tkinter look a bit more modern
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
        
    app = WatermarkApp(root, debug_mode=debug_mode)
    
    # Bind resize event to update preview thumbnail dynamically when window resizes
    root.bind("<Configure>", app.on_resize)
    
    root.mainloop()