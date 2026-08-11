from __future__ import annotations

import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, Dict, List, Optional

from .config import APP_NAME, APP_VERSION, data_dir
from .database import Database, Session
from .exporter import export_csv, export_xlsx
from .forms import Field, MODULES, ROLE_LABELS, Module, modules_for_role


COLORS = {
    "navy": "#183B66",
    "navy_dark": "#102A49",
    "accent": "#0F6CBD",
    "accent_hover": "#0B5797",
    "bg": "#F3F6F9",
    "surface": "#FFFFFF",
    "border": "#D7DEE8",
    "text": "#1C2734",
    "muted": "#5E6C7B",
    "success": "#217A55",
    "warning": "#A56408",
    "danger": "#B42318",
}


class ScrollFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, **kwargs: Any):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=COLORS["bg"])
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = ttk.Frame(self.canvas, style="Page.TFrame")
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.body.bind("<MouseWheel>", self._wheel)

    def _wheel(self, event: tk.Event) -> None:
        if self.winfo_ismapped():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class FormDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        module: Module,
        on_save: Callable[[str, Dict[str, Any], Optional[str]], None],
        record: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.module = module
        self.on_save = on_save
        self.record = record
        self.widgets: Dict[str, Any] = {}
        self.title(("Edit " if record else "New ") + module.name)
        self.geometry("760x760")
        self.minsize(640, 560)
        self.configure(background=COLORS["bg"])
        self.transient(parent)
        self.grab_set()

        header = tk.Frame(self, bg=COLORS["navy"], height=76)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text=module.name, bg=COLORS["navy"], fg="white", font=("Segoe UI", 17, "bold")).pack(anchor="w", padx=28, pady=(15, 0))
        tk.Label(header, text="%s  •  %s" % (ROLE_LABELS[module.role], "Edit record" if record else "New record"), bg=COLORS["navy"], fg="#DCE9F7", font=("Segoe UI", 9)).pack(anchor="w", padx=29)

        scroll = ScrollFrame(self)
        scroll.pack(fill="both", expand=True)
        form = ttk.Frame(scroll.body, style="Card.TFrame", padding=(28, 22))
        form.pack(fill="x", padx=28, pady=24)
        form.columnconfigure(0, weight=1)
        existing = record.get("data", {}) if record else {}

        for row, field in enumerate(module.fields):
            label = field.label + (" *" if field.required else "")
            ttk.Label(form, text=label, style="FieldLabel.TLabel").grid(row=row * 3, column=0, sticky="w", pady=(0 if row == 0 else 14, 5))
            value = str(existing.get(field.key, ""))
            if not value and field.kind == "date" and field.key == "event_date":
                value = datetime.now().strftime("%d-%m-%Y")
            if field.kind == "longtext":
                widget = tk.Text(form, height=4, wrap="word", font=("Segoe UI", 10), relief="solid", borderwidth=1, padx=9, pady=8)
                widget.insert("1.0", value)
            elif field.kind == "choice":
                widget = ttk.Combobox(form, values=field.choices, state="readonly", font=("Segoe UI", 10))
                widget.set(value)
            else:
                widget = ttk.Entry(form, font=("Segoe UI", 10))
                widget.insert(0, value)
            widget.grid(row=row * 3 + 1, column=0, sticky="ew", ipady=5 if field.kind != "longtext" else 0)
            self.widgets[field.key] = widget
            if field.hint:
                ttk.Label(form, text=field.hint, style="Hint.TLabel").grid(row=row * 3 + 2, column=0, sticky="e")

        footer = ttk.Frame(self, style="Card.TFrame", padding=(22, 14))
        footer.pack(fill="x", side="bottom")
        ttk.Button(footer, text="Cancel", style="Secondary.TButton", command=self.destroy).pack(side="right")
        ttk.Button(footer, text="Submit", style="Primary.TButton", command=lambda: self._save("submitted")).pack(side="right", padx=10)
        ttk.Button(footer, text="Save draft", style="Secondary.TButton", command=lambda: self._save("draft")).pack(side="right")

    def _values(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field in self.module.fields:
            widget = self.widgets[field.key]
            value = widget.get("1.0", "end-1c").strip() if field.kind == "longtext" else widget.get().strip()
            result[field.key] = int(value) if field.kind == "integer" and value else value
        return result

    def _save(self, status: str) -> None:
        try:
            values = self._values()
        except ValueError:
            messagebox.showerror("Check the form", "Number fields must contain whole numbers.", parent=self)
            return
        if status == "submitted":
            missing = [field.label for field in self.module.fields if field.required and not values.get(field.key)]
            if missing:
                messagebox.showerror("Required fields", "Complete these fields:\n\n• " + "\n• ".join(missing), parent=self)
                return
        for field in self.module.fields:
            value = values.get(field.key)
            if field.kind == "date" and value:
                try:
                    datetime.strptime(str(value), "%d-%m-%Y")
                except ValueError:
                    messagebox.showerror("Invalid date", "%s must use DD-MM-YYYY." % field.label, parent=self)
                    return
            if field.kind == "integer" and value != "" and int(value) < 0:
                messagebox.showerror("Invalid number", "%s cannot be negative." % field.label, parent=self)
                return
        try:
            self.on_save(status, values, self.record.get("id") if self.record else None)
        except Exception as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)
            return
        self.destroy()


