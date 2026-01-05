import flet
import numpy as np
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from ikpy.chain import Chain
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp

# === TOOL DICTIONARY ===
# UPDATED WITH USER OFFSET: Z(-90) -> RY(-180) -> X(-100)
ROBOT_TOOLS = {
    "CHWYTAK_MALY": {
        "translation": [0.100, 0.0, -0.090],  # 100mm Forward (due to RY flip), 90mm down
        "orientation": [0.0, -180.0, 0.0]
    },
    
    "CHWYTAK_DUZY": {
        "translation": [0.0, 0.0, -0.18831],  # Z: -188.31mm
        "orientation": [0.0, -90.0, 0.0]       # Rotation around Y: -90 degrees
    }
}

# ==============================================================================
# 1. KINEMATICS ENGINE (UPDATED FROM USER REQUEST)
# ==============================================================================
class KinematicsEngine:
    def __init__(self, urdf_path, active_links_mask=None):
        self.chain = None
        self.urdf_path = urdf_path
        self.n_active_joints = 6
        self.visual_origins = {}
        self.joint_limits_rad = [(-np.pi, np.pi)] * 6
        
        self.tool_translation = np.zeros(3) 
        self.tool_rotation_matrix = np.eye(3) 
        self.current_tool = "NONE"
        
        # Zero World Offset - using pure tool calibration instead
        self.world_offset = np.array([0.0, 0.0, 0.0]) 

        try:
            print(f"[IK] Loading URDF: {urdf_path}")
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                self.chain = Chain.from_urdf_file(urdf_path)
            
            # Automatyczna maska (fallback logic matching User's code)
            mask = []
            for link in self.chain.links:
                if link.joint_type == 'fixed':
                    mask.append(False)
                else:
                    mask.append(True)
            
            self.chain.active_links_mask = mask
            self.active_links_mask = mask # Store strictly for reference if needed
            
            # === ZWIĘKSZONA PRECYZJA (ZOPTYMALIZOWANA DLA LINUX/RPI) ===
            self.chain.max_iterations = 20
            self.chain.convergence_limit = 1e-3
            
            self.joint_limits_rad = self._load_active_joint_limits()
            self.visual_origins = self._load_visual_origins(urdf_path)
            
            # Default to Small Gripper as per previous behavior/logic
            self.set_tool("CHWYTAK_MALY")
            
            print(f"[IK] Ready. Mask: {mask}")

        except Exception as e:
            print(f"[IK ERROR] {e}")
            self._setup_mock_chain()

    def set_tool(self, tool_name):
        if tool_name not in ROBOT_TOOLS:
            print(f"[IK] Unknown tool: {tool_name}")
            return

        tool_data = ROBOT_TOOLS[tool_name]
        self.tool_translation = np.array(tool_data["translation"])
        rpy = tool_data.get("orientation", [0,0,0])
        self.tool_rotation_matrix = R.from_euler('xyz', rpy, degrees=True).as_matrix()
        
        self.current_tool = tool_name
        print(f"[IK] Tool Set: {tool_name} -> Offset: {self.tool_translation}")

    # ================= KINEMATYKA =================

    def forward_kinematics(self, active_angles):
        """Returns 4x4 TCP Matrix (including tool offset)."""
        full_joints = self._active_to_full(active_angles)
        flange_matrix = self.chain.forward_kinematics(full_joints)
        
        R_flange = flange_matrix[:3, :3]
        P_flange = flange_matrix[:3, 3]
        
        # P_tcp = P_flange + (R_flange * Offset) + WorldOffset
        offset_global = R_flange @ self.tool_translation
        P_tcp = P_flange + offset_global + self.world_offset
        
        tcp_matrix = np.eye(4)
        tcp_matrix[:3, 3] = P_tcp
        tcp_matrix[:3, :3] = R_flange @ self.tool_rotation_matrix
        
        return tcp_matrix

    def inverse_kinematics(self, target_position, target_orientation, initial_guess=None):
        """
        Solves IK for a target TCP position and orientation.
        target_position: [x, y, z] of TCP
        target_orientation: 3x3 rotation matrix of TCP
        """
        if initial_guess is None: initial_guess = np.zeros(6)
        
        # Revert World Offset before solving in URDF frame
        target_raw = target_position - self.world_offset
        
        # 1. Determine Flange Orientation
        # R_tcp = R_flange * R_tool  =>  R_flange = R_tcp * inv(R_tool)
        target_rot_matrix = target_orientation 
        flange_rot_matrix = target_rot_matrix @ np.linalg.inv(self.tool_rotation_matrix)
        
        # 2. Determine Flange Position
        # P_tcp = P_flange + (R_flange * Offset)  =>  P_flange = P_tcp - (R_flange * Offset)
        offset_global = flange_rot_matrix @ self.tool_translation
        target_pos_flange = target_raw - offset_global
        
        full_guess = self._active_to_full(initial_guess)
        
        # 3. Solver IKPy
        full_sol = self.chain.inverse_kinematics(
            target_position=target_pos_flange,
            target_orientation=flange_rot_matrix, 
            orientation_mode='all', 
            initial_position=full_guess
        )
        
        return self._full_to_active(full_sol)

    # ================= HELPERS (Updated to match User's logic) =================

    def _active_to_full(self, active_joints):
        arr = np.array(active_joints, dtype=float).flatten()
        # Handle cases where input might be [0, J1, J2...] or just [J1, J2...]
        if len(arr) == 7: arr = arr[1:] 
        if len(arr) != 6: arr = np.resize(arr, 6)
        
        full = np.zeros(len(self.chain.links))
        curr = 0
        for i, act in enumerate(self.active_links_mask):
            if act and curr < 6:
                full[i] = arr[curr]
                curr += 1
        return full

    def _full_to_active(self, full_vector):
        if self.active_links_mask: return np.compress(self.active_links_mask, full_vector)
        return np.zeros(6)
    
    def _load_active_joint_limits(self):
        # Specific Parol6 limits
        deg = [
            (-90, 90),  # J1
            (-50, 140), # J2
            (-100, 70), # J3
            (-100, 180),# J4
            (-120, 110),# J5
            (-110, 180) # J6
        ]
        return [(np.deg2rad(mn), np.deg2rad(mx)) for mn, mx in deg]

    def _load_visual_origins(self, urdf_path):
        origins = {}
        try:
            tree = ET.parse(urdf_path); root = tree.getroot()
            for link in root.findall('link'):
                vis = link.find('visual')
                if vis:
                    o = vis.find('origin')
                    if o is not None:
                        xyz = [float(x) for x in o.attrib.get('xyz','0 0 0').split()]
                        rpy = [float(r) for r in o.attrib.get('rpy','0 0 0').split()]
                        origins[link.attrib.get('name')] = (xyz, rpy)
        except: pass
        return origins

    def _setup_mock_chain(self):
        self.chain = type('Mock', (object,), {
            'links': [], 
            'active_links_mask': [], 
            'forward_kinematics': lambda *a, **k: np.eye(4), 
            'inverse_kinematics': lambda *a, **k: np.zeros(8)
        })()


# ==============================================================================
# 2. CARTESIAN VIEW (MINIMALISTYCZNY)
# ==============================================================================
class CartesianView(flet.Container):
    def __init__(self, uart_communicator, urdf_path, active_links_mask=None, on_error=None):
        super().__init__()
        self.uart = uart_communicator
        # Note: New KinematicsEngine handles masks internally mostly, but we pass what we have
        self.ik = KinematicsEngine(urdf_path, active_links_mask)
        self.on_error = on_error
        
        self.is_jogging = False
        self.is_robot_homed = False 
        self.alive = True 
        
        # Pozycje (startowe zera)
        self.commanded_joints = [0.0] * 6 # Fixed to 6 for standard 6-axis
        # self.tool_offset is now handled by self.ik.tool_translation / self.ik.set_tool()
        
        # UART feedback values (for display - same as JogView)
        self.feedback_joints_deg = [0.0] * 6
        
        # Gripper states
        self.gripper_states = {"pneumatic": False, "electric": False}
        self.jog_speed_percent = 50.0
        
        self.last_jog_time = 0.0 # Debounce timer

        self.padding = 10 

        # Start update loop IMMEDIATELY
        self.update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self.update_thread.start() 

        self._setup_ui()
        


    def did_unmount(self):
        self.alive = False
        self.is_jogging = False



    def _setup_ui(self):
        # ----------------------------------------------------------------------
        # STYLES (MATCHING JOG.PY)
        # ----------------------------------------------------------------------
        panel_style = {
            "bgcolor": "#2D2D2D", 
            "border_radius": 10, 
            "border": flet.border.all(1, "#555555"), 
            "padding": 10
        }
        
        # ----------------------------------------------------------------------
        # 1. LEFT COLUMN: AXIS CONTROLS
        # ----------------------------------------------------------------------
        # Match JogView: A=Roll(X), B=Yaw(Z), C=Pitch(Y) - swapped B/C to match display
        axes_list = [
            ("X Axis", "x"), ("A (Rot X)", "rx"),
            ("Y Axis", "y"), ("B (Rot Z)", "rz"),
            ("Z Axis", "z"), ("C (Rot Y)", "ry")
        ]

        # Use Grid-like structure (Rows of 2)
        controls_column = flet.Column(spacing=5, expand=True)
        for i in range(0, len(axes_list), 2):
            if i+1 < len(axes_list):
                name1, code1 = axes_list[i]
                name2, code2 = axes_list[i+1]
                controls_column.controls.append(
                    flet.Row([
                        self._create_axis_control(name1, code1), 
                        self._create_axis_control(name2, code2)
                    ], spacing=5, expand=True)
                )

        # Grippers Row
        gripper_row = flet.Row(spacing=5, expand=True)
        gripper_row.controls.append(self._create_gripper_control("Electric Gripper"))
        gripper_row.controls.append(self._create_gripper_control("Pneumatic Gripper"))
        controls_column.controls.append(gripper_row)

        controls_container = flet.Container(content=controls_column, expand=20)

        # ----------------------------------------------------------------------
        # 2. CENTER COLUMN: TOOLS & VELOCITY (MATCHING JOG.PY)
        # ----------------------------------------------------------------------
        # Velocity Panel
        # Velocity Panel
        self.lbl_speed = flet.Text(f"{int(self.jog_speed_percent)}%", size=18, weight="bold", color="cyan", text_align="center")
        speed_panel = flet.Container(
            content=flet.Column([
                flet.Text("VELOCITY", color="white", weight="bold", size=12),
                flet.Row([
                    flet.IconButton(flet.icons.REMOVE, icon_color="white", bgcolor="#444", icon_size=18, 
                                    on_click=lambda e: self.change_speed(-10), width=35, height=35),
                    flet.Container(content=self.lbl_speed, alignment=flet.alignment.center, 
                                   width=60, bgcolor="#222", border_radius=5, height=35),
                    flet.IconButton(flet.icons.ADD, icon_color="white", bgcolor="#444", icon_size=18,
                                    on_click=lambda e: self.change_speed(10), width=35, height=35)
                ], alignment=flet.MainAxisAlignment.CENTER, spacing=5)
            ], horizontal_alignment="center", spacing=2, alignment=flet.MainAxisAlignment.CENTER),
            bgcolor="#2D2D2D", border_radius=10, border=flet.border.all(1, "#555555"), padding=5, height=80
        )

        TOOL_BTN_H = 40
        tools_column = flet.Column([
            speed_panel, 
            flet.Container(height=5),
            flet.ElevatedButton("HOME", icon=flet.icons.HOME, style=flet.ButtonStyle(bgcolor=flet.colors.BLUE_GREY_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_home_click, expand=True, width=10000),
            flet.ElevatedButton("SAFETY", icon=flet.icons.SHIELD, style=flet.ButtonStyle(bgcolor=flet.colors.TEAL_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_safety_click, expand=True, width=10000),
            flet.ElevatedButton("GRIPPER CHANGE", icon=flet.icons.HANDYMAN, style=flet.ButtonStyle(bgcolor=flet.colors.PURPLE_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_change_tool_click, expand=True, width=10000),
            flet.ElevatedButton("STOP", icon=flet.icons.STOP_CIRCLE, style=flet.ButtonStyle(bgcolor=flet.colors.RED_700, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_stop_click, expand=True, width=10000),
            flet.ElevatedButton("STANDBY", icon=flet.icons.ACCESSIBILITY, style=flet.ButtonStyle(bgcolor=flet.colors.ORANGE_900, color="white", shape=flet.RoundedRectangleBorder(radius=8)), on_click=self.on_standby_click, expand=True, width=10000),
            # Spacer removed to allow buttons to fill space
            # ERROR RESET moved to Errors tab
        ], spacing=5, expand=True)

        tools_container = flet.Container(content=tools_column, expand=5, padding=flet.padding.symmetric(horizontal=5))

        # ----------------------------------------------------------------------
        # 3. RIGHT COLUMN: POSITIONS (READOUT)
        # ----------------------------------------------------------------------
        pos_list = flet.Column(spacing=5, horizontal_alignment="stretch", expand=True)
        pos_list.controls.append(flet.Text("POSITION", weight="bold", color="white", text_align="center"))
        
        self.lbl_cart = {}
        
        # Joints
        self.lbl_joints = []
        for i in range(self.ik.n_active_joints):
            lbl = flet.Text("0.00°", color="cyan", weight="bold")
            self.lbl_joints.append(lbl)
            pos_list.controls.append(
                flet.Row([flet.Text(f"J{i+1}:", weight="bold"), lbl], alignment="spaceBetween", expand=True)
            )
            
        pos_list.controls.append(flet.Divider(color="#555"))
        
        # TCP
        for ax in ["X", "Y", "Z", "A", "B", "C"]:
            col = "cyan" if ax in ["X", "Y", "Z"] else "orange"
            unit = "mm" if ax in ["X", "Y", "Z"] else "°"
            
            lbl = flet.Text(f"0.00 {unit}", color=col, weight="bold")
            self.lbl_cart[ax] = lbl
            pos_list.controls.append(
                flet.Row([flet.Text(f"{ax}:", weight="bold"), lbl], alignment="spaceBetween", expand=True)
            )

        position_frame = flet.Container(content=pos_list, **panel_style, expand=4)

        # ----------------------------------------------------------------------
        # MAIN LAYOUT
        # ----------------------------------------------------------------------
        self.content = flet.Row(
            [controls_container, tools_container, position_frame], 
            spacing=10, 
            vertical_alignment=flet.CrossAxisAlignment.STRETCH
        )

    # --- LOGIC METHODS ---

    def change_speed(self, delta):
        self.jog_speed_percent = max(10, min(100, self.jog_speed_percent + delta))
        self.lbl_speed.value = f"{int(self.jog_speed_percent)}%"
        self.lbl_speed.update()
    
    # ... (rest of methods)
    
    # --- LOGIC METHODS ---
    
    # --- LIFECYCLE METHODS ---
    
    def did_mount(self):
        # Trigger an immediate logic update to popuplate values before first render frame if possible
        try:
            self._update_labels_logic()
            self.update() # Update this control (CartesianView)
        except: pass
        
    def _update_loop(self):
        while self.alive:
            # Fallback: Force sync IF AND ONLY IF we are purely stationary and data has arrived
            # This handles the initial connection sync without interrupting movements.
            if not self.is_jogging:
                has_zeros = all(abs(v) < 0.001 for v in self.commanded_joints)
                has_feedback = any(abs(v) > 0.01 for v in self.feedback_joints_deg)
                
                if has_zeros and has_feedback:
                    try:
                        self.commanded_joints = [np.radians(v) for v in self.feedback_joints_deg]
                    except: pass

            self._update_labels_logic()
            
            # Use page update if possible
            if self.page:
                try: self.page.update()
                except: pass
            
            time.sleep(0.05)

        
    def set_homed_status(self, is_homed):
        # HARDENING: Ensure boolean
        if isinstance(is_homed, str):
            if is_homed.lower() == "true": is_homed = True
            else: is_homed = False
        
        print(f"[CARTESIAN] set_homed_status called: {is_homed} (type: {type(is_homed)})")
        self.is_robot_homed = bool(is_homed)
        
        msg = "Robot homed!" if self.is_robot_homed else "Homing lost! Homing required."
        color = flet.colors.GREEN if self.is_robot_homed else flet.colors.RED
        
        if self.page:
            self.page.snack_bar = flet.SnackBar(flet.Text(msg), bgcolor=color)
            self.page.snack_bar.open = True
            self.page.update()

    def show_homing_required_dialog(self):
        if not self.page: return
        if self.on_error: self.on_error("E1")
        
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

    def on_jog_start(self, e, axis, direction):
        # 1. Check Homing
        if not self.is_robot_homed:
            self.show_homing_required_dialog()
            return
            
        if self.is_jogging: return
        self.is_jogging = True
        
        # Button styling
        e.control.content.bgcolor = "#111111"
        e.control.content.border = flet.border.all(1, "cyan")
        e.control.content.update()
        
        threading.Thread(target=self._jog_thread, args=(axis, direction), daemon=True).start()

    def on_jog_stop(self, e):
        self.is_jogging = False
        self.last_jog_time = time.time() # Start debounce timer
        # Reset styling
        if hasattr(e, "control") and e.control:
            e.control.content.bgcolor = "#444444"
            e.control.content.border = flet.border.all(1, "#666")
            e.control.content.update()

    def update_from_feedback(self, joint_values: dict):
        """
        Updates the display based on feedback from the robot (via main.py).
        joint_values: dict like {"J1": 10.0, "J2": -5.0, ...} in degrees.
        """
        try:
            # Store feedback values for display (in degrees, like JogView)
            for i in range(6):
                key = f"J{i+1}"
                if key in joint_values:
                    self.feedback_joints_deg[i] = joint_values[key]
            
            # Debounce: Do NOT sync commanded_joints during jogging or within 1.5s after
            # This prevents lagging UART feedback from overwriting our IK-computed targets
            if self.is_jogging:
                return
            if (time.time() - self.last_jog_time) < 1.5:
                return
                
            # Sync commanded_joints when NOT jogging and robot is stationary
            # Use a higher threshold to avoid jitter syncs
            feedback_rad = [np.radians(v) for v in self.feedback_joints_deg]
            for i in range(6):
                if abs(self.commanded_joints[i] - feedback_rad[i]) > np.radians(0.5):
                    self.commanded_joints[i] = feedback_rad[i]
                
        except Exception as e:
            print(f"[CARTESIAN] Error updating from feedback: {e}")

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
                self.uart.send_message("HOME")
            # Reset local joints to 0
            self.commanded_joints = [0.0] * 6

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
            self.page.snack_bar = flet.SnackBar(flet.Text("Position confirmed manually."), bgcolor="green")
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

    def on_safety_click(self, e):
        # Trigger W2 warning
        if self.on_error:
            self.on_error("W2")
        # Target: [0, 50, -70, -90, 0, 0] degrees
        target_rad = np.radians([0, -50, 70, 90, 0, 0]).tolist()
        self._animate_move(target_rad)

    def on_standby_click(self, e):
        # Target: All zeros
        target_rad = [0.0] * 6
        self._animate_move(target_rad)

    def _animate_move(self, target_joints_rad):
        """Moves robot to target joints smoothly using current velocity."""
        if self.is_jogging: return
        self.is_jogging = True
        
        def run():
            # Standard movement speed: 1.5 rad/s at 100% velocity
            # USE COPIES to avoid race conditions during iteration
            current_local = np.array(list(self.commanded_joints))
            target = np.array(target_joints_rad)
            
            try:
                while self.is_jogging and self.alive:
                    diff = target - current_local
                    dist = np.linalg.norm(diff)
                    
                    if dist < 0.005:
                        self.commanded_joints = target.tolist()
                        self.send_current_pose()
                        break
                    
                    # Respect current velocity slider
                    factor = self.jog_speed_percent / 100.0
                    # Max step per 0.05s frame (~1.5 rad/s max speed / 20Hz = 0.075)
                    step_size = min(dist, 0.075 * factor)
                    
                    current_local = current_local + (diff / dist) * step_size
                    self.commanded_joints = current_local.tolist()
                    self.send_current_pose()
                    time.sleep(0.05)
            finally:
                self.is_jogging = False
                self.last_jog_time = time.time()
            
        threading.Thread(target=run, daemon=True).start()

    def on_stop_click(self, e):
        # Trigger W1 warning
        if self.on_error:
            self.on_error("W1")
        self.is_jogging = False
        if self.uart: self.uart.send_message("EGRIP_STOP")

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
            else:
                self.ik.set_tool("CHWYTAK_MALY")
            if self.uart: self.uart.send_message("TOOL_VAC")
            close_dlg()
            self._update_labels_logic()
            self.page.snack_bar = flet.SnackBar(flet.Text("Active Tool: Vacuum Gripper"), bgcolor=flet.colors.GREEN)
            self.page.snack_bar.open = True
            self.page.update()
        
        def select_electric(e):
            if hasattr(self, 'on_global_set_tool') and self.on_global_set_tool:
                self.on_global_set_tool("CHWYTAK_DUZY")
            else:
                self.ik.set_tool("CHWYTAK_DUZY")
            if self.uart: self.uart.send_message("TOOL_EGRIP")
            close_dlg()
            self._update_labels_logic()
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

    def _ui_updater_loop(self):
        while self.alive:
            try:
                if self.page:
                    self._update_labels_logic()
                    self.page.update()
            except: pass 
            time.sleep(0.15) 

    def _update_labels_logic(self):
        """
        Use URDF-based FK from KinematicsEngine for display.
        This ensures consistency with the IK solver and removes DH table dependency.
        """
        if not self.ik.chain: 
            return
        
        try:
            # Get TCP matrix from URDF-based FK
            tcp_matrix = self.ik.forward_kinematics(self.commanded_joints)
            pos = tcp_matrix[:3, 3]  # [x, y, z] in meters
            rot = tcp_matrix[:3, :3]
            
            # Calculate Euler angles (A=Roll, B=Pitch, C=Yaw for xyz convention)
            euler = R.from_matrix(rot).as_euler('xyz', degrees=True)
            
            # UPDATE UI - position in mm
            self.lbl_cart["X"].value = f"{pos[0]*1000:.2f} mm"
            self.lbl_cart["Y"].value = f"{pos[1]*1000:.2f} mm"
            self.lbl_cart["Z"].value = f"{pos[2]*1000:.2f} mm"
            
            # Rotation in degrees (A=Roll, B=Yaw, C=Pitch - swapped to match buttons)
            self.lbl_cart["A"].value = f"{euler[0]:.2f}°"
            self.lbl_cart["B"].value = f"{euler[1]:.2f}°"
            self.lbl_cart["C"].value = f"{euler[2]:.2f}°"

            # Update Joint displays - use commanded values
            for i, rad_val in enumerate(self.commanded_joints):
                if i < len(self.lbl_joints):
                    deg_val = np.degrees(rad_val)
                    self.lbl_joints[i].value = f"{deg_val:.2f}°"
                    
        except Exception as e:
            print(f"[CARTESIAN] FK error: {e}")

    # --- LOGIKA RUCHU (AGGRESSIVE STABILITY) ---
    def _jog_thread(self, axis, direction):
        # Parametry "Ultra-Responsive":
        # Mały krok (2.0mm) + Mało iteracji (5) = Płynność
        # 2.0mm * 20Hz = 40mm/s (nieco wolniej, ale stabilnie)
        BASE_STEP_MM = 2.0
        BASE_STEP_RAD = 0.006  # Smaller step for rotation stability near singularities
        
        # Workspace limits (Expanded for pure URDF exploration)
        WORKSPACE_LIMITS = {
            'x': (-0.700, 0.700),
            'y': (-0.700, 0.700),
            'z': (-0.300, 0.900)
        }
        
        sign = 1 if direction == "plus" else -1
        
        while self.is_jogging:
            loop_start = time.time()
            
            # 1. Skalowanie prędkości
            factor = self.jog_speed_percent / 100.0
            step_mm = max(0.2, BASE_STEP_MM * factor)
            step_rad = max(0.002, BASE_STEP_RAD * factor)  # Lower minimum for rotation
            
            if self.ik.chain:
                # Use RAW joints for calculation
                current_raw = list(self.commanded_joints)
                
                # Get current TCP Pose (4x4)
                current_tcp_matrix = self.ik.forward_kinematics(current_raw)
                current_pos = current_tcp_matrix[:3, 3]
                current_rot = current_tcp_matrix[:3, :3]
                
                # Calculate Deltas (Identity Mapping)
                dx, dy, dz = 0, 0, 0
                drx, dry, drz = 0, 0, 0
                
                if axis == 'x': dx = step_mm * sign
                elif axis == 'y': dy = step_mm * sign
                elif axis == 'z': dz = step_mm * sign
                elif axis == 'rx': drx = step_rad * sign
                elif axis == 'ry': dry = step_rad * sign
                elif axis == 'rz': drz = step_rad * sign
                
                # Apply Deltas to TCP
                target_pos = current_pos + np.array([dx, dy, dz]) / 1000.0
                
                # Enforce workspace limits
                target_pos[0] = np.clip(target_pos[0], WORKSPACE_LIMITS['x'][0], WORKSPACE_LIMITS['x'][1])
                target_pos[1] = np.clip(target_pos[1], WORKSPACE_LIMITS['y'][0], WORKSPACE_LIMITS['y'][1])
                target_pos[2] = np.clip(target_pos[2], WORKSPACE_LIMITS['z'][0], WORKSPACE_LIMITS['z'][1])
                
                # ROTATION SCHEME (Local Tool Frame Pivot at Tip):
                # A (rx): Tool X rotation
                # B (ry): Tool Y rotation
                # C (rz): Tool Z rotation
                
                if axis == 'rx':  # A = Tool X
                    delta_rot = R.from_euler('x', drx).as_matrix()
                    target_rot = current_rot @ delta_rot
                
                elif axis == 'ry':  # B = Tool Y
                    delta_rot = R.from_euler('y', dry).as_matrix()
                    target_rot = current_rot @ delta_rot
                    
                elif axis == 'rz':  # C = Tool Z
                    delta_rot = R.from_euler('z', drz).as_matrix()
                    target_rot = current_rot @ delta_rot
                     
                else:
                    target_rot = current_rot
                
                try:
                    # New IK Solver handles tool offset internally!
                    nj_model = self.ik.inverse_kinematics(target_pos, target_rot, current_raw)
                    
                    # Normalize angles
                    nj_model = [(q + np.pi) % (2*np.pi) - np.pi for q in nj_model]
                    
                    # Singularity detection: check individual joint jumps
                    diffs = [abs(nj_model[i] - current_raw[i]) for i in range(6)]
                    max_diff = max(diffs)
                    
                    # Tighter thresholds for rotation stability
                    if max_diff < 0.3:  # ~17 degrees - safe movement
                        self.commanded_joints = nj_model
                    elif max_diff < 0.6:  # Moderate jump - interpolate to reduce jerk
                        # Blend: 20% new, 80% old - smoother transition near singularity
                        blend_factor = 0.2
                        blended = [current_raw[i] + blend_factor * (nj_model[i] - current_raw[i]) for i in range(6)]
                        self.commanded_joints = blended
                    # else: Large jump - reject completely (singularity protection)
                        
                except:
                    pass  # IK error - silently skip

            self.send_current_pose()
            
            # Target: 20Hz (50ms)
            elapsed = time.time() - loop_start
            sleep_time = max(0.01, 0.05 - elapsed)
            time.sleep(sleep_time)

    def send_current_pose(self):
        if self.uart and self.uart.is_open():
            vals_deg = [np.degrees(r) for r in self.commanded_joints]
            data_str = ",".join([f"{v:.2f}" for v in vals_deg])
            self.uart.send_message(f"J_{data_str}")

    def on_gripper_toggle_click(self, e):
        g_type = e.control.data 
        new_state = not self.gripper_states.get(g_type, False)
        self.gripper_states[g_type] = new_state
        
        cmd = "VAC_ON" if new_state else "VAC_OFF"
        if g_type == "electric": 
            cmd = "EGRIP_CLOSE" if new_state else "EGRIP_OPEN"
            
        e.control.style.bgcolor = flet.colors.GREEN_600 if new_state else flet.colors.RED_600
        e.control.content.value = "ON" if new_state else "OFF"
        if g_type == "electric": 
            e.control.content.value = "CLOSED" if new_state else "OPEN"
            
        e.control.update()
        if self.uart: 
            self.uart.send_message(cmd)

    def _create_gripper_control(self, display_name: str) -> flet.Container:
        container_style = {
            "bgcolor": "#2D2D2D", 
            "border_radius": 8, 
            "border": flet.border.all(1, "#555555"), 
            "padding": 5, 
            "expand": True
        }
        g_type = "electric" if "electric" in display_name.lower() else "pneumatic"
        state = self.gripper_states[g_type]
        
        txt = "CLOSED" if state and g_type=="electric" else ("OPEN" if g_type=="electric" else ("ON" if state else "OFF"))
        color = flet.colors.GREEN_600 if state else flet.colors.RED_600
        
        btn = flet.ElevatedButton(
            content=flet.Text(txt, size=14), 
            style=flet.ButtonStyle(bgcolor=color), 
            on_click=self.on_gripper_toggle_click, 
            data=g_type, 
            height=50, 
            expand=True
        )
        return flet.Container(
            content=flet.Column([
                flet.Text(display_name, size=13, color="white", text_align="center"), 
                flet.Row([btn], expand=True)
            ], spacing=2), 
            **container_style
        )

    def _create_axis_control(self, display_name: str, code: str) -> flet.Container:
        container_style = {
            "bgcolor": "#2D2D2D", 
            "border_radius": 8, 
            "border": flet.border.all(1, "#555555"), 
            "padding": 5, 
            "expand": True
        }

        def mk_btn(txt, direction):
            c = flet.Container(
                content=flet.Text(txt, size=30, weight="bold", color="white"), 
                bgcolor="#444444", 
                border_radius=8, 
                alignment=flet.alignment.center, 
                height=65, 
                shadow=flet.BoxShadow(blur_radius=2, color="black"), 
                border=flet.border.all(1, "#666")
            )
            gest = flet.GestureDetector(
                content=c, 
                on_tap_down=lambda e: self.on_jog_start(e, code, direction), 
                on_tap_up=lambda e: self.on_jog_stop(e), 
                on_long_press_end=lambda e: self.on_jog_stop(e), 
                on_pan_end=lambda e: self.on_jog_stop(e)
            )
            return flet.Container(content=gest, expand=True)

        return flet.Container(
            content=flet.Column([
                flet.Text(display_name, size=14, weight="bold", color="white", text_align="center"), 
                flet.Row([
                    mk_btn("-", "minus"), 
                    mk_btn("+", "plus")
                ], spacing=5, expand=True)
            ], spacing=2), 
            **container_style
        )
