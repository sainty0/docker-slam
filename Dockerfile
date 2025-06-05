# slam-sc-lio
FROM gtsam-base:noetic

# --- ROS & build tools -------------------------------------------------------
RUN apt-get update && apt-get install -y \
    python3-pip python3-catkin-tools \
    ros-noetic-pcl-conversions ros-noetic-pcl-ros \
    ros-noetic-tf ros-noetic-rviz \
    ros-noetic-camera-info-manager \
    libpcl-dev libgeographic-dev     \
 && rm -rf /var/lib/apt/lists/*

# evo (works the same in ROS 1)
RUN pip3 install --no-cache-dir \
      "numpy<1.25.0" "scipy<1.11.0" evo

# --- catkin workspace --------------------------------------------------------
ENV WS=/workspace/catkin_ws
RUN mkdir -p $WS/src
WORKDIR $WS/src

# ---- clone sources ----------------------------------------------------------
# SC-LIO-SAM (Noetic branch)
RUN git clone --depth=1 https://github.com/jxxdyy/SC-LIO-SAM.git

# MulRan file-player (Noetic branch)
RUN git clone --branch noetic --depth=1 https://github.com/RPM-Robotics-Lab/file_player_mulran.git

# (optional) any extra packages here …

# ---- build ------------------------------------------------------------------
WORKDIR $WS
RUN /bin/bash -c "source /opt/ros/noetic/setup.bash && \
                  catkin_make -DCMAKE_BUILD_TYPE=Release"

# ---- runtime ----------------------------------------------------------------
ENV ROS_PACKAGE_PATH=$WS/src:$ROS_PACKAGE_PATH
ENTRYPOINT ["/bin/bash", "-c", \
  "source /opt/ros/noetic/setup.bash && \
   source $WS/devel/setup.bash && exec bash"]
