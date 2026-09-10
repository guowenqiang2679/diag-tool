import sys
import os
import random
import traceback
from datetime import datetime

# ============ 调试日志 ============
LOG_PATH = os.path.join(os.path.expanduser("~"), "DiagTool_debug.log")

def log_file(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass

log_file("========== 程序启动 ==========")
log_file(f"Python: {sys.version}")
log_file(f"frozen: {getattr(sys, 'frozen', False)}")
log_file(f"exe: {sys.executable}")

# 设置 Qt 平台插件路径（PyInstaller onefile 兼容）
if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    os.environ["QT_PLUGIN_PATH"] = os.path.join(base, "PySide6", "plugins")
    log_file(f"QT_PLUGIN_PATH = {os.environ['QT_PLUGIN_PATH']}")

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QPushButton, QLabel, QListWidget, QStackedWidget, QTableWidget,
        QTableWidgetItem, QTextEdit, QLineEdit, QComboBox, QMessageBox,
        QHeaderView, QFormLayout, QAbstractItemView
    )
    from PySide6.QtCore import QTimer, Qt
    log_file("PySide6 导入成功")
except Exception:
    log_file("PySide6 导入失败:\n" + traceback.format_exc())
    sys.exit(1)


class MockECU:
    def __init__(self):
        self.connected = False
        self.dtcs = [
            {"code": "P0301", "status": "当前故障", "desc": "1缸失火"},
            {"code": "P0420", "status": "历史故障", "desc": "催化器效率低"},
            {"code": "U0100", "status": "当前故障", "desc": "与ECM通讯丢失"},
        ]
        self.freeze_frames = {
            "P0301": [
                ("发动机转速", "3200", "rpm"),
                ("车速", "45", "km/h"),
                ("冷却液温度", "92", "°C"),
                ("进气歧管压力", "45", "kPa"),
            ],
            "P0420": [
                ("发动机转速", "2200", "rpm"),
                ("车速", "60", "km/h"),
                ("冷却液温度", "88", "°C"),
                ("催化器温度", "450", "°C"),
            ],
            "U0100": [
                ("发动机转速", "0", "rpm"),
                ("车速", "0", "km/h"),
                ("蓄电池电压", "11.8", "V"),
            ],
        }
        self.data_stream = [
            {"did": "0xF190", "name": "VIN", "value": "LSVAA1234567890", "unit": ""},
            {"did": "0xF191", "name": "发动机转速", "value": "800", "unit": "rpm"},
            {"did": "0xF192", "name": "车速", "value": "0", "unit": "km/h"},
            {"did": "0xF193", "name": "冷却液温度", "value": "90", "unit": "°C"},
            {"did": "0xF194", "name": "节气门位置", "value": "12.5", "unit": "%"},
            {"did": "0xF195", "name": "蓄电池电压", "value": "13.8", "unit": "V"},
        ]
        self.params = {}

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read_dtcs(self):
        return self.dtcs

    def clear_dtcs(self):
        self.dtcs = []

    def read_freeze_frame(self, code):
        return self.freeze_frames.get(code, [])

    def read_data_stream(self):
        for item in self.data_stream:
            if item["name"] == "发动机转速":
                item["value"] = str(random.randint(750, 3500))
            elif item["name"] == "车速":
                item["value"] = str(random.randint(0, 120))
            elif item["name"] == "冷却液温度":
                item["value"] = str(random.randint(80, 105))
            elif item["name"] == "节气门位置":
                item["value"] = f"{random.uniform(0, 100):.1f}"
            elif item["name"] == "蓄电池电压":
                item["value"] = f"{random.uniform(12.0, 14.5):.2f}"
        return self.data_stream

    def write_param(self, did, value):
        self.params[did] = value
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ecu = MockECU()
        self.setWindowTitle("UDS 汽车诊断仪 - 模拟模式")
        self.resize(1200, 800)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data_stream)
        self.init_ui()
        self.log("程序启动，当前为模拟模式")
        log_file("MainWindow 初始化完成")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("功能菜单"))
        self.menu = QListWidget()
        self.menu.addItems(["故障码", "冻结帧", "数据流", "参数写入", "系统设置"])
        self.menu.setFixedWidth(180)
        left_layout.addWidget(self.menu)
        left_layout.addStretch()
        main_layout.addLayout(left_layout)

        right_layout = QVBoxLayout()

        top_bar = QHBoxLayout()
        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.status_label = QLabel("未连接")
        self.status_label.setStyleSheet("color: red;")
        self.vin_label = QLabel("VIN: --")
        self.voltage_label = QLabel("电压: -- V")
        top_bar.addWidget(self.btn_connect)
        top_bar.addWidget(self.status_label)
        top_bar.addStretch()
        top_bar.addWidget(self.vin_label)
        top_bar.addWidget(self.voltage_label)
        right_layout.addLayout(top_bar)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.create_dtc_page())
        self.stack.addWidget(self.create_freeze_page())
        self.stack.addWidget(self.create_data_page())
        self.stack.addWidget(self.create_write_page())
        self.stack.addWidget(self.create_settings_page())
        right_layout.addWidget(self.stack)

        right_layout.addWidget(QLabel("日志"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(150)
        right_layout.addWidget(self.log_text)

        main_layout.addLayout(right_layout)
        self.menu.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.menu.setCurrentRow(0)

    def setup_table(self, table, headers):
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)

    def create_dtc_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        btn_layout = QHBoxLayout()
        self.btn_read_dtc = QPushButton("读取故障码")
        self.btn_clear_dtc = QPushButton("清除故障码")
        btn_layout.addWidget(self.btn_read_dtc)
        btn_layout.addWidget(self.btn_clear_dtc)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        self.dtc_table = QTableWidget()
        self.setup_table(self.dtc_table, ["故障码", "状态", "描述"])
        layout.addWidget(self.dtc_table)
        self.btn_read_dtc.clicked.connect(self.read_dtcs)
        self.btn_clear_dtc.clicked.connect(self.clear_dtcs)
        return page

    def create_freeze_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        top.addWidget(QLabel("选择故障码:"))
        self.freeze_combo = QComboBox()
        top.addWidget(self.freeze_combo)
        self.btn_read_freeze = QPushButton("读取冻结帧")
        top.addWidget(self.btn_read_freeze)
        top.addStretch()
        layout.addLayout(top)
        self.freeze_table = QTableWidget()
        self.setup_table(self.freeze_table, ["项目", "值", "单位"])
        layout.addWidget(self.freeze_table)
        self.btn_read_freeze.clicked.connect(self.read_freeze)
        return page

    def create_data_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        top = QHBoxLayout()
        self.btn_start_data = QPushButton("开始读取")
        self.btn_stop_data = QPushButton("停止读取")
        top.addWidget(self.btn_start_data)
        top.addWidget(self.btn_stop_data)
        top.addStretch()
        layout.addLayout(top)
        self.data_table = QTableWidget()
        self.setup_table(self.data_table, ["DID", "名称", "值", "单位"])
        layout.addWidget(self.data_table)
        self.btn_start_data.clicked.connect(self.start_data_stream)
        self.btn_stop_data.clicked.connect(self.stop_data_stream)
        return page

    def create_write_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.did_input = QLineEdit()
        self.did_input.setPlaceholderText("例如 0xF190")
        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("例如 1234 或 文本")
        form.addRow("DID:", self.did_input)
        form.addRow("值:", self.value_input)
        layout.addLayout(form)
        self.btn_write = QPushButton("写入参数")
        layout.addWidget(self.btn_write)
        layout.addStretch()
        self.btn_write.clicked.connect(self.write_param)
        return page

    def create_settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("通讯配置（模拟模式）"))
        layout.addWidget(QLabel("CAN ID: 0x7E0 / 0x7E8"))
        layout.addWidget(QLabel("波特率: 500 kbps"))
        layout.addWidget(QLabel("协议: UDS over ISO-TP"))
        layout.addWidget(QLabel("后续接入真实硬件时，请在此配置 PCAN/Kvaser/Vector 等参数。"))
        layout.addStretch()
        return page

    def toggle_connection(self):
        if self.ecu.connected:
            self.ecu.disconnect()
            self.btn_connect.setText("连接")
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: red;")
            self.log("已断开 ECU")
            self.timer.stop()
        else:
            self.ecu.connect()
            self.btn_connect.setText("断开")
            self.status_label.setText("已连接")
            self.status_label.setStyleSheet("color: green;")
            self.log("已连接 ECU (模拟)")
            self.load_freeze_codes()
            self.update_vehicle_info()

    def load_freeze_codes(self):
        self.freeze_combo.clear()
        for dtc in self.ecu.read_dtcs():
            self.freeze_combo.addItem(dtc["code"])

    def read_dtcs(self):
        if not self.ecu.connected:
            QMessageBox.warning(self, "提示", "请先连接 ECU")
            return
        dtcs = self.ecu.read_dtcs()
        self.dtc_table.setRowCount(0)
        for row, dtc in enumerate(dtcs):
            self.dtc_table.insertRow(row)
            self.dtc_table.setItem(row, 0, QTableWidgetItem(dtc["code"]))
            self.dtc_table.setItem(row, 1, QTableWidgetItem(dtc["status"]))
            self.dtc_table.setItem(row, 2, QTableWidgetItem(dtc["desc"]))
        self.log(f"读取故障码完成，共 {len(dtcs)} 条")

    def clear_dtcs(self):
        if not self.ecu.connected:
            QMessageBox.warning(self, "提示", "请先连接 ECU")
            return
        self.ecu.clear_dtcs()
        self.dtc_table.setRowCount(0)
        self.load_freeze_codes()
        self.log("已清除故障码")

    def read_freeze(self):
        if not self.ecu.connected:
            QMessageBox.warning(self, "提示", "请先连接 ECU")
            return
        code = self.freeze_combo.currentText()
        if not code:
            QMessageBox.warning(self, "提示", "没有可读取的故障码")
            return
        data = self.ecu.read_freeze_frame(code)
        self.freeze_table.setRowCount(0)
        for row, (item, value, unit) in enumerate(data):
            self.freeze_table.insertRow(row)
            self.freeze_table.setItem(row, 0, QTableWidgetItem(item))
            self.freeze_table.setItem(row, 1, QTableWidgetItem(value))
            self.freeze_table.setItem(row, 2, QTableWidgetItem(unit))
        self.log(f"读取冻结帧 {code} 完成，共 {len(data)} 项")

    def start_data_stream(self):
        if not self.ecu.connected:
            QMessageBox.warning(self, "提示", "请先连接 ECU")
            return
        self.timer.start(500)
        self.log("开始读取数据流")

    def stop_data_stream(self):
        self.timer.stop()
        self.log("停止读取数据流")

    def update_data_stream(self):
        if not self.ecu.connected:
            self.timer.stop()
            return
        data = self.ecu.read_data_stream()
        self.data_table.setRowCount(0)
        for row, item in enumerate(data):
            self.data_table.insertRow(row)
            self.data_table.setItem(row, 0, QTableWidgetItem(item["did"]))
            self.data_table.setItem(row, 1, QTableWidgetItem(item["name"]))
            self.data_table.setItem(row, 2, QTableWidgetItem(item["value"]))
            self.data_table.setItem(row, 3, QTableWidgetItem(item["unit"]))
        self.update_vehicle_info()

    def update_vehicle_info(self):
        data = self.ecu.read_data_stream()
        for item in data:
            if item["name"] == "VIN":
                self.vin_label.setText(f"VIN: {item['value']}")
            elif item["name"] == "蓄电池电压":
                self.voltage_label.setText(f"电压: {item['value']} V")

    def write_param(self):
        if not self.ecu.connected:
            QMessageBox.warning(self, "提示", "请先连接 ECU")
            return
        did = self.did_input.text().strip()
        value = self.value_input.text().strip()
        if not did or not value:
            QMessageBox.warning(self, "提示", "请输入 DID 和值")
            return
        if self.ecu.write_param(did, value):
            self.log(f"参数写入成功: DID={did}, 值={value}")
        else:
            self.log(f"参数写入失败: DID={did}")

    def log(self, msg):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{t}] {msg}")


def main():
    try:
        log_file("创建 QApplication")
        app = QApplication(sys.argv)
        log_file("QApplication 创建成功")

        window = MainWindow()
        log_file("MainWindow 创建成功")

        # 关键：强制窗口居中、置顶、激活
        screen = app.primaryScreen().availableGeometry()
        w, h = 1200, 800
        x = (screen.width() - w) // 2
        y = (screen.height() - h) // 2
        window.move(x, y)
        window.show()
        window.raise_()
        window.activateWindow()
        window.setWindowState(window.windowState() | Qt.WindowActive)
        log_file(f"窗口已显示，位置=({x},{y})，尺寸=({w},{h})")

        sys.exit(app.exec())
    except Exception:
        log_file("主程序异常:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
