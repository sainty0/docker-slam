# SC-LIO-SAM ROS Interfaces

SC-LIO-SAM exposes a predictable set of ROS topics across its four main nodes:

- **Front-end** (`imageProjection`, `featureExtraction`) handles LiDAR/IMU ingestion and features.
- **Back-end** (`mapOptmization`) publishes odometry, maps, and consumes GPS + loop-closure hints.
- **IMU fusion** (`imuPreintegration`, `TransformFusion`) derive incremental odometry and TFs.

The table below lists every topic touched by those nodes when `rl_vo/launch/lio_stack.launch` loads `config/params_mulran.yaml`.

| Topic Name (default) | Direction | Type | Produced / Consumed by | Description | RL-Relevant |
|---|---|---|---|---|---|
| `/os1_points` (`pointCloudTopic`) | Subscribe | `sensor_msgs/PointCloud2` | imageProjection | Raw MulRan LiDAR stream, reorganised into a range image before deskew (`src/imageProjection.cpp`). | Medium – drives point-count metrics. |
| `/imu/data_raw` (`imuTopic`) | Subscribe | `sensor_msgs/Imu` | imageProjection, IMUPreintegration | IMU queue for deskew and preintegration; converted to LiDAR frame in `ParamServer::imuConverter`. | Medium – IMU RMS appears in RL observations. |
| `odometry/imu_incremental` (`odomTopic+"_incremental"`) | Publish / Subscribe | `nav_msgs/Odometry` | published by IMUPreintegration; consumed by imageProjection & TransformFusion | IMU-only incremental odometry used for deskewing and TF fusion. | Medium – ensures deskew stability the RL agent expects. |
| `odometry/imu` (`odomTopic`) | Publish | `nav_msgs/Odometry` | TransformFusion | Smoothed odometry fused between mapping and IMU; also sources `/tf` for `odom→base_link`. | Low. |
| `odometry/gpsz` (`gpsTopic`) | Subscribe | `nav_msgs/Odometry` | mapOptimization | GPS/navsat odometry queue; fused only when covariance < thresholds (`mapOptmization.cpp:1682+`). | Low. |
| `lio_loop/loop_closure_detection` | Subscribe | `std_msgs/Float64MultiArray` | mapOptimization | Optional external loop-closure hints (`loopInfoHandler`), currently unused unless another node publishes. | Low. |
| `/lio_sam/deskew/cloud_deskewed` | Publish | `sensor_msgs/PointCloud2` | imageProjection | Deskewed full-resolution cloud with timestamps preserved (`ImageProjection::publishCloud`). | **Yes – `metric_pkg` samples it for `pts_per_scan_*`.** |
| `/lio_sam/deskew/cloud_info` | Publish / Subscribe | `lio_sam/cloud_info` | pub: imageProjection, sub: featureExtraction | Metadata per point (ring indices, ranges, IMU pose, initial guess) used during feature extraction. | Low. |
| `/lio_sam/feature/cloud_info` | Publish / Subscribe | `lio_sam/cloud_info` | pub: featureExtraction, sub: mapOptimization | Propagates extracted feature clouds plus IMU initial guesses into the mapper. | Low. |
| `/lio_sam/feature/cloud_corner` | Publish | `sensor_msgs/PointCloud2` | featureExtraction | Downsampled edge features. | **Yes – metrics exporter counts `corner_pts_*`.** |
| `/lio_sam/feature/cloud_surface` | Publish | `sensor_msgs/PointCloud2` | featureExtraction | Downsampled surface features generated using `odometrySurfLeafSize`. | **Yes – RL observations use `surf_pts_*` and planarity ratios.** |
| `/lio_sam/mapping/odometry` | Publish / Subscribe | `nav_msgs/Odometry` | pub: mapOptimization, sub: TransformFusion | Globally consistent odometry published at map frequency; consumed to fuse with IMU. | Medium – exported to TUM via `odom_to_tum.py` for reward. |
| `/lio_sam/mapping/odometry_incremental` | Publish | `nav_msgs/Odometry` | mapOptimization | Incremental odometry in map frame (after scan-to-map); `metrics_exporter` uses it for odom rates and velocity tokens. | **Yes – RL env subscribes (via `EpisodeOrchestrator`) and uses it for APE.** |
| `/lio_sam/mapping/path` | Publish | `nav_msgs/Path` | mapOptimization | Sliding map path for visualisation. | Low. |
| `/lio_sam/mapping/trajectory` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Key-pose trajectory; intensity encodes keyframe indices. | Low. |
| `/lio_sam/mapping/map_global` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Downsampled global map assembled from all keyframes. | Low (visualisation). |
| `/lio_sam/mapping/map_local` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Local map (recent keyframes) for inspection/debug. | Low. |
| `/lio_sam/mapping/cloud_registered` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Latest deskewed cloud aligned to map (after optimization). | Low. |
| `/lio_sam/mapping/cloud_registered_raw` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Same as above but before downsampling, mainly for debugging. | Low. |
| `/lio_sam/mapping/icp_loop_closure_history_cloud` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | History cloud used during RANSAC loop closure. | Low. |
| `/lio_sam/mapping/icp_loop_closure_corrected_cloud` | Publish | `sensor_msgs/PointCloud2` | mapOptimization | Corrected keyframe cloud after loop closure ICP. | Low. |
| `/lio_sam/mapping/loop_closure_constraints` | Publish | `visualization_msgs/MarkerArray` | mapOptimization | Visual markers for loop-closure edges. | Low. |
| `/lio_sam/imu/path` | Publish | `nav_msgs/Path` | TransformFusion | Recent IMU-integrated path (updated every 0.1 s). | Low. |
| `/lio_sam/params/mapping_surf_leaf_size` | Subscribe | `std_msgs/Float32` | mapOptimization (handler), metric_pkg (for action logging) | Runtime voxel leaf size for surf map downsampling (`mappingSurfLeafSizeHandler`). Values ≤0 are rejected. | **High – RL action topic.** |

### Notes on Frames and TF
- `TransformFusion::imuOdometryHandler` continuously broadcasts the `map→odom` and `odom→base_link` TF frames. Although TF uses `/tf` topics internally, the transforms originate from the SC-LIO-SAM nodes above.
- All point clouds are published in `lidarFrame` (`base_link` by default), while map/odometry topics use `mapFrame`/`odometryFrame`.

### Interaction with Rosbridge, Metrics, and RL
- `metric_pkg/scripts/metrics_exporter.py` subscribes to `/lio_sam/deskew/cloud_deskewed`, `/lio_sam/feature/cloud_surface`, `/lio_sam/feature/cloud_corner`, `/lio_sam/mapping/odometry_incremental`, `/imu/data_raw`, and `/lio_sam/params/mapping_surf_leaf_size`. It aggregates rolling statistics exposed to the RL environment via `/rl_metrics/reset`/`/rl_metrics/commit` (service calls triggered from `EpisodeOrchestrator.commit_metrics()`).
- `EpisodeOrchestrator.set_leaf()` publishes Float32 messages to `/lio_sam/params/mapping_surf_leaf_size` over rosbridge each RL step. `mappingSurfLeafSizeHandler` (lines 610‑627 in `src/mapOptmization.cpp`) locks the map mutex, updates the parameter, and reconfigures `pcl::VoxelGrid` filters on the fly.
- The RL reward uses `/lio_sam/mapping/odometry_incremental` as the pose stream exported by `odom_to_tum.py`. Any topic remapping should keep `topics.odom` in `rl_vo/config/config.yaml` consistent with the mapping output row in the table above.
