import flet
from flet import Column, Row, Container, Text, Icon, colors, ElevatedButton, ListView, padding, border
from flet import icons
from datetime import datetime

class ErrorsView(flet.Container):
    # Error codes dictionary (E = Error, W = Warning, OT = Overtemperature, CT = Critical Temperature)
    ERROR_CODES = {
        "E1": ("ERROR", "Not Homed - Robot requires homing before movement"),
        "E2": ("ERROR", "E-STOP Active - Emergency stop button pressed"),
        "E3": ("ERROR", "Syntax Error - Error detected in program"),
        "E4": ("ERROR", "Port Disconnected - No connection to robot"),
        "E5": ("WARNING", "Limit Switch - Robot hit the limit switch"),
        "W1": ("WARNING", "Stop - STOP button pressed"),
        "W2": ("WARNING", "Safe Move - SAFETY button pressed"),
        # Temperature sensors 1-4
        "OT1": ("WARNING", "Overtemperature Sensor 1 - Temperature above normal"),
        "OT2": ("WARNING", "Overtemperature Sensor 2 - Temperature above normal"),
        "OT3": ("WARNING", "Overtemperature Sensor 3 - Temperature above normal"),
        "OT4": ("WARNING", "Overtemperature Sensor 4 - Temperature above normal"),
        "CT1": ("ERROR", "Critical Temperature Sensor 1 - Temperature critical"),
        "CT2": ("ERROR", "Critical Temperature Sensor 2 - Temperature critical"),
        "CT3": ("ERROR", "Critical Temperature Sensor 3 - Temperature critical"),
        "CT4": ("ERROR", "Critical Temperature Sensor 4 - Temperature critical"),
        # Motor errors 1-6
        "EMM1": ("ERROR", "Error Missing Motor 1 - Motor 1 not responding"),
        "EMM2": ("ERROR", "Error Missing Motor 2 - Motor 2 not responding"),
        "EMM3": ("ERROR", "Error Missing Motor 3 - Motor 3 not responding"),
        "EMM4": ("ERROR", "Error Missing Motor 4 - Motor 4 not responding"),
        "EMM5": ("ERROR", "Error Missing Motor 5 - Motor 5 not responding"),
        "EMM6": ("ERROR", "Error Missing Motor 6 - Motor 6 not responding"),
        # Kinematics & Range errors
        "IKE": ("ERROR", "Inverse Kinematics Error - Position unreachable"),
        "OOR1": ("ERROR", "Out Of Range Joint 1 - Joint angle exceeds limits"),
        "OOR2": ("ERROR", "Out Of Range Joint 2 - Joint angle exceeds limits"),
        "OOR3": ("ERROR", "Out Of Range Joint 3 - Joint angle exceeds limits"),
        "OOR4": ("ERROR", "Out Of Range Joint 4 - Joint angle exceeds limits"),
        "OOR5": ("ERROR", "Out Of Range Joint 5 - Joint angle exceeds limits"),
        "OOR6": ("ERROR", "Out Of Range Joint 6 - Joint angle exceeds limits"),
        # Communication & Safety errors
        "COM": ("ERROR", "Communication Timeout - No response from controller"),
        "COL": ("ERROR", "Collision Detected - Unexpected resistance"),
        "OVL": ("ERROR", "Overload Detected - Motor current too high"),
        "GRE": ("ERROR", "Gripper Error - Gripper malfunction"),
        # Near limit warnings (joints 1-6)
        "NRL1": ("WARNING", "Near Limit Joint 1 - Approaching joint limit"),
        "NRL2": ("WARNING", "Near Limit Joint 2 - Approaching joint limit"),
        "NRL3": ("WARNING", "Near Limit Joint 3 - Approaching joint limit"),
        "NRL4": ("WARNING", "Near Limit Joint 4 - Approaching joint limit"),
        "NRL5": ("WARNING", "Near Limit Joint 5 - Approaching joint limit"),
        "NRL6": ("WARNING", "Near Limit Joint 6 - Approaching joint limit"),
        # Other warnings
        "SLW": ("WARNING", "Slow Response - Communication delay detected"),
        "HMS": ("WARNING", "Homing Skipped - Position confirmed manually"),
        "CFG": ("WARNING", "Config Mismatch - PC and controller config differ"),
        "GRW": ("WARNING", "Gripper Warning - Object not detected"),
        "SPD": ("WARNING", "Speed Limited - Speed automatically reduced"),
        # Stall detection (motors 1-6)
        "STL1": ("WARNING", "Stall Detected Motor 1 - Motor blocked"),
        "STL2": ("WARNING", "Stall Detected Motor 2 - Motor blocked"),
        "STL3": ("WARNING", "Stall Detected Motor 3 - Motor blocked"),
        "STL4": ("WARNING", "Stall Detected Motor 4 - Motor blocked"),
        "STL5": ("WARNING", "Stall Detected Motor 5 - Motor blocked"),
        "STL6": ("WARNING", "Stall Detected Motor 6 - Motor blocked"),
        # Info messages
        "HMD": ("INFO", "Homing Done - Robot successfully homed"),
        "CON": ("INFO", "Connected - Communication established"),
        "DIS": ("INFO", "Disconnected - Communication closed"),
        "RDY": ("INFO", "Ready - Robot ready for operation"),
        "PRG": ("INFO", "Program Completed - Task finished successfully"),
    }
    
    def __init__(self, uart_communicator=None, on_status_change=None):
        super().__init__()
        self.uart = uart_communicator
        self.on_status_change = on_status_change # Callback: function(is_error: bool)
        
        # Track active alarms: {code: (container, timestamp_text)}
        self.active_alarms = {}
        
        # --- MAIN SETTINGS ---
        self.expand = True
        self.padding = 5
        self.bgcolor = "#2D2D2D" 
        
        # ======================================================================
        # === 1. STATUS HEADER (Monitor) ===
        # ======================================================================
        self.status_icon = Icon(name=icons.CHECK_CIRCLE, size=40, color=colors.GREEN_400)
        self.status_text = Text("SYSTEM OK", size=20, weight="bold", color=colors.GREEN_400)
        
        self.header_panel = Container(
            content=Row(
                controls=[self.status_icon, self.status_text],
                alignment=flet.MainAxisAlignment.CENTER,
            ),
            bgcolor="#2D2D2D",
            border_radius=10,
            border=border.all(1, colors.GREEN_900),
            padding=15,
        )

        # ======================================================================
        # === 2. LOG LIST (Scrollable) ===
        # ======================================================================
        self.logs_list_view = ListView(
            expand=True, spacing=5, padding=10, auto_scroll=True
        )

        logs_container = Container(
            content=self.logs_list_view,
            bgcolor="#2D2D2D",
            border_radius=10,
            border=border.all(1, "#444444"),
            expand=True, 
        )

        # ======================================================================
        # === 3. BUTTON BAR (Bottom) ===
        # ======================================================================
        clear_btn = ElevatedButton(
            text="Clear History",
            icon=icons.DELETE_SWEEP,
            style=flet.ButtonStyle(
                bgcolor=colors.RED_900, color=colors.WHITE,
                shape=flet.RoundedRectangleBorder(radius=8),
            ),
            on_click=self._clear_logs
        )

        reset_robot_btn = ElevatedButton(
            text="Reset Robot Errors",
            icon=icons.BUILD_CIRCLE,
            style=flet.ButtonStyle(
                bgcolor=colors.ORANGE_800, color=colors.WHITE,
                shape=flet.RoundedRectangleBorder(radius=8),
                elevation=4,
            ),
            on_click=self._reset_robot_errors
        )

        buttons_row = Row(
            controls=[clear_btn, Container(width=10), reset_robot_btn],
            alignment=flet.MainAxisAlignment.START
        )

        # ======================================================================
        # === MAIN LAYOUT ===
        # ======================================================================
        self.content = Column(
            controls=[
                self.header_panel,
                Text("Event Log:", size=14, color=colors.GREY_500),
                logs_container,
                buttons_row
            ],
            expand=True,
            spacing=10
        )

    # ======================================================================
    # === ADD LOG FUNCTION ===
    # ======================================================================
    def add_log(self, level, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color configuration based on error level
        if level == "ERROR":
            icon_name = icons.ERROR_OUTLINE
            icon_color = colors.RED_400
            text_color = colors.RED_200
            bg_color = colors.RED_900
            self._update_alert_status("ERROR")
        elif level == "WARNING":
            icon_name = icons.WARNING_AMBER
            icon_color = colors.AMBER_400
            text_color = colors.AMBER_200
            bg_color = "#4d3b00"
            self._update_alert_status("WARNING") 
        else: # INFO
            icon_name = icons.INFO_OUTLINE
            icon_color = colors.BLUE_400
            text_color = colors.BLUE_200
            bg_color = "#0d1f33"
            # INFO notification? Usually no alert for INFO.

        log_row = Container(
            content=Row(
                controls=[
                    Text(f"[{timestamp}]", color=colors.GREY_500, size=12, weight="bold"),
                    Icon(name=icon_name, color=icon_color, size=16),
                    Text(level, color=icon_color, weight="bold", width=85), 
                    Text(message, color=text_color, size=14, expand=True, no_wrap=False),
                ],
                alignment=flet.MainAxisAlignment.START,
                vertical_alignment=flet.CrossAxisAlignment.CENTER
            ),
            bgcolor=bg_color,
            border_radius=5,
            padding=5,
            border=border.only(left=border.BorderSide(4, icon_color))
        )

        # 1. Add entry to list
        self.logs_list_view.controls.append(log_row)
        
        # 2. Update view only if visible
        if self.logs_list_view.page:
            self.logs_list_view.update()

    def _clear_logs(self, e):
        # NOTE: User requested this button SHOULD NOT reset error state, only clear text.
        self.logs_list_view.controls.clear()
        self.active_alarms.clear()  
        
        if self.logs_list_view.page:
            self.logs_list_view.update()
            
        self.add_log("INFO", "Log cleared.")

    def _set_system_status(self, is_ok):
        if is_ok:
            self.status_icon.name = icons.CHECK_CIRCLE
            self.status_icon.color = colors.GREEN_400
            self.status_text.value = "SYSTEM OK"
            self.status_text.color = colors.GREEN_400
            self.header_panel.border = border.all(1, colors.GREEN_900)
            
            # Notify main app that error is cleared
            if self.on_status_change:
                self.on_status_change("NONE") 
        else:
            self.status_icon.name = icons.DANGEROUS
            self.status_icon.color = colors.RED_500
            self.status_text.value = "ERRORS DETECTED"
            self.status_text.color = colors.RED_500
            self.header_panel.border = border.all(1, colors.RED_500)
            
            # Notify main app about error/warning type
            # We need to determine if it's ERROR or WARNING based on checking active alarms?
            # Ideally we pass 'level' to _set_system_status.
            # But here we only have the generic call. 
            # Let's check active alarms highest severity or just rely on what triggered it.
            # Simpler: we modify call sites to pass the level or 'ERROR' by default.
            pass # See add_log modifications below

    def _update_alert_status(self, level):
        """
        Updates the internal status and notifies callback with 'ERROR', 'WARNING', or 'NONE'.
        This replaces/augments _set_system_status logic for external notification.
        """
        if level == "NONE":
            self.status_icon.name = icons.CHECK_CIRCLE
            self.status_icon.color = colors.GREEN_400
            self.status_text.value = "SYSTEM OK"
            self.status_text.color = colors.GREEN_400
            self.header_panel.border = border.all(1, colors.GREEN_900)
        else:
            self.status_icon.name = icons.DANGEROUS
            self.status_icon.color = colors.RED_500
            self.status_text.value = "ERRORS DETECTED"
            self.status_text.color = colors.RED_500
            self.header_panel.border = border.all(1, colors.RED_500)

        if self.header_panel.page:
            self.header_panel.update()

        if self.on_status_change:
            self.on_status_change(level)


    # ======================================================================
    # === ERROR CODE HANDLING ===
    # ======================================================================
    def handle_error_code(self, code: str):
        """
        Handle incoming error code from UART (e.g., 'E1', 'W2').
        If alarm is already active, just update the timestamp.
        Otherwise, create a new log entry.
        """
        code = code.strip().upper()
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Check if this alarm is already active - just update timestamp
        if code in self.active_alarms:
            timestamp_text = self.active_alarms[code]
            timestamp_text.value = f"[{timestamp}]"
            if timestamp_text.page:
                timestamp_text.update()
            return
        
        # New alarm - create entry
        if code in self.ERROR_CODES:
            level, message = self.ERROR_CODES[code]
            self._add_alarm_log(code, level, f"[{code}] {message}")
        else:
            # Unknown code - still log it
            self.add_log("WARNING", f"Unknown code: {code}")
    
    def _add_alarm_log(self, code: str, level: str, message: str):
        """Add an alarm log entry and track it for deduplication."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Color configuration based on error level
        # Color configuration based on error level
        if level == "ERROR":
            icon_name = icons.ERROR_OUTLINE
            icon_color = colors.RED_400
            text_color = colors.RED_200
            bg_color = colors.RED_900
            self._update_alert_status("ERROR")
        elif level == "WARNING":
            icon_name = icons.WARNING_AMBER
            icon_color = colors.AMBER_400
            text_color = colors.AMBER_200
            bg_color = "#4d3b00"
            self._update_alert_status("WARNING")
        else:  # INFO
            icon_name = icons.INFO_OUTLINE
            icon_color = colors.BLUE_400
            text_color = colors.BLUE_200
            bg_color = "#0d1f33"
        
        # Create timestamp text reference for later updates
        timestamp_text = Text(f"[{timestamp}]", color=colors.GREY_500, size=12, weight="bold")
        
        log_row = Container(
            content=Row(
                controls=[
                    timestamp_text,
                    Icon(name=icon_name, color=icon_color, size=16),
                    Text(level, color=icon_color, weight="bold", width=85),
                    Text(message, color=text_color, size=14, expand=True, no_wrap=False),
                ],
                alignment=flet.MainAxisAlignment.START,
                vertical_alignment=flet.CrossAxisAlignment.CENTER
            ),
            bgcolor=bg_color,
            border_radius=5,
            padding=5,
            border=border.only(left=border.BorderSide(4, icon_color))
        )
        
        # Track this alarm
        self.active_alarms[code] = timestamp_text
        
        # Add to list
        self.logs_list_view.controls.append(log_row)
        
        if self.logs_list_view.page:
            self.logs_list_view.update()

    def send_error_code(self, code: str):
        """
        Send an error code via UART and also display it locally.
        Use this when the application triggers an error/warning.
        """
        code = code.strip().upper()
        
        # Display locally
        self.handle_error_code(code)
        
        # Send via UART if connected
        if self.uart and self.uart.is_open():
            self.uart.send_message(code)
            print(f"[ERRORS] Sent error code: {code}")

    def _reset_robot_errors(self, e):
        """Sends the command to reset robot errors AND clears error state locally."""
        # 1. Clear local error state
        self._update_alert_status("NONE")
        self.active_alarms.clear()
        
        # 2. Add log entry
        self.add_log("INFO", "Resetting robot errors...")

        # 3. Send command
        if self.uart and self.uart.is_open():
            self.uart.send_message("ROBOT_OK") # Changed from COLLISION_OK as requested
            print("[ERRORS] Sent ROBOT_OK")
        else:
            self.add_log("WARNING", "Cannot send reset command: UART disconnected.")