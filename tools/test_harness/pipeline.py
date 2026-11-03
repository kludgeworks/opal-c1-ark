# SPDX-License-Identifier: MIT
"""DepthAI pipeline graph construction for Opal C1 dual-stream and standalone modes."""

import depthai as dai


def build_dual_stream_pipeline(
    fps: int = 30,
    bitrate_kbps: int = 25000,
    uvc_width: int = 1920,
    uvc_height: int = 1080,
    camera_name: str = "Opal C1 (Ark Edition)",
) -> dai.Pipeline:
    """Construct the hybrid DepthAI pipeline: 1080p UVC + 4K H.265 + System Telemetry."""
    pipeline = dai.Pipeline()

    # 1. Early UVC USB descriptor configuration (Plug & Play 1080p fallback)
    board_config = dai.BoardConfig()
    uvc_config = dai.BoardConfig.UVC()
    uvc_config.enable = True
    uvc_config.width = uvc_width
    uvc_config.height = uvc_height
    uvc_config.cameraName = camera_name
    board_config.uvc = uvc_config
    pipeline.setBoardConfig(board_config)

    # 2. Configure 48 MP Sony IMX582 Sensor (CAM_A)
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
    cam.setFps(fps)
    cam.setImageOrientation(dai.CameraImageOrientation.ROTATE_180_DEG)
    cam.initialControl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)

    # Native full 4K output for the H.265 encoder
    cam.setVideoSize(3840, 2160)
    # Hardware downscaler for 1080p UVC stream
    cam.setPreviewSize(uvc_width, uvc_height)

    # 3. UVC Output (Streams 1080p uncompressed NV12 from hardware downscaler)
    uvc = pipeline.create(dai.node.UVC)
    cam.preview.link(uvc.input)

    # 4. Hardware H.265 Encoder ASIC (Full 4K @ 25 Mbps CBR)
    enc = pipeline.create(dai.node.VideoEncoder)
    enc.setDefaultProfilePreset(fps, dai.VideoEncoderProperties.Profile.H265_MAIN)
    enc.setBitrateKbps(bitrate_kbps)
    enc.setKeyframeFrequency(fps)  # 1 keyframe per second (GOP 30)
    enc.setRateControlMode(dai.VideoEncoderProperties.RateControlMode.CBR)
    cam.video.link(enc.input)

    # 5. Non-blocking XLinkOut for H.265 (Immunity against UVC starvation)
    xout_h265 = pipeline.create(dai.node.XLinkOut)
    xout_h265.setStreamName("h265")
    xout_h265.input.setBlocking(False)  # CRITICAL: drops oldest frames if host lags
    xout_h265.input.setQueueSize(30)
    enc.bitstream.link(xout_h265.input)

    # 6. Real-time Silicon Health & Thermal Telemetry
    sys_logger = pipeline.create(dai.node.SystemLogger)
    sys_logger.setRate(1.0)  # 1 Hz sample rate
    xout_sys = pipeline.create(dai.node.XLinkOut)
    xout_sys.setStreamName("sysinfo")
    sys_logger.out.link(xout_sys.input)

    return pipeline


def build_standalone_uvc_pipeline(
    fps: int = 30,
    uvc_width: int = 1920,
    uvc_height: int = 1080,
    camera_name: str = "Opal C1 (Ark Edition)",
) -> dai.Pipeline:
    """Construct a pure standalone UVC pipeline for permanent SPI flash storage."""
    pipeline = dai.Pipeline()

    board_config = dai.BoardConfig()
    uvc_config = dai.BoardConfig.UVC()
    uvc_config.enable = True
    uvc_config.width = uvc_width
    uvc_config.height = uvc_height
    uvc_config.cameraName = camera_name
    board_config.uvc = uvc_config
    pipeline.setBoardConfig(board_config)

    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
    cam.setIspScale(1, 2)
    cam.setFps(fps)
    cam.setImageOrientation(dai.CameraImageOrientation.ROTATE_180_DEG)
    cam.initialControl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)

    uvc = pipeline.create(dai.node.UVC)
    cam.video.link(uvc.input)

    return pipeline


def build_companion_pipeline(
    fps: int = 30,
    bitrate_kbps: int = 25000,
) -> dai.Pipeline:
    """Pipeline for the macOS Companion App.

    Streams full 4K H.265 video with interactive camera control (presets,
    digital crop) and system telemetry. Omits UVC nodes to prevent
    UVCAssistant contention (0xe0005000) and idle backpressure stalls.
    """
    pipeline = dai.Pipeline()

    # 1. Configure 48 MP Sony IMX582 Sensor (CAM_A)
    cam = pipeline.create(dai.node.ColorCamera)
    cam.setBoardSocket(dai.CameraBoardSocket.CAM_A)
    cam.setResolution(dai.ColorCameraProperties.SensorResolution.THE_4_K)
    cam.setFps(fps)
    cam.setImageOrientation(dai.CameraImageOrientation.ROTATE_180_DEG)
    cam.initialControl.setAutoFocusMode(dai.CameraControl.AutoFocusMode.CONTINUOUS_VIDEO)
    cam.setVideoSize(3840, 2160)

    # 2. Dynamic Camera Control (Pause, Focus, Exposure)
    xin_control = pipeline.create(dai.node.XLinkIn)
    xin_control.setStreamName("control")
    xin_control.out.link(cam.inputControl)

    # 3. Dynamic ISP Configuration (Lossless e-PTZ crop presets)
    xin_config = pipeline.create(dai.node.XLinkIn)
    xin_config.setStreamName("config")
    xin_config.out.link(cam.inputConfig)

    # 4. Hardware H.265 Encoder ASIC (Full 4K @ 25 Mbps CBR)
    enc = pipeline.create(dai.node.VideoEncoder)
    enc.setDefaultProfilePreset(fps, dai.VideoEncoderProperties.Profile.H265_MAIN)
    enc.setBitrateKbps(bitrate_kbps)
    enc.setKeyframeFrequency(fps)
    enc.setRateControlMode(dai.VideoEncoderProperties.RateControlMode.CBR)
    cam.video.link(enc.input)

    # 5. Non-blocking XLinkOut for 4K bitstream
    xout_h265 = pipeline.create(dai.node.XLinkOut)
    xout_h265.setStreamName("h265")
    xout_h265.input.setBlocking(False)
    xout_h265.input.setQueueSize(30)
    enc.bitstream.link(xout_h265.input)

    # 6. System Health & Thermal Telemetry
    sys_logger = pipeline.create(dai.node.SystemLogger)
    sys_logger.setRate(1.0)
    xout_sys = pipeline.create(dai.node.XLinkOut)
    xout_sys.setStreamName("sysinfo")
    sys_logger.out.link(xout_sys.input)

    return pipeline
