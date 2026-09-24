import tkinter as tk
from tkinter import ttk, messagebox

# Import the hardware interface module
# # If you want to read Vout from the hardware, uncomment the line in calculate()
# import megaind

def get_level_height(vin, r_load, vout):
    """
    Calculate level height from Vin, R_load (R1), and Vout.
    """
    try:
        r_load = float(r_load)
        vin = float(vin)
        vout = float(vout)
        # Calculate switch resistor
        r_switch_resistor = ((vin * r_load) / vout) - r_load
        # Convert to height (mm)
        height = round(r_switch_resistor / 1000)
        height_mm = height * 5  # 5mm per level in this setup
        return height_mm, r_switch_resistor
    except Exception as e:
        messagebox.showerror("Calculation Error", str(e))
        return None, None

def get_vout(vin, r_load, height_mm):
    """
    Calculate Vout needed for a given height.
    """
    try:
        vin = float(vin)
        r_load = float(r_load)
        height_mm = float(height_mm)
        height = height_mm / 5
        r_switch_resistor = height * 1000  # reverse from mm to resistor
        vout = (vin * r_load) / (r_load + r_switch_resistor)
        return vout, r_switch_resistor
    except Exception as e:
        messagebox.showerror("Calculation Error", str(e))
        return None, None

def calculate():
    mode = mode_var.get()
    vin = entry_vin.get()
    r_load = entry_rload.get()
    if mode == "height":
        vout = entry_vout.get()

        # --- Hardware Reading Support ---
        # If you want to get the Vout directly from the machine,
        # Uncomment the next line and comment out the 'vout = entry_vout.get()' above:
        # vout = megaind.get0_10In(0,1)
        # -------------------------------

        if not vout:
            messagebox.showinfo("Tip", "Enter V_out manually or uncomment the 'vout = megaind.get0_10In(0,1)' line in the code to get live reading from the hardware.")
            return
        height_mm, r_switch_resistor = get_level_height(vin, r_load, vout)
        if height_mm is not None:
            result_var.set(
                f"Calculated Height: {height_mm} mm\n"
                f"Switch Resistor (R2): {r_switch_resistor:.2f} Ω"
            )
    else:
        height_mm = entry_height.get()
        vout, r_switch_resistor = get_vout(vin, r_load, height_mm)
        if vout is not None:
            result_var.set(
                f"Required V_out: {vout:.3f} V\n"
                f"Switch Resistor (R2): {r_switch_resistor:.2f} Ω"
            )

def update_mode():
    if mode_var.get() == "height":
        entry_vout.config(state="normal")
        entry_height.config(state="disabled")
        label_vout.config(fg="black")
        label_height.config(fg="gray")
    else:
        entry_vout.config(state="disabled")
        entry_height.config(state="normal")
        label_vout.config(fg="gray")
        label_height.config(fg="black")

# --- GUI SETUP ---
root = tk.Tk()
root.title("Level Sensor Calculator (Reed Chain)")

frame = ttk.Frame(root, padding=20)
frame.pack(fill="both", expand=True)

mode_var = tk.StringVar(value="height")
result_var = tk.StringVar()

# --- Mode Selection ---
ttk.Label(frame, text="Choose Calculation Mode:").grid(row=0, column=0, columnspan=2, sticky="w")
ttk.Radiobutton(frame, text="Calculate Height from Vin, Vout", variable=mode_var, value="height", command=update_mode).grid(row=1, column=0, sticky="w")
ttk.Radiobutton(frame, text="Calculate Vout from Height", variable=mode_var, value="vout", command=update_mode).grid(row=1, column=1, sticky="w")

# --- Inputs ---
ttk.Label(frame, text="V_in (V):").grid(row=2, column=0, sticky="e")
entry_vin = ttk.Entry(frame)
entry_vin.grid(row=2, column=1)

ttk.Label(frame, text="R_load (Ω) (R1):").grid(row=3, column=0, sticky="e")
entry_rload = ttk.Entry(frame)
entry_rload.grid(row=3, column=1)

label_vout = tk.Label(frame, text="V_out (V):")
label_vout.grid(row=4, column=0, sticky="e")
entry_vout = ttk.Entry(frame)
entry_vout.grid(row=4, column=1)

label_height = tk.Label(frame, text="Level Height (mm):")
label_height.grid(row=5, column=0, sticky="e")
entry_height = ttk.Entry(frame, state="disabled")
entry_height.grid(row=5, column=1)

# --- Calculate Button ---
ttk.Button(frame, text="Calculate", command=calculate).grid(row=6, column=0, columnspan=2, pady=10)

# --- Result Output ---
ttk.Label(frame, text="Result:").grid(row=7, column=0, sticky="nw")
result_box = ttk.Label(frame, textvariable=result_var, background="#f2f2f2", anchor="w", width=40, relief="sunken")
result_box.grid(row=7, column=1, sticky="we")

update_mode()  # Set initial state

# Show hardware note
messagebox.showinfo(
    "Hardware Reading Note",
    "If you want to use the real sensor, uncomment the 'vout = megaind.get0_10In(0,1)' line in the code (inside the calculate function)."
)

root.mainloop()
