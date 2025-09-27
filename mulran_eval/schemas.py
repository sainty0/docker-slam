from __future__ import annotations
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class RunConfig(BaseModel):
    seq: str
    rate: float = 1.0
    duration_s: int = 160
    full_seq: bool = False
    out_root: str = "/output"
    odom_topic: str = "/lio_sam/mapping/odometry"
    gt_tum_root: str = "/output/gts"
    odom_to_tum: str = "/odom_to_tum.py"
    params_file: Optional[str] = None
    label: str = "base"
    sweep_id: Optional[str] = None

class Params(BaseModel):
    odometrySurfLeafSize: Optional[float] = None
    mappingCornerLeafSize: Optional[float] = None
    mappingSurfLeafSize: Optional[float] = None
    edgeFeatureMinValidNum: Optional[int] = None
    surfFeatureMinValidNum: Optional[int] = None
    edgeThreshold: Optional[float] = None
    surfThreshold: Optional[float] = None

class Metrics(BaseModel):
    ape_rmse_m: Optional[float] = None
    ape_sse: Optional[float] = None
    rpe_trans_1m_rmse_m: Optional[float] = None
    rpe_trans_1s_rmse_m: Optional[float] = None
    rpe_rot_1s_rmse_deg: Optional[float] = None

class RunRecord(BaseModel):
    run_id: str
    timestamp: datetime
    status: str
    wall_time_s: int
    run_dir: str
    est_bag: str
    est_tum: str
    gt_tum: str
    params_sha1: str
    cfg: RunConfig
    params: Params
    metrics: Optional[Metrics] = None
