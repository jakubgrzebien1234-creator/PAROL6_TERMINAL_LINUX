import flet
from flet import Column, Row, Container, Text, alignment, colors, MainAxisAlignment, ScrollMode, padding, border

class StatusView(flet.Container):
    def __init__(self): 
        super().__init__()
        
        # NOTE: self.uart and parse_data removed.
        # Now main.py controls this view using update_status().

        # --- MAIN SETTINGS ---
        self.expand = True
        self.padding = 5
        self.bgcolor = "#2D2D2D"
        
        self.value_controls = {}

        # ======================================================================
        # === LEFT COLUMN (Power, Temperatures, Pneumatics) ===
        # ======================================================================
        self.left_column_content = Column(
            controls=[
                # --- 1. POWER (Data from PROT_) ---
                self._create_header("POWER STATUS"),
                self._create_status_row("3.3V Rail", "--", key="PWR3V3"),
                self._create_status_row("5.0V Rail", "--", key="PWR5V"),
                self._create_status_row("Power OK",   "--", key="PWROK"),
                self._create_status_row("Power Stat", "--", key="PWRSTAT"),
                
                # --- 2. TEMPERATURES (Data from PROT_) ---
                self._create_header("TEMPERATURES (NTC)"),
                self._create_status_row("Sensor T1", "0.00 °C", color=colors.ORANGE_300, key="TEMP1"),
                self._create_status_row("Sensor T2", "0.00 °C", color=colors.ORANGE_300, key="TEMP2"),
                self._create_status_row("Sensor T3", "0.00 °C", color=colors.ORANGE_300, key="TEMP3"),
                self._create_status_row("Sensor T4", "0.00 °C", color=colors.ORANGE_300, key="TEMP4"),
                
                # --- 3. PNEUMATICS ---
                self._create_header("PNEUMATICS"),
                self._create_status_row("Pressure", "0.00 kPa", color=colors.CYAN_400, key="CISNIENIE"),
                self._create_status_row("Pump", "OFF", color=colors.RED_400, key="POMPA"),
                self._create_status_row("Valve", "OPEN", color=colors.GREEN_400, key="ZAWOR"),

                # --- 4. GENERAL STATUS ---
                self._create_header("SYSTEM STATUS"),
                self._create_status_row("Connection", "Disconnected", color=colors.GREY_400, key="CONN_STAT"),
                self._create_status_row("Port", "--", color=colors.BLUE_400, key="PORT_NAME"),
            ],
            scroll=ScrollMode.ADAPTIVE,
            spacing=5,
            expand=True
        )

        # ======================================================================
        # === RIGHT COLUMN (Limit Switches and StallGuard) ===
        # ======================================================================
        self.right_column_content = Column(
            controls=[
                # --- 1. LIMIT SWITCHES ---
                self._create_header("LIMIT SWITCHES"),
                self._create_status_row("Limit Switch J1", "RELEASED", color=colors.GREEN_400, key="LS1"),
                self._create_status_row("Limit Switch J2", "RELEASED", color=colors.GREEN_400, key="LS2"),
                self._create_status_row("Limit Switch J3", "RELEASED", color=colors.GREEN_400, key="LS3"),
                self._create_status_row("Limit Switch J4", "RELEASED", color=colors.GREEN_400, key="LS4"),
                self._create_status_row("Limit Switch J5", "RELEASED", color=colors.GREEN_400, key="LS5"),
                self._create_status_row("Limit Switch J6", "RELEASED", color=colors.GREEN_400, key="LS6"),

                # --- 2. DRIVES STATUS (New) ---
                self._create_header("DRIVES STATUS"),
                self._create_status_row("Motor 1 Connected", "True", color=colors.GREEN_400, key="M1_CONN"),
                self._create_status_row("Motor 2 Connected", "True", color=colors.GREEN_400, key="M2_CONN"),
                self._create_status_row("Motor 3 Connected", "True", color=colors.GREEN_400, key="M3_CONN"),
                self._create_status_row("Motor 4 Connected", "True", color=colors.GREEN_400, key="M4_CONN"),
                self._create_status_row("Motor 5 Connected", "True", color=colors.GREEN_400, key="M5_CONN"),
                self._create_status_row("Motor 6 Connected", "True", color=colors.GREEN_400, key="M6_CONN"),
            ],
            scroll=ScrollMode.ADAPTIVE,
            spacing=5,
            expand=True
        )

        # Frame styles
        frame_style = {
            "bgcolor": "#2D2D2D",
            "border_radius": 10,
            "padding": 15,
            "border": flet.border.all(1, "#444444"),
            "expand": True,
        }

        # Main Layout
        self.content = Row(
            controls=[
                Container(content=self.left_column_content, **frame_style),
                Container(content=self.right_column_content, **frame_style)
            ],
            spacing=5,
            expand=True,
            vertical_alignment=flet.CrossAxisAlignment.STRETCH
        )

    # ======================================================================
    # === UPDATE API (Called from main.py) ===
    # ======================================================================
    def update_status(self, parameter_name, new_value, new_color=None):
        """
        Called by main.py upon receiving UART data.
        """
        if parameter_name in self.value_controls:
            control = self.value_controls[parameter_name]
            control.value = str(new_value)
            
            if new_color:
                control.color = new_color
            
            # Refresh only this element
            if control.page:
                control.update()

    # ======================================================================
    # === UI HELPER METHODS ===
    # ======================================================================
    def _create_header(self, text):
        return Container(
            content=Text(text, color=colors.BLUE_GREY_200, weight="bold", size=14),
            padding=padding.only(top=10, bottom=5)
        )

    def _create_status_row(self, label_text, start_value, color="white", key=None):
        value_display = Text(
            value=start_value,
            color=color,
            weight="bold",
            size=16,
            text_align=flet.TextAlign.CENTER
        )
        
        # If key is not provided, use label as key
        dict_key = key if key is not None else label_text
        self.value_controls[dict_key] = value_display

        value_box = Container(
            content=value_display,
            bgcolor=colors.BLUE_GREY_900,
            border=border.all(1, colors.BLUE_GREY_700),
            border_radius=6,
            padding=padding.symmetric(horizontal=5, vertical=5),
            width=130, 
            alignment=alignment.center
        )

        row = Row(
            controls=[
                Text(label_text, color="white", size=16, expand=True),
                value_box
            ],
            alignment=MainAxisAlignment.SPACE_BETWEEN,
        )

        return Container(
            content=row,
            padding=padding.symmetric(vertical=3),
            border=border.only(bottom=border.BorderSide(1, "#444444"))
        )