import serial
import serial.tools.list_ports
import threading
import time

class UARTCommunicator:
    def __init__(self, baudrate=115200, timeout=0.1): # Zmniejszyłem timeout dla szybszej reakcji
        self.port = None
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial_connection = None
        self.is_running = False
        self.read_thread = None
        self.on_data_received = None # Callback

    def find_port(self):
        ports = serial.tools.list_ports.comports()
        available_ports = [p.device for p in ports]
        print(f"[UART] Dostępne porty: {available_ports}")
        if available_ports:
            self.port = available_ports[0]
            print(f"[UART] Wybrano domyślny port: {self.port}")
            return self.port
        return None

    def connect(self, port=None, baudrate=None):
        if port: self.port = port
        if baudrate: self.baudrate = baudrate
            
        if not self.port:
            self.find_port()
            
        if not self.port:
            print("[UART] BŁĄD: Brak portu.")
            return False

        try:
            # WAŻNE: timeout=0.05 sprawia, że read() nie blokuje programu na wieki
            self.serial_connection = serial.Serial(
                self.port, self.baudrate, timeout=self.timeout
            )
            self.is_running = True
            
            self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.read_thread.start()
            
            print(f"[UART] SUKCES: Połączono z {self.port}")
            return True
        except serial.SerialException as e:
            print(f"[UART] BŁĄD OTWARCIA PORTU: {e}")
            self.serial_connection = None
            return False

    def disconnect(self):
        self.is_running = False
        if self.serial_connection:
            try:
                self.serial_connection.close()
                print("[UART] Rozłączono.")
            except:
                pass
        self.serial_connection = None

    def is_open(self):
        return self.serial_connection is not None and self.serial_connection.is_open

    def _read_loop(self):
        """
        Czyta dane w pętli. Zmienione na bardziej niezawodne czytanie.
        """
        print("[UART] Wątek nasłuchujący wystartował.")
        
        while self.is_running:
            if not self.is_open():
                time.sleep(0.5)
                continue
                
            try:
                # Sprawdzamy czy są dane w buforze
                if self.serial_connection.in_waiting > 0:
                    # Czytamy wszystko co jest, zamiast czekać na \n
                    # To eliminuje problem, jeśli STM nie wysyła entera
                    raw_data = self.serial_connection.read(self.serial_connection.in_waiting)
                    
                    if raw_data:
                        try:
                            # Próba dekodowania
                            decoded_chunk = raw_data.decode('utf-8', errors='ignore')
                           # print(f"[UART RAW] Odebrano: {repr(decoded_chunk)}") # Pokaże ukryte znaki np \n \r
                            
                            # Tu jest prosty trik: jeśli dane przychodzą w kawałkach,
                            # to parsowanie może być trudne, ale na razie zobaczmy czy COKOLWIEK wpada.
                            # Zakładamy, że STM wysyła linie.
                            
                            lines = decoded_chunk.split('\n')
                            for line in lines:
                                line = line.strip()
                                if line and self.on_data_received:
                                    # WYWOŁANIE CALLBACKA
                                    self.on_data_received(line)
                                    
                        except Exception as decode_error:
                            print(f"[UART] Błąd dekodowania: {decode_error}")

            except Exception as e:
                print(f"[UART] Błąd w pętli: {e}")
                time.sleep(0.1)
            
            time.sleep(0.01) # Lekki oddech dla procesora

    def send_message(self, message):
        if not self.is_open(): return False
        try:
            clean_message = message.strip() + '\n'
            self.serial_connection.write(clean_message.encode('utf-8'))
            print(f"[UART TX] Wysłano: {clean_message.strip()}")
            return True
        except Exception as e:
            print(f"[UART TX ERROR] {e}")
            return False