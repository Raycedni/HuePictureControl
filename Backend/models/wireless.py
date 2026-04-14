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


class WirelessSessionResponse(BaseModel):
    session_id: str
    source_type: str          # "miracast" | "android_scrcpy"
    device_path: str
    status: str               # "starting" | "active" | "error" | "stopped"
    error_message: str | None = None
    started_at: str


class SessionsResponse(BaseModel):
    sessions: list[WirelessSessionResponse]
