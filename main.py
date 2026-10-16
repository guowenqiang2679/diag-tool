import sys
import os
import random
import traceback
from datetime import datetime

LOG_PATH = os.path.join(os.path.expanduser("~"), "DiagTool_debug.log")


def log_file(msg):
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


log_file("========== 程序启动 ==========")

if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    os.environ["QT_PLUGIN_PATH"] = os.path.join(base, "PySide6", "plugins")

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QListWidget, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QLineEdit, QComboBox, QMessageBox,
    QHeaderView, QFormLayout, QAbstractItemView, QGroupBox
)
from PySide6.QtCore import QTimer, Qt

from can_adapter import create_adapter, VENDORS, BITRATES
from uds_client import UdsClient, UdsError, UdsNegativeResponse


# ============================================================
# 后端 1: 模拟 ECU（离线测试用）
# ============================================================
class MockBackend:
    name = "模拟"

    def __init__(self):
        self.connected = False
        self.dtcs = [
            ("P0301", 0x09, "1 缸失火"),
            ("P0420", 0x08, "催化器效率低"),
            ("U0100", 0x09, "与 ECM 通讯丢失"),
        ]
        self.freeze = {
            "P0301": [("发动机转速", "3200", "rpm"),
                      ("车速", "45", "km/h"),
                      ("冷却液温度", "92", "°C")],
            "P0420": [("发动机转速", "2200", "rpm"),
                      ("车速", "60", "km/h"),
                      ("催化器温度", "450", "°C")],
            "U0100": [("蓄电池电压", "11.8", "V")],
        }
        self.live = [
            {"did": 0xF190, "name": "VIN", "value": "LSVAA1234567890", "unit": ""},
            {"did": 0xF191, "name": "发动机转速", "value": "800", "unit": "rpm"},
            {"did": 0xF192, "name": "车速", "value": "0", "unit": "km/h"},
            {"did": 0xF193, "name": "冷却液温度", "value": "90", "unit": "°C"},
            {"did": 0xF194, "name": "节气门位置", "value": "12.5", "unit": "%"},
            {"did": 0xF195, "name": "蓄电池电压", "value": "13.8", "unit": "V"},
        ]
        self.params = {}

    def connect(self, cfg):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read_dtcs(self):
        return [(c, f"0x{s:02X}", d) for c, s, d in self.dtcs]

    def clear_dtcs(self):
        self.dtcs = []

    def read_freeze_frame(self, code):
        return self.freeze.get(code, [])

    def read_data_stream(self):
        for item in self.live:
            n = item["name"]
            if n == "发动机转速":
                item["value"] = str(random.randint(750, 3500))
            elif n == "车速":
                item["value"] = str(random.randint(0, 120))
            elif n == "冷却液温度":
                item["value"] = str(random.randint(80, 105))
            elif n == "节气门位置":
                item["value"] = f"{random.uniform(0, 100):.1f}"
            elif n == "蓄电池电压":
                item["value"] = f"{random.uniform(12.0, 14.5):.2f}"
        return self.live

    def write_param(self, did, value):
        self.params[did] = value
        return True


# ============================================================
# 后端 2: 真实 UDS
# ============================================================
class UdsBackend:
    name = "UDS"

    def __init__(self):
        self.adapter = None
        self.client = None
        self.connected = False

    def connect(self, cfg):
        self.adapter = create_adapter(
            cfg["vendor"], cfg["channel"], cfg["bitrate"])
        self.adapter.open()
        self.client = UdsClient(
            self.adapter,
            tx_id=cfg["tx_id"],
            rx_id=cfg["rx_id"],
            func_id=cfg["func_id"],
        )
        self.connected = True

    def disconnect(self):
        if self.adapter is not None:
            try:
                self.adapter.close()
            except Exception:
                pass
        self.adapter = None
        self.client = None
        self.connected = False

    # ------- 以下每个方法都调用 UdsClient，可以自行修改 -------
    def read_dtcs(self):
        result = self.client.read_dtc_by_status_mask(0xFF)
        return [(code, f"0x{st:02X}", "") for code, st in result]

    def clear_dtcs(self):
        self.client.clear_diagnostic_information(0xFFFFFF)

    def read_freeze_frame(self, code):
        # 简化实现：以固定 DID 读取，需按你的 ECU 修改
        # 这里示范读 0xF191/0xF192/0xF193
        items = []
        for did, name, unit in [
            (0xF191, "发动机转速", "rpm"),
            (0xF192, "车速", "km/h"),
            (0xF193, "冷却液温度", "°C"),
        ]:
            try:
                raw = self.client.read_data_by_identifier(did)
                items.append((name, raw.hex(" ").upper(), unit))
            except UdsError as e:
                items.append((name, f"错误: {e}", unit))
        return items

    def read_data_stream(self):
        result = []
        # 需要按你的 ECU 修改 DID 列表
        did_list = [
            (0xF190, "VIN", ""),
            (0xF191, "发动机转速", "rpm"),
            (0xF192, "车速", "km/h"),
            (0xF193, "冷却液温度", "°C"),
        ]
        for did, name, unit in did_list:
            try:
                raw = self.client.read_data_by_identifier(did)
                if did == 0xF190:
                    value = raw.decode("ascii", errors="replace").strip("\x00")
                elif len(raw) == 1:
                    value = str(raw[0])
                elif len(raw) == 2:
                    value = str((raw[0] << 8) | raw[1])
                else:
                    value = raw.hex(" ").upper()
            except UdsError as e:
                value = f"错误: {e}"
            result.append({"did": did, "name": name, "value": value, "unit": unit})
        return result

    def write_param(self, did_str, value_str):
        did = int(did_str.replace("0x", "").replace("0X", ""), 16)
        # 简化：按 ASCII 写入。要写数值，请自行按字节序转换。
        try:
            value_bytes = value_str.encode("ascii")
        except Exception:
            value_bytes = bytes.fromhex(value_str.replace(" ", ""))
        self.client.write_data_by_identifier(did, value_bytes)
        return True


