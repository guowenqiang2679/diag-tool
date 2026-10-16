"""
最简 ISO-TP (ISO 15765-2) 传输层，默认参数: BS=0, STmin=0。

支持:
    - 单帧 (SF) 收发
    - 首帧 (FF) + 流控 (FC) + 连续帧 (CF) 收发

不依赖 can-isotp 库，方便你在 ZLG / 创芯 DLL 上自定义。
"""
import time


class IsoTpError(Exception):
    pass


class IsoTpTimeout(IsoTpError):
    pass


class IsoTp:
    def __init__(self, adapter, tx_id, rx_id, timeout=1.0, stmin=0.0):
        self.adapter = adapter
        self.tx_id = tx_id
        self.rx_id = rx_id
        self.timeout = timeout
        self.stmin = stmin

    # ---------- 请求 ----------
    def request(self, payload, timeout=None):
        self._send_request(bytes(payload))
        return self._recv_response(timeout if timeout is not None else self.timeout)

    # ---------- 发送 ----------
    def _send_request(self, data):
        if not data:
            raise IsoTpError("空请求")
        if len(data) <= 7:
            # 单帧
            frame = bytes([len(data) & 0x0F]) + data
            self.adapter.send(self.tx_id, frame)
            return

        # 首帧
        ff = bytes([0x10 | ((len(data) >> 8) & 0x0F), len(data) & 0xFF]) + data[:6]
        self.adapter.send(self.tx_id, ff)

        # 等待流控帧
        fc = self._wait_frame(self.rx_id)
        if fc is None:
            raise IsoTpTimeout("等待流控帧超时")
        if (fc[0] & 0xF0) != 0x30:
            raise IsoTpError(f"意外的流控帧: {fc.hex()}")

        # 连续帧
        idx = 6
        seq = 1
        while idx < len(data):
            chunk = data[idx:idx + 7]
            cf = bytes([0x20 | (seq & 0x0F)]) + chunk
            self.adapter.send(self.tx_id, cf)
            idx += 7
            seq = (seq + 1) & 0x0F
            if self.stmin > 0:
                time.sleep(self.stmin)

    # ---------- 接收 ----------
    def _recv_response(self, timeout):
        first = self._wait_frame(self.rx_id, timeout)
        if first is None:
            raise IsoTpTimeout("等待响应超时")

        pci = first[0] & 0xF0
        if pci == 0x00:
            length = first[0] & 0x0F
            return first[1:1 + length]

        if pci == 0x10:
            length = ((first[0] & 0x0F) << 8) | first[1]
            data = bytearray(first[2:])

            # 回复流控: BS=0, STmin=0
            self.adapter.send(self.tx_id, bytes([0x30, 0x00, 0x00]))

            while len(data) < length:
                cf = self._wait_frame(self.rx_id, timeout)
                if cf is None:
                    raise IsoTpTimeout("等待连续帧超时")
                if (cf[0] & 0xF0) != 0x20:
                    continue
                data.extend(cf[1:])
            return bytes(data[:length])

        raise IsoTpError(f"未知 PCI 类型: {first.hex()}")

    def _wait_frame(self, expect_id, timeout=None):
        timeout = timeout if timeout is not None else self.timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = self.adapter.recv(timeout=0.05)
            if f is None:
                continue
            if f.can_id == expect_id:
                return f.data
        return None
