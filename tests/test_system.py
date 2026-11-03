from types import SimpleNamespace as NS

from sensor_bridge.sources.system import SystemSource, pick_cpu_temp


def T(label, current):
    return NS(label=label, current=current)


def test_pick_intel_package_temp():
    temps = {"acpitz": [T("", 30.0)], "coretemp": [T("Core 0", 50.0), T("Package id 0", 55.04), T("Core 1", 57.0)]}
    assert pick_cpu_temp(temps) == 55.0


def test_pick_rpi_and_preferred_and_none():
    assert pick_cpu_temp({"cpu_thermal": [T("", 48.3)]}) == 48.3
    assert pick_cpu_temp({"coretemp": [T("Core 0", 40.0)], "nvme": [T("Composite", 35.0)]}, "nvme") == 35.0
    assert pick_cpu_temp({"coretemp": [T("Core 0", 40.0), T("Core 1", 44.0)]}) == 44.0
    assert pick_cpu_temp({}) is None


class FakePsutil:
    def cpu_percent(self, interval=None):
        return 12.34

    def virtual_memory(self):
        return NS(percent=41.6, total=8 * 2**30, available=5 * 2**30)

    def disk_usage(self, path):
        return NS(percent=63.2)

    def sensors_temperatures(self):
        return {"cpu_thermal": [T("", 51.2)]}


def test_reading_from_host():
    src = SystemSource({"type": "system", "hostname": "g2labs-rpi"}, {}, psutil_module=FakePsutil())
    r = src.reading()
    assert r.device_id == "host_g2labs_rpi"
    assert r.aliases == ("g2labs-rpi",)
    assert r.values == {"cpu_usage": 12.3, "memory_usage": 41.6, "memory_used": 3072,
                        "disk_usage": 63.2, "cpu_temperature": 51.2}


def test_no_temperature_support():
    ps = FakePsutil()
    ps.sensors_temperatures = lambda: {}
    r = SystemSource({"hostname": "pc"}, {}, psutil_module=ps).reading()
    assert "cpu_temperature" not in r.values