# ============================================================
# 主窗口
# ============================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.backend = MockBackend()
        self.setWindowTitle("UDS 汽车诊断仪")
        self.resize(1200, 800)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data_stream)
        self.init_ui()
        self.log("程序启动，当前为模拟模式")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("功能菜单"))
        self.menu = QListWidget()
        self.menu.addItems(["连接设置", "故障码", "冻结帧", "数据流", "参数写入", "关于"])
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
        self.stack.addWidget(self.create_conn_page())
        self.stack.addWidget(self.create_dtc_page())
        self.stack.addWidget(self.create_freeze_page())
        self.stack.addWidget(self.create_data_page())
        self.stack.addWidget(self.create_write_page())
        self.stack.addWidget(self.create_about_page())
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

    # -------- 页面: 连接设置 --------
    def create_conn_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        # 模式
        mode_group = QGroupBox("模式")
        mode_layout = QFormLayout(mode_group)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["模拟（离线测试）", "真实 UDS（连接硬件）"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        mode_layout.addRow("运行模式:", self.mode_combo)
        layout.addWidget(mode_group)

        # CAN 配置
        can_group = QGroupBox("CAN 通讯配置")
        can_layout = QFormLayout(can_group)
        self.vendor_combo = QComboBox()
        self.vendor_combo.addItems(VENDORS)
        can_layout.addRow("CAN 盒厂商:", self.vendor_combo)

        self.channel_input = QLineEdit()
        self.channel_input.setPlaceholderText("PCAN: PCAN_USBBUS1  |  Kvaser: 0  |  ZLG: 0")
        can_layout.addRow("通道:", self.channel_input)

        self.bitrate_combo = QComboBox()
        for b in BITRATES:
            self.bitrate_combo.addItem(f"{b // 1000} kbps", b)
        self.bitrate_combo.setCurrentIndex(1)  # 默认 500k
        can_layout.addRow("波特率:", self.bitrate_combo)

        self.tx_input = QLineEdit("0x7E0")
        self.rx_input = QLineEdit("0x7E8")
        self.func_input = QLineEdit("0x7DF")
        can_layout.addRow("物理请求 ID:", self.tx_input)
        can_layout.addRow("物理响应 ID:", self.rx_input)
        can_layout.addRow("功能寻址 ID:", self.func_input)

        layout.addWidget(can_group)

        # 按钮
        btn_row = QHBoxLayout()
        self.btn_apply = QPushButton("应用并连接")
        self.btn_apply.clicked.connect(self.toggle_connection)
        btn_row.addWidget(self.btn_apply)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addStretch()
        return page

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
        self.value_input.setPlaceholderText("ASCII 文本，或十六进制如 01 02 03")
        form.addRow("DID:", self.did_input)
        form.addRow("值:", self.value_input)
        layout.addLayout(form)
        self.btn_write = QPushButton("写入参数")
        layout.addWidget(self.btn_write)
        layout.addStretch()
        self.btn_write.clicked.connect(self.write_param)
        return page

    def create_about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("UDS 诊断仪 - 多厂商 CAN 版"))
        layout.addWidget(QLabel("支持厂商: " + "、".join(VENDORS)))
        layout.addWidget(QLabel("波特率: 250 kbps / 500 kbps"))
        layout.addWidget(QLabel("默认寻址: 物理 0x7E0 / 0x7E8，功能 0x7DF"))
        layout.addWidget(QLabel("UDS 服务在 uds_client.py 中，可自由扩展"))
        layout.addStretch()
        return page

    # -------- 交互 --------
    def on_mode_changed(self, idx):
        if self.backend.connected:
            QMessageBox.warning(self, "提示", "请先断开当前连接再切换模式")
            return
        if idx == 0:
            self.backend = MockBackend()
            self.log("已切换到模拟模式")
        else:
            self.backend = UdsBackend()
            self.log("已切换到真实 UDS 模式")

    def _parse_hex(self, s, default):
        try:
            return int(s.strip().replace("0x", "").replace("0X", ""), 16)
        except Exception:
            return default

    def toggle_connection(self):
        if self.backend.connected:
            try:
                self.backend.disconnect()
            except Exception as e:
                self.log(f"断开时出错: {e}")
            self.backend.connected = False
            self.btn_connect.setText("连接")
            self.status_label.setText("未连接")
            self.status_label.setStyleSheet("color: red;")
            self.log("已断开")
            self.timer.stop()
            return

        cfg = {
            "vendor": self.vendor_combo.currentText(),
            "channel": self.channel_input.text().strip(),
            "bitrate": self.bitrate_combo.currentData(),
            "tx_id": self._parse_hex(self.tx_input.text(), 0x7E0),
            "rx_id": self._parse_hex(self.rx_input.text(), 0x7E8),
            "func_id": self._parse_hex(self.func_input.text(), 0x7DF),
        }
        try:
            self.backend.connect(cfg)
            self.status_label.setText(f"已连接 [{self.backend.name}]")
            self.status_label.setStyleSheet("color: green;")
            self.btn_connect.setText("断开")
            self.log(f"连接成功: {cfg}")
            self.load_freeze_codes()
        except NotImplementedError as e:
            QMessageBox.warning(self, "未实现", str(e))
            self.log(f"适配器未实现: {e}")
        except Exception as e:
            QMessageBox.critical(self, "连接失败", str(e))
            self.log(f"连接失败: {e}\n{traceback.format_exc()}")

    def load_freeze_codes(self):
        self.freeze_combo.clear()
        try:
            for code, _, _ in self.backend.read_dtcs():
                self.freeze_combo.addItem(code)
        except Exception as e:
            self.log(f"加载故障码失败: {e}")

    def read_dtcs(self):
        if not self.backend.connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        try:
            dtcs = self.backend.read_dtcs()
        except Exception as e:
            self.log(f"读取故障码失败: {e}")
            QMessageBox.critical(self, "错误", str(e))
            return
        self.dtc_table.setRowCount(0)
        for row, (code, status, desc) in enumerate(dtcs):
            self.dtc_table.insertRow(row)
            self.dtc_table.setItem(row, 0, QTableWidgetItem(code))
            self.dtc_table.setItem(row, 1, QTableWidgetItem(status))
            self.dtc_table.setItem(row, 2, QTableWidgetItem(desc))
        self.load_freeze_codes()
        self.log(f"读取故障码完成，共 {len(dtcs)} 条")

    def clear_dtcs(self):
        if not self.backend.connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        try:
            self.backend.clear_dtcs()
        except Exception as e:
            self.log(f"清除故障码失败: {e}")
            QMessageBox.critical(self, "错误", str(e))
            return
        self.dtc_table.setRowCount(0)
        self.load_freeze_codes()
        self.log("已清除故障码")

    def read_freeze(self):
        if not self.backend.connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        code = self.freeze_combo.currentText()
        if not code:
            QMessageBox.warning(self, "提示", "没有可读取的故障码")
            return
        try:
            data = self.backend.read_freeze_frame(code)
        except Exception as e:
            self.log(f"读取冻结帧失败: {e}")
            QMessageBox.critical(self, "错误", str(e))
            return
        self.freeze_table.setRowCount(0)
        for row, (item, value, unit) in enumerate(data):
            self.freeze_table.insertRow(row)
            self.freeze_table.setItem(row, 0, QTableWidgetItem(item))
            self.freeze_table.setItem(row, 1, QTableWidgetItem(value))
            self.freeze_table.setItem(row, 2, QTableWidgetItem(unit))
        self.log(f"读取冻结帧 {code} 完成，共 {len(data)} 项")

    def start_data_stream(self):
        if not self.backend.connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        self.timer.start(500)
        self.log("开始读取数据流")

    def stop_data_stream(self):
        self.timer.stop()
        self.log("停止读取数据流")

    def update_data_stream(self):
        if not self.backend.connected:
            self.timer.stop()
            return
        try:
            data = self.backend.read_data_stream()
        except Exception as e:
            self.log(f"读数据流失败: {e}")
            return
        self.data_table.setRowCount(0)
        for row, item in enumerate(data):
            self.data_table.insertRow(row)
            did = item["did"]
            did_str = f"0x{did:04X}" if isinstance(did, int) else str(did)
            self.data_table.setItem(row, 0, QTableWidgetItem(did_str))
            self.data_table.setItem(row, 1, QTableWidgetItem(item["name"]))
            self.data_table.setItem(row, 2, QTableWidgetItem(str(item["value"])))
            self.data_table.setItem(row, 3, QTableWidgetItem(item["unit"]))
        # 更新 VIN / 电压
        for item in data:
            if item["name"] == "VIN":
                self.vin_label.setText(f"VIN: {item['value']}")
            elif item["name"] == "蓄电池电压":
                self.voltage_label.setText(f"电压: {item['value']} V")

    def write_param(self):
        if not self.backend.connected:
            QMessageBox.warning(self, "提示", "请先连接")
            return
        did = self.did_input.text().strip()
        value = self.value_input.text().strip()
        if not did or not value:
            QMessageBox.warning(self, "提示", "请输入 DID 和值")
            return
        try:
            ok = self.backend.write_param(did, value)
        except UdsNegativeResponse as e:
            self.log(f"参数写入被拒: {e}")
            QMessageBox.warning(self, "负响应", str(e))
            return
        except Exception as e:
            self.log(f"参数写入失败: {e}")
            QMessageBox.critical(self, "错误", str(e))
            return
        self.log(f"参数写入 {'成功' if ok else '失败'}: DID={did}, 值={value}")

    def log(self, msg):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{t}] {msg}")


def main():
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        screen = app.primaryScreen().availableGeometry()
        w, h = 1200, 800
        x = (screen.width() - w) // 2
        y = (screen.height() - h) // 2
        window.move(x, y)
        window.show()
        window.raise_()
        window.activateWindow()
        window.setWindowState(window.windowState() | Qt.WindowActive)
        sys.exit(app.exec())
    except Exception:
        log_file("主程序异常:\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
