# 📍 LIO-SAM — Understanding and Tuning `mappingSurfLeafSize`

This document explains **what `mappingSurfLeafSize` does**, how it fits into the **LIO-SAM pipeline**, and how it impacts **localization quality**, **mapping performance**, and **feature processing**.

---

## 🧭 1. Overview of LIO-SAM Pipeline

```

LiDAR + IMU
│
▼
[ ImageProjection ]
│ publishes /lio_sam/deskew/cloud_deskewed + cloud_info
▼
[ FeatureExtraction ]
│ publishes /lio_sam/feature/cloud_corner & cloud_surface
▼
[ mapOptimization ]
│ uses mappingSurfLeafSize for scan-to-map alignment
├─ publishes /lio_sam/mapping/odometry_incremental
└─ updates map (local & global)

````

- **ImageProjection**: Deskews LiDAR points using IMU.  
- **FeatureExtraction**: Extracts corner & surface features from deskewed points.  
- **mapOptimization**: Performs scan-to-map optimization (the actual localization step).

---

## 🧱 2. What `mappingSurfLeafSize` Controls

`mappingSurfLeafSize` sets the **voxel leaf size** for **downsampling surface features** during mapping.

Specifically:
- Downsamples **local surf map** (`laserCloudSurfFromMapDS`)  
- Downsamples **current scan’s surf features** (`laserCloudSurfLastDS`)  
- Downsamples surf features for **ICP loop closure** (`downSizeFilterICP`)

This parameter affects:
- **Map resolution & density**
- **Optimization speed**
- **Localization accuracy**

---

## 🧠 3. What It Does *Not* Affect Directly

- ❌ **ImageProjection**  
  - Does not use mappingSurfLeafSize at all.  
  - Deskewing relies on IMU (and optionally odometry), not mapping resolution.

- ❌ **FeatureExtraction**  
  - Uses its own `odometrySurfLeafSize` to downsample features.  
  - Changing mappingSurfLeafSize does not change extracted features.

- ✅ *Indirectly*, mappingSurfLeafSize can change the **incremental odometry** published by the mapping node.  
  - ImageProjection uses this only as an **initial guess**, not for deskewing (unless positional deskew is enabled).

---

## 📊 4. Effect on Localization

| `mappingSurfLeafSize` | Pros | Cons | Localization Impact |
|------------------------|------|------|----------------------|
| **Small (e.g., 0.1 m)** | High detail, precise matching | High CPU cost, sensitive to noise | ✅ More accurate poses (if clean data) |
| **Medium (e.g., 0.3 m)** | Balanced performance | — | ⚖️ Good default |
| **Large (e.g., 0.5 m)** | Faster, more robust to noise | Less detail, weaker constraints | ⚠️ Risk of drift/slippage |

**Too large** → map too coarse → optimizer has fewer constraints → poor localization.  
**Too small** → heavier compute, potential overfitting to noisy features.

---

## 🧪 5. Practical Tuning Guidelines

| Environment | Sensor | Recommended surfLeafSize |
|-------------|---------|---------------------------|
| Structured indoor | Velodyne 16/32, Ouster 64 | `0.1 m – 0.2 m` |
| Outdoor urban | Velodyne/Ouster | `0.2 m – 0.3 m` |
| Forest / unstructured | Velodyne/Ouster | `0.3 m – 0.5 m` |

Tips:
- Start at **0.3 m** and adjust based on performance.
- Check `/lio_sam/mapping/map_local` in RViz to see map density.
- Watch `/lio_sam/mapping/odometry_incremental` for trajectory smoothness.
- If the system is slow or unstable:
  - Increase surfLeafSize slightly for speed.
  - Decrease it if losing detail or drifting.

---

## 🧰 6. Adjusting at Runtime

LIO-SAM lets you update this parameter on the fly:

```bash
# Example: set mappingSurfLeafSize to 0.2 m
rostopic pub -1 /lio_sam/params/mapping_surf_leaf_size std_msgs/Float32 "data: 0.2"
````

You should see:

```
[ INFO] Updated mappingSurfLeafSize to 0.200000 at runtime
```

This affects:

* `downSizeFilterSurf`
* `downSizeFilterICP`
* Future map optimization cycles

---

## 🛰️ 7. Recommended RViz Topics

| Topic                                   | What it shows                | Affected by `mappingSurfLeafSize` |
| --------------------------------------- | ---------------------------- | --------------------------------- |
| `/lio_sam/deskew/cloud_deskewed`        | Raw deskewed LiDAR points    | ❌ No                              |
| `/lio_sam/feature/cloud_surface`        | Extracted surf features      | ❌ No                              |
| `/lio_sam/mapping/map_local`            | Downsampled local map        | ✅ Yes                             |
| `/lio_sam/mapping/cloud_registered`     | Downsampled current features | ✅ Yes                             |
| `/lio_sam/mapping/odometry_incremental` | Pose / localization output   | ✅ Yes                             |

---

## 🧠 8. Key Takeaways

* `mappingSurfLeafSize` does **not** change what features are extracted.
* It **directly impacts scan-to-map alignment** — i.e., your **localization accuracy**.
* Smaller = more detail, more compute. Larger = coarser, faster, but less accurate.
* Proper tuning can significantly reduce drift and improve loop closure.

---

## 📝 References

* [LIO-SAM Paper (J. Zhang & S. Singh)](https://arxiv.org/abs/2007.00258)
* [LIO-SAM GitHub Repository](https://github.com/TixiaoShan/LIO-SAM)
* Discussions & tuning notes from community experiments

