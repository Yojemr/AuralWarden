from auralwarden.hardware import (
    GpuAdapter,
    HardwareCapabilities,
    hardware_summary,
    select_inference_plan,
)


def test_auto_plan_uses_cuda_and_turbo_on_nvidia_with_enough_vram() -> None:
    capabilities = HardwareCapabilities(
        physical_cores=8,
        logical_cores=16,
        memory_gb=32,
        gpus=(GpuAdapter("NVIDIA GeForce RTX 3060", "nvidia", 12_288),),
        cuda_available=True,
        cuda_compute_types=("float16", "int8_float16"),
    )
    plan = select_inference_plan(capabilities)
    assert plan.backend == "faster_whisper"
    assert plan.device == "cuda"
    assert plan.compute_type == "float16"
    assert plan.model_candidates[0] == "large-v3-turbo"


def test_low_power_plan_is_portable_cpu_and_limits_threads() -> None:
    capabilities = HardwareCapabilities(
        physical_cores=4,
        logical_cores=8,
        memory_gb=8,
        gpus=(GpuAdapter("AMD Radeon Graphics", "amd", 2_048),),
    )
    plan = select_inference_plan(capabilities, performance_mode="low_power")
    assert plan.backend == "faster_whisper"
    assert plan.device == "cpu"
    assert plan.compute_type == "int8"
    assert plan.cpu_threads == 2
    assert plan.model_candidates[0] == "tiny"


def test_nvidia_without_cuda_recommends_installing_optional_acceleration() -> None:
    capabilities = HardwareCapabilities(
        physical_cores=8,
        logical_cores=16,
        memory_gb=32,
        gpus=(GpuAdapter("NVIDIA GeForce RTX 3060", "nvidia", 12_288),),
        cuda_available=False,
    )
    plan = select_inference_plan(capabilities)

    assert plan.device == "cpu"
    assert capabilities.cuda_setup_recommended
    assert capabilities.preferred_cuda_model == "large-v3-turbo"
    summary = hardware_summary(capabilities, plan)
    assert "Configuración disponible" in summary
    assert "Configuración ideal detectada: NVIDIA CUDA + large-v3-turbo" in summary


def test_amd_uses_configured_whisper_cpp_vulkan_component(tmp_path) -> None:
    executable = tmp_path / "whisper-cli.exe"
    model = tmp_path / "ggml-small.bin"
    executable.write_bytes(b"exe")
    model.write_bytes(b"model")
    capabilities = HardwareCapabilities(
        physical_cores=8,
        logical_cores=16,
        memory_gb=16,
        gpus=(GpuAdapter("AMD Radeon RX 7600", "amd", 8_192),),
        whisper_cpp_executable=str(executable),
    )
    plan = select_inference_plan(
        capabilities,
        whisper_cpp_model=str(model),
        whisper_cpp_acceleration="vulkan",
    )
    assert plan.backend == "whisper_cpp"
    assert plan.device == "vulkan"
    assert plan.whisper_cpp_model == str(model.resolve())


def test_missing_whisper_cpp_component_falls_back_safely_to_cpu(tmp_path) -> None:
    capabilities = HardwareCapabilities(6, 12, 16)
    plan = select_inference_plan(
        capabilities,
        backend="whisper_cpp",
        whisper_cpp_model=str(tmp_path / "missing.bin"),
    )
    assert plan.backend == "faster_whisper"
    assert plan.device == "cpu"