class ActivityDeskApp:
    def __init__(self, root: tk.Tk, database: Database):
        self.root = root
        self.db = database
        self.session: Optional[Session] = None
        self.main: Optional[ttk.Frame] = None
        self.content: Optional[ttk.Frame] = None
        self.page_title: Optional[ttk.Label] = None
        self._records_cache: Dict[str, Dict[str, Any]] = {}
        self._configure_root()
        self._configure_styles()
        if self.db.is_initialized():
            self.show_login()
        else:
            self.show_setup()

    def _configure_root(self) -> None:
        self.root.title(APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(960, 620)
        self.root.configure(background=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _configure_styles(self) -> None:
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(".", font=("Segoe UI", 10), foreground=COLORS["text"])
        style.configure("Page.TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["surface"], relief="flat")
        style.configure("Card.TLabel", background=COLORS["surface"])
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 22, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["bg"], foreground=COLORS["muted"], font=("Segoe UI", 10))
        style.configure("FieldLabel.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI", 9, "bold"))
        style.configure("Hint.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("Segoe UI", 8))
        style.configure("Primary.TButton", background=COLORS["accent"], foreground="white", borderwidth=0, padding=(16, 10), font=("Segoe UI", 10, "bold"))
        style.map("Primary.TButton", background=[("active", COLORS["accent_hover"]), ("disabled", "#9AA8B6")])
        style.configure("Secondary.TButton", background="#E7EDF4", foreground=COLORS["navy"], borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.map("Secondary.TButton", background=[("active", "#D7E1EC")])
        style.configure("Danger.TButton", background="#FDE8E7", foreground=COLORS["danger"], borderwidth=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        style.configure("Nav.TButton", background=COLORS["navy_dark"], foreground="#DCE9F7", borderwidth=0, padding=(18, 13), anchor="w", font=("Segoe UI", 10))
        style.map("Nav.TButton", background=[("active", COLORS["navy"])] , foreground=[("active", "white")])
        style.configure("Treeview", background="white", fieldbackground="white", rowheight=31, bordercolor=COLORS["border"])
        style.configure("Treeview.Heading", background="#E8EEF5", foreground=COLORS["navy"], font=("Segoe UI", 9, "bold"), padding=8)
        style.map("Treeview", background=[("selected", COLORS["accent"])], foreground=[("selected", "white")])
        style.configure("TEntry", fieldbackground="white", padding=8)
        style.configure("TCombobox", fieldbackground="white", padding=7)

    def _clear_root(self) -> None:
        for child in self.root.winfo_children():
            child.destroy()

    def _primary_button(self, parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(
            parent, text=text, command=command,
            bg=COLORS["accent"], activebackground=COLORS["accent_hover"],
            fg="white", activeforeground="white", disabledforeground="#DCE3EA",
            relief="flat", borderwidth=0, highlightthickness=0, cursor="hand2",
            font=("Segoe UI", 11, "bold"), padx=18, pady=12,
        )

    def show_setup(self) -> None:
        self._clear_root()
        outer = tk.Frame(self.root, bg=COLORS["bg"])
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, minsize=350, weight=2)
        outer.grid_columnconfigure(1, minsize=560, weight=3)
        outer.grid_rowconfigure(0, weight=1)

        brand = tk.Frame(outer, bg=COLORS["navy"], padx=48, pady=48)
        brand.grid(row=0, column=0, sticky="nsew")
        tk.Label(brand, text="TVS", bg=COLORS["navy"], fg="white", font=("Segoe UI", 38, "bold")).pack(anchor="w", pady=(90, 0))
        tk.Label(brand, text="Activity Desk", bg=COLORS["navy"], fg="#DCE9F7", font=("Segoe UI", 22)).pack(anchor="w")
        tk.Label(brand, text="Secure school activity management", bg=COLORS["navy"], fg="#AFC7DF", font=("Segoe UI", 10), wraplength=260, justify="left").pack(anchor="w", pady=(18, 0))
        tk.Label(brand, text="OFFLINE  •  LOCAL  •  ENCRYPTED", bg=COLORS["navy"], fg="#AFC7DF", font=("Segoe UI", 8, "bold")).pack(side="bottom", anchor="w")

        form_host = tk.Frame(outer, bg=COLORS["bg"])
        form_host.grid(row=0, column=1, sticky="nsew")
        card = tk.Frame(form_host, bg=COLORS["surface"], padx=44, pady=34, highlightthickness=1, highlightbackground=COLORS["border"])
        card.place(relx=.5, rely=.5, anchor="center", relwidth=.78)
        card.grid_columnconfigure(0, weight=1)
        tk.Label(card, text="First-time setup", bg=COLORS["surface"], fg=COLORS["navy"], font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(card, text="Create the protected administrator account for this computer.", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10), wraplength=440, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 18))

        values: Dict[str, tk.Entry] = {}
        fields = (
            ("school", "School / organisation name", False),
            ("name", "Administrator display name", False),
            ("password", "Master password", True),
            ("confirm", "Confirm master password", True),
        )
        for index, (key, label, secret) in enumerate(fields):
            label_row = 2 + index * 2
            tk.Label(card, text=label, bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI", 9, "bold")).grid(row=label_row, column=0, sticky="w", pady=(8, 5))
            entry = tk.Entry(card, show="•" if secret else "", font=("Segoe UI", 11), bg="white", fg=COLORS["text"], insertbackground=COLORS["text"], relief="solid", borderwidth=1, highlightthickness=1, highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"])
            entry.grid(row=label_row + 1, column=0, sticky="ew", ipady=9)
            values[key] = entry
        values["name"].insert(0, "System Administrator")
        tk.Label(card, text="Use 10+ characters with uppercase, lowercase and a number. This password cannot be recovered.", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8), wraplength=440, justify="left").grid(row=10, column=0, sticky="w", pady=(8, 14))

        def finish() -> None:
            if not values["school"].get().strip():
                messagebox.showerror("Setup", "Enter the school or organisation name.")
                return
            if values["password"].get() != values["confirm"].get():
                messagebox.showerror("Setup", "The passwords do not match.")
                return
            try:
                self.session = self.db.create_master(values["school"].get(), values["name"].get(), values["password"].get())
            except Exception as exc:
                messagebox.showerror("Setup", str(exc))
                return
            self.show_shell()

        self._primary_button(card, "Continue and create workspace", finish).grid(row=11, column=0, sticky="ew")
        tk.Label(card, text="No internet connection is required.", bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8)).grid(row=12, column=0, pady=(10, 0))
        values["confirm"].bind("<Return>", lambda _e: finish())
        values["school"].focus_set()

    def show_login(self) -> None:
        self.session = None
        self._records_cache.clear()
        self._clear_root()
        split = tk.Frame(self.root, bg=COLORS["bg"])
        split.pack(fill="both", expand=True)
        brand = tk.Frame(split, bg=COLORS["navy"], width=430)
        brand.pack(side="left", fill="y")
        brand.pack_propagate(False)
        tk.Label(brand, text="TVS", bg=COLORS["navy"], fg="white", font=("Segoe UI", 42, "bold")).pack(anchor="w", padx=55, pady=(155, 0))
        tk.Label(brand, text="Activity Desk", bg=COLORS["navy"], fg="#DCE9F7", font=("Segoe UI", 23)).pack(anchor="w", padx=58)
        tk.Label(brand, text="Secure • Offline • Local", bg=COLORS["navy"], fg="#AFC7DF", font=("Segoe UI", 10)).pack(anchor="w", padx=59, pady=(18, 0))

        area = tk.Frame(split, bg=COLORS["bg"])
        area.pack(side="left", fill="both", expand=True)
        card = tk.Frame(area, bg=COLORS["surface"], padx=48, pady=42, highlightthickness=1, highlightbackground=COLORS["border"])
        card.place(relx=.5, rely=.5, anchor="center", width=470)
        tk.Label(card, text="Sign in", bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI", 24, "bold")).pack(anchor="w")
        tk.Label(card, text=self.db.school_name(), bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 10)).pack(anchor="w", pady=(4, 25))
        tk.Label(card, text="Username", bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 6))
        username = tk.Entry(card, font=("Segoe UI", 11), bg="white", fg=COLORS["text"], insertbackground=COLORS["text"], relief="solid", borderwidth=1, highlightthickness=1, highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"])
        username.pack(fill="x", ipady=5)
        tk.Label(card, text="Password", bg=COLORS["surface"], fg=COLORS["text"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(16, 6))
        password = tk.Entry(card, show="•", font=("Segoe UI", 11), bg="white", fg=COLORS["text"], insertbackground=COLORS["text"], relief="solid", borderwidth=1, highlightthickness=1, highlightbackground=COLORS["border"], highlightcolor=COLORS["accent"])
        password.pack(fill="x", ipady=5)

        def login() -> None:
            try:
                self.session = self.db.authenticate(username.get(), password.get())
            except Exception as exc:
                password.delete(0, "end")
                messagebox.showerror("Sign in failed", str(exc))
                return
            self.show_shell()

        self._primary_button(card, "Sign in", login).pack(fill="x", pady=(24, 0))
        tk.Label(card, text="Data remains on this computer. Version %s" % APP_VERSION, bg=COLORS["surface"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="center", pady=(24, 0))
        username.bind("<Return>", lambda _e: password.focus_set())
        password.bind("<Return>", lambda _e: login())
        username.focus_set()

    def show_shell(self) -> None:
        if not self.session:
            return
        self._clear_root()
        shell = tk.Frame(self.root, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=COLORS["navy_dark"], width=224)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="TVS", bg=COLORS["navy_dark"], fg="white", font=("Segoe UI", 23, "bold")).pack(anchor="w", padx=22, pady=(24, 0))
        tk.Label(sidebar, text="ACTIVITY DESK", bg=COLORS["navy_dark"], fg="#AFC7DF", font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=23, pady=(0, 28))

        nav = ttk.Frame(sidebar, style="Card.TFrame")
        nav.configure(style="NavArea.TFrame")
        nav.pack(fill="x")
        ttk.Style().configure("NavArea.TFrame", background=COLORS["navy_dark"])
        for label, command in (
            ("Dashboard", self.show_dashboard),
            ("Records", self.show_records),
            ("Reports & exports", self.show_reports),
        ):
            ttk.Button(nav, text=label, style="Nav.TButton", command=command).pack(fill="x")
        if self.session.role == "administrator":
            ttk.Button(nav, text="Users", style="Nav.TButton", command=self.show_users).pack(fill="x")
            ttk.Button(nav, text="Form controls", style="Nav.TButton", command=self.show_form_controls).pack(fill="x")
            ttk.Button(nav, text="Audit log", style="Nav.TButton", command=self.show_audit).pack(fill="x")
        ttk.Button(nav, text="Backup", style="Nav.TButton", command=self.show_backup).pack(fill="x")

        user = tk.Frame(sidebar, bg=COLORS["navy_dark"])
        user.pack(side="bottom", fill="x", padx=20, pady=20)
        tk.Label(user, text=self.session.display_name, bg=COLORS["navy_dark"], fg="white", font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
        tk.Label(user, text=ROLE_LABELS.get(self.session.role, self.session.role), bg=COLORS["navy_dark"], fg="#AFC7DF", font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(2, 9))
        ttk.Button(user, text="Lock / sign out", style="Nav.TButton", command=self.show_login).pack(fill="x")

        workspace = ttk.Frame(shell, style="Page.TFrame")
        workspace.pack(side="left", fill="both", expand=True)
        top = ttk.Frame(workspace, style="Card.TFrame", padding=(28, 17))
        top.pack(fill="x")
        self.page_title = ttk.Label(top, text="", style="Card.TLabel", font=("Segoe UI", 15, "bold"), foreground=COLORS["navy"])
        self.page_title.pack(side="left")
        ttk.Label(top, text=self.db.school_name(), style="Card.TLabel", foreground=COLORS["muted"]).pack(side="right")
        self.content = ttk.Frame(workspace, style="Page.TFrame", padding=(28, 24))
        self.content.pack(fill="both", expand=True)
        self.show_dashboard()

    def _page(self, title: str) -> ttk.Frame:
        assert self.content is not None
        for child in self.content.winfo_children():
            child.destroy()
        if self.page_title:
            self.page_title.configure(text=title)
        return self.content

    def _available_modules(self, include_disabled: bool = False) -> List[Module]:
        assert self.session is not None
        modules = modules_for_role(self.session.role)
        if include_disabled:
            return modules
        return [module for module in modules if self.db.module_is_enabled(module.key)]

    def show_dashboard(self) -> None:
        if not self.session:
            return
        page = self._page("Dashboard")
        counts = self.db.dashboard_counts(self.session)
        stats = ttk.Frame(page, style="Page.TFrame")
        stats.pack(fill="x")
        for col, (label, value, color) in enumerate((
            ("Total records", counts["total"], COLORS["navy"]),
            ("Submitted", counts["submitted"], COLORS["success"]),
            ("Drafts", counts["draft"], COLORS["warning"]),
        )):
            stats.columnconfigure(col, weight=1)
            card = ttk.Frame(stats, style="Card.TFrame", padding=(20, 15))
            card.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else 7, 0 if col == 2 else 7))
            ttk.Label(card, text=str(value), style="Card.TLabel", font=("Segoe UI", 22, "bold"), foreground=color).pack(anchor="w")
            ttk.Label(card, text=label, style="Card.TLabel", foreground=COLORS["muted"]).pack(anchor="w")

        tools = ttk.Frame(page, style="Page.TFrame")
        tools.pack(fill="x", pady=(24, 12))
        ttk.Label(tools, text="Forms", style="Title.TLabel", font=("Segoe UI", 17, "bold")).pack(side="left")
        search_var = tk.StringVar()
        search = ttk.Entry(tools, textvariable=search_var, width=30)
        search.pack(side="right")
        ttk.Label(tools, text="Search", style="Subtitle.TLabel").pack(side="right", padx=(0, 8))

        scroll = ScrollFrame(page)
        scroll.pack(fill="both", expand=True)

        def draw(*_args: Any) -> None:
            for child in scroll.body.winfo_children():
                child.destroy()
            query = search_var.get().strip().lower()
            modules = [m for m in self._available_modules() if query in m.name.lower()]
            for column in range(3):
                scroll.body.columnconfigure(column, weight=1, uniform="modules")
            for index, module in enumerate(modules):
                card = ttk.Frame(scroll.body, style="Card.TFrame", padding=(18, 16))
                card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=7, pady=7)
                ttk.Label(card, text=module.name, style="Card.TLabel", font=("Segoe UI", 11, "bold"), wraplength=210).pack(anchor="w")
                ttk.Label(card, text=ROLE_LABELS[module.role], style="Card.TLabel", foreground=COLORS["muted"], font=("Segoe UI", 8)).pack(anchor="w", pady=(4, 12))
                ttk.Button(card, text="New entry", style="Primary.TButton", command=lambda m=module: self.open_form(m)).pack(anchor="w")
            if not modules:
                ttk.Label(scroll.body, text="No forms match your search.", style="Subtitle.TLabel").pack(pady=40)

        search_var.trace_add("write", draw)
        draw()

    def open_form(self, module: Module, record: Optional[Dict[str, Any]] = None) -> None:
        assert self.session is not None

        def save(status: str, values: Dict[str, Any], record_id: Optional[str]) -> None:
            self.db.save_record(self.session, module.key, module.name, module.role, status, values, record_id)
            messagebox.showinfo("Saved", "%s was saved as %s." % (module.name, "a draft" if status == "draft" else "submitted"), parent=self.root)
            self.show_records()

        FormDialog(self.root, module, save, record)

    def show_records(self) -> None:
        assert self.session is not None
        page = self._page("Records")
        filters = ttk.Frame(page, style="Card.TFrame", padding=(16, 13))
        filters.pack(fill="x", pady=(0, 16))
        search_var = tk.StringVar()
        status_var = tk.StringVar(value="All statuses")
        ttk.Label(filters, text="Search", style="FieldLabel.TLabel").pack(side="left")
        ttk.Entry(filters, textvariable=search_var, width=28).pack(side="left", padx=(8, 18))
        ttk.Combobox(filters, textvariable=status_var, values=("All statuses", "Submitted", "Draft"), state="readonly", width=16).pack(side="left")
        ttk.Button(filters, text="Refresh", style="Secondary.TButton", command=lambda: load()).pack(side="right")

        table_frame = ttk.Frame(page, style="Card.TFrame")
        table_frame.pack(fill="both", expand=True)
        columns = ("date", "module", "status", "owner", "updated")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (("date", "Activity date", 110), ("module", "Form", 240), ("status", "Status", 90), ("owner", "Entered by", 150), ("updated", "Last updated", 160)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        actions = ttk.Frame(page, style="Page.TFrame")
        actions.pack(fill="x", pady=(14, 0))

        def selected_record() -> Optional[Dict[str, Any]]:
            selection = tree.selection()
            return self._records_cache.get(selection[0]) if selection else None

        def edit() -> None:
            record = selected_record()
            if not record:
                messagebox.showinfo("Edit record", "Select a record first.")
                return
            module = MODULES.get(record["module_key"])
            if not module:
                messagebox.showerror("Edit record", "The form definition is unavailable.")
                return
            self.open_form(module, record)

        ttk.Button(actions, text="Edit selected", style="Primary.TButton", command=edit).pack(side="right")

        def load(*_args: Any) -> None:
            status = status_var.get().lower()
            status = "" if status.startswith("all") else status
            records = self.db.list_records(self.session, status=status, search=search_var.get().strip(), include_all=True)
            self._records_cache = {record["id"]: record for record in records}
            tree.delete(*tree.get_children())
            for record in records:
                tree.insert("", "end", iid=record["id"], values=(
                    record.get("event_date", ""), record["module_name"], record["status"].title(),
                    record["owner_name"], record["updated_at"].replace("T", " "),
                ))

        search_var.trace_add("write", load)
        status_var.trace_add("write", load)
        tree.bind("<Double-1>", lambda _e: edit())
        load()

    def show_reports(self) -> None:
        assert self.session is not None
        page = self._page("Reports & exports")
        intro = ttk.Frame(page, style="Card.TFrame", padding=(24, 20))
        intro.pack(fill="x")
        ttk.Label(intro, text="Export activity records", style="Card.TLabel", font=("Segoe UI", 16, "bold"), foreground=COLORS["navy"]).pack(anchor="w")
        ttk.Label(intro, text="Choose a form and status, then save a spreadsheet or standards-compatible CSV file.", style="Card.TLabel", foreground=COLORS["muted"]).pack(anchor="w", pady=(5, 0))

        form = ttk.Frame(page, style="Card.TFrame", padding=(24, 22))
        form.pack(fill="x", pady=18)
        modules = self._available_modules(include_disabled=True)
        labels = ["All forms"] + [module.name for module in modules]
        module_by_name = {module.name: module.key for module in modules}
        module_var = tk.StringVar(value="All forms")
        status_var = tk.StringVar(value="All statuses")
        ttk.Label(form, text="Form", style="FieldLabel.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Combobox(form, textvariable=module_var, values=labels, state="readonly", width=38).grid(row=1, column=0, sticky="ew", pady=(5, 16), padx=(0, 12))
        ttk.Label(form, text="Status", style="FieldLabel.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Combobox(form, textvariable=status_var, values=("All statuses", "Submitted", "Draft"), state="readonly", width=20).grid(row=1, column=1, sticky="ew", pady=(5, 16))
        form.columnconfigure(0, weight=2)
        form.columnconfigure(1, weight=1)
        count_label = ttk.Label(form, text="", style="Card.TLabel", foreground=COLORS["muted"])
        count_label.grid(row=2, column=0, sticky="w")

        def records() -> List[Dict[str, Any]]:
            status = status_var.get().lower()
            status = "" if status.startswith("all") else status
            return self.db.list_records(self.session, module_key=module_by_name.get(module_var.get(), ""), status=status, include_all=True)

        def update_count(*_args: Any) -> None:
            count_label.configure(text="%d record(s) match these filters" % len(records()))

        def export(kind: str) -> None:
            selected = records()
            if not selected:
                messagebox.showinfo("Export", "There are no records matching these filters.")
                return
            stamp = datetime.now().strftime("%Y-%m-%d")
            extension = ".xlsx" if kind == "xlsx" else ".csv"
            path = filedialog.asksaveasfilename(title="Export records", defaultextension=extension, initialfile="TVS-activity-records-%s%s" % (stamp, extension), filetypes=[("Excel workbook", "*.xlsx")] if kind == "xlsx" else [("CSV file", "*.csv")])
            if not path:
                return
            try:
                export_xlsx(selected, Path(path)) if kind == "xlsx" else export_csv(selected, Path(path))
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc))
                return
            messagebox.showinfo("Export complete", "%d records exported to:\n%s" % (len(selected), path))

        buttons = ttk.Frame(form, style="Card.TFrame")
        buttons.grid(row=2, column=1, sticky="e")
        ttk.Button(buttons, text="Export CSV", style="Secondary.TButton", command=lambda: export("csv")).pack(side="left")
        ttk.Button(buttons, text="Export XLSX", style="Primary.TButton", command=lambda: export("xlsx")).pack(side="left", padx=(9, 0))
        module_var.trace_add("write", update_count)
        status_var.trace_add("write", update_count)
        update_count()

    def show_users(self) -> None:
        assert self.session is not None
        page = self._page("Users")
        toolbar = ttk.Frame(page, style="Page.TFrame")
        toolbar.pack(fill="x", pady=(0, 14))
        ttk.Label(toolbar, text="Local role-based accounts", style="Subtitle.TLabel").pack(side="left")
        ttk.Button(toolbar, text="Add user", style="Primary.TButton", command=lambda: add_user()).pack(side="right")
        columns = ("username", "name", "role", "status")
        tree = ttk.Treeview(page, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (("username", "Username", 150), ("name", "Display name", 220), ("role", "Role", 200), ("status", "Status", 100)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        def refresh() -> None:
            tree.delete(*tree.get_children())
            for user in self.db.list_users(self.session):
                tree.insert("", "end", iid=str(user["id"]), values=(user["username"], user["display_name"], ROLE_LABELS.get(user["role"], user["role"]), "Active" if user["active"] else "Inactive"))

        def selected_id() -> Optional[int]:
            selected = tree.selection()
            return int(selected[0]) if selected else None

        def add_user() -> None:
            dialog = tk.Toplevel(self.root)
            dialog.title("Add user")
            dialog.geometry("470x510")
            dialog.transient(self.root)
            dialog.grab_set()
            card = ttk.Frame(dialog, style="Card.TFrame", padding=(30, 25))
            card.pack(fill="both", expand=True)
            entries: Dict[str, ttk.Entry] = {}
            for key, label, secret in (("username", "Username", False), ("name", "Display name", False), ("password", "Temporary password", True), ("confirm", "Confirm password", True)):
                ttk.Label(card, text=label, style="FieldLabel.TLabel").pack(anchor="w", pady=(9, 4))
                entry = ttk.Entry(card, show="•" if secret else "")
                entry.pack(fill="x")
                entries[key] = entry
            ttk.Label(card, text="Role", style="FieldLabel.TLabel").pack(anchor="w", pady=(9, 4))
            role_var = tk.StringVar(value="Class Teacher")
            roles = [ROLE_LABELS[key] for key in ROLE_LABELS if key != "administrator"]
            ttk.Combobox(card, textvariable=role_var, values=roles, state="readonly").pack(fill="x")
            ttk.Label(card, text="The user can change records assigned to this local account. Passwords require 10+ characters, mixed case and a number.", style="Hint.TLabel", wraplength=390).pack(anchor="w", pady=(12, 16))

            def create() -> None:
                if entries["password"].get() != entries["confirm"].get():
                    messagebox.showerror("Add user", "The passwords do not match.", parent=dialog)
                    return
                role = next(key for key, label in ROLE_LABELS.items() if label == role_var.get())
                try:
                    self.db.create_user(self.session, entries["username"].get(), entries["name"].get(), role, entries["password"].get())
                except Exception as exc:
                    messagebox.showerror("Add user", str(exc), parent=dialog)
                    return
                dialog.destroy()
                refresh()

            ttk.Button(card, text="Create user", style="Primary.TButton", command=create).pack(fill="x")

        def reset_password() -> None:
            user_id = selected_id()
            if not user_id:
                messagebox.showinfo("Password reset", "Select a user first.")
                return
            dialog = tk.Toplevel(self.root)
            dialog.title("Reset password")
            dialog.geometry("420x280")
            dialog.transient(self.root)
            dialog.grab_set()
            frame = ttk.Frame(dialog, style="Card.TFrame", padding=28)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text="New password", style="FieldLabel.TLabel").pack(anchor="w")
            first = ttk.Entry(frame, show="•")
            first.pack(fill="x", pady=(5, 12))
            ttk.Label(frame, text="Confirm password", style="FieldLabel.TLabel").pack(anchor="w")
            second = ttk.Entry(frame, show="•")
            second.pack(fill="x", pady=(5, 18))

            def save() -> None:
                if first.get() != second.get():
                    messagebox.showerror("Password reset", "The passwords do not match.", parent=dialog)
                    return
                try:
                    self.db.reset_password(self.session, user_id, first.get())
                except Exception as exc:
                    messagebox.showerror("Password reset", str(exc), parent=dialog)
                    return
                dialog.destroy()
                messagebox.showinfo("Password reset", "The password was updated.")

            ttk.Button(frame, text="Update password", style="Primary.TButton", command=save).pack(fill="x")

        def toggle_active() -> None:
            user_id = selected_id()
            if not user_id:
                messagebox.showinfo("User status", "Select a user first.")
                return
            values = tree.item(str(user_id), "values")
            make_active = values[3] != "Active"
            try:
                self.db.set_user_active(self.session, user_id, make_active)
            except Exception as exc:
                messagebox.showerror("User status", str(exc))
                return
            refresh()

        actions = ttk.Frame(page, style="Page.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Reset password", style="Secondary.TButton", command=reset_password).pack(side="right")
        ttk.Button(actions, text="Activate / deactivate", style="Secondary.TButton", command=toggle_active).pack(side="right", padx=9)
        refresh()

    def show_audit(self) -> None:
        page = self._page("Audit log")
        columns = ("time", "user", "action", "target")
        tree = ttk.Treeview(page, columns=columns, show="headings")
        for key, label, width in (("time", "Date and time", 170), ("user", "User", 160), ("action", "Action", 160), ("target", "Target", 340)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)
        assert self.session is not None
        for row in self.db.recent_audit(self.session):
            tree.insert("", "end", values=(row["created_at"].replace("T", " "), row["user_name"], row["action"].replace("_", " ").title(), row["target"]))

    def show_form_controls(self) -> None:
        assert self.session is not None
        page = self._page("Form controls")
        top = ttk.Frame(page, style="Page.TFrame")
        top.pack(fill="x", pady=(0, 14))
        ttk.Label(top, text="Disabled forms are hidden from operational users; existing records remain available for reports.", style="Subtitle.TLabel").pack(side="left")
        columns = ("form", "role", "status")
        tree = ttk.Treeview(page, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (("form", "Form", 300), ("role", "Role", 220), ("status", "Availability", 120)):
            tree.heading(key, text=label)
            tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        def refresh() -> None:
            tree.delete(*tree.get_children())
            for module in modules_for_role("administrator"):
                enabled = self.db.module_is_enabled(module.key)
                tree.insert("", "end", iid=module.key, values=(module.name, ROLE_LABELS[module.role], "Enabled" if enabled else "Disabled"))

        def toggle() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo("Form controls", "Select a form first.")
                return
            module_key = selected[0]
            self.db.set_module_enabled(self.session, module_key, not self.db.module_is_enabled(module_key))
            refresh()

        actions = ttk.Frame(page, style="Page.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="Enable / disable selected", style="Primary.TButton", command=toggle).pack(side="right")
        tree.bind("<Double-1>", lambda _e: toggle())
        refresh()

    def show_backup(self) -> None:
        assert self.session is not None
        page = self._page("Backup")
        card = ttk.Frame(page, style="Card.TFrame", padding=(28, 26))
        card.pack(fill="x")
        ttk.Label(card, text="Create an encrypted local backup", style="Card.TLabel", font=("Segoe UI", 16, "bold"), foreground=COLORS["navy"]).pack(anchor="w")
        ttk.Label(card, text="The backup includes accounts, audit history and encrypted form content. Store it on a separate drive. User passwords are still required to unlock it.", style="Card.TLabel", foreground=COLORS["muted"], wraplength=700).pack(anchor="w", pady=(7, 20))

        def backup() -> None:
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M")
            path = filedialog.asksaveasfilename(title="Save backup", defaultextension=".tvsbackup", initialfile="TVS-Activity-Desk-%s.tvsbackup" % stamp, filetypes=[("TVS backup", "*.tvsbackup")])
            if not path:
                return
            try:
                self.db.backup_to(self.session, Path(path))
            except Exception as exc:
                messagebox.showerror("Backup failed", str(exc))
                return
            messagebox.showinfo("Backup complete", "Backup saved to:\n%s" % path)

        ttk.Button(card, text="Create backup", style="Primary.TButton", command=backup).pack(anchor="w")
        ttk.Label(card, text="Local data folder: %s" % data_dir(), style="Hint.TLabel").pack(anchor="w", pady=(20, 0))

    def _close(self) -> None:
        try:
            self.db.close()
        finally:
            self.root.destroy()
