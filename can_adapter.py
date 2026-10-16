"""
多厂商 CAN 适配器抽象层。

支持的厂商:
    PCAN        - 通过 python-can (需要 PCAN-Basic 驱动)
    Kvaser      - 通过 python-can (需要 Kvaser CANlib 驱动)
    ZLG 2EU     - 周立功，需要 ControlCAN.dll 或 zlgcan
    ZLG EU      - 周立功，需要 ControlCAN.dll 或 zlgcan
    ZLG USBCAN1 - 周立功，需要 ControlCAN.dll 或 zlgcan
    ZLG USBCAN2 - 周立功，需要 ControlCAN.dll 或 zlgcan
    创芯科技     - 需要厂家 DLL

所有适配器都实现同一套接口:
    open()  -> bool
    close()
    send(can_id, data, extended=False)
    recv(timeout=0.1) -> CanFrame | None
"""
import time
from abc import ABC, abstractmethod


# 支持的厂商清单（供 GUI 下拉框使用）
VENDORS = [
    "PCAN",
    "Kvaser",
    "ZLG 2EU",
    "ZLG EU",
    "ZLG USBCAN1",
    "ZLG USBCAN2",
    "创芯科技",
]

# 可选波特率
BITRATES = [250000, 500000]


class CanFrame:
    __slots__ = ("can_id", "data", "extended", "timestamp")

    def __init__(self, can_id, data, extended=False, timestamp=None):
        self.can_id = can_id
        self.data = bytes(data)
        self.extended = extended
        self.timestamp = timestamp if timestamp is not None else time.time()

    def __repr__(self):
        return f"<CanFrame id=0x{self.can_id:X} data={self.data.hex(' ').upper()}>"


class CanAdapter(ABC):
    """所有厂商适配器的基类。"""
    name = "abstract"

    def __init__(self, channel=None, bitrate=500000):
        self.channel = channel
        self.bitrate = bitrate
        self._opened = False

    @property
    def is_open(self):
        return self._opened

    @abstractmethod
    def open(self):
        ...

    @abstractmethod
    def close(self):
        ...

    @abstractmethod
    def send(self, can_id, data, extended=False):
        ...

    @abstractmethod
    def recv(self, timeout=0.1):
        ...


# ============================================================
# PCAN
# ============================================================
class PcanAdapter(CanAdapter):
    name = "PCAN"

    def open(self):
        import can
        channel = self.channel or "PCAN_USBBUS1"
        self._bus = can.interface.Bus(
            interface="pcan",
            channel=channel,
            bitrate=self.bitrate,
        )
        self._opened = True
        return True

    def close(self):
        if self._opened:
            try:
                self._bus.shutdown()
            finally:
                self._opened = False

    def send(self, can_id, data, extended=False):
        import can
        msg = can.Message(
            arbitration_id=can_id,
            data=bytes(data),
            is_extended_id=extended,
        )
        self._bus.send(msg)

    def recv(self, timeout=0.1):
        msg = self._bus.recv(timeout=timeout)
        if msg is None:
            return None
        return CanFrame(msg.arbitration_id, msg.data,
                        msg.is_extended_id, msg.timestamp)


# ============================================================
# Kvaser
# ============================================================
class KvaserAdapter(CanAdapter):
    name = "Kvaser"

    def open(self):
        import can
        channel = int(self.channel) if self.channel not in (None, "") else 0
        self._bus = can.interface.Bus(
            interface="kvaser",
            channel=channel,
            bitrate=self.bitrate,
        )
        self._opened = True
        return True

    def close(self):
        if self._opened:
            try:
                self._bus.shutdown()
            finally:
                self._opened = False

    def send(self, can_id, data, extended=False):
        import can
        msg = can.Message(
            arbitration_id=can_id,
            data=bytes(data),
            is_extended_id=extended,
        )
        self._bus.send(msg)

    def recv(self, timeout=0.1):
        msg = self._bus.recv(timeout=timeout)
        if msg is None:
            return None
        return CanFrame(msg.arbitration_id, msg.data,
                        msg.is_extended_id, msg.timestamp)


