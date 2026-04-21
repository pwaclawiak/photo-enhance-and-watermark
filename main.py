import os
import sys
import time
import threading
import json
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageEnhance, ImageOps, ImageStat, ImageFilter, ImageDraw

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
        self.per_image_manual_settings = []
        self.manual_enabled_states = []

        self.manual_setting_defs = [
            ("brightness", "Brightness"),
            ("contrast", "Contrast"),
            ("gamma", "Gamma"),
            ("color", "Color"),
            ("sharpness", "Sharpness"),
            ("lighting", "Lighting"),
            ("dark_threshold", "Dark Pixel Threshold"),
            ("bright_threshold", "Bright Pixel Threshold"),
            ("outer_vignette", "Outer Vignette"),
            ("inner_vignette", "Inner Vignette"),
        ]
        self.manual_setting_vars = {}
        self.manual_setting_value_labels = {}
        self.manual_setting_sliders = {}
        self.manual_setting_reset_buttons = {}
        self._loading_manual_settings = False
        
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
        self._pending_select_index = 0
        self._initial_enhance_defaults = []
        
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
        self.root.bind("<Down>", self._on_key_down)
        self.root.bind("<space>", self._on_key_space)
        self.root.bind("<Delete>", self._on_key_delete)
        self.root.bind("<m>", self._on_key_m)
        self.root.bind("<M>", self._on_key_m)
        
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
            "use_sharpen": True,
            "use_watermark": True
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
            config["use_watermark"] = self.use_watermark_var.get()
            
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

        # --- Left Panel (Scrollable Controls) ---
        left_panel = ttk.Frame(self.root)
        left_panel.grid(row=0, column=0, sticky="nsew")
        left_panel.rowconfigure(0, weight=1)
        left_panel.columnconfigure(0, weight=1)

        self.controls_canvas = tk.Canvas(left_panel, highlightthickness=0)
        self.controls_canvas.grid(row=0, column=0, sticky="nsew")
        controls_scrollbar = ttk.Scrollbar(left_panel, orient="vertical", command=self.controls_canvas.yview)
        controls_scrollbar.grid(row=0, column=1, sticky="ns")
        self.controls_canvas.configure(yscrollcommand=controls_scrollbar.set)

        control_frame = ttk.Frame(self.controls_canvas, padding="15")
        self._controls_window_id = self.controls_canvas.create_window((0, 0), window=control_frame, anchor="nw")
        control_frame.bind("<Configure>", self._on_controls_frame_configure)
        self.controls_canvas.bind("<Configure>", self._on_controls_canvas_configure)
        self.root.bind_all("<MouseWheel>", self._on_controls_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_controls_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_controls_mousewheel, add="+")

        step1_frame = self._create_collapsible_step(control_frame, "Step 1: Select Images")
        btn_frame1 = ttk.Frame(step1_frame)
        btn_frame1.pack(fill="x", pady=(0, 5))
        ttk.Button(btn_frame1, text="Select Folder", command=self.load_folder).pack(side="left", fill="x", expand=True, padx=(0, 2))
        ttk.Button(btn_frame1, text="Select Files", command=self.load_files).pack(side="left", fill="x", expand=True, padx=(2, 0))
        self.lbl_input_status = ttk.Label(step1_frame, text="No images selected", foreground="gray")
        self.lbl_input_status.pack(anchor="w")

        step2_frame = self._create_collapsible_step(control_frame, "Step 2: Select Output Folder")
        ttk.Button(step2_frame, text="Browse Output Folder", command=self.load_output_dir).pack(fill="x")
        out_text = self.output_dir if self.output_dir else "No output folder selected"
        out_color = "green" if self.output_dir else "gray"
        self.lbl_out_status = ttk.Label(step2_frame, text=out_text, foreground=out_color, wraplength=300)
        self.lbl_out_status.pack(anchor="w", pady=(4, 0))

        step3_frame = self._create_collapsible_step(control_frame, "Step 3: Select Watermark")
        ttk.Button(step3_frame, text="Browse Logo / Watermark", command=self.load_watermark).pack(fill="x")
        wm_text = os.path.basename(self.watermark_path) if self.watermark_path else "No watermark selected"
        wm_color = "green" if self.watermark_path else "gray"
        self.lbl_wm_status = ttk.Label(step3_frame, text=wm_text, foreground=wm_color, wraplength=300)
        self.lbl_wm_status.pack(anchor="w", pady=(4, 0))

        step4_frame = self._create_collapsible_step(control_frame, "Step 4: Watermark Settings")
        self.use_watermark_var = tk.BooleanVar(value=self.config_data.get("use_watermark", True))
        self.chk_use_watermark = ttk.Checkbutton(
            step4_frame,
            text="Apply watermark to images",
            variable=self.use_watermark_var,
            command=self._on_use_watermark_toggle
        )
        self.chk_use_watermark.pack(anchor="w", pady=(0, 8))

        self.watermark_settings_frame = ttk.Frame(step4_frame)
        self.watermark_settings_frame.pack(fill="x")

        # Scale
        scale_header = ttk.Frame(self.watermark_settings_frame)
        scale_header.pack(fill="x")
        self.lbl_scale_title = ttk.Label(scale_header, text="Watermark Size (%):")
        self.lbl_scale_title.pack(side="left")
        
        self.scale_var = tk.DoubleVar(value=self.config_data.get("scale", 15.0))
        self.lbl_scale_val = ttk.Label(scale_header, text=f"{self.scale_var.get():.0f}% (Default: 15)", foreground="#0066cc")
        self.lbl_scale_val.pack(side="right")
        
        self.scale_slider = ttk.Scale(self.watermark_settings_frame, from_=5.0, to=100.0, variable=self.scale_var, command=lambda v: self.on_slider_move(v, 'scale'))
        self.scale_slider.pack(fill="x", pady=(0, 10))

        # Opacity
        opacity_header = ttk.Frame(self.watermark_settings_frame)
        opacity_header.pack(fill="x")
        self.lbl_opacity_title = ttk.Label(opacity_header, text="Watermark Opacity (%):")
        self.lbl_opacity_title.pack(side="left")
        
        self.opacity_var = tk.DoubleVar(value=self.config_data.get("opacity", 100.0))
        self.lbl_opacity_val = ttk.Label(opacity_header, text=f"{self.opacity_var.get():.0f}% (Default: 100)", foreground="#0066cc")
        self.lbl_opacity_val.pack(side="right")
        
        self.opacity_slider = ttk.Scale(self.watermark_settings_frame, from_=10.0, to=100.0, variable=self.opacity_var, command=lambda v: self.on_slider_move(v, 'opacity'))
        self.opacity_slider.pack(fill="x", pady=(0, 10))

        # Margin
        margin_header = ttk.Frame(self.watermark_settings_frame)
        margin_header.pack(fill="x")
        self.lbl_margin_title = ttk.Label(margin_header, text="Margin (pixels):")
        self.lbl_margin_title.pack(side="left")
        
        self.margin_var = tk.IntVar(value=self.config_data.get("margin", 30))
        self.lbl_margin_val = ttk.Label(margin_header, text=f"{self.margin_var.get()} px (Default: 30)", foreground="#0066cc")
        self.lbl_margin_val.pack(side="right")
        
        self.margin_slider = ttk.Scale(self.watermark_settings_frame, from_=0, to=200, variable=self.margin_var, command=lambda v: self.on_slider_move(v, 'margin'))
        self.margin_slider.pack(fill="x", pady=(0, 10))

        # Position
        self.lbl_position_title = ttk.Label(self.watermark_settings_frame, text="Position:")
        self.lbl_position_title.pack(anchor="w")
        self.position_var = tk.StringVar(value=self.config_data.get("position", "Bottom-Left"))
        positions = ["Bottom-Left", "Bottom-Right", "Top-Left", "Top-Right", "Center"]
        self.pos_combo = ttk.Combobox(self.watermark_settings_frame, textvariable=self.position_var, values=positions, state="readonly")
        self.pos_combo.pack(fill="x", pady=(0, 5))
        self.pos_combo.bind("<<ComboboxSelected>>", lambda e: [self.save_config(), self.schedule_preview_update()])

        step5_frame = self._create_collapsible_step(control_frame, "Step 5: Picture Enhancements")

        enh_frame1 = ttk.Frame(step5_frame)
        enh_frame1.pack(fill="x", pady=(0, 10))
        self.opt_sharpen = tk.BooleanVar(value=self.config_data.get("use_sharpen", True))
        ttk.Checkbutton(enh_frame1, text="Advanced Crisp Sharpening", variable=self.opt_sharpen, command=lambda: [self.save_config(), self.schedule_preview_update()]).pack(side="left")
        lbl_info1 = ttk.Label(enh_frame1, text=" ⓘ ", foreground="#0066cc", cursor="hand2", font=("Arial", 10, "bold"))
        lbl_info1.pack(side="left")
        Tooltip(lbl_info1, "Applies an Unsharp Mask filter to make details pop.\nDisable this if your photos are already perfectly sharp\nor if it exaggerates camera grain.")

        self.manual_settings_frame = ttk.LabelFrame(step5_frame, text="Manual Per-Image Enhance")
        self.manual_settings_frame.pack(fill="x")
        self.manual_mode_var = tk.BooleanVar(value=False)
        self.chk_manual_mode = ttk.Checkbutton(
            self.manual_settings_frame,
            text="Manual enhancment (M)",
            variable=self.manual_mode_var,
            command=self.on_manual_mode_toggle,
        )
        self.chk_manual_mode.pack(anchor="w", pady=(0, 8))

        for key, label in self.manual_setting_defs:
            self._create_manual_setting_slider(self.manual_settings_frame, key, label)

        ttk.Label(control_frame, text="Step 6: Run", font=("Arial", 11, "bold")).pack(anchor="w", pady=(0, 5))
        step6_frame = ttk.Frame(control_frame)
        step6_frame.pack(fill="x", pady=(0, 8))
        self.btn_process = ttk.Button(step6_frame, text="PROCESS IMAGES (4K Max)", command=self.process_images, style="Accent.TButton")
        self.btn_process.pack(fill="x", pady=(0, 10))
        
        # Hidden Progress Area (Starts hidden)
        self.progress_frame = ttk.Frame(step6_frame)
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

        preview_header = ttk.Frame(preview_frame)
        preview_header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        preview_header.columnconfigure(0, weight=1)
        ttk.Label(preview_header, text="Live Preview", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w")
        self.btn_delete = ttk.Button(preview_header, text="Delete", command=self.delete_active_image)
        self.btn_delete.grid(row=0, column=1, sticky="e")
        self.btn_delete.state(["disabled"])
        
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
        
        btn_col = ttk.Frame(self.gal_ctrl_frame)
        btn_col.pack(anchor="center")
        ttk.Button(btn_col, text="All", width=5, command=self.check_all_enhance, takefocus=False).pack(fill="x", padx=1)
        ttk.Button(btn_col, text="None", width=5, command=self.uncheck_all_enhance, takefocus=False).pack(fill="x", padx=1, pady=(2, 0))
        
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

        self._update_watermark_controls_state()
        self._update_manual_controls_state()

    def _create_collapsible_step(self, parent, title):
        section_frame = ttk.Frame(parent)
        section_frame.pack(fill="x", pady=(0, 8))

        header_frame = ttk.Frame(section_frame)
        header_frame.pack(fill="x")
        ttk.Label(header_frame, text=title, font=("Arial", 11, "bold")).pack(side="left", anchor="w")

        body_frame = ttk.Frame(section_frame)
        is_open = tk.BooleanVar(value=True)

        arrow_text = tk.StringVar()

        def refresh_arrow():
            arrow_text.set("▼" if is_open.get() else "▶")

        def toggle_section():
            if is_open.get():
                is_open.set(False)
                body_frame.pack_forget()
            else:
                is_open.set(True)
                body_frame.pack(fill="x", pady=(4, 0))
            refresh_arrow()

        ttk.Button(header_frame, textvariable=arrow_text, command=toggle_section, width=3, takefocus=False).pack(side="right")
        body_frame.pack(fill="x", pady=(4, 0))
        refresh_arrow()
        return body_frame

    def _on_controls_frame_configure(self, event):
        self.controls_canvas.configure(scrollregion=self.controls_canvas.bbox("all"))

    def _on_controls_canvas_configure(self, event):
        self.controls_canvas.itemconfigure(self._controls_window_id, width=event.width)

    def _on_controls_mousewheel(self, event):
        px = self.root.winfo_pointerx()
        py = self.root.winfo_pointery()
        cx = self.controls_canvas.winfo_rootx()
        cy = self.controls_canvas.winfo_rooty()
        cw = self.controls_canvas.winfo_width()
        ch = self.controls_canvas.winfo_height()

        if not (cx <= px <= cx + cw and cy <= py <= cy + ch):
            return

        if event.num == 4:
            self.controls_canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.controls_canvas.yview_scroll(1, "units")
        else:
            self.controls_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _create_manual_setting_slider(self, parent, key, label):
        row = ttk.Frame(parent)
        row.pack(fill="x")
        ttk.Label(row, text=f"{label}:").pack(side="left")
        reset_button = tk.Label(row, text="↻", fg="#0066cc", cursor="hand2")
        reset_button.pack(side="left", padx=(6, 0))
        reset_button.bind("<Button-1>", lambda e, k=key: self.on_manual_setting_reset(k))
        value_label = ttk.Label(row, text="+0", foreground="#0066cc")
        value_label.pack(side="right")

        var = tk.DoubleVar(value=0.0)
        slider = ttk.Scale(parent, from_=-100.0, to=100.0, variable=var, command=lambda value, k=key: self.on_manual_setting_move(k, value))
        slider.pack(fill="x", pady=(0, 6))

        self.manual_setting_vars[key] = var
        self.manual_setting_value_labels[key] = value_label
        self.manual_setting_sliders[key] = slider
        self.manual_setting_reset_buttons[key] = reset_button

    def _on_use_watermark_toggle(self):
        self.save_config()
        self._update_watermark_controls_state()
        self.schedule_preview_update()

    def _update_watermark_controls_state(self):
        enabled = self.use_watermark_var.get()
        slider_state = "normal" if enabled else "disabled"

        self.scale_slider.configure(state=slider_state)
        self.opacity_slider.configure(state=slider_state)
        self.margin_slider.configure(state=slider_state)
        if enabled:
            self.pos_combo.state(["!disabled", "readonly"])
        else:
            self.pos_combo.state(["disabled"])

        text_color = "#0066cc" if enabled else "gray"
        title_color = "black" if enabled else "gray"
        self.lbl_scale_title.configure(foreground=title_color)
        self.lbl_opacity_title.configure(foreground=title_color)
        self.lbl_margin_title.configure(foreground=title_color)
        self.lbl_position_title.configure(foreground=title_color)
        self.lbl_scale_val.configure(foreground=text_color)
        self.lbl_opacity_val.configure(foreground=text_color)
        self.lbl_margin_val.configure(foreground=text_color)

    def _new_manual_settings(self):
        return {key: 0.0 for key, _ in self.manual_setting_defs}

    def _current_manual_mode_enabled(self):
        if not self.input_paths:
            return False
        if self.current_preview_index >= len(self.manual_enabled_states):
            return False
        return bool(self.manual_enabled_states[self.current_preview_index])

    def _current_manual_settings(self):
        if not self.input_paths:
            return self._new_manual_settings()
        if self.current_preview_index >= len(self.per_image_manual_settings):
            return self._new_manual_settings()
        return self.per_image_manual_settings[self.current_preview_index]

    def _load_manual_controls_for_current_image(self):
        mode_enabled = self._current_manual_mode_enabled()
        self.manual_mode_var.set(mode_enabled)
        settings = self._current_manual_settings()
        self._loading_manual_settings = True
        for key, _ in self.manual_setting_defs:
            value = float(settings.get(key, 0.0))
            self.manual_setting_vars[key].set(value)
            self.manual_setting_value_labels[key].configure(text=f"{value:+.0f}")
        self._loading_manual_settings = False
        self._update_manual_controls_state()

    def _update_manual_controls_state(self):
        has_current = bool(self.input_paths) and self.current_preview_index < len(self.per_image_manual_settings)
        enhance_on = has_current and self.current_preview_index < len(self.enhance_states) and self.enhance_states[self.current_preview_index].get()
        manual_on = has_current and self.current_preview_index < len(self.manual_enabled_states) and self.manual_enabled_states[self.current_preview_index]
        enabled = bool(has_current and manual_on and enhance_on)

        slider_state = "normal" if enabled else "disabled"
        color = "#0066cc" if enabled else "gray"

        if has_current:
            self.chk_manual_mode.state(["!disabled"])
        else:
            self.chk_manual_mode.state(["disabled"])

        for key in self.manual_setting_sliders:
            self.manual_setting_sliders[key].configure(state=slider_state)
            self.manual_setting_value_labels[key].configure(foreground=color)
            if enabled:
                self.manual_setting_reset_buttons[key].configure(fg="#0066cc", cursor="hand2")
            else:
                self.manual_setting_reset_buttons[key].configure(fg="gray", cursor="arrow")

    def on_manual_mode_toggle(self):
        if not self.input_paths:
            self.manual_mode_var.set(False)
            self._update_manual_controls_state()
            return

        if self.current_preview_index >= len(self.manual_enabled_states):
            self._update_manual_controls_state()
            return

        self.manual_enabled_states[self.current_preview_index] = self.manual_mode_var.get()
        self._update_manual_controls_state()
        self.schedule_preview_update()

    def on_manual_setting_reset(self, key):
        has_current = bool(self.input_paths) and self.current_preview_index < len(self.per_image_manual_settings)
        enhance_on = has_current and self.current_preview_index < len(self.enhance_states) and self.enhance_states[self.current_preview_index].get()
        manual_on = has_current and self.current_preview_index < len(self.manual_enabled_states) and self.manual_enabled_states[self.current_preview_index]
        if not (has_current and enhance_on and manual_on):
            return

        if not self.input_paths or self.current_preview_index >= len(self.per_image_manual_settings):
            return

        self._loading_manual_settings = True
        self.manual_setting_vars[key].set(0.0)
        self._loading_manual_settings = False
        self.manual_setting_value_labels[key].configure(text="+0")
        self.per_image_manual_settings[self.current_preview_index][key] = 0.0
        self.schedule_preview_update()

    def on_manual_setting_move(self, key, value):
        numeric_value = float(value)
        self.manual_setting_value_labels[key].configure(text=f"{numeric_value:+.0f}")

        if self._loading_manual_settings:
            return

        if self.input_paths and self.current_preview_index < len(self.per_image_manual_settings):
            self.per_image_manual_settings[self.current_preview_index][key] = numeric_value
            self.schedule_preview_update()

    def check_all_enhance(self):
        """Checks all enhance checkboxes."""
        for state in self.enhance_states:
            state.set(True)
        self._update_manual_controls_state()
        self.schedule_preview_update()

    def uncheck_all_enhance(self):
        """Unchecks all enhance checkboxes."""
        for state in self.enhance_states:
            state.set(False)
        self._update_manual_controls_state()
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

    def _handle_input_files(self, files, enhance_defaults=None, initial_index=0):
        self.input_paths = [f for f in files if f.lower().endswith(self.valid_extensions)]
        
        # Cancel any ongoing load jobs
        if self._load_job_id:
            self.root.after_cancel(self._load_job_id)
            self._load_job_id = None
            
        if not self.input_paths:
            self.lbl_input_status.config(text="No valid images found.", foreground="red")
            self.gal_canvas.delete("all")
            self.lbl_preview.config(image="", text="Load images to see preview...")
            self.btn_delete.state(["disabled"])
            self.per_image_manual_settings = []
            self.manual_enabled_states = []
            self._load_manual_controls_for_current_image()
            return

        self._pending_select_index = max(0, min(initial_index, len(self.input_paths) - 1))
        if enhance_defaults is not None and len(enhance_defaults) == len(self.input_paths):
            self._initial_enhance_defaults = list(enhance_defaults)
        else:
            self._initial_enhance_defaults = [False] * len(self.input_paths)
        self.per_image_manual_settings = [self._new_manual_settings() for _ in self.input_paths]
        self.manual_enabled_states = [False for _ in self.input_paths]

        self.lbl_input_status.config(text=f"Loading 0 / {len(self.input_paths)} images...", foreground="blue")
        self.lbl_preview.config(text="Starting load...", image="")
        self.root.update_idletasks()
        self.btn_delete.state(["!disabled"])
        
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
        self._update_manual_controls_state()
        
        # Start incremental load
        self._load_next_thumbnail()

    def _load_next_thumbnail(self):
        """Asynchronously loads images one by one to prevent GUI freezing."""
        if self._load_index >= len(self.input_paths):
            # All done loading
            self.lbl_input_status.config(text=f"Selected {len(self.input_paths)} images", foreground="green")
            self.btn_process.config(state="normal")
            self.thumbnails_loaded = True
            self._update_manual_controls_state()
            return

        i = self._load_index
        self._load_index += 1
        self.lbl_input_status.config(text=f"Loading {self._load_index} / {len(self.input_paths)} images...", foreground="blue")
        self.root.update_idletasks()

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
            enhance_default = False
            if i < len(self._initial_enhance_defaults):
                enhance_default = self._initial_enhance_defaults[i]
            self.enhance_states.append(tk.BooleanVar(value=enhance_default))
            
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
            
            if i == self._pending_select_index:
                self.select_preview_image(i)
                
        except Exception as e:
            print(f"Thumbnail error for {path}: {e}")
            self.thumb_rects.append(None)
            enhance_default = False
            if i < len(self._initial_enhance_defaults):
                enhance_default = self._initial_enhance_defaults[i]
            self.enhance_states.append(tk.BooleanVar(value=enhance_default))
            
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

        self._ensure_active_thumbnail_visible()
        self._load_manual_controls_for_current_image()
        
        # Pull from cache if available, otherwise generate
        self.generate_base_thumbnail()

    def _ensure_active_thumbnail_visible(self):
        if not self.thumb_rects or self.current_preview_index >= len(self.thumb_rects):
            return

        rect_id = self.thumb_rects[self.current_preview_index]
        if rect_id is None:
            return

        rect_bbox = self.gal_canvas.bbox(rect_id)
        all_bbox = self.gal_canvas.bbox("all")
        if not rect_bbox or not all_bbox:
            return

        total_width = max(1, all_bbox[2] - all_bbox[0])
        canvas_width = self.gal_canvas.winfo_width()
        if canvas_width <= 1:
            return

        view_start, view_end = self.gal_canvas.xview()
        view_left = view_start * total_width
        view_right = view_end * total_width
        max_left = max(0, total_width - canvas_width)
        padding = 12

        target_left = None
        if rect_bbox[0] - padding < view_left:
            target_left = max(0, rect_bbox[0] - padding)
        elif rect_bbox[2] + padding > view_right:
            target_left = min(max_left, rect_bbox[2] + padding - canvas_width)

        if target_left is not None:
            self.gal_canvas.xview_moveto(target_left / total_width)

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

    def _on_key_down(self, event):
        if self.input_paths and self.current_preview_index < len(self.input_paths) - 1:
            self.select_preview_image(self.current_preview_index + 1)
            return "break"
            
    def _on_key_space(self, event):
        # Ignore spacebar if user is interacting with a dropdown/combobox
        if isinstance(event.widget, ttk.Combobox):
            return
            
        if self.input_paths and self.current_preview_index < len(self.enhance_states):
            current = self.enhance_states[self.current_preview_index].get()
            self.enhance_states[self.current_preview_index].set(not current)
            self._update_manual_controls_state()
            self.schedule_preview_update()
            
            # Force focus back to main root to prevent double toggling if a checkbox was clicked recently
            self.root.focus_set()
            return "break" # Prevent spacebar from triggering other focused UI elements

    def _on_key_m(self, event):
        if isinstance(event.widget, ttk.Combobox):
            return

        if self.input_paths and self.current_preview_index < len(self.manual_enabled_states):
            current = self.manual_enabled_states[self.current_preview_index]
            self.manual_mode_var.set(not current)
            self.on_manual_mode_toggle()
            self.root.focus_set()
            return "break"

    def _on_key_delete(self, event):
        if isinstance(event.widget, ttk.Combobox):
            return
        self.delete_active_image()
        return "break"

    def _rebuild_gallery_from_memory(self):
        self.gal_canvas.delete("all")
        self.thumb_rects = []
        self._x_offset = 10

        for i, tk_img in enumerate(self.thumbnails):
            thumb_w = tk_img.width()
            thumb_h = tk_img.height()

            rect_id = self.gal_canvas.create_rectangle(
                self._x_offset - 4, 34 - thumb_h // 2 - 4,
                self._x_offset + thumb_w + 4, 34 + thumb_h // 2 + 4,
                outline="#e0e0e0", width=3
            )
            self.thumb_rects.append(rect_id)

            img_id = self.gal_canvas.create_image(self._x_offset, 34, anchor="w", image=tk_img)

            chk = tk.Checkbutton(
                self.gal_canvas,
                variable=self.enhance_states[i],
                command=self.schedule_preview_update,
                bg="#e0e0e0",
                activebackground="#e0e0e0",
                bd=0,
                highlightthickness=0,
                padx=0,
                pady=0,
                takefocus=False,
            )
            self.gal_canvas.create_window(self._x_offset + thumb_w - 3, 34 - thumb_h // 2 + 3, window=chk, anchor="ne")

            for item_id in (img_id, rect_id):
                self.gal_canvas.tag_bind(item_id, "<ButtonPress-1>", self.on_gal_press)
                self.gal_canvas.tag_bind(item_id, "<B1-Motion>", self.on_gal_drag)
                self.gal_canvas.tag_bind(item_id, "<ButtonRelease-1>", lambda e, idx=i: self.on_thumb_click(e, idx))

            self._x_offset += thumb_w + 15

        self.gal_canvas.configure(scrollregion=(0, 0, max(self._x_offset, 0), 75))

    def delete_active_image(self):
        if not self.input_paths:
            return

        if not self.thumbnails_loaded:
            messagebox.showinfo("Still loading", "Please wait until thumbnails finish loading before deleting an image.")
            return

        idx = self.current_preview_index

        if self._load_job_id:
            self.root.after_cancel(self._load_job_id)
            self._load_job_id = None

        del self.input_paths[idx]
        if idx < len(self.enhance_states):
            del self.enhance_states[idx]
        if idx < len(self.thumbnails):
            del self.thumbnails[idx]
        if idx < len(self.per_image_manual_settings):
            del self.per_image_manual_settings[idx]
        if idx < len(self.manual_enabled_states):
            del self.manual_enabled_states[idx]

        with self.preview_cache_lock:
            shifted_cache = {}
            for cache_idx, cache_img in self.cached_previews.items():
                if cache_idx == idx:
                    continue
                new_idx = cache_idx - 1 if cache_idx > idx else cache_idx
                shifted_cache[new_idx] = cache_img
            self.cached_previews = shifted_cache

        self.cached_base_thumb = None
        self.tk_preview_image = None

        if not self.input_paths:
            self.input_paths = []
            self.current_preview_index = 0
            self.cached_base_thumb = None
            self.tk_preview_image = None
            with self.preview_cache_lock:
                self.cached_previews.clear()
            self.thumbnails = []
            self.thumb_rects = []
            self.enhance_states = []
            self.gal_canvas.delete("all")
            self.gal_canvas.configure(scrollregion=(0, 0, 0, 75))
            self.lbl_input_status.config(text="No images selected", foreground="gray")
            self.lbl_preview.config(image="", text="Load images to see preview...", background="#e0e0e0")
            self.btn_process.config(state="disabled")
            self.btn_delete.state(["disabled"])
            self.per_image_manual_settings = []
            self.manual_enabled_states = []
            self._load_manual_controls_for_current_image()
            return

        self.current_preview_index = min(idx, len(self.input_paths) - 1)
        self.lbl_input_status.config(text=f"Selected {len(self.input_paths)} images", foreground="green")
        self._rebuild_gallery_from_memory()
        self.btn_process.config(state="normal")
        self.btn_delete.state(["!disabled"])
        self.select_preview_image(self.current_preview_index)

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

    def _apply_manual_enhancements(self, img, settings):
        if not settings:
            return img

        has_alpha = img.mode == "RGBA"
        alpha = None
        result = img
        if has_alpha:
            alpha = img.split()[3]
            result = img.convert("RGB")

        brightness = float(settings.get("brightness", 0.0))
        contrast = float(settings.get("contrast", 0.0))
        gamma = float(settings.get("gamma", 0.0))
        color = float(settings.get("color", 0.0))
        sharpness = float(settings.get("sharpness", 0.0))
        lighting = float(settings.get("lighting", 0.0))
        dark_threshold = float(settings.get("dark_threshold", 0.0))
        bright_threshold = float(settings.get("bright_threshold", 0.0))
        outer_vignette = float(settings.get("outer_vignette", 0.0))
        inner_vignette = float(settings.get("inner_vignette", 0.0))

        if abs(brightness) > 0.1:
            result = ImageEnhance.Brightness(result).enhance(max(0.0, 1.0 + (brightness / 100.0)))

        if abs(contrast) > 0.1:
            result = ImageEnhance.Contrast(result).enhance(max(0.0, 1.0 + (contrast / 100.0)))

        if abs(gamma) > 0.1:
            gamma_factor = max(0.2, 1.0 + (gamma / 100.0))
            result = result.point(lambda i: min(255, max(0, int(255 * ((i / 255.0) ** gamma_factor)))))

        if abs(color) > 0.1:
            result = ImageEnhance.Color(result).enhance(max(0.0, 1.0 + (color / 100.0)))

        if abs(sharpness) > 0.1:
            result = ImageEnhance.Sharpness(result).enhance(max(0.0, 1.0 + (sharpness / 100.0)))

        if abs(lighting) > 0.1:
            result = ImageEnhance.Brightness(result).enhance(max(0.2, 1.0 + (lighting / 200.0)))

        if abs(dark_threshold) > 0.1 or abs(bright_threshold) > 0.1:
            black_point = int((dark_threshold / 100.0) * 64)
            white_point = 255 - int((bright_threshold / 100.0) * 64)
            if white_point <= black_point + 1:
                white_point = black_point + 2

            lut = []
            span = float(white_point - black_point)
            for i in range(256):
                mapped = int((i - black_point) * 255.0 / span)
                lut.append(min(255, max(0, mapped)))
            result = result.point(lut)

        result = self._apply_vignette(result, outer_vignette, inner_vignette)

        if has_alpha and alpha is not None:
            result = result.convert("RGBA")
            result.putalpha(alpha)
        return result

    def _apply_vignette(self, img, outer_strength, inner_strength):
        if abs(outer_strength) <= 0.1 and abs(inner_strength) <= 0.1:
            return img

        width, height = img.size
        mask = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, width, height), fill=255)
        blur_radius = max(1, int(min(width, height) * 0.22))
        mask = mask.filter(ImageFilter.GaussianBlur(blur_radius))

        result = img

        if abs(outer_strength) > 0.1:
            if outer_strength > 0:
                edge_factor = max(0.15, 1.0 - (outer_strength / 100.0) * 0.75)
            else:
                edge_factor = 1.0 + ((-outer_strength) / 100.0) * 0.75
            edge_variant = ImageEnhance.Brightness(result).enhance(edge_factor)
            result = Image.composite(result, edge_variant, mask)

        if abs(inner_strength) > 0.1:
            if inner_strength > 0:
                center_factor = 1.0 + (inner_strength / 100.0) * 0.75
            else:
                center_factor = max(0.15, 1.0 - ((-inner_strength) / 100.0) * 0.75)
            center_variant = ImageEnhance.Brightness(result).enhance(center_factor)
            result = Image.composite(center_variant, result, mask)

        return result

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
            manual_mode_enabled = (
                self.current_preview_index < len(self.manual_enabled_states)
                and self.manual_enabled_states[self.current_preview_index]
            )
            if manual_mode_enabled:
                manual_settings = None
                if self.current_preview_index < len(self.per_image_manual_settings):
                    manual_settings = self.per_image_manual_settings[self.current_preview_index]
                base_thumb = self._apply_manual_enhancements(base_thumb, manual_settings)
            else:
                base_thumb = self.auto_enhance_image(
                    base_thumb,
                    use_sharpen=self.opt_sharpen.get(),
                )
        
        # Apply Watermark if a watermark image is loaded and enabled
        if self.watermark_image_orig and self.use_watermark_var.get():
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
            
        has_watermark = self.watermark_image_orig is not None and self.use_watermark_var.get()
        any_enhanced = any(state.get() for state in self.enhance_states)

        if not has_watermark and not any_enhanced:
            messagebox.showwarning("Nothing to do", "Please select a watermark image or choose at least one image to enhance.")
            return

        if not has_watermark and any_enhanced:
            if not messagebox.askyesno("No Watermark", "No watermark will be applied.\n\nAre you sure you want to process the images applying ONLY the enhancements?"):
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
        use_watermark = self.use_watermark_var.get()

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
                    manual_mode_enabled = i < len(self.manual_enabled_states) and self.manual_enabled_states[i]
                    if manual_mode_enabled:
                        manual_settings = None
                        if i < len(self.per_image_manual_settings):
                            manual_settings = self.per_image_manual_settings[i]
                        base_img = self._apply_manual_enhancements(base_img, manual_settings)
                    else:
                        debug_dir = current_run_out_dir if self.debug_mode else None
                        base_img = self.auto_enhance_image(
                            base_img,
                            use_sharpen=use_sharpen,
                            debug_dir=debug_dir,
                            base_filename=filename,
                        )
                    
                if self.watermark_image_orig and use_watermark:
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