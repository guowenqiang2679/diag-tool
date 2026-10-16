"""
UDS 客户端 (ISO 14229)。

所有服务都在这个文件里，方便你按 ECU 实际情况修改。

基础传输：
    request(service, data, functional=False) -> bytes
    返回正响应去掉 SID+0x40 之后的字节。负响应抛 UdsNegativeResponse。
"""
from isotp import IsoTp, IsoTpError


class UdsError(Exception):
    pass


class UdsNegativeResponse(UdsError):
    def __init__(self, sid, nrc):
        self.sid = sid
        self.nrc = nrc
        super().__init__(f"负响应 SID=0x{sid:02X} NRC=0x{nrc:02X} ({NRC_TEXT.get(nrc, '未知')})")


NRC_TEXT = {
    0x10: "一般拒绝",
    0x11: "服务不支持",
    0x12: "子功能不支持",
    0x13: "报文长度或格式错误",
    0x14: "响应过长",
    0x21: "忙，请重试",
    0x22: "条件不满足",
    0x24: "请求序列错误",
    0x31: "请求超出范围",
    0x33: "安全访问被拒",
    0x35: "无效密钥",
    0x36: "超过尝试次数",
    0x37: "延时未到",
    0x70: "上传下载未接受",
    0x71: "传输中止",
    0x72: "编程失败",
    0x73: "块序号错误",
    0x78: "响应挂起",
    0x7E: "子功能当前会话不支持",
    0x7F: "当前会话不支持该服务",
}


def decode_dtc(b1, b2, b3):
    """3 字节 DTC -> 字符串，例如 P0301"""
    letters = ["P", "C", "B", "U"]
    letter = letters[(b1 >> 6) & 0x03]
    d1 = (b1 >> 4) & 0x03
    d2 = (b2 >> 4) & 0x0F
    d3 = b2 & 0x0F
    d4 = (b3 >> 4) & 0x0F
    return f"{letter}{d1}{d2}{d3}{d4}"


class UdsClient:
    def __init__(self, adapter, tx_id=0x7E0, rx_id=0x7E8, func_id=0x7DF, timeout=1.0):
        self.adapter = adapter
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.func_id = func_id
        self.isotp = IsoTp(adapter, tx_id, rx_id, timeout=timeout)

    # ============================================================
    # 基础请求
    # ============================================================
    def request(self, service, data=b"", timeout=None):
        """
        发送 UDS 请求，返回正响应数据（去掉 SID+0x40）。
        负响应抛 UdsNegativeResponse。
        """
        req = bytes([service]) + bytes(data)
        resp = self.isotp.request(req, timeout=timeout)
        if not resp:
            raise UdsError("空响应")

        if resp[0] == 0x7F:
            if len(resp) < 3:
                raise UdsError("负响应格式错误")
            raise UdsNegativeResponse(resp[1], resp[2])

        expected = (service + 0x40) & 0xFF
        if resp[0] != expected:
            raise UdsError(f"响应 SID 不匹配: 期望 0x{expected:02X}, 收到 0x{resp[0]:02X}")
        return resp[1:]

    # ============================================================
    # 0x10 诊断会话控制
    # ============================================================
    def diagnostic_session_control(self, session_type=0x03):
        """
        01=默认, 02=编程, 03=扩展, 04=安全系统
        """
        return self.request(0x10, bytes([session_type]))

    # ============================================================
    # 0x11 ECU 复位
    # ============================================================
    def ecu_reset(self, reset_type=0x01):
        return self.request(0x11, bytes([reset_type]))

    # ============================================================
    # 0x14 清除诊断信息（清故障码）
    # ============================================================
    def clear_diagnostic_information(self, group=0xFFFFFF):
        """
        group: 3 字节组号，0xFFFFFF 表示所有。
        """
        g = bytes([(group >> 16) & 0xFF, (group >> 8) & 0xFF, group & 0xFF])
        return self.request(0x14, g)

    # ============================================================
    # 0x19 读取 DTC 信息
    # ============================================================
    def read_dtc_by_status_mask(self, status_mask=0xFF):
        """
        0x19 0x02: reportDTCByStatusMask
        返回 [(dtc_str, status_byte), ...]
        """
        data = self.request(0x19, bytes([0x02, status_mask]))
        # data = [0x02, availability_mask, dtc1_hi, dtc1_mid, dtc1_lo, st1, ...]
        if len(data) < 2:
            return []
        records = data[2:]
        result = []
        for i in range(0, len(records) - 3, 4):
            b1, b2, b3, st = records[i:i + 4]
            result.append((decode_dtc(b1, b2, b3), st))
        return result

    def read_dtc_snapshot(self, dtc_bytes, record=0xFF):
        """
        0x19 0x04: reportDTCSnapshotRecordByDTCNumber
        dtc_bytes: 3 字节 DTC 原始值, 例如 b'\\x00\\x30\\x10' 表示 P0301
        返回原始响应字节, 你自己解析。
        """
        return self.request(0x19, bytes([0x04]) + bytes(dtc_bytes) + bytes([record]))

    def read_dtc_extended_data(self, dtc_bytes, record=0xFF):
        """0x19 0x06"""
        return self.request(0x19, bytes([0x06]) + bytes(dtc_bytes) + bytes([record]))

    # ============================================================
    # 0x22 读数据流
    # ============================================================
    def read_data_by_identifier(self, did):
        """返回该 DID 的原始字节（去掉 SID 和 DID 本身）"""
        data = self.request(0x22, bytes([(did >> 8) & 0xFF, did & 0xFF]))
        # data = [did_hi, did_lo, payload...]
        if len(data) < 2:
            raise UdsError(f"DID 0x{did:04X} 响应过短")
        return data[2:]

    # ============================================================
    # 0x27 安全访问
    # ============================================================
    def security_access_request_seed(self, level):
        """返回种子字节"""
        data = self.request(0x27, bytes([level]))
        # data = [level_echo, seed...]
        return data[1:] if data else b""

    def security_access_send_key(self, level, key_bytes):
        return self.request(0x27, bytes([level + 1]) + bytes(key_bytes))

    # ============================================================
    # 0x2E 写数据（参数写入）
    # ============================================================
    def write_data_by_identifier(self, did, value_bytes):
        payload = bytes([(did >> 8) & 0xFF, did & 0xFF]) + bytes(value_bytes)
        return self.request(0x2E, payload)

    # ============================================================
    # 0x31 例程控制
    # ============================================================
    def routine_control(self, sub, routine_id, data=b""):
        """
        sub: 0x01 启动, 0x02 停止, 0x03 请求结果
        """
        payload = bytes([sub,
                         (routine_id >> 8) & 0xFF, routine_id & 0xFF]) + bytes(data)
        return self.request(0x31, payload)

    # ============================================================
    # 0x3E TesterPresent
    # ============================================================
    def tester_present(self, suppress=True):
        sub = 0x80 if suppress else 0x00
        return self.request(0x3E, bytes([sub]))