# ============================================================
# 周立功 ZLG（2EU / EU / USBCAN1 / USBCAN2）
# ============================================================
class ZlgAdapter(CanAdapter):
    """
    周立功设备适配器。

    你需要补齐下面 4 个方法。典型做法：
        pip install zlgcan    # 官方 SDK (如可用)
    或用 ctypes 调用 ControlCAN.dll:
        VCI_OpenDevice / VCI_InitCAN / VCI_StartCAN / VCI_Transmit / VCI_Receive

    设备类型号 (按 ZLG ControlCAN.h):
        VCI_USBCAN1     = 3
        VCI_USBCAN2     = 4
        VCI_USBCAN_E_U  = 20
        VCI_USBCAN_2E_U = 21

    波特率 (BTR0, BTR1):
        250k -> (0x01, 0x1C)
        500k -> (0x00, 0x1C)
    """
    name = "ZLG"

    DEVICE_TYPE_MAP = {
        "ZLG 2EU":      21,
        "ZLG EU":       20,
        "ZLG USBCAN1":  3,
        "ZLG USBCAN2":  4,
    }

    BTR_MAP = {
        250000: (0x01, 0x1C),
        500000: (0x00, 0x1C),
    }

    def __init__(self, channel=None, bitrate=500000, model="ZLG USBCAN2"):
        super().__init__(channel, bitrate)
        self.model = model
        self.dev_type = self.DEVICE_TYPE_MAP.get(model, 4)
        self.dev_index = 0
        self.can_index = 0
        if channel not in (None, ""):
            try:
                self.can_index = int(channel)
            except ValueError:
                self.can_index = 0
        self._dll = None

    def open(self):
        # ================== TODO: 补全 ==================
        # 1. 加载 DLL：
        #    self._dll = ctypes.WinDLL("ControlCAN.dll")
        #    或 from zlgcan import ZCAN
        # 2. 打开设备：
        #    self._dll.VCI_OpenDevice(self.dev_type, self.dev_index, 0)
        # 3. 初始化 CAN：
        #    btr0, btr1 = self.BTR_MAP[self.bitrate]
        #    init_config = VCI_INIT_CONFIG(... btr0, btr1 ...)
        #    self._dll.VCI_InitCAN(self.dev_type, self.dev_index, self.can_index, ...)
        # 4. 启动：
        #    self._dll.VCI_StartCAN(self.dev_type, self.dev_index, self.can_index)
        # self._opened = True
        # return True
        raise NotImplementedError(
            f"{self.model} 适配器未实现。请按注释在 can_adapter.py 的 "
            f"ZlgAdapter.open() 中补全。"
        )

    def close(self):
        # TODO: VCI_CloseDevice(self.dev_type, self.dev_index)
        raise NotImplementedError("ZLG close() 未实现")

    def send(self, can_id, data, extended=False):
        # TODO: 组装 VCI_CAN_OBJ 并 VCI_Transmit
        raise NotImplementedError("ZLG send() 未实现")

    def recv(self, timeout=0.1):
        # TODO: VCI_Receive，返回 CanFrame
        raise NotImplementedError("ZLG recv() 未实现")


# ============================================================
# 创芯科技
# ============================================================
class ChuangxinAdapter(CanAdapter):
    """
    创芯科技 USB-CAN 适配器（CanalystII 等）。

    需要厂家提供的 DLL。补齐下面 4 个方法。
    """
    name = "创芯科技"

    def open(self):
        raise NotImplementedError(
            "创芯科技适配器未实现。请在 can_adapter.py 的 "
            "ChuangxinAdapter.open() 中按厂家 DLL 补全。"
        )

    def close(self):
        raise NotImplementedError("创芯 close() 未实现")

    def send(self, can_id, data, extended=False):
        raise NotImplementedError("创芯 send() 未实现")

    def recv(self, timeout=0.1):
        raise NotImplementedError("创芯 recv() 未实现")


# ============================================================
# 工厂
# ============================================================
def create_adapter(vendor, channel=None, bitrate=500000):
    if vendor == "PCAN":
        return PcanAdapter(channel, bitrate)
    if vendor == "Kvaser":
        return KvaserAdapter(channel, bitrate)
    if vendor in ZlgAdapter.DEVICE_TYPE_MAP:
        return ZlgAdapter(channel, bitrate, vendor)
    if vendor == "创芯科技":
        return ChuangxinAdapter(channel, bitrate)
    raise ValueError(f"未知的 CAN 厂商: {vendor}")
