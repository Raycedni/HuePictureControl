from pydantic import BaseModel


class BridgeCredentials(BaseModel):
    bridge_id: str
    rid: str
    ip_address: str
    username: str
    hue_app_id: str
    client_key: str
    swversion: int
    name: str


class PairRequest(BaseModel):
    bridge_ip: str


class PairResponse(BaseModel):
    status: str
    bridge_ip: str
    bridge_name: str


class EntertainmentConfigResponse(BaseModel):
    id: str
    name: str
    status: str
    channel_count: int


class LightResponse(BaseModel):
    id: str
    name: str
    type: str
    is_gradient: bool = False
    points_capable: int = 0


class BridgeStatusResponse(BaseModel):
    paired: bool
    bridge_ip: str | None = None
    bridge_name: str | None = None
