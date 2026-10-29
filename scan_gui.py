"""Simple desktop GUI for the scan post-processing pipeline.

Run:  .venv\\Scripts\\python scan_gui.py
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from artec_post.pipeline import Result, Settings

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))


def cli_command():
    """Command that runs the processing CLI (bundled exe or the script in the venv)."""
    if FROZEN:
        return [os.path.join(HERE, "3DScanPostProcessorCLI.exe")]
    return [sys.executable, "-u", os.path.join(HERE, "process_scan.py")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("3D Scan Post-Processor  -  scan to watertight STL solid")
        self.geometry("900x640")
        self.q = queue.Queue()
        self.result = None
        d = Settings()

        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)

        self.in_var = tk.StringVar()
        self.out_var = tk.StringVar()
        ttk.Label(frm, text="Input scan (PLY)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.in_var).grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(frm, text="Browse...", command=self.pick_in).grid(row=0, column=2)
        ttk.Label(frm, text="Output STL").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.out_var).grid(row=1, column=1, sticky="ew", padx=5)
        ttk.Button(frm, text="Browse...", command=self.pick_out).grid(row=1, column=2)

        opt = ttk.LabelFrame(frm, text="Settings", padding=8)
        opt.grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)
        self.vars = {}

        def num(r, c, key, label, val):
            ttk.Label(opt, text=label).grid(row=r, column=c, sticky="w", padx=(0, 4))
            var = tk.StringVar(value=str(val))
            ttk.Entry(opt, textvariable=var, width=12).grid(row=r, column=c + 1, sticky="w", padx=(0, 20))
            self.vars[key] = var

        def chk(r, c, key, label, val):
            var = tk.BooleanVar(value=val)
            ttk.Checkbutton(opt, text=label, variable=var).grid(row=r, column=c, columnspan=2, sticky="w")
            self.vars[key] = var

        num(0, 0, "target_faces", "Target triangles", d.target_faces)
        num(0, 2, "min_component_frac", "Debris threshold (fraction)", d.min_component_frac)
        num(0, 4, "max_hole_perimeter_mm", "Max hole perimeter (mm)", "inf")
        num(1, 0, "cut_offset_mm", "Base cut height (mm)", d.cut_offset_mm)
        num(1, 2, "plane_threshold_mm", "Base plane tolerance (mm)", d.plane_threshold_mm)
        chk(2, 0, "remove_base", "Remove scanning base + flat bottom", d.remove_base)
        chk(2, 2, "snap_bottom_to_plane", "Flat bottom on base plane", d.snap_bottom_to_plane)
        chk(2, 4, "keep_largest_only", "Keep largest piece only", d.keep_largest_only)
        chk(3, 0, "align_to_base", "Align output (bottom on Z=0, +Z up)", d.align_to_base)
        chk(3, 2, "screenshots", "Save screenshots", d.screenshots)
        chk(3, 4, "save_intermediate_ply", "Save full-res filled PLY", d.save_intermediate_ply)

        btns = ttk.Frame(frm)
        btns.grid(row=3, column=0, columnspan=3, sticky="w")
        self.run_btn = ttk.Button(btns, text="Process", command=self.run)
        self.run_btn.pack(side="left")
        self.view_btn = ttk.Button(btns, text="View result in 3D", command=self.view, state="disabled")
        self.view_btn.pack(side="left", padx=6)
        self.folder_btn = ttk.Button(btns, text="Open output folder", command=self.open_folder, state="disabled")
        self.folder_btn.pack(side="left")
        self.prog = ttk.Progressbar(btns, mode="indeterminate", length=200)
        self.prog.pack(side="left", padx=12)

        self.log = tk.Text(frm, height=20, font=("Consolas", 9))
        self.log.grid(row=4, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
        frm.rowconfigure(4, weight=1)
        self.after(100, self.poll)

    def pick_in(self):
        p = filedialog.askopenfilename(filetypes=[("Scans", "*.ply *.stl *.obj"), ("All", "*.*")])
        if p:
            self.in_var.set(p)
            if not self.out_var.get():
                self.out_var.set(os.path.join(os.path.dirname(p), "output",
                                              os.path.splitext(os.path.basename(p))[0] + ".stl"))

    def pick_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".stl", filetypes=[("STL", "*.stl")])
        if p:
            self.out_var.set(p)

    def settings(self):
        kw = {}
        for k, var in self.vars.items():
            val = var.get()
            if isinstance(var, tk.BooleanVar):
                kw[k] = bool(val)
            elif k == "target_faces":
                kw[k] = int(float(val))
            else:
                kw[k] = float(val)
        return Settings(**kw)

    def run(self):
        src, dst = self.in_var.get(), self.out_var.get()
        if not os.path.isfile(src):
            messagebox.showerror("Input", "Choose an input scan file.")
            return
        if not dst:
            messagebox.showerror("Output", "Choose an output STL path.")
            return
        try:
            s = self.settings()
        except ValueError as exc:
            messagebox.showerror("Settings", f"Invalid number: {exc}")
            return
        self.log.delete("1.0", "end")
        self.run_btn.config(state="disabled")
        self.prog.start(15)

        # run the CLI in a child process: keeps the GUI responsive, frees memory afterwards,
        # and lets Open3D render screenshots on that process's main thread
        args = cli_command() + [src, "-o", dst,
                "--faces", str(s.target_faces), "--min-component", str(s.min_component_frac),
                "--max-hole", str(s.max_hole_perimeter_mm), "--cut-offset", str(s.cut_offset_mm),
                "--plane-threshold", str(s.plane_threshold_mm)]
        for flag, on in (("--no-base-removal", not s.remove_base), ("--no-snap", not s.snap_bottom_to_plane),
                         ("--keep-all-components", not s.keep_largest_only),
                         ("--keep-coords", not s.align_to_base), ("--no-screenshots", not s.screenshots),
                         ("--save-intermediate", s.save_intermediate_ply)):
            if on:
                args.append(flag)

        def work():
            try:
                p = subprocess.Popen(args, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in p.stdout:
                    self.q.put(("log", line.rstrip()))
                p.wait()
                rep_path = os.path.join(os.path.dirname(os.path.abspath(dst)),
                                        os.path.splitext(os.path.basename(dst))[0] + "_report.json")
                if p.returncode in (0, 2) and os.path.isfile(rep_path):
                    with open(rep_path) as fh:
                        self.q.put(("done", Result(dst, json.load(fh))))
                else:
                    self.q.put(("error", RuntimeError(f"processing failed (exit code {p.returncode})")))
            except Exception as exc:  # report any failure in the GUI
                self.q.put(("error", exc))

        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", payload + "\n")
                    self.log.see("end")
                else:
                    self.prog.stop()
                    self.run_btn.config(state="normal")
                    if kind == "done":
                        self.result = payload
                        self.view_btn.config(state="normal")
                        self.folder_btn.config(state="normal")
                        r = payload.report
                        ok = r["watertight"] and r["nonmanifold_edges"] == 0
                        msg = (f"{'Watertight solid' if ok else 'WARNING: not fully watertight'}\n"
                               f"{r['faces']:,} triangles, volume {r['volume_mm3'] or 0:,.0f} mm3\n{payload.stl_path}")
                        messagebox.showinfo("Finished", msg)
                    else:
                        messagebox.showerror("Failed", str(payload))
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def view(self):
        if self.result:
            # separate process so the Open3D window does not block the GUI
            subprocess.Popen(cli_command() + ["--view", self.result.stl_path], cwd=HERE,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def open_folder(self):
        if self.result:
            os.startfile(os.path.dirname(os.path.abspath(self.result.stl_path)))


if __name__ == "__main__":
    App().mainloop()
