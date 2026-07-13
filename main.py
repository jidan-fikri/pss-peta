import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog
from PIL import Image, ImageTk
import cv2
import numpy as np
import platform
import pandas as pd
import json
from scipy.spatial import KDTree
from scipy.interpolate import griddata
import matplotlib.colors as mcolors
import os
import sys

try:
    import rasterio
except ImportError:
    rasterio = None

try:
    import sv_ttk
except ImportError:
    sv_ttk = None
    print("Warning: sv_ttk is not installed. Run 'pip install sv-ttk' for the modern theme.")

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# --- ToolTip Helper Class ---
class ToolTip(object):
    def __init__(self, widget, text='widget info'):
        self.widget = widget
        self.text = text
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)
        self.tw = None

    def enter(self, event=None):
        x = y = 0
        x, y, cx, cy = self.widget.bbox("insert") or (0, 0, 0, 0)
        x += self.widget.winfo_rootx() + 25
        y += self.widget.winfo_rooty() + 25

        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")

        # Keep tooltips as standard tk.Label to strictly control their pop-up coloring
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background="#ffffe0", foreground="black", relief='solid', borderwidth=1,
                         font=("Arial", "9", "normal"), padx=4, pady=2)
        label.pack(ipadx=1)

    def leave(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None


class MapDigitizerProApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PETA v1.0")
        self.root.iconbitmap(resource_path('logo.ico'))
        self.root.geometry("1400x850")

        # --- Variables ---
        self.image_path = None
        self.cv_img = None
        self.original_img_w = 0
        self.original_img_h = 0

        self.base_scale = 1.0
        self.zoom_factor = 1.0
        self.display_img = None

        # Spatial Variables
        self.has_spatial_data = False
        self.spatial_transform = None
        self.coord_x_start = None
        self.coord_x_end = None
        self.coord_y_start = None
        self.coord_y_end = None
        self.z_enabled = False
        self.z_start = 0.0
        self.z_end = 0.0

        # Legend Selection Variables
        self.rect_id = None
        self.temp_box_id = None
        self.start_x = None
        self.start_y = None
        self.crop_coords = None

        # Grid & Overlay Variables
        self.grid_points = []
        self.color_data = []
        self.interp_img_orig_size = None

        # Area Selection Variables
        self.data_area_points = []
        self.measure_points = []
        self.crosshair_x_id = None
        self.crosshair_y_id = None
        self.guide_line_id = None

        # Undo/Redo Stacks
        self.undo_stack = []
        self.redo_stack = []

        self.tool_var = tk.StringVar(value="pan")
        self.setup_ui()

        # --- Keyboard Shortcuts ---
        self.root.bind('<Control-h>', lambda e: self.tool_var.set("pan"))
        self.root.bind('<Control-H>', lambda e: self.tool_var.set("pan"))
        self.root.bind('<Command-h>', lambda e: self.tool_var.set("pan"))

        # Undo / Redo Keybinds
        self.root.bind('<Control-z>', lambda e: self.undo_action())
        self.root.bind('<Control-Z>', lambda e: self.undo_action())
        self.root.bind('<Command-z>', lambda e: self.undo_action())

        self.root.bind('<Control-y>', lambda e: self.redo_action())
        self.root.bind('<Control-Y>', lambda e: self.redo_action())
        self.root.bind('<Command-y>', lambda e: self.redo_action())

        # Apply Sun Valley Theme if available
        if sv_ttk is not None:
            sv_ttk.set_theme("light")

    def setup_ui(self):
        # Configure custom fonts for the toolbar icons
        style = ttk.Style()
        style.configure("Icon.TButton", font=("Segoe UI Emoji", 12))

        # --- Top Toolbar ---
        self.toolbar = ttk.Frame(self.root)
        self.toolbar.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)

        # File Dropdown Menu
        file_mb = ttk.Menubutton(self.toolbar, text="📁 File")
        file_mb.pack(side=tk.LEFT, padx=10)
        file_menu = tk.Menu(file_mb, tearoff=0)
        file_menu.add_command(label="Load Map Image", command=self.load_image)
        file_menu.add_command(label="Import CSV", command=self.open_import_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Export Data to CSV", command=self.open_export_dialog)
        file_mb.config(menu=file_menu)

        ttk.Separator(self.toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=5)

        tools_f = ttk.Frame(self.toolbar)
        tools_f.pack(side=tk.LEFT, padx=5)

        t_pan = ttk.Radiobutton(tools_f, text=" ✋ ", variable=self.tool_var, value="pan", command=self.on_tool_change,
                                style="Toolbutton")
        t_pan.pack(side=tk.LEFT, padx=2)
        ToolTip(t_pan, "Free Hand [Ctrl+H]")

        t_measure = ttk.Radiobutton(tools_f, text=" 📏 ", variable=self.tool_var, value="measure",
                                    command=self.on_tool_change, style="Toolbutton")
        t_measure.pack(side=tk.LEFT, padx=2)
        ToolTip(t_measure, "Ruler Tool")

        t_legend = ttk.Radiobutton(tools_f, text=" 🎨 ", variable=self.tool_var, value="legend",
                                   command=self.on_tool_change, style="Toolbutton")
        t_legend.pack(side=tk.LEFT, padx=2)
        ToolTip(t_legend, "Color Bar Selection")

        t_area = ttk.Radiobutton(tools_f, text=" ⬠ ", variable=self.tool_var, value="area", command=self.on_tool_change,
                                 style="Toolbutton")
        t_area.pack(side=tk.LEFT, padx=2)
        ToolTip(t_area, "Add Data Area (Polygon)")

        t_add = ttk.Radiobutton(tools_f, text=" 🟢 ", variable=self.tool_var, value="add", command=self.on_tool_change,
                                style="Toolbutton")
        t_add.pack(side=tk.LEFT, padx=2)
        ToolTip(t_add, "Add Dots Selection")

        t_del = ttk.Radiobutton(tools_f, text=" 🔴 ", variable=self.tool_var, value="delete",
                                command=self.on_tool_change, style="Toolbutton")
        t_del.pack(side=tk.LEFT, padx=2)
        ToolTip(t_del, "Delete Dots Selection")

        ttk.Separator(self.toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Zoom Controls
        zoom_f = ttk.Frame(self.toolbar)
        zoom_f.pack(side=tk.LEFT, padx=5)

        btn_reset = ttk.Button(zoom_f, text=" 🔎 ", command=lambda: self.apply_zoom(0), style="Icon.TButton")
        btn_reset.pack(side=tk.LEFT, padx=1)
        ToolTip(btn_reset, "Reset View")

        btn_zi = ttk.Button(zoom_f, text=" ➕ ", command=lambda: self.apply_zoom(1.2), style="Icon.TButton")
        btn_zi.pack(side=tk.LEFT, padx=1)
        ToolTip(btn_zi, "Zoom In")

        btn_zo = ttk.Button(zoom_f, text=" ➖ ", command=lambda: self.apply_zoom(0.8), style="Icon.TButton")
        btn_zo.pack(side=tk.LEFT, padx=1)
        ToolTip(btn_zo, "Zoom Out")

        ttk.Separator(self.toolbar, orient='vertical').pack(side=tk.LEFT, fill=tk.Y, padx=5)

        # Undo / Redo
        self.btn_undo = ttk.Button(self.toolbar, text=" ↩ ", command=self.undo_action, state=tk.DISABLED,
                                   style="Icon.TButton")
        self.btn_undo.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_undo, "Undo [Ctrl+Z]")

        self.btn_redo = ttk.Button(self.toolbar, text=" ↪ ", command=self.redo_action, state=tk.DISABLED,
                                   style="Icon.TButton")
        self.btn_redo.pack(side=tk.LEFT, padx=2)
        ToolTip(self.btn_redo, "Redo [Ctrl+Y]")

        btn_clear = ttk.Button(self.toolbar, text=" 🔄 ", command=self.clear_view, style="Icon.TButton")
        btn_clear.pack(side=tk.LEFT, padx=8)
        ToolTip(btn_clear, "Clear View")

        # Theme Toggle Button (Far Right)
        btn_theme = ttk.Button(self.toolbar, text=" 🌓 ", command=self.toggle_theme, style="Icon.TButton")
        btn_theme.pack(side=tk.RIGHT, padx=10)
        ToolTip(btn_theme, "Toggle Theme")

        # Spatial Status Warning Label
        self.lbl_spatial_status = tk.Label(self.toolbar, text="Waiting for Map...", font=("Arial", 10, "bold"),
                                           fg="gray")
        self.lbl_spatial_status.pack(side=tk.RIGHT, padx=15)

        # --- Left Panel (Canvas with Scrollbars) ---
        self.left_frame = ttk.Frame(self.root)
        self.left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self.left_frame, cursor="cross", bg="#8E8E8E", highlightthickness=0)

        self.scroll_y = ttk.Scrollbar(self.left_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scroll_x = ttk.Scrollbar(self.left_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)

        self.canvas.configure(yscrollcommand=self.scroll_y.set, xscrollcommand=self.scroll_x.set)

        self.scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.apply_smart_scroll(self.canvas)

        # --- Right Panel ---
        self.right_frame = ttk.Frame(self.root, width=400)
        self.right_frame.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_frame.pack_propagate(False)

        # View Layers Panel
        layers_frame = ttk.LabelFrame(self.right_frame, text="View Layers")
        layers_frame.pack(fill=tk.X, padx=5, pady=5)

        self.var_show_original = tk.BooleanVar(value=True)
        self.var_show_interp = tk.BooleanVar(value=False)
        self.var_show_dots = tk.BooleanVar(value=True)

        ttk.Checkbutton(layers_frame, text="Original Map", variable=self.var_show_original,
                        command=self.render_canvas).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Checkbutton(layers_frame, text="Interpolation", variable=self.var_show_interp,
                        command=self.toggle_interp_layer).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Checkbutton(layers_frame, text="Grid Dots", variable=self.var_show_dots, command=self.render_canvas).pack(
            side=tk.LEFT, padx=5, pady=5)

        ttk.Label(self.right_frame, text="© PSS PETA 2026", font=("Arial", 8, "italic"),
                  foreground="gray").pack(side=tk.BOTTOM, pady=10)

        # --- Notebook Tabs ---
        self.notebook = ttk.Notebook(self.right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # TAB 1: Legend Extraction
        self.tab_legend = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_legend, text="Color Bar Option")

        ttk.Label(self.tab_legend, text="Select the color bar with 'Color Bar Selection' tool.").pack(pady=5)
        ttk.Button(self.tab_legend, text="Extract Colors", style="Accent.TButton",
                   command=self.extract_colors_from_box).pack(pady=5, padx=10, fill=tk.X)

        # Preset Buttons
        preset_frame = ttk.Frame(self.tab_legend)
        preset_frame.pack(fill=tk.X, padx=10, pady=5)
        ttk.Button(preset_frame, text="Save Preset", command=self.save_preset).pack(side=tk.LEFT, expand=True,
                                                                                    fill=tk.X, padx=(0, 2))
        ttk.Button(preset_frame, text="Load Preset", command=self.load_preset).pack(side=tk.RIGHT, expand=True,
                                                                                    fill=tk.X, padx=(2, 0))

        self.lbl_color_count = ttk.Label(self.tab_legend, text="0 Colors Found", font=("Arial", 11, "bold"))
        self.lbl_color_count.pack(pady=5)

        color_container = ttk.Frame(self.tab_legend)
        color_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Color canvas stays tk.Canvas for scrolling, but background removes hardcoded white to adapt to theme
        self.color_canvas = tk.Canvas(color_container, highlightthickness=0)
        self.color_scroll = ttk.Scrollbar(color_container, orient="vertical", command=self.color_canvas.yview)
        self.scrollable_color_frame = ttk.Frame(self.color_canvas)

        self.scrollable_color_frame.bind("<Configure>", lambda e: self.color_canvas.configure(
            scrollregion=self.color_canvas.bbox("all")))
        self.color_canvas.create_window((0, 0), window=self.scrollable_color_frame, anchor="nw")
        self.color_canvas.configure(yscrollcommand=self.color_scroll.set)

        self.color_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.color_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.apply_smart_scroll(self.color_canvas)

        # TAB 2: Grid Preview
        self.tab_grid = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_grid, text="Grid Option")

        # --- GRID MODE TOGGLE ---
        self.grid_mode = tk.StringVar(value="pixel")
        mode_frame = ttk.Frame(self.tab_grid)
        mode_frame.pack(fill=tk.X, padx=20, pady=(15, 0))
        ttk.Radiobutton(mode_frame, text="Pixel Spacing", variable=self.grid_mode, value="pixel",
                        command=self.toggle_grid_ui).pack(side=tk.LEFT)
        ttk.Radiobutton(mode_frame, text="Total Point", variable=self.grid_mode, value="point",
                        command=self.toggle_grid_ui).pack(side=tk.LEFT)

        self.spacing_container = ttk.Frame(self.tab_grid)
        self.spacing_container.pack(fill=tk.X, padx=20, pady=5)

        # Pixel Options Container (Holds Spacing + Align)
        self.pixel_options_container = ttk.Frame(self.spacing_container)
        self.pixel_options_container.pack(fill=tk.X)

        # Pixel Spacing Frame
        self.pixel_frame = ttk.Frame(self.pixel_options_container)
        self.pixel_frame.pack(fill=tk.X)
        self.slider_spacing = ttk.Scale(self.pixel_frame, from_=5, to=100, orient=tk.HORIZONTAL)
        self.slider_spacing.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry_spacing_var = tk.StringVar(value="25")
        entry_spacing = ttk.Entry(self.pixel_frame, textvariable=self.entry_spacing_var, width=5, justify=tk.CENTER)
        entry_spacing.pack(side=tk.RIGHT, padx=(10, 0))

        # --- ALIGNMENT OPTIONS ---
        self.align_frame = ttk.Frame(self.pixel_options_container)
        self.align_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Label(self.align_frame, text="Align X:", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self.var_align_x = tk.StringVar(value="Left")
        ttk.Combobox(self.align_frame, textvariable=self.var_align_x, values=["Left", "Center", "Right"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=5)

        ttk.Label(self.align_frame, text="Align Y:", font=("Arial", 9, "bold")).pack(side=tk.LEFT, padx=(10, 0))
        self.var_align_y = tk.StringVar(value="Top")
        ttk.Combobox(self.align_frame, textvariable=self.var_align_y, values=["Top", "Center", "Bottom"], width=7,
                     state="readonly").pack(side=tk.LEFT, padx=5)

        # Point Count Frame
        self.point_frame = ttk.Frame(self.spacing_container)

        # X Point Count
        f_pt_x = ttk.Frame(self.point_frame)
        f_pt_x.pack(fill=tk.X, pady=2)
        ttk.Label(f_pt_x, text="Horiz (X):", font=("Arial", 9, "bold"), width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.slider_pt_x = ttk.Scale(f_pt_x, from_=2, to=200, orient=tk.HORIZONTAL)
        self.slider_pt_x.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry_pt_x_var = tk.StringVar(value="50")
        entry_pt_x = ttk.Entry(f_pt_x, textvariable=self.entry_pt_x_var, width=4, justify=tk.CENTER)
        entry_pt_x.pack(side=tk.LEFT, padx=5)

        # Y Point Count
        f_pt_y = ttk.Frame(self.point_frame)
        f_pt_y.pack(fill=tk.X, pady=2)
        ttk.Label(f_pt_y, text="Vert (Y):", font=("Arial", 9, "bold"), width=8, anchor=tk.W).pack(side=tk.LEFT)
        self.slider_pt_y = ttk.Scale(f_pt_y, from_=2, to=200, orient=tk.HORIZONTAL)
        self.slider_pt_y.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry_pt_y_var = tk.StringVar(value="20")
        entry_pt_y = ttk.Entry(f_pt_y, textvariable=self.entry_pt_y_var, width=4, justify=tk.CENTER)
        entry_pt_y.pack(side=tk.LEFT, padx=5)

        # Spacing Bindings
        def on_slider_change(val):
            self.entry_spacing_var.set(str(int(float(val))))

        def on_entry_change(event):
            try:
                val = int(self.entry_spacing_var.get())
                if val < 5: val = 5
                if val > 100: val = 100
                self.slider_spacing.set(val)
                self.entry_spacing_var.set(str(val))
            except ValueError:
                self.entry_spacing_var.set(str(int(self.slider_spacing.get())))

        self.slider_spacing.config(command=on_slider_change)
        self.slider_spacing.set(25)
        entry_spacing.bind("<Return>", on_entry_change)
        entry_spacing.bind("<FocusOut>", on_entry_change)

        # Point X Bindings
        def on_slider_pt_x_change(val):
            self.entry_pt_x_var.set(str(int(float(val))))

        def on_entry_pt_x_change(event):
            try:
                val = int(self.entry_pt_x_var.get())
                if val < 2: val = 2
                if val > 500: val = 500
                self.slider_pt_x.set(val)
                self.entry_pt_x_var.set(str(val))
            except ValueError:
                self.entry_pt_x_var.set(str(int(self.slider_pt_x.get())))

        self.slider_pt_x.config(command=on_slider_pt_x_change)
        self.slider_pt_x.set(50)
        entry_pt_x.bind("<Return>", on_entry_pt_x_change)
        entry_pt_x.bind("<FocusOut>", on_entry_pt_x_change)

        # Point Y Bindings
        def on_slider_pt_y_change(val):
            self.entry_pt_y_var.set(str(int(float(val))))

        def on_entry_pt_y_change(event):
            try:
                val = int(self.entry_pt_y_var.get())
                if val < 2: val = 2
                if val > 500: val = 500
                self.slider_pt_y.set(val)
                self.entry_pt_y_var.set(str(val))
            except ValueError:
                self.entry_pt_y_var.set(str(int(self.slider_pt_y.get())))

        self.slider_pt_y.config(command=on_slider_pt_y_change)
        self.slider_pt_y.set(20)
        entry_pt_y.bind("<Return>", on_entry_pt_y_change)
        entry_pt_y.bind("<FocusOut>", on_entry_pt_y_change)

        # --- EXCLUSIONS & GENERATE BUTTONS ---
        ttk.Separator(self.tab_grid, orient='horizontal').pack(fill=tk.X, padx=10, pady=10)

        self.var_exclude_bg = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.tab_grid, text="Exclude Background & Lines",
                        variable=self.var_exclude_bg).pack(anchor=tk.W, padx=20, pady=2)

        self.var_exclude_legend = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.tab_grid, text="Exclude Legend Box", variable=self.var_exclude_legend).pack(anchor=tk.W,
                                                                                                         padx=20,
                                                                                                         pady=2)

        ttk.Button(self.tab_grid, text="Generate Grid", style="Accent.TButton",
                   command=self.generate_grid_preview).pack(pady=15, padx=10, fill=tk.X)

        ttk.Button(self.tab_grid, text="Generate Interpolation Layer", command=self.generate_interpolation_layer).pack(
            pady=5, padx=10, fill=tk.X)

        self.lbl_dot_count = ttk.Label(self.tab_grid, text="Dots generated: 0", font=("Arial", 10, "bold"),
                                       foreground="#0078D7")
        self.lbl_dot_count.pack(pady=10)

        # --- Event Bindings ---
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Motion>", self.on_mouse_move)

        if platform.system() == "Darwin":
            self.canvas.bind("<Button-2>", self.delete_dot_on_click)
        else:
            self.canvas.bind("<Button-3>", self.delete_dot_on_click)

    def toggle_theme(self):
        if sv_ttk is None:
            messagebox.showinfo("Theme Toggle",
                                "sv_ttk is not installed. Please run 'pip install sv-ttk' to enable themes.")
            return
        if sv_ttk.get_theme() == "dark":
            sv_ttk.set_theme("light")
        else:
            sv_ttk.set_theme("dark")

    def on_tool_change(self):
        self.measure_points = []
        if self.temp_box_id:
            self.canvas.delete(self.temp_box_id)
        self.render_canvas()

    def toggle_grid_ui(self):
        if self.grid_mode.get() == "pixel":
            self.point_frame.pack_forget()
            self.pixel_options_container.pack(fill=tk.X)
        else:
            self.pixel_options_container.pack_forget()
            self.point_frame.pack(fill=tk.X)

    # --- CSV Import Logic ---
    def open_import_csv(self):
        top = tk.Toplevel(self.root)
        top.title("Import Coordinate Data (CSV)")
        top.iconbitmap(resource_path('logo.ico'))
        top.geometry("750x800")

        # Ensures sv_ttk themes the Toplevel background correctly
        main_frame = ttk.Frame(top)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- SCROLLABLE WINDOW SETUP ---
        my_canvas = tk.Canvas(main_frame, highlightthickness=0)
        my_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        my_scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=my_canvas.yview)
        my_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        my_canvas.configure(yscrollcommand=my_scrollbar.set)

        content_frame = ttk.Frame(my_canvas)
        canvas_window = my_canvas.create_window((0, 0), window=content_frame, anchor="nw")

        def configure_canvas(event):
            my_canvas.configure(scrollregion=my_canvas.bbox("all"))
            my_canvas.itemconfig(canvas_window, width=event.width)

        content_frame.bind("<Configure>", configure_canvas)
        my_canvas.bind("<Configure>", lambda e: my_canvas.itemconfig(canvas_window, width=e.width))

        def _on_mousewheel(event):
            if platform.system() == 'Windows':
                my_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif platform.system() == 'Darwin':
                my_canvas.yview_scroll(int(-1 * event.delta), "units")
            else:
                if event.num == 4:
                    my_canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    my_canvas.yview_scroll(1, "units")

        def _bind_mousewheel(event):
            top.bind_all("<MouseWheel>", _on_mousewheel)
            top.bind_all("<Button-4>", _on_mousewheel)
            top.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_mousewheel(event):
            top.unbind_all("<MouseWheel>")
            top.unbind_all("<Button-4>")
            top.unbind_all("<Button-5>")

        content_frame.bind("<Enter>", _bind_mousewheel)
        content_frame.bind("<Leave>", _unbind_mousewheel)

        # Select File Frame
        file_frame = ttk.Frame(content_frame)
        file_frame.pack(fill=tk.X, padx=10, pady=10)

        self.csv_path_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.csv_path_var, state="readonly", width=45).pack(side=tk.LEFT)
        ttk.Button(file_frame, text="Browse", command=lambda: self.browse_import_csv(top)).pack(side=tk.LEFT, padx=5)

        self.has_header_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(file_frame, text="First row is header", variable=self.has_header_var,
                        command=lambda: self.reload_csv_preview(top)).pack(side=tk.LEFT, padx=10)

        # Viewer Frame
        self.csv_viewer_frame = ttk.Frame(content_frame)
        self.csv_viewer_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(content_frame, text="Map Columns:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10,
                                                                                       pady=(10, 0))

        # Column Selection Frame
        map_frame = ttk.Frame(content_frame)
        map_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(map_frame, text="X Column:").grid(row=0, column=0, pady=5)
        self.csv_x_cb = ttk.Combobox(map_frame, state="readonly", width=15)
        self.csv_x_cb.grid(row=0, column=1, padx=5, pady=5)
        self.csv_x_cb.bind("<<ComboboxSelected>>", lambda e: self.update_csv_scatter(top, update_cb=True))

        ttk.Label(map_frame, text="Y Column:").grid(row=0, column=2, pady=5)
        self.csv_y_cb = ttk.Combobox(map_frame, state="readonly", width=15)
        self.csv_y_cb.grid(row=0, column=3, padx=5, pady=5)
        self.csv_y_cb.bind("<<ComboboxSelected>>", lambda e: self.update_csv_scatter(top, update_cb=True))

        # Vertical Options
        vert_frame = ttk.LabelFrame(content_frame, text="Vertical Options (Z / Elevation)")
        vert_frame.pack(fill=tk.X, padx=10, pady=10, ipadx=10, ipady=10)

        self.z_enabled_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(vert_frame, text="Enable Z Coordinate Extraction", variable=self.z_enabled_var,
                        command=self.toggle_z_options).grid(row=0, column=0, columnspan=4, sticky=tk.W, pady=(0, 5))

        self.z_mode_var = tk.StringVar(value="manual")

        self.z_from_csv_rb = ttk.Radiobutton(vert_frame, text="From CSV Header:", variable=self.z_mode_var, value="csv",
                                             state=tk.DISABLED, command=self.toggle_z_options)
        self.z_from_csv_rb.grid(row=1, column=0, sticky=tk.W)
        self.csv_z_cb = ttk.Combobox(vert_frame, state="disabled", width=15)
        self.csv_z_cb.grid(row=1, column=1, padx=5)
        self.csv_z_cb.bind("<<ComboboxSelected>>", lambda e: self.update_z_manual())

        self.z_manual_rb = ttk.Radiobutton(vert_frame, text="Manual Bounds:", variable=self.z_mode_var, value="manual",
                                           state=tk.DISABLED, command=self.toggle_z_options)
        self.z_manual_rb.grid(row=2, column=0, sticky=tk.W, pady=5)

        z_man_frame = ttk.Frame(vert_frame)
        z_man_frame.grid(row=2, column=1, columnspan=3, sticky=tk.W)
        ttk.Label(z_man_frame, text="Top:").pack(side=tk.LEFT)
        self.z_top_var = tk.StringVar(value="0")
        self.z_top_entry = ttk.Entry(z_man_frame, textvariable=self.z_top_var, width=8, state=tk.DISABLED)
        self.z_top_entry.pack(side=tk.LEFT, padx=5)

        ttk.Label(z_man_frame, text="Bottom:").pack(side=tk.LEFT)
        self.z_bot_var = tk.StringVar(value="-100")
        self.z_bot_entry = ttk.Entry(z_man_frame, textvariable=self.z_bot_var, width=8, state=tk.DISABLED)
        self.z_bot_entry.pack(side=tk.LEFT, padx=5)

        # Calculator Button
        self.btn_z_calc = ttk.Button(z_man_frame, text="🧮 Calculator", state=tk.DISABLED,
                                     command=self.open_z_calculator)
        self.btn_z_calc.pack(side=tk.LEFT, padx=15)

        # Plot Frame for shape validation
        ttk.Label(content_frame, text="Data Shape Validation:", font=("Arial", 10, "bold")).pack(anchor=tk.W, padx=10,
                                                                                                 pady=(10, 0))
        self.plot_frame = ttk.LabelFrame(content_frame, text="Preview")
        self.plot_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # Plot Canvas stays as tk.Canvas, neutral background matches theme inherently
        self.plot_canvas = tk.Canvas(self.plot_frame, height=200, highlightthickness=0)
        self.plot_canvas.pack(fill=tk.BOTH, expand=True)
        self.plot_canvas.bind("<Configure>", lambda e: self.update_csv_scatter(top, update_cb=False))

        self.lbl_csv_stats = ttk.Label(content_frame, text="Average Euclidean Distance: -", font=("Arial", 9, "bold"),
                                       foreground="#0078D7")
        self.lbl_csv_stats.pack(pady=5)

        # --- NEW ANCHOR SELECTION FRAME ---
        anchor_frame = ttk.Frame(content_frame)
        anchor_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(anchor_frame, text="Set Start Point (Left Edge):", font=("Arial", 9, "bold")).pack(side=tk.LEFT)
        self.first_point_cb = ttk.Combobox(anchor_frame, state="readonly", width=15)
        self.first_point_cb.pack(side=tk.LEFT, padx=5)
        self.first_point_cb.bind("<<ComboboxSelected>>", lambda e: self.on_first_point_selected(top))

        self.lbl_selected_pt = ttk.Label(anchor_frame, text="X: - | Y: -", font=("Arial", 9, "bold"),
                                         foreground="purple")
        self.lbl_selected_pt.pack(side=tk.LEFT, padx=10)

        ttk.Button(content_frame, text="Import", style="Accent.TButton",
                   command=lambda: self.save_csv_import(top)).pack(pady=20)

        self.current_csv_df = None

    def open_z_calculator(self):
        calc = tk.Toplevel(self.root)
        calc.title("Z-Bounds Extrapolation Calculator")
        calc.iconbitmap(resource_path('logo.ico'))
        calc.geometry("380x350")
        calc.grab_set()

        calc_main = ttk.Frame(calc)
        calc_main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        ttk.Label(calc_main, text="1. Enter Known Values:", font=("Arial", 10, "bold")).pack(anchor=tk.W, pady=(5, 5))

        f1 = ttk.Frame(calc_main)
        f1.pack(fill=tk.X, pady=2)
        ttk.Label(f1, text="Top Pixel Value:").pack(side=tk.LEFT)
        v_top = ttk.Entry(f1, width=10)
        v_top.pack(side=tk.RIGHT)

        f2 = ttk.Frame(calc_main)
        f2.pack(fill=tk.X, pady=2)
        ttk.Label(f2, text="Bottom Pixel Value:").pack(side=tk.LEFT)
        v_bot = ttk.Entry(f2, width=10)
        v_bot.pack(side=tk.RIGHT)

        ttk.Label(calc_main, text="2. Enter Pixel Measurements:", font=("Arial", 10, "bold")).pack(anchor=tk.W,
                                                                                                   pady=(15, 5))

        f3 = ttk.Frame(calc_main)
        f3.pack(fill=tk.X, pady=2)
        ttk.Label(f3, text="Pixels Between Top & Bottom marks:").pack(side=tk.LEFT)
        px_mid = ttk.Entry(f3, width=10)
        px_mid.pack(side=tk.RIGHT)

        f4 = ttk.Frame(calc_main)
        f4.pack(fill=tk.X, pady=2)
        ttk.Label(f4, text="Pixels from Top Mark to True Top:").pack(side=tk.LEFT)
        px_top_over = ttk.Entry(f4, width=10)
        px_top_over.pack(side=tk.RIGHT)
        px_top_over.insert(0, "0")

        f5 = ttk.Frame(calc_main)
        f5.pack(fill=tk.X, pady=2)
        ttk.Label(f5, text="Pixels from Bottom Mark to True Bottom:").pack(side=tk.LEFT)
        px_bot_over = ttk.Entry(f5, width=10)
        px_bot_over.pack(side=tk.RIGHT)
        px_bot_over.insert(0, "0")

        def do_calc():
            try:
                top_val = float(v_top.get())
                bot_val = float(v_bot.get())
                p_mid = float(px_mid.get())
                p_top = float(px_top_over.get())
                p_bot = float(px_bot_over.get())

                if p_mid <= 0:
                    messagebox.showerror("Error", "Pixels between marks must be > 0", parent=calc)
                    return

                scale = (bot_val - top_val) / p_mid
                true_top = top_val - (p_top * scale)
                true_bot = bot_val + (p_bot * scale)

                self.z_mode_var.set("manual")
                self.toggle_z_options()
                self.z_top_var.set(str(round(true_top, 3)))
                self.z_bot_var.set(str(round(true_bot, 3)))

                messagebox.showinfo("Success",
                                    f"Extrapolation Successful!\n\nCalculated True Top: {round(true_top, 3)}\nCalculated True Bottom: {round(true_bot, 3)}",
                                    parent=calc)
                calc.destroy()
            except ValueError:
                messagebox.showerror("Error", "Please enter valid numbers in all fields.", parent=calc)

        ttk.Button(calc_main, text="Calculate & Apply", style="Accent.TButton", command=do_calc).pack(pady=20)

    def browse_import_csv(self, top):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path:
            self.csv_path_var.set(path)
            self.reload_csv_preview(top)

    def reload_csv_preview(self, top):
        path = self.csv_path_var.get()
        if not path: return
        try:
            if self.has_header_var.get():
                self.current_csv_df = pd.read_csv(path)
            else:
                df_temp = pd.read_csv(path, header=None)
                df_temp.columns = [f"Value {i + 1}" for i in range(len(df_temp.columns))]
                self.current_csv_df = df_temp

            cols = list(self.current_csv_df.columns)

            for widget in self.csv_viewer_frame.winfo_children():
                widget.destroy()

            tree = ttk.Treeview(self.csv_viewer_frame, columns=cols, show='headings', height=5)
            for c in cols:
                tree.heading(c, text=c)
                tree.column(c, width=80)
            for _, row in self.current_csv_df.head().iterrows():
                tree.insert('', tk.END, values=list(row))

            tree_scroll_x = ttk.Scrollbar(self.csv_viewer_frame, orient="horizontal", command=tree.xview)
            tree.configure(xscrollcommand=tree_scroll_x.set)
            tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
            tree.pack(fill=tk.X)

            self.csv_x_cb['values'] = cols
            self.csv_y_cb['values'] = cols
            self.csv_z_cb['values'] = cols

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load CSV:\n{e}")

    def on_first_point_selected(self, top):
        self.update_csv_scatter(top, update_cb=False)
        self.update_z_manual()

    def update_csv_scatter(self, top, update_cb=False):
        self.plot_canvas.delete("all")
        if self.current_csv_df is None: return
        x_col = self.csv_x_cb.get()
        y_col = self.csv_y_cb.get()
        if not x_col or not y_col: return

        try:
            x_data = self.current_csv_df[x_col].astype(float).values
            y_data = self.current_csv_df[y_col].astype(float).values

            if update_cb:
                self.first_point_cb['values'] = [f"Point {i}" for i in range(len(x_data))]
                if len(x_data) > 0:
                    self.first_point_cb.current(0)
                self.update_z_manual()

            dx = np.diff(x_data)
            dy = np.diff(y_data)
            dists = np.sqrt(dx ** 2 + dy ** 2)
            avg_dist = np.mean(dists) if len(dists) > 0 else 0
            self.lbl_csv_stats.config(text=f"Average Euclidean Distance: {avg_dist:.4f} | Total Points: {len(x_data)}")

            idx = self.first_point_cb.current() if hasattr(self, 'first_point_cb') else -1
            if idx >= 0 and idx < len(x_data):
                self.lbl_selected_pt.config(text=f"Selected -> X: {x_data[idx]:.3f} | Y: {y_data[idx]:.3f}")
            else:
                self.lbl_selected_pt.config(text="X: - | Y: -")

            w = self.plot_canvas.winfo_width()
            h = self.plot_canvas.winfo_height()
            if w < 10 or h < 10: return

            min_x, max_x = np.min(x_data), np.max(x_data)
            min_y, max_y = np.min(y_data), np.max(y_data)

            pad = 20
            w_draw = w - 2 * pad
            h_draw = h - 2 * pad

            def scale_pt(px, py):
                sx = pad + (px - min_x) / (max_x - min_x + 1e-9) * w_draw
                sy = pad + h_draw - (py - min_y) / (max_y - min_y + 1e-9) * h_draw
                return sx, sy

            for i in range(1, len(x_data)):
                px, py = scale_pt(x_data[i - 1], y_data[i - 1])
                sx, sy = scale_pt(x_data[i], y_data[i])
                self.plot_canvas.create_line(px, py, sx, sy, fill="gray", dash=(2, 2))

            for i in range(len(x_data)):
                sx, sy = scale_pt(x_data[i], y_data[i])
                if i == idx:
                    self.plot_canvas.create_oval(sx - 6, sy - 6, sx + 6, sy + 6, fill="#0078D7", outline="cyan",
                                                 width=2)
                else:
                    self.plot_canvas.create_oval(sx - 3, sy - 3, sx + 3, sy + 3, fill="red")

        except ValueError:
            self.lbl_csv_stats.config(text="Select numeric columns to plot data.")

    def toggle_z_options(self):
        if self.z_enabled_var.get():
            self.z_from_csv_rb.config(state=tk.NORMAL)
            self.z_manual_rb.config(state=tk.NORMAL)
            if self.z_mode_var.get() == "csv":
                self.csv_z_cb.config(state="readonly")
                self.z_top_entry.config(state=tk.DISABLED)
                self.z_bot_entry.config(state=tk.DISABLED)
                if hasattr(self, 'btn_z_calc'): self.btn_z_calc.config(state=tk.DISABLED)
            else:
                self.csv_z_cb.config(state=tk.DISABLED)
                self.z_top_entry.config(state=tk.NORMAL)
                self.z_bot_entry.config(state=tk.NORMAL)
                if hasattr(self, 'btn_z_calc'): self.btn_z_calc.config(state=tk.NORMAL)
        else:
            self.z_from_csv_rb.config(state=tk.DISABLED)
            self.z_manual_rb.config(state=tk.DISABLED)
            self.csv_z_cb.config(state=tk.DISABLED)
            self.z_top_entry.config(state=tk.DISABLED)
            self.z_bot_entry.config(state=tk.DISABLED)
            if hasattr(self, 'btn_z_calc'): self.btn_z_calc.config(state=tk.DISABLED)

    def update_z_manual(self):
        if self.z_mode_var.get() == "csv":
            z_col = self.csv_z_cb.get()
            if z_col and self.current_csv_df is not None:
                try:
                    z_data = self.current_csv_df[z_col].astype(float).values
                    if len(z_data) > 0:
                        cb_idx = getattr(self, 'first_point_cb', None)
                        idx = cb_idx.current() if (cb_idx and cb_idx.current() >= 0) else 0
                        end_idx = len(z_data) - 1 if idx < len(z_data) / 2 else 0

                        self.z_top_var.set(str(z_data[idx]))
                        self.z_bot_var.set(str(z_data[end_idx]))
                except ValueError:
                    pass

    def save_csv_import(self, top):
        x_col = self.csv_x_cb.get()
        y_col = self.csv_y_cb.get()
        if not x_col or not y_col:
            messagebox.showerror("Error", "Please select X and Y columns.")
            return

        try:
            x_data = self.current_csv_df[x_col].astype(float).values
            y_data = self.current_csv_df[y_col].astype(float).values
        except ValueError:
            messagebox.showerror("Error", "Selected coordinate columns must be numeric.")
            return

        if len(x_data) < 2:
            messagebox.showerror("Error", "Not enough data points in CSV.")
            return

        cb_idx = getattr(self, 'first_point_cb', None)
        start_idx = cb_idx.current() if (cb_idx and cb_idx.current() >= 0) else 0
        end_idx = len(x_data) - 1 if start_idx < len(x_data) / 2 else 0

        self.coord_x_start = float(x_data[start_idx])
        self.coord_x_end = float(x_data[end_idx])
        self.coord_y_start = float(y_data[start_idx])
        self.coord_y_end = float(y_data[end_idx])

        self.z_enabled = self.z_enabled_var.get()
        if self.z_enabled:
            try:
                self.z_start = float(self.z_top_var.get())
                self.z_end = float(self.z_bot_var.get())
            except ValueError:
                messagebox.showerror("Error", "Invalid Z top/bottom values. Must be numeric.")
                return

        self.has_spatial_data = True
        self.lbl_spatial_status.config(text="🌐 Geo-Coordinates Active (CSV Interpolation)", fg="lightgreen")
        top.destroy()

    # --- Smart Hover Scroll Logic ---
    def apply_smart_scroll(self, widget):
        def _on_mousewheel(event):
            is_ctrl_pressed = (event.state & 0x0004) != 0 or (event.state & 0x0008) != 0
            if platform.system() == 'Darwin':
                is_ctrl_pressed = (event.state & 0x0008) != 0 or (event.state & 0x0010) != 0

            if is_ctrl_pressed:
                delta = event.delta if platform.system() in ('Windows', 'Darwin') else (1 if event.num == 4 else -1)
                if delta > 0:
                    self.apply_zoom(1.1)
                else:
                    self.apply_zoom(0.9)
                return "break"

            if platform.system() == 'Windows':
                widget.yview_scroll(int(-1 * (event.delta / 120)), "units")
            elif platform.system() == 'Darwin':
                widget.yview_scroll(int(-1 * event.delta), "units")
            else:
                if event.num == 4:
                    widget.yview_scroll(-1, "units")
                elif event.num == 5:
                    widget.yview_scroll(1, "units")

        def _bind(event):
            widget.bind_all("<MouseWheel>", _on_mousewheel)
            widget.bind_all("<Button-4>", _on_mousewheel)
            widget.bind_all("<Button-5>", _on_mousewheel)

        def _unbind(event):
            widget.unbind_all("<MouseWheel>")
            widget.unbind_all("<Button-4>")
            widget.unbind_all("<Button-5>")

        widget.bind("<Enter>", _bind)
        widget.bind("<Leave>", _unbind)

    def clear_view(self):
        if self.data_area_points or self.grid_points or self.measure_points:
            self.save_state()
            self.data_area_points = []
            self.grid_points = []
            self.measure_points = []
            self.on_data_changed()
            self.render_canvas()

    # --- Data Update Hook ---
    def on_data_changed(self):
        self.interp_img_orig_size = None
        self.lbl_dot_count.config(text=f"Dots generated: {len(self.grid_points)}")

        if self.var_show_interp.get():
            self.generate_interpolation_layer()
        else:
            self.render_canvas()

    # --- Undo / Redo Logic ---
    def save_state(self):
        state = {
            'grid': list(self.grid_points),
            'area': list(self.data_area_points)
        }
        self.undo_stack.append(state)
        self.redo_stack.clear()
        self.update_undo_redo_buttons()

    def undo_action(self):
        if self.undo_stack:
            current_state = {
                'grid': list(self.grid_points),
                'area': list(self.data_area_points)
            }
            self.redo_stack.append(current_state)
            prev_state = self.undo_stack.pop()
            self.grid_points = prev_state['grid']
            self.data_area_points = prev_state['area']
            self.on_data_changed()
            self.update_undo_redo_buttons()

    def redo_action(self):
        if self.redo_stack:
            current_state = {
                'grid': list(self.grid_points),
                'area': list(self.data_area_points)
            }
            self.undo_stack.append(current_state)
            next_state = self.redo_stack.pop()
            self.grid_points = next_state['grid']
            self.data_area_points = next_state['area']
            self.on_data_changed()
            self.update_undo_redo_buttons()

    def update_undo_redo_buttons(self):
        self.btn_undo.config(state=tk.NORMAL if self.undo_stack else tk.DISABLED)
        self.btn_redo.config(state=tk.NORMAL if self.redo_stack else tk.DISABLED)

    # --- Preset Save/Load ---
    def save_preset(self):
        preset_data = {}
        for item in self.color_data:
            if item['frame'].winfo_exists():
                val_str = item['entry'].get()
                if val_str.strip() != "":
                    try:
                        r, g, b = item['rgb']
                        preset_data[f"{r},{g},{b}"] = float(val_str)
                    except ValueError:
                        pass

        if not preset_data:
            messagebox.showinfo("Empty", "No valid assigned values to save.")
            return

        filepath = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json")],
                                                title="Save Color Preset")
        if filepath:
            with open(filepath, 'w') as f:
                json.dump(preset_data, f, indent=4)
            messagebox.showinfo("Success", "Color preset saved successfully!")

    def load_preset(self):
        filepath = filedialog.askopenfilename(filetypes=[("JSON Files", "*.json")], title="Load Color Preset")
        if filepath:
            try:
                with open(filepath, 'r') as f:
                    preset_data = json.load(f)

                extracted_colors = []
                values = []
                for key, val in preset_data.items():
                    r, g, b = map(int, key.split(','))
                    extracted_colors.append((r, g, b))
                    values.append(val)

                self.populate_color_list(extracted_colors)
                for i, item in enumerate(self.color_data):
                    item['entry'].delete(0, tk.END)
                    item['entry'].insert(0, str(values[i]))

                self.lbl_color_count.config(text=f"{len(extracted_colors)} Colors Loaded")
                messagebox.showinfo("Success", f"Summoned {len(extracted_colors)} values from preset.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load preset:\n{e}")

    # --- Image Handling, Spatial Data, & Zooming ---
    def load_image(self):
        self.image_path = filedialog.askopenfilename(filetypes=[("Image Files", "*.tif *.jpg *.jpeg *.png *.tiff")])
        if not self.image_path: return

        self.cv_img = cv2.imread(self.image_path)
        self.cv_img = cv2.cvtColor(self.cv_img, cv2.COLOR_BGR2RGB)
        self.original_img_h, self.original_img_w = self.cv_img.shape[:2]

        self.has_spatial_data = False
        self.spatial_transform = None
        self.coord_x_start = None

        if rasterio:
            try:
                with rasterio.open(self.image_path) as dataset:
                    transform = dataset.transform
                    if not (transform[0] == 1.0 and transform[4] == 1.0 and transform[2] == 0.0):
                        self.spatial_transform = transform
                        self.has_spatial_data = True
            except Exception as e:
                print(f"Rasterio spatial loading failed or not applicable: {e}")

        if self.has_spatial_data:
            self.lbl_spatial_status.config(text="🌐 Geo-Coordinates Active", fg="lightgreen")
        else:
            self.lbl_spatial_status.config(text="⚠️ No Geo-Coordinates (Pixel Mode)", fg="orange")

        self.canvas.update()
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()

        scale_w = canvas_w / self.original_img_w
        scale_h = canvas_h / self.original_img_h
        self.base_scale = min(scale_w, scale_h)
        self.zoom_factor = 1.0

        self.grid_points = []
        self.data_area_points = []
        self.measure_points = []
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.update_undo_redo_buttons()
        self.crop_coords = None
        self.interp_img_orig_size = None
        self.var_show_interp.set(False)
        self.render_canvas()

    def get_pixel_steps(self):
        spacing_val = self.slider_spacing.get()
        if spacing_val <= 0: spacing_val = 1
        if self.has_spatial_data and self.spatial_transform and not self.coord_x_start:
            pixel_size_x = abs(self.spatial_transform[0])
            pixel_size_y = abs(self.spatial_transform[4])
            step_x = max(1, int(spacing_val / pixel_size_x))
            step_y = max(1, int(spacing_val / pixel_size_y))
            return step_x, step_y
        return int(spacing_val), int(spacing_val)

    def apply_zoom(self, multiplier):
        if self.cv_img is None: return
        if multiplier == 0:
            self.zoom_factor = 1.0
        else:
            self.zoom_factor *= multiplier
            self.zoom_factor = max(0.2, min(self.zoom_factor, 10.0))
        self.render_canvas()

    def render_canvas(self):
        if self.cv_img is None: return

        current_scale = self.base_scale * self.zoom_factor
        new_w = max(1, int(self.original_img_w * current_scale))
        new_h = max(1, int(self.original_img_h * current_scale))

        if self.var_show_original.get():
            resized_base = cv2.resize(self.cv_img, (new_w, new_h))
            base_pil = Image.fromarray(resized_base).convert("RGBA")
        else:
            base_pil = Image.new("RGBA", (new_w, new_h), (220, 220, 220, 255))

        if self.var_show_interp.get() and self.interp_img_orig_size is not None:
            resized_interp = cv2.resize(self.interp_img_orig_size, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            interp_pil = Image.fromarray(resized_interp, "RGBA")
            base_pil = Image.alpha_composite(base_pil, interp_pil)

        self.display_img = ImageTk.PhotoImage(image=base_pil)

        self.canvas.delete("all")
        self.guide_line_id = None
        self.crosshair_x_id = None
        self.crosshair_y_id = None
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_img)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        if self.crop_coords:
            x1, y1, x2, y2 = [int(c * current_scale) for c in self.crop_coords]
            self.rect_id = self.canvas.create_rectangle(x1, y1, x2, y2, outline="red", width=3, tags="legend_box")

        if self.data_area_points:
            scaled_pts = [(int(px * current_scale), int(py * current_scale)) for px, py in self.data_area_points]
            for i, (cx, cy) in enumerate(scaled_pts):
                self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="purple", outline="white",
                                        tags="area_poly")
                if i > 0:
                    prev_x, prev_y = scaled_pts[i - 1]
                    self.canvas.create_line(prev_x, prev_y, cx, cy, fill="purple", width=2, dash=(4, 2),
                                            tags="area_poly")
            if len(scaled_pts) >= 3:
                self.canvas.create_line(scaled_pts[-1][0], scaled_pts[-1][1], scaled_pts[0][0], scaled_pts[0][1],
                                        fill="purple", width=2, dash=(4, 2), tags="area_poly")

        if self.tool_var.get() == "measure" and self.measure_points:
            scaled_pts = [(int(px * current_scale), int(py * current_scale)) for px, py in self.measure_points]
            for cx, cy in scaled_pts:
                self.canvas.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill="cyan", outline="black",
                                        tags="measure_poly")

        if self.var_show_dots.get():
            for pt in self.grid_points:
                ox, oy, cx_idx, cy_idx = pt
                cx, cy = int(ox * current_scale), int(oy * current_scale)
                self.canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill="yellow", outline="black",
                                        tags=("dot", f"{ox},{oy},{cx_idx},{cy_idx}"))

    # --- Tool Routing: Mouse Events ---
    def on_mouse_move(self, event):
        if self.cv_img is None: return

        if self.crosshair_x_id: self.canvas.delete(self.crosshair_x_id)
        if self.crosshair_y_id: self.canvas.delete(self.crosshair_y_id)
        if self.guide_line_id:  self.canvas.delete(self.guide_line_id)

        if self.tool_var.get() in ("area", "measure"):
            current_scale = self.base_scale * self.zoom_factor
            raw_x, raw_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            img_x, img_y = int(raw_x / current_scale), int(raw_y / current_scale)

            pts_list = self.data_area_points if self.tool_var.get() == "area" else self.measure_points

            is_shift = (event.state & 0x0001) != 0
            if is_shift and pts_list:
                last_px, last_py = pts_list[-1]
                if abs(img_x - last_px) > abs(img_y - last_py):
                    img_y = last_py
                else:
                    img_x = last_px

            snap_x, snap_y = img_x * current_scale, img_y * current_scale

            bbox = self.canvas.bbox("all")
            if bbox:
                w, h = bbox[2], bbox[3]
                self.crosshair_x_id = self.canvas.create_line(0, snap_y, w, snap_y, fill="purple", dash=(2, 2))
                self.crosshair_y_id = self.canvas.create_line(snap_x, 0, snap_x, h, fill="purple", dash=(2, 2))

            if pts_list:
                last_px, last_py = pts_list[-1]
                start_x, start_y = last_px * current_scale, last_py * current_scale
                self.guide_line_id = self.canvas.create_line(start_x, start_y, snap_x, snap_y, fill="cyan", width=2,
                                                             dash=(4, 4))

    def on_mouse_down(self, event):
        if self.cv_img is None: return
        tool = self.tool_var.get()

        if tool == "pan":
            self.canvas.config(cursor="fleur")
            self.canvas.scan_mark(event.x, event.y)
            return

        if tool in ("area", "measure"):
            current_scale = self.base_scale * self.zoom_factor
            raw_x, raw_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
            img_x, img_y = int(raw_x / current_scale), int(raw_y / current_scale)

            pts_list = self.data_area_points if tool == "area" else self.measure_points

            is_shift = (event.state & 0x0001) != 0
            if is_shift and pts_list:
                last_px, last_py = pts_list[-1]
                if abs(img_x - last_px) > abs(img_y - last_py):
                    img_y = last_py
                else:
                    img_x = last_px

            if tool == "area":
                self.save_state()
                self.data_area_points.append((img_x, img_y))
                self.render_canvas()
                self.on_mouse_move(event)
                return
            elif tool == "measure":
                self.measure_points.append((img_x, img_y))
                if len(self.measure_points) == 2:
                    px_x1, px_y1 = self.measure_points[0]
                    px_x2, px_y2 = self.measure_points[1]

                    dist_x = abs(px_x2 - px_x1)
                    dist_y = abs(px_y2 - px_y1)
                    dist_total = int(np.sqrt(dist_x ** 2 + dist_y ** 2))

                    messagebox.showinfo("Ruler Tool Measurement",
                                        f"Measurements in Original Image Pixels:\n\n"
                                        f"Vertical Distance (Y): {dist_y} px\n"
                                        f"Horizontal Distance (X): {dist_x} px\n"
                                        f"Total Direct Distance: {dist_total} px")

                    self.measure_points = []
                self.render_canvas()
                self.on_mouse_move(event)
                return

        self.canvas.config(cursor="cross")
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)

        color = "red" if tool == "legend" else "green" if tool == "add" else "orange"
        if self.temp_box_id: self.canvas.delete(self.temp_box_id)
        if tool == "legend" and self.rect_id: self.canvas.delete("legend_box")

        self.temp_box_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y,
                                                        outline=color, width=3, tags="temp_box")

    def on_mouse_drag(self, event):
        if self.cv_img is None: return
        tool = self.tool_var.get()

        if tool == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return

        if tool in ("area", "measure"):
            self.on_mouse_move(event)
            return

        if not self.temp_box_id: return
        cur_x, cur_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.coords(self.temp_box_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_mouse_up(self, event):
        if self.cv_img is None: return
        tool = self.tool_var.get()

        if tool in ("pan", "area", "measure"):
            if tool == "pan": self.canvas.config(cursor="cross")
            return

        if not self.temp_box_id: return
        end_x, end_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        current_scale = self.base_scale * self.zoom_factor

        x1 = int(min(self.start_x, end_x) / current_scale)
        y1 = int(min(self.start_y, end_y) / current_scale)
        x2 = int(max(self.start_x, end_x) / current_scale)
        y2 = int(max(self.start_y, end_y) / current_scale)

        step_x, step_y = self.get_pixel_steps()

        if abs(x2 - x1) < 5 or abs(y2 - y1) < 5:
            self.canvas.delete("temp_box")
            if tool == "legend": self.render_canvas()
            return

        if tool == "legend":
            self.crop_coords = (x1, y1, x2, y2)
            self.canvas.delete("temp_box")
            self.render_canvas()

        elif tool == "add":
            self.save_state()
            start_x = (x1 // step_x) * step_x
            start_y = (y1 // step_y) * step_y

            for y in range(start_y, y2 + 1, step_y):
                for x in range(start_x, x2 + 1, step_x):
                    if x1 <= x <= x2 and y1 <= y <= y2:
                        if not any(pt[0] == x and pt[1] == y for pt in self.grid_points):
                            self.grid_points.append((x, y, -1, -1))

            self.canvas.delete("temp_box")
            self.on_data_changed()

        elif tool == "delete":
            self.save_state()
            self.grid_points = [pt for pt in self.grid_points if not (x1 <= pt[0] <= x2 and y1 <= pt[1] <= y2)]

            self.canvas.delete("temp_box")
            self.on_data_changed()

    def delete_dot_on_click(self, event):
        if not self.grid_points: return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        clicked_items = self.canvas.find_overlapping(cx - 5, cy - 5, cx + 5, cy + 5)

        for item_id in clicked_items:
            tags = self.canvas.gettags(item_id)
            if "dot" in tags and len(tags) > 1:
                coords_str = tags[1]
                try:
                    parts = coords_str.split(',')
                    ox, oy = int(parts[0]), int(parts[1])
                    for pt in self.grid_points:
                        if pt[0] == ox and pt[1] == oy:
                            self.save_state()
                            self.grid_points.remove(pt)
                            self.canvas.delete(item_id)
                            self.on_data_changed()
                            break
                except Exception:
                    continue

    def extract_colors_from_box(self):
        if not self.crop_coords or self.cv_img is None:
            messagebox.showwarning("Warning", "Please draw a red box over the legend first!")
            return

        x1, y1, x2, y2 = self.crop_coords
        cropped_roi = self.cv_img[y1:y2, x1:x2]
        height, width = cropped_roi.shape[:2]

        best_col = width // 2
        max_color_pixels = 0

        for x in range(width):
            color_count = 0
            for y in range(height):
                r, g, b = cropped_roi[y, x]
                is_black = (r < 60 and g < 60 and b < 60)
                is_white = (r > 220 and g > 220 and b > 220) and (max(r, g, b) - min(r, g, b) < 15)
                if not is_black and not is_white: color_count += 1
            if color_count > max_color_pixels:
                max_color_pixels = color_count
                best_col = x

        extracted_colors = []
        current_block = []

        for y in range(height):
            r, g, b = cropped_roi[y, best_col]
            r, g, b = int(r), int(g), int(b)

            is_black_line = r < 60 and g < 60 and b < 60
            is_bg_white = (r > 220 and g > 220 and b > 220) and (max(r, g, b) - min(r, g, b) < 15)

            if is_black_line or is_bg_white:
                if current_block:
                    if len(current_block) > 40:
                        num_samples = simpledialog.askinteger("Gradient Detected",
                                                              "Continuous color gradient detected!\nHow many color classes/ticks do you want to extract?",
                                                              initialvalue=15, minvalue=2, maxvalue=100)
                        if not num_samples: num_samples = 15

                        step = len(current_block) / float(num_samples)
                        for i in range(num_samples):
                            sample_idx = int(i * step + step / 2)
                            if sample_idx >= len(current_block): sample_idx = len(current_block) - 1
                            extracted_colors.append(current_block[sample_idx])
                    elif len(current_block) > 2:
                        extracted_colors.append(current_block[len(current_block) // 2])
                    current_block = []
            else:
                current_block.append((r, g, b))

        if current_block:
            if len(current_block) > 40:
                num_samples = simpledialog.askinteger("Gradient Detected",
                                                      "Continuous color gradient detected!\nHow many color classes/ticks do you want to extract?",
                                                      initialvalue=15, minvalue=2, maxvalue=100)
                if not num_samples: num_samples = 15
                step = len(current_block) / float(num_samples)
                for i in range(num_samples):
                    sample_idx = int(i * step + step / 2)
                    if sample_idx >= len(current_block): sample_idx = len(current_block) - 1
                    extracted_colors.append(current_block[sample_idx])
            elif len(current_block) > 2:
                extracted_colors.append(current_block[len(current_block) // 2])

        final_colors = []
        for c in extracted_colors:
            if not final_colors:
                final_colors.append(c)
            else:
                last_c = final_colors[-1]
                dist = sum(abs(c[i] - last_c[i]) for i in range(3))
                if dist > 5: final_colors.append(c)

        self.populate_color_list(final_colors)
        self.lbl_color_count.config(text=f"{len(final_colors)} Colors Found")

    def populate_color_list(self, colors):
        self.color_data = []
        for widget in self.scrollable_color_frame.winfo_children(): widget.destroy()

        for i, (r, g, b) in enumerate(colors):
            row_frame = ttk.Frame(self.scrollable_color_frame)
            row_frame.pack(fill=tk.X, pady=2)
            hex_color = f'#{r:02x}{g:02x}{b:02x}'

            tk.Label(row_frame, bg=hex_color, width=4, relief="ridge").pack(side=tk.LEFT, padx=5)
            ttk.Label(row_frame, text="Val:").pack(side=tk.LEFT)
            val_entry = ttk.Entry(row_frame, width=8)
            val_entry.pack(side=tk.LEFT, padx=5)

            def delete_row(f=row_frame, idx=i):
                f.destroy()
                self.update_color_count()

            ttk.Button(row_frame, text=" ❌ ", command=delete_row).pack(side=tk.RIGHT, padx=5)
            self.color_data.append({'rgb': (r, g, b), 'entry': val_entry, 'frame': row_frame})

            val_entry.bind("<Return>", lambda e, idx=i: self.navigate_entries(idx, 1))
            val_entry.bind("<Down>", lambda e, idx=i: self.navigate_entries(idx, 1))
            val_entry.bind("<Up>", lambda e, idx=i: self.navigate_entries(idx, -1))

    def update_color_count(self):
        count = sum(1 for item in self.color_data if item['frame'].winfo_exists())
        self.lbl_color_count.config(text=f"{count} Colors Found")

    def navigate_entries(self, current_idx, direction):
        target_idx = current_idx + direction
        while 0 <= target_idx < len(self.color_data):
            item = self.color_data[target_idx]
            if item['frame'].winfo_exists():
                item['entry'].focus_set()
                item['entry'].select_range(0, tk.END)
                self.auto_scroll_to_widget(item['frame'])
                return "break"
            target_idx += direction
        return "break"

    def auto_scroll_to_widget(self, widget):
        widget_y = widget.winfo_y()
        canvas_h = self.color_canvas.winfo_height()
        bbox = self.color_canvas.bbox("all")
        if not bbox: return
        total_h = bbox[3]
        current_top, current_bottom = self.color_canvas.yview()
        widget_fraction_top = widget_y / total_h
        widget_fraction_bottom = (widget_y + widget.winfo_height()) / total_h

        if widget_fraction_top < current_top:
            self.color_canvas.yview_moveto(max(0, widget_fraction_top - 0.05))
        elif widget_fraction_bottom > current_bottom:
            self.color_canvas.yview_moveto(min(1.0, widget_fraction_bottom - (canvas_h / total_h) + 0.05))

    # --- Grid Generation Logic ---
    def generate_grid_preview(self):
        if self.cv_img is None: return
        self.save_state()

        exclude_bg = self.var_exclude_bg.get()
        exclude_legend = self.var_exclude_legend.get()

        self.grid_points = []
        pts_array = np.array(self.data_area_points, dtype=np.int32) if len(self.data_area_points) >= 3 else None

        if pts_array is not None:
            start_x, end_x = int(np.min(pts_array[:, 0])), int(np.max(pts_array[:, 0]))
            start_y, end_y = int(np.min(pts_array[:, 1])), int(np.max(pts_array[:, 1]))
        else:
            start_x, end_x = 0, self.original_img_w - 1
            start_y, end_y = 0, self.original_img_h - 1

        start_x, end_x = max(0, min(start_x, self.original_img_w - 1)), max(0, min(end_x, self.original_img_w - 1))
        start_y, end_y = max(0, min(start_y, self.original_img_h - 1)), max(0, min(end_y, self.original_img_h - 1))

        x_coords_with_idx = []
        y_coords_with_idx = []

        if self.grid_mode.get() == "point":
            nx, ny = self.slider_pt_x.get(), self.slider_pt_y.get()
            x_flt, y_flt = np.linspace(start_x, end_x, int(nx)), np.linspace(start_y, end_y, int(ny))
            x_coords_with_idx = [(i, int(round(x))) for i, x in enumerate(x_flt)]
            y_coords_with_idx = [(i, int(round(y))) for i, y in enumerate(y_flt)]
        else:
            step_x, step_y = self.get_pixel_steps()
            # X Align
            if self.var_align_x.get() == "Left":
                x_c = list(range(start_x, end_x + 1, step_x))
            elif self.var_align_x.get() == "Right":
                x_c = list(range(end_x, start_x - 1, -step_x))[::-1]
            else:
                spn = ((end_x - start_x) // step_x) * step_x
                off = start_x + (end_x - start_x - spn) // 2
                x_c = [off + i * step_x for i in range((end_x - start_x) // step_x + 1)]
            # Y Align
            if self.var_align_y.get() == "Top":
                y_c = list(range(start_y, end_y + 1, step_y))
            elif self.var_align_y.get() == "Bottom":
                y_c = list(range(end_y, start_y - 1, -step_y))[::-1]
            else:
                spn = ((end_y - start_y) // step_y) * step_y
                off = start_y + (end_y - start_y - spn) // 2
                y_c = [off + i * step_y for i in range((end_y - start_y) // step_y + 1)]

            x_coords_with_idx = [(i, x) for i, x in enumerate(x_c)]
            y_coords_with_idx = [(i, y) for i, y in enumerate(y_c)]

        for cy_idx, y in y_coords_with_idx:
            for cx_idx, x in x_coords_with_idx:

                if pts_array is not None:
                    if cv2.pointPolygonTest(pts_array, (float(x), float(y)), True) < -2:
                        continue

                if exclude_legend and self.crop_coords:
                    x1, y1, x2, y2 = self.crop_coords
                    if x1 <= x <= x2 and y1 <= y <= y2: continue

                if exclude_bg:
                    r, g, b = self.cv_img[y, x]
                    r, g, b = int(r), int(g), int(b)
                    is_white = r > 240 and g > 240 and b > 240
                    is_black = r < 60 and g < 60 and b < 60
                    is_red_cross = r > 240 and g < 30 and b < 30
                    if is_white or is_black or is_red_cross: continue

                self.grid_points.append((x, y, cx_idx, cy_idx))

        self.on_data_changed()

    def toggle_interp_layer(self):
        if self.var_show_interp.get() and self.interp_img_orig_size is None:
            self.generate_interpolation_layer()
        else:
            self.render_canvas()

    def generate_interpolation_layer(self):
        if not self.grid_points or self.cv_img is None:
            if not self.grid_points and self.var_show_interp.get():
                messagebox.showerror("Error", "No grid points! Generate a grid first.")
                self.var_show_interp.set(False)
            return

        reference_rgbs = []
        reference_values = []
        for item in self.color_data:
            if item['frame'].winfo_exists() and item['entry'].get().strip() != "":
                try:
                    reference_rgbs.append(item['rgb'])
                    reference_values.append(float(item['entry'].get()))
                except ValueError:
                    pass

        if len(reference_rgbs) < 2:
            messagebox.showerror("Error", "Please extract the legend and assign at least 2 numbers.")
            self.var_show_interp.set(False)
            return

        if len(self.grid_points) < 4:
            messagebox.showerror("Error", "Need at least 4 dots to perform interpolation.")
            self.var_show_interp.set(False)
            return

        color_tree = KDTree(reference_rgbs)
        x_coords, y_coords, z_values = [], [], []
        for px, py, cx, cy in self.grid_points:
            r, g, b = self.cv_img[py, px]
            distance, closest_index = color_tree.query((int(r), int(g), int(b)))
            x_coords.append(px)
            y_coords.append(py)
            z_values.append(reference_values[closest_index])

        x_arr, y_arr, z_arr = np.array(x_coords), np.array(y_coords), np.array(z_values)

        val_color_pairs = list(zip(reference_values, reference_rgbs))
        val_color_pairs.sort(key=lambda x: x[0])
        normalized_colors = [(r / 255.0, g / 255.0, b / 255.0) for val, (r, g, b) in val_color_pairs]
        custom_cmap = mcolors.LinearSegmentedColormap.from_list("custom_legend", normalized_colors)

        scale_f = max(1, max(self.original_img_w, self.original_img_h) / 300.0)
        w_small, h_small = int(self.original_img_w / scale_f), int(self.original_img_h / scale_f)
        grid_x, grid_y = np.meshgrid(np.linspace(0, self.original_img_w - 1, w_small),
                                     np.linspace(0, self.original_img_h - 1, h_small))

        try:
            grid_z = griddata((x_arr, y_arr), z_arr, (grid_x, grid_y), method='linear')
        except Exception as e:
            messagebox.showerror("Interpolation Error", f"Failed to interpolate: {e}")
            self.var_show_interp.set(False)
            return

        z_min, z_max = np.nanmin(grid_z), np.nanmax(grid_z)
        if z_max > z_min:
            grid_z_norm = (grid_z - z_min) / (z_max - z_min)
        else:
            grid_z_norm = np.zeros_like(grid_z)

        rgba_img = custom_cmap(grid_z_norm)
        rgba_img[np.isnan(grid_z), 3] = 0.0
        rgba_img[~np.isnan(grid_z), 3] = 0.75
        rgba_uint8 = (rgba_img * 255).astype(np.uint8)

        self.interp_img_orig_size = cv2.resize(rgba_uint8, (self.original_img_w, self.original_img_h),
                                               interpolation=cv2.INTER_LINEAR)
        self.var_show_interp.set(True)
        self.render_canvas()

    # --- ADVANCED EXPORT CSV LOGIC ---
    def open_export_dialog(self):
        if not self.grid_points:
            messagebox.showerror("Error", "No grid points to export! Generate a grid first.")
            return

        top = tk.Toplevel(self.root)
        top.title("Export Configuration")
        top.iconbitmap(resource_path('logo.ico'))
        top.geometry("400x450")

        main_frame = ttk.Frame(top)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        ttk.Label(main_frame, text="Select metrics to include in export:", font=("Arial", 11, "bold")).pack(pady=10)

        vars_dict = {
            'x_coord': tk.BooleanVar(value=True),
            'y_coord': tk.BooleanVar(value=True),
            'z_coord': tk.BooleanVar(value=True),
            'dist': tk.BooleanVar(value=True),
            'depth': tk.BooleanVar(value=True),
            'amp': tk.BooleanVar(value=True),
            'r': tk.BooleanVar(value=True),
            'g': tk.BooleanVar(value=True),
            'b': tk.BooleanVar(value=True),
        }

        opts_frame = ttk.Frame(main_frame)
        opts_frame.pack(anchor=tk.W, padx=10)

        ttk.Checkbutton(opts_frame, text="X_Coordinate (X_Lokal)", variable=vars_dict['x_coord']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Y_Coordinate (Y_Lokal)", variable=vars_dict['y_coord']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Z_Coordinate (Elevation)", variable=vars_dict['z_coord']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Distance (Horizontal Position/Index)", variable=vars_dict['dist']).pack(
            anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Depth (Vertical Position/Index)", variable=vars_dict['depth']).pack(
            anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Amplitude (Z_Value Color)", variable=vars_dict['amp']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Red", variable=vars_dict['r']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Green", variable=vars_dict['g']).pack(anchor=tk.W)
        ttk.Checkbutton(opts_frame, text="Blue", variable=vars_dict['b']).pack(anchor=tk.W)

        ttk.Button(main_frame, text="💾 Export Now", style="Accent.TButton",
                   command=lambda: self.perform_export(top, vars_dict)).pack(pady=20)

    def perform_export(self, top, vars_dict):
        reference_rgbs = []
        reference_values = []

        for item in self.color_data:
            if item['frame'].winfo_exists() and item['entry'].get().strip() != "":
                try:
                    reference_rgbs.append(item['rgb'])
                    reference_values.append(float(item['entry'].get()))
                except ValueError:
                    pass

        color_tree = KDTree(reference_rgbs) if reference_rgbs else None
        if not color_tree and vars_dict['amp'].get():
            messagebox.showwarning("Warning", "No mapped colors found! Amplitude will be 0.")

        pts_array = np.array(self.data_area_points, dtype=np.int32) if len(self.data_area_points) >= 3 else None
        if pts_array is not None:
            min_px, max_px = np.min(pts_array[:, 0]), np.max(pts_array[:, 0])
            min_py, max_py = np.min(pts_array[:, 1]), np.max(pts_array[:, 1])
        else:
            min_px, max_px = 0, self.original_img_w - 1
            min_py, max_py = 0, self.original_img_h - 1

        final_data = []
        for px, py, cx_idx, cy_idx in self.grid_points:
            r, g, b = int(self.cv_img[py, px][0]), int(self.cv_img[py, px][1]), int(self.cv_img[py, px][2])

            matched_value = 0.0
            if color_tree is not None:
                distance, closest_index = color_tree.query((r, g, b))
                matched_value = reference_values[closest_index]

            rx = (px - min_px) / (max_px - min_px + 1e-9) if max_px != min_px else 0
            ry = (py - min_py) / (max_py - min_py + 1e-9) if max_py != min_py else 0

            real_x, real_y, real_z = float(px), float(py), 0.0

            if self.has_spatial_data:
                if self.coord_x_start is not None:
                    # Ratio X Interpolates both X_Lokal and Y_Lokal on the traverse diagonal!
                    real_x = self.coord_x_start + rx * (self.coord_x_end - self.coord_x_start)
                    real_y = self.coord_y_start + rx * (self.coord_y_end - self.coord_y_start)
                    if self.z_enabled:
                        real_z = self.z_start + ry * (self.z_end - self.z_start)
                elif self.spatial_transform is not None:
                    real_x, real_y = self.spatial_transform * (px, py)

            row_data = {}
            if vars_dict['x_coord'].get(): row_data['X_Coordinate'] = round(real_x, 3)
            if vars_dict['y_coord'].get(): row_data['Y_Coordinate'] = round(real_y, 3)
            if vars_dict['z_coord'].get(): row_data['Z_Coordinate'] = round(real_z, 3)
            if vars_dict['dist'].get(): row_data['Distance'] = cx_idx
            if vars_dict['depth'].get(): row_data['Depth'] = cy_idx
            if vars_dict['amp'].get(): row_data['Amplitude'] = matched_value
            if vars_dict['r'].get(): row_data['Red'] = r
            if vars_dict['g'].get(): row_data['Green'] = g
            if vars_dict['b'].get(): row_data['Blue'] = b

            final_data.append(row_data)

        output_file = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Files", "*.csv")],
                                                   title="Save Output Data")
        if output_file:
            df = pd.DataFrame(final_data)
            df.to_csv(output_file, index=False)
            messagebox.showinfo("Success", f"Successfully interpolated and exported {len(final_data)} points to CSV!")
            top.destroy()


if __name__ == "__main__":
    try:
        import pyi_splash

        pyi_splash.update_text('UI Loaded ... Starting App')
        pyi_splash.close()
    except ImportError:
        pass

    root = tk.Tk()
    app = MapDigitizerProApp(root)
    root.mainloop()