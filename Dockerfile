# slam-sc-lio
FROM gtsam-base:noetic

# --- ROS & build tools -------------------------------------------------------
RUN apt-get update && apt-get install -y \
    python3-pip python3-catkin-tools \
    build-essential python3-dev \
    ros-noetic-pcl-conversions ros-noetic-pcl-ros \
    ros-noetic-tf ros-noetic-rviz \
    ros-noetic-camera-info-manager \
    libpcl-dev libgeographic-dev     \
 && rm -rf /var/lib/apt/lists/*

# Install yq v4 (YAML processor)
RUN wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
    -O /usr/bin/yq && \
    chmod +x /usr/bin/yq && \
    yq --version

# evo (works the same in ROS 1)
RUN pip3 install --no-cache-dir \
      "numpy==1.24.4" "scipy==1.10.1" "matplotlib==3.7.5" evo

# --- Add the Python evaluation toolkit --------------------------------------
# Copy only requirements first to leverage layer caching
WORKDIR /app
COPY requirements.txt /app/requirements.txt

# Install requirements (upgrade pip, then install)
RUN python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt

# Copy the toolkit code
COPY mulran_eval/ /app/mulran_eval

# --- catkin workspace --------------------------------------------------------
ENV DISABLE_ROS1_EOL_WARNINGS=1
ENV WS=/workspace/catkin_ws
RUN mkdir -p $WS/src
WORKDIR $WS/src

# ---- clone sources ----------------------------------------------------------
# SC-LIO-SAM (Noetic branch)
# RUN git clone --depth=1 https://github.com/jxxdyy/SC-LIO-SAM.git
COPY SC-LIO-SAM/SC-LIO-SAM/ $WS/src/SC-LIO-SAM

# MulRan file-player (Noetic branch)
COPY file_player_mulran/ $WS/src/file_player_mulran
# RUN git clone --branch noetic --depth=1 https://github.com/RPM-Robotics-Lab/file_player_mulran.git

# (optional) any extra packages here …

# ---- build ------------------------------------------------------------------
WORKDIR $WS
RUN /bin/bash -c "source /opt/ros/noetic/setup.bash && \
                  catkin_make -DCMAKE_BUILD_TYPE=Release"

# ---- runtime ----------------------------------------------------------------
RUN echo "source /opt/ros/noetic/setup.bash" >> /root/.bashrc && \
    echo "source /workspace/catkin_ws/devel/setup.bash" >> /root/.bashrc

ENV ROS_PACKAGE_PATH=$WS/src:$ROS_PACKAGE_PATH
ENTRYPOINT ["/bin/bash", "-c", \
  "source /opt/ros/noetic/setup.bash && \
   source $WS/devel/setup.bash && exec bash"]
