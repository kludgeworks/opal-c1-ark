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

    # Hardware ISP: downscale 4K raw Bayer to 1080p directly on-die (0 ms overhead)
    cam.setIspScale(1, 2)
    # Native full 4K output for the H.265 encoder
    cam.setVideoSize(3840, 2160)

    # 3. UVC Output (Streams 1080p uncompressed NV12 from hardware ISP)
    uvc = pipeline.create(dai.node.UVC)
    cam.isp.link(uvc.input)

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
