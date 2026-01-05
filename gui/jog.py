import flet
import threading
import time
import math
import numpy as np
from scipy.spatial.transform import Rotation as R

# Import KinematicsEngine from cartesian module
try:
    from gui.cartesian import KinematicsEngine
except ImportError:
    KinematicsEngine = None

class JogView(flet.Container):
    """
    JOG View - Uses URDF-based kinematics (same as CartesianView)
    """

    def __init__(self, uart_communicator, on_status_update=None, on_error=None):
        super().__init__()
        
        self.uart = uart_communicator
        self.on_status_update = on_status_update
        self.on_error = on_error  # Callback do wysyłania błędów 
        
        # Initialize URDF-based kinematics engine
        if KinematicsEngine:
            self.ik = KinematicsEngine("resources/PAROL6.urdf")
        else:
            self.ik = None
        
        # --- ZMIENNE STANU ---
        self.is_jogging = False
        self.active_jog_btn = None
        self.speed_percent = 50 
        self.is_robot_homed = False 
        
        self.homing_loading_dialog = None

        self.gripper_states = {"pneumatic": False, "electric": False}
        self.current_raw_values = { f"J{i}": 0.0 for i in range(1, 7) }
        
        # Wewnętrzne cele (to co chcemy osiągnąć)
        self.internal_target_values = { f"J{i}": 0.0 for i in range(1, 7) }
        self.initial_sync_done = False

        # Limity
        self.joint_limits = {
            "J1": (-90, 90), "J2": (-50, 140), "J3": (-100, 70),
            "J4": (-100, 180), "J5": (-120, 110), "J6": (-110, 180) 
        }

        self.padding = 10 
        self.motors_list = ["Motor 1 (J1)", "Motor 2 (J2)", "Motor 3 (J3)", "Motor 4 (J4)", "Motor 5 (J5)", "Motor 6 (J6)"]
        self.grippers_list = ["Electric Gripper", "Pneumatic Gripper"]
        self._setup_ui()

    def _setup_ui(self):
        panel_style = {"bgcolor": "#2D2D2D", "border_radius": 10, "border": flet.border.all(1, "#555555"), "padding": 10}

        motors_column = flet.Column(spacing=5, expand=True)
        for i in range(0, len(self.motors_list), 2):
            if i+1 < len(self.motors_list):
                panel1 = self._create_joint_control(self.motors_list[i])
                panel2 = self._create_joint_control(self.motors_list[i+1])
                motors_column.controls.append(flet.Row(controls=[panel1, panel2], spacing=5, expand=True))

        gripper_row = flet.Row(spacing=5, expand=True)
        for g_name in self.grippers_list:
            gripper_row.controls.append(self._create_joint_control(g_name))
        motors_column.controls.append(gripper_row)
        motors_container = flet.Container(content=motors_column, expand=20)
        
        self.lbl_speed = flet.Text(f"{self.speed_percent}%", size=18, weight="bold", color="cyan", text_align="center")
        speed_panel = flet.Container(
            content=flet.Column([
                flet.Text("VELOCITY", color="white", weight="bold", size=12),
                flet.Row([
                    flet.IconButton(flet.icons.REMOVE, icon_color="white", bgcolor="#444", icon_size=18, on_click=lambda e: self.change_speed(-10), width=35, height=35),
                    flet.Container(content=self.lbl_speed, alignment=flet.alignment.center, width=60, bgcolor="#222", border_radius=5, height=35),
                    flet.IconButton(flet.icons.ADD, icon_color="white", bgcolor="#444", icon_size=18, on_click=lambda e: self.change_speed(10), width=35, height=35)
                ], alignment=flet.MainAxisAlignment.CENTER, spacing=5)
            ], horizontal_alignment="center", spacing=2, alignment=flet.MainAxisAlignment.CENTER),
            bgcolor="#2D2D2D", border_radius=10, border=flet.border.all(1, "#555555"), padding=5, height=80
        )

        TOOL_BTN_H = 40 
        tools_column = flet.Column([
            speed_panel, flet.Container(height=5),
            flet.ElevatedButton("HOME", icon=flet.icons.HOME, style=flet.ButtonStyle(bgcolor=flet.colors.BLUE_GREY_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_home_click, expand=True, width=10000),
            flet.ElevatedButton("SAFETY", icon=flet.icons.SHIELD, style=flet.ButtonStyle(bgcolor=flet.colors.TEAL_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_safety_click, expand=True, width=10000),
            flet.ElevatedButton("GRIPPER CHANGE", icon=flet.icons.HANDYMAN, style=flet.ButtonStyle(bgcolor=flet.colors.PURPLE_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_change_tool_click, expand=True, width=10000),
            flet.ElevatedButton("STOP", icon=flet.icons.STOP_CIRCLE, style=flet.ButtonStyle(bgcolor=flet.colors.RED_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_stop_click, expand=True, width=10000),
            flet.ElevatedButton("STANDBY", icon=flet.icons.ACCESSIBILITY, style=flet.ButtonStyle(bgcolor=flet.colors.ORANGE_900, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_standby_click, expand=True, width=10000),
            # Spacer removed to allow buttons to fill space
            # ERROR RESET moved to Errors tab
        ], spacing=5, expand=True)
        tools_container = flet.Container(content=tools_column, expand=5, padding=flet.padding.symmetric(horizontal=5))

        pos_list = flet.Column(spacing=5, horizontal_alignment="stretch", expand=True)
        pos_list.controls.append(flet.Text("POSITION", weight="bold", color="white", text_align="center"))
        self.position_value_labels = {} 
        for name in ["J1", "J2", "J3", "J4", "J5", "J6"]:
            lbl = flet.Text("0.00°", color="cyan", weight="bold")
            self.position_value_labels[name] = lbl
            pos_list.controls.append(flet.Row([flet.Text(f"{name}:", weight="bold"), lbl], alignment="spaceBetween", expand=True))
        
        pos_list.controls.append(flet.Divider(color="#555"))
        
        self.tcp_labels = {}
        for name in ["X", "Y", "Z", "A", "B", "C"]:
            col = "cyan" if name in ["X", "Y", "Z"] else "orange"
            unit = "mm" if name in ["X", "Y", "Z"] else "°"
            lbl = flet.Text(f"0.00 {unit}", color=col, weight="bold")
            self.tcp_labels[name] = lbl
            pos_list.controls.append(flet.Row([flet.Text(f"{name}:", weight="bold"), lbl], alignment="spaceBetween", expand=True))

        position_frame = flet.Container(content=pos_list, **panel_style, expand=4)
        self.content = flet.Row([motors_container, tools_container, position_frame], spacing=10, vertical_alignment=flet.CrossAxisAlignment.STRETCH)

    # --- LIFECYCLE METHODS ---
    def did_mount(self):
        # Force UI update when view is mounted
        try:
            self._calculate_forward_kinematics()
            self.update()
        except: pass

    # -------------------------------------------------------------------------
    # >>> NOWA FUNKCJA: WYSYŁANIE WSZYSTKICH OSI <<<
    # -------------------------------------------------------------------------
    def send_all_joints(self):
        """
        Wysyła zbiorczą ramkę: J_v1,v2,v3,v4,v5,v6
        Pobiera wartości z self.internal_target_values.
        """
        if self.uart and self.uart.is_open():
            try:
                # Pobierz wartości w kolejności J1...J6
                vals = [self.internal_target_values.get(f"J{i}", 0.0) for i in range(1, 7)]
                
                # Zbuduj string: "J_10.0,20.0,-5.0,..."
                # Używamy .2f dla precyzji
                data_str = ",".join([f"{v:.2f}" for v in vals])
                cmd = f"J_{data_str}"
                
                # Wyślij (biblioteka communication dodaje \r\n zazwyczaj, 
                # ale jeśli nie, upewnij się w communication.py)
                self.uart.send_message(cmd)
            except Exception as e:
                print(f"[JOG] Błąd wysyłania: {e}")

    def update_joints_and_fk(self, joint_values: dict):
        for k, v in joint_values.items():
            # Invert feedback to match URDF model
            corrected_val = -v
            self.current_raw_values[k] = corrected_val 
            
            # Only sync on INITIAL startup (before first jog) to avoid feedback overwriting user targets
            if not self.initial_sync_done:
                self.internal_target_values[k] = corrected_val
            
            # Display normalized value
            if k in self.position_value_labels:
                self.position_value_labels[k].value = f"{corrected_val:.2f}°"
        
        if joint_values:
            self.initial_sync_done = True
        self._calculate_forward_kinematics()
        if self.page: self.page.update()

    def _jog_thread(self, joint_code, button_type):
        STEP_INCREMENT = 0.5
        # No direction inversion needed with URDF-based kinematics
        # + button = positive direction, - button = negative direction

        while self.is_jogging:
            current_target = self.internal_target_values.get(joint_code, 0.0)
            button_dir = 1 if button_type == "plus" else -1
            delta = STEP_INCREMENT * button_dir
            new_target = current_target + delta
            
            if joint_code in self.joint_limits:
                min_limit, max_limit = self.joint_limits[joint_code]
                if new_target < min_limit: new_target = min_limit
                elif new_target > max_limit: new_target = max_limit

            self.internal_target_values[joint_code] = new_target
            
            # >>> ZMIANA: Zamiast wysyłać J1_..., wysyłamy wszystko <<<
            self.send_all_joints()
            
            # Update local UI immediately (FK + displayed angles)
            self.update_joints_and_fk(self.internal_target_values)
            
            time.sleep(0.05)

    def on_jog_start(self, e, joint_code, direction, btn):
        if not self.is_robot_homed:
            self.show_homing_required_dialog()
            return 
        if self.is_jogging: return
        self.active_jog_btn = btn
        self.is_jogging = True
        btn.content.bgcolor = "#111111"
        btn.content.border = flet.border.all(1, "cyan")
        btn.content.update()
        threading.Thread(target=self._jog_thread, args=(joint_code, direction), daemon=True).start()

    def on_jog_stop(self, e, joint_code, direction, btn):
        self.is_jogging = False
        self.active_jog_btn = None
        btn.content.bgcolor = "#444444"
        btn.content.border = flet.border.all(1, "#666")
        btn.content.update()

    def set_homed_status(self, is_homed: bool):
        print(f"[JOG] set_homed_status wywołane: {is_homed}") 
        self.is_robot_homed = is_homed
        if is_homed:
            self.internal_target_values = { f"J{i}": 0.0 for i in range(1, 7) }
            self.initial_sync_done = True 

        if self.page:
            if self.homing_loading_dialog:
                self.homing_loading_dialog.open = False
                self.page.update()
                # self.page.close(self.homing_loading_dialog)
                self.homing_loading_dialog = None
            
            msg = "Robot homed!" if is_homed else "Homing lost!"
            color = flet.colors.GREEN if is_homed else flet.colors.RED
            self.page.snack_bar = flet.SnackBar(flet.Text(msg), bgcolor=color)
            self.page.snack_bar.open = True
            self.page.update()

    def on_home_click(self, e):
        self._show_homing_choice_dialog()

    def _show_homing_choice_dialog(self):
        if not self.page: return
        
        def close_dlg(e):
            dlg.open = False
            self.page.update()

        def on_start_homing(e):
            close_dlg(e)
            if self.uart:
                print("[JOG] Start Homing")
                self.uart.send_message("HOME")
                self._show_homing_progress_dialog()

        def on_confirm_position(e):
            close_dlg(e)
            # Use GLOBAL callback to set homing for ALL views
            if hasattr(self, 'on_global_set_homed') and self.on_global_set_homed:
                self.on_global_set_homed(True)
            else:
                self.set_homed_status(True)  # Fallback
            # Log HMS warning - homing skipped
            if self.on_error:
                self.on_error("HMS")
            self.page.snack_bar = flet.SnackBar(flet.Text("Robot position manually confirmed."), bgcolor="green")
            self.page.snack_bar.open = True
            self.page.update()

        dlg = flet.AlertDialog(
            title=flet.Text("Homing Selection"),
            content=flet.Container(
                width=350,
                content=flet.Text("Do you want to start automatic homing sequence or confirm that the robot is currently in the home position?")
            ),
            actions=[
                flet.TextButton("Start Homing", on_click=on_start_homing),
                flet.TextButton("Confirm Position", on_click=on_confirm_position),
            ],
            actions_alignment=flet.MainAxisAlignment.END,
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def _show_homing_progress_dialog(self):
        if not self.page: return
        if self.homing_loading_dialog is not None: return

        self.homing_loading_dialog = flet.AlertDialog(
            title=flet.Text("HOMING..."),
            content=flet.Container(
                height=150,
                content=flet.Column([
                    flet.Row([flet.ProgressRing(width=50, height=50, stroke_width=4, color="cyan")], alignment=flet.MainAxisAlignment.CENTER),
                    flet.Container(height=20),  
                    flet.Text("Please wait...", size=12, color="grey")
                ], alignment=flet.MainAxisAlignment.CENTER, horizontal_alignment=flet.CrossAxisAlignment.CENTER)
            ),
            modal=True
        )
        self.page.dialog = self.homing_loading_dialog
        self.homing_loading_dialog.open = True
        self.page.update()

    def show_homing_required_dialog(self):
        if not self.page: return
        # Trigger E1 error
        if self.on_error:
            self.on_error("E1")
            
        def close_dlg(e):
            dlg.open = False
            self.page.update()

        dlg = flet.AlertDialog(
            modal=True,
            title=flet.Row([
                flet.Icon(flet.icons.WARNING_AMBER, color=flet.colors.AMBER_400, size=30),
                flet.Text("HOMING REQUIRED", color=flet.colors.RED_200, weight="bold")
            ], alignment=flet.MainAxisAlignment.START, spacing=10),
            content=flet.Container(
                content=flet.Text("The robot must be homed before performing any movement.\nPlease run the Homing sequence first.", size=16),
                padding=10
            ),
            actions=[
                flet.ElevatedButton("OK", on_click=close_dlg, style=flet.ButtonStyle(bgcolor=flet.colors.RED_700, color="white"))
            ],
            actions_alignment=flet.MainAxisAlignment.END,
            bgcolor="#1f1f1f",
        )
        self.page.dialog = dlg
        dlg.open = True
        self.page.update()

    def on_stop_click(self, e):
        # Trigger W1 warning
        if self.on_error:
            self.on_error("W1")
        if self.uart: self.uart.send_message("EGRIP_STOP"); self.is_jogging = False
        
    # on_reset_click removed from here as per request
        
    def on_change_tool_click(self, e):
        """Shows tool selection dialog with images."""
        if not self.page: return
        
        self.tool_change_dialog = None
        
        def close_dlg(e=None):
            if self.tool_change_dialog:
                self.tool_change_dialog.open = False
                self.page.update()
        
        def select_vacuum(e):
            if hasattr(self, 'on_global_set_tool') and self.on_global_set_tool:
                self.on_global_set_tool("CHWYTAK_MALY")
            elif self.ik: 
                self.ik.set_tool("CHWYTAK_MALY")
            if self.uart: self.uart.send_message("TOOL_VAC")
            close_dlg()
            self._calculate_forward_kinematics()
            self.page.snack_bar = flet.SnackBar(flet.Text("Active Tool: Vacuum Gripper"), bgcolor=flet.colors.GREEN)
            self.page.snack_bar.open = True
            self.page.update()
        
        def select_electric(e):
            if hasattr(self, 'on_global_set_tool') and self.on_global_set_tool:
                self.on_global_set_tool("CHWYTAK_DUZY")
            elif self.ik: 
                self.ik.set_tool("CHWYTAK_DUZY")
            if self.uart: self.uart.send_message("TOOL_EGRIP")
            close_dlg()
            self._calculate_forward_kinematics()
            self.page.snack_bar = flet.SnackBar(flet.Text("Active Tool: Electric Gripper"), bgcolor=flet.colors.GREEN)
            self.page.snack_bar.open = True
            self.page.update()
        
        # Create clickable tool panels
        panel_style = {
            "bgcolor": "#3D3D3D",
            "border_radius": 10,
            "border": flet.border.all(2, "#555555"),
            "padding": 10,
            "width": 220,
            "height": 210,
            "alignment": flet.alignment.center,
        }
        
        def make_hover_effect(container, on_click_func):
            def on_hover(e):
                if e.data == "true":
                    container.border = flet.border.all(3, flet.colors.CYAN_400)
                    container.bgcolor = "#4D4D4D"
                else:
                    container.border = flet.border.all(2, "#555555")
                    container.bgcolor = "#3D3D3D"
                container.update()
            container.on_hover = on_hover
            container.on_click = on_click_func
        
        vacuum_panel = flet.Container(
            content=flet.Column([
                flet.Image(src="Gripper1.png", height=160, fit=flet.ImageFit.CONTAIN),
                flet.Text("Vacuum Gripper", size=15, weight="bold", color="white", text_align=flet.TextAlign.CENTER)
            ], horizontal_alignment=flet.CrossAxisAlignment.CENTER, spacing=8),
            **panel_style
        )
        make_hover_effect(vacuum_panel, select_vacuum)
        
        electric_panel = flet.Container(
            content=flet.Column([
                flet.Image(src="Gripper2.png", height=160, fit=flet.ImageFit.CONTAIN),
                flet.Text("Electric Gripper", size=15, weight="bold", color="white", text_align=flet.TextAlign.CENTER)
            ], horizontal_alignment=flet.CrossAxisAlignment.CENTER, spacing=8),
            **panel_style
        )
        make_hover_effect(electric_panel, select_electric)
        
        tools_row = flet.Row([
            vacuum_panel,
            electric_panel
        ], spacing=30, alignment=flet.MainAxisAlignment.CENTER)
        
        def on_change_click(e):
            if self.uart: self.uart.send_message("TOOL_CHANGE")
            self.page.snack_bar = flet.SnackBar(flet.Text("Tool change command sent"), bgcolor=flet.colors.BLUE)
            self.page.snack_bar.open = True
            self.page.update()
        
        change_button = flet.ElevatedButton(
            "CHANGE",
            icon=flet.icons.SWAP_HORIZ,
            style=flet.ButtonStyle(
                bgcolor=flet.colors.ORANGE_700,
                color="white",
                shape=flet.RoundedRectangleBorder(radius=10)
            ),
            height=60,
            width=300,
            on_click=on_change_click
        )
        
        dialog_content = flet.Column([
            tools_row,
            flet.Container(height=40),
            flet.Container(content=change_button, alignment=flet.alignment.center)
        ], horizontal_alignment=flet.CrossAxisAlignment.CENTER, spacing=0)
        
        title_row = flet.Row([
            flet.Text("CHANGE ACTIVE TOOL", size=22, weight="bold", color="white"),
            flet.IconButton(icon=flet.icons.CLOSE, icon_size=28, on_click=close_dlg)
        ], alignment=flet.MainAxisAlignment.SPACE_BETWEEN)
        
        self.tool_change_dialog = flet.AlertDialog(
            title=title_row,
            title_padding=flet.padding.only(left=20, right=10, top=10, bottom=0),
            content=flet.Container(content=dialog_content, padding=10, width=520, height=310),
            modal=True,
            bgcolor="#2D2D2D"
        )
        
        self.page.dialog = self.tool_change_dialog
        self.tool_change_dialog.open = True
        self.page.update()
                
    def on_standby_click(self, e):
        # Target: All zeros
        target_deg = [0.0] * 6
        self._animate_move(target_deg)
                
    def on_safety_click(self, e):
        # Trigger W2 warning
        if self.on_error:
            self.on_error("W2")
        # Target: [0, 50, -70, -90, 0, 0] degrees (Harmonized with CartesianView)
        target_deg = [0, -50, 70, 90, 0, 0]
        self._animate_move(target_deg)

    def _animate_move(self, target_joints_deg):
        """Moves robot to target joints smoothly using current velocity."""
        if self.is_jogging: return
        self.is_jogging = True
        
        def run():
            # Standard movement speed: 90 deg/s at 100% velocity
            # Loop runs at 20Hz (0.05s), so max step is 4.5 deg
            while self.is_jogging:
                current = np.array([self.internal_target_values[f"J{i}"] for i in range(1, 7)])
                target = np.array(target_joints_deg)
                diff = target - current
                dist = np.linalg.norm(diff)
                
                if dist < 0.1:
                    for i, val in enumerate(target_joints_deg):
                        self.internal_target_values[f"J{i+1}"] = val
                    self.send_all_joints()
                    self.update_joints_and_fk(self.internal_target_values)
                    break
                
                factor = self.speed_percent / 100.0
                step_size = min(dist, 4.5 * factor)
                
                new_pos = current + (diff / dist) * step_size
                for i, val in enumerate(new_pos):
                    self.internal_target_values[f"J{i+1}"] = val
                
                self.send_all_joints()
                self.update_joints_and_fk(self.internal_target_values)
                time.sleep(0.05)
            
            self.is_jogging = False
            
        threading.Thread(target=run, daemon=True).start()
    
    def change_speed(self, delta):
        self.speed_percent = max(10, min(100, self.speed_percent + delta))
        self.lbl_speed.value = f"{self.speed_percent}%"
        self.lbl_speed.update()

    def on_gripper_toggle_click(self, e):
        g_type = e.control.data 
        new_state = not self.gripper_states.get(g_type, False)
        self.gripper_states[g_type] = new_state
        cmd = "VAC_ON" if new_state else "VAC_OFF"
        if g_type == "electric": cmd = "EGRIP_CLOSE" if new_state else "EGRIP_OPEN"
        e.control.style.bgcolor = flet.colors.GREEN_600 if new_state else flet.colors.RED_600
        e.control.content.value = "ON" if new_state else "OFF"
        if g_type == "electric": e.control.content.value = "CLOSED" if new_state else "OPEN"
        e.control.update()
        if self.uart: self.uart.send_message(cmd)

    def _create_joint_control(self, display_name: str) -> flet.Container:
        container_style = {"bgcolor": "#2D2D2D", "border_radius": 8, "border": flet.border.all(1, "#555555"), "padding": 5, "expand": True}
        if "gripper" in display_name.lower():
            g_type = "electric" if "electric" in display_name.lower() else "pneumatic"
            state = self.gripper_states[g_type]
            txt = "CLOSED" if state and g_type=="electric" else ("OPEN" if g_type=="electric" else ("ON" if state else "OFF"))
            btn = flet.ElevatedButton(content=flet.Text(txt, size=14), style=flet.ButtonStyle(bgcolor=flet.colors.GREEN_600 if state else flet.colors.RED_600), on_click=self.on_gripper_toggle_click, data=g_type, height=50, expand=True)
            return flet.Container(content=flet.Column([flet.Text(display_name, size=13, color="white", text_align="center"), flet.Row([btn], expand=True)], spacing=2), **container_style)
        else:
            joint_code = "UNK"
            if "(" in display_name: joint_code = display_name.split("(")[1].split(")")[0]
            
            def mk_btn(txt, d, code):
                # Increased height (85), width fills space via max width
                c = flet.Container(
                    content=flet.Text(txt, size=30, weight="bold", color="white"),
                    bgcolor="#444444",
                    border_radius=8,
                    alignment=flet.alignment.center,
                    height=85,
                    width=10000, # FORCE EXPAND INSIDE GESTURE DETECTOR
                    shadow=flet.BoxShadow(blur_radius=2, color="black"),
                    border=flet.border.all(1, "#666")
                )
                gest = flet.GestureDetector(
                    content=c,
                    on_tap_down=lambda e: self.on_jog_start(e, code, d, gest),
                    on_tap_up=lambda e: self.on_jog_stop(e, code, d, gest),
                    on_long_press_end=lambda e: self.on_jog_stop(e, code, d, gest),
                    on_pan_start=lambda e: self.on_jog_start(e, code, d, gest),
                    on_pan_update=lambda e: None,
                    on_pan_end=lambda e: self.on_jog_stop(e, code, d, gest)
                )
                return flet.Container(content=gest, expand=True) # EXPAND KEY

            # Layout: [-]  [J1]  [+]
            return flet.Container(
                content=flet.Row(
                    controls=[
                        mk_btn("-", "minus", joint_code),
                        flet.Container(
                            content=flet.Text(joint_code, size=24, weight="bold", color="cyan", text_align="center"),
                            alignment=flet.alignment.center,
                            width=60,      # Reduced width for label
                            expand=False   # Do not expand label
                        ),
                        mk_btn("+", "plus", joint_code)
                    ],
                    alignment=flet.MainAxisAlignment.CENTER,
                    spacing=5
                ),
                **container_style
            )

    def _calculate_forward_kinematics(self):
        """
        Use URDF-based FK from KinematicsEngine (same as CartesianView).
        This ensures X,Y,Z,A,B,C values are identical in both tabs.
        """
        if not self.ik or not self.ik.chain:
            return
            
        try:
            # Convert current_raw_values (degrees) to radians for FK
            joints_rad = [np.radians(self.current_raw_values.get(f"J{i+1}", 0.0)) for i in range(6)]
            
            # Get TCP matrix from URDF-based FK
            tcp_matrix = self.ik.forward_kinematics(joints_rad)
            pos = tcp_matrix[:3, 3]  # [x, y, z] in meters
            rot = tcp_matrix[:3, :3]
            
            # Calculate Euler angles (same as CartesianView)
            euler = R.from_matrix(rot).as_euler('xyz', degrees=True)
            
            # UPDATE UI - position in mm
            if "X" in self.tcp_labels: self.tcp_labels["X"].value = f"{pos[0]*1000:.2f} mm"
            if "Y" in self.tcp_labels: self.tcp_labels["Y"].value = f"{pos[1]*1000:.2f} mm"
            if "Z" in self.tcp_labels: self.tcp_labels["Z"].value = f"{pos[2]*1000:.2f} mm"
            
            # Rotation in degrees
            if "A" in self.tcp_labels: self.tcp_labels["A"].value = f"{euler[0]:.2f}°"
            if "B" in self.tcp_labels: self.tcp_labels["B"].value = f"{euler[1]:.2f}°"
            if "C" in self.tcp_labels: self.tcp_labels["C"].value = f"{euler[2]:.2f}°"
            
        except Exception as e:
            print(f"[JOG] FK error: {e}")