from pydantic import BaseModel


class ToolInfo(BaseModel):
    available: bool
    version: str


class NicCapability(BaseModel):
    p2p_supported: bool
    interface: str | None = None


class CapabilitiesResponse(BaseModel):
    ffmpeg: ToolInfo
    scrcpy: ToolInfo
    adb: ToolInfo
    iw: ToolInfo
    nic: NicCapability
    ready: bool
    miracast_ready: bool
    scrcpy_ready: bool


class ScrcpyStartRequest(BaseModel):
    device_ip: str   # Validated by ipaddress.ip_address() in PipelineManager
    device_port: int = 5555   # Default 5555 (classic adb tcpip). Android 11+ Wireless Debugging uses a dynamic port.


class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str          # "miracast" | "android_scrcpy"
    device_path: str
    status: str               # "starting" | "active" | "error" | "stopped"
    error_message: str | None = None
    error_code: str | None = None      # D-04: structured error codes
    started_at: str


class SessionsResponse(BaseModel):
    sessions: list[WirelessSessionResponse]
