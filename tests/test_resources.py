from auralwarden.models import ResourceSnapshot
from auralwarden.resources import AdaptiveLoadController, LoadProfile


def snapshot(cpu: float = 20, gpu: float = 30, ram: float = 40) -> ResourceSnapshot:
    return ResourceSnapshot(cpu_percent=cpu, gpu_percent=gpu, memory_percent=ram)


def test_adaptation_requires_sustained_pressure_and_recovers_gradually() -> None:
    controller = AdaptiveLoadController()

    assert controller.update(snapshot(cpu=88)) == LoadProfile.NORMAL
    assert controller.update(snapshot(cpu=88)) == LoadProfile.CONSTRAINED
    assert controller.update(snapshot(cpu=96)) == LoadProfile.CONSTRAINED
    assert controller.update(snapshot(cpu=96)) == LoadProfile.CRITICAL
    assert controller.update(snapshot(cpu=40)) == LoadProfile.CRITICAL
    assert controller.update(snapshot(cpu=40)) == LoadProfile.CRITICAL
    assert controller.update(snapshot(cpu=40)) == LoadProfile.NORMAL


def test_adaptation_considers_memory_and_vram_pressure() -> None:
    controller = AdaptiveLoadController()
    ram_pressure = snapshot(ram=90)
    assert controller.update(ram_pressure) == LoadProfile.NORMAL
    assert controller.update(ram_pressure) == LoadProfile.CONSTRAINED
    assert controller.pressure_source == "ram"

    vram_pressure = ResourceSnapshot(
        cpu_percent=10,
        gpu_percent=20,
        memory_percent=30,
        vram_used_mb=7900,
        vram_total_mb=8000,
    )
    assert controller.update(vram_pressure) == LoadProfile.CONSTRAINED
    assert controller.update(vram_pressure) == LoadProfile.CRITICAL
    assert controller.pressure_source == "vram"
