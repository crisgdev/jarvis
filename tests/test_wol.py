import unittest
from unittest import mock

from tools import system
from tools.system import _wol_payload


class FakeSocket:
    def __init__(self):
        self.sent = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def setsockopt(self, *_):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))


class WolTest(unittest.TestCase):
    def test_payload_correcto(self):
        payload = _wol_payload("B0:6E:BF:11:1A:4C")
        self.assertEqual(len(payload), 102)
        self.assertEqual(payload[:6], b"\xff" * 6)
        mac = bytes.fromhex("b06ebf111a4c")
        self.assertEqual(payload[6:], mac * 16)

    def test_payload_ignora_separadores(self):
        self.assertEqual(_wol_payload("b0:6e:bf:11:1a:4c"), _wol_payload("b06ebf111a4c"))

    def test_payload_mac_invalida(self):
        with self.assertRaises(ValueError):
            _wol_payload("hola")

    def test_wake_on_lan_sin_mac_error(self):
        with mock.patch.object(system, "get_config", return_value={"wol": {}}):
            result = system._wake_on_lan()
        self.assertIn("error", result)

    def test_wake_on_lan_mac_invalida(self):
        with mock.patch.object(system, "get_config", return_value={"wol": {"mac": "xyz"}}):
            result = system._wake_on_lan()
        self.assertIn("error", result)

    def test_wake_on_lan_envia_paquete(self):
        fake = FakeSocket()
        with mock.patch.object(system, "get_config", return_value={
            "wol": {"mac": "B0:6E:BF:11:1A:4C", "broadcast": "192.168.1.255", "port": 9}
        }), mock.patch("socket.socket", return_value=fake):
            result = system._wake_on_lan()

        self.assertIn("result", result)
        self.assertEqual(len(fake.sent), 1)
        data, addr = fake.sent[0]
        self.assertEqual(len(data), 102)
        self.assertEqual(addr, ("192.168.1.255", 9))


if __name__ == "__main__":
    unittest.main()