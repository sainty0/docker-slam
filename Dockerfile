FROM gtsam-base

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-colcon-common-extensions \
    build-essential \
    cmake \
    git \
    libboost-all-dev \
    libeigen3-dev \
    libgoogle-glog-dev \
    libgflags-dev \
    libtbb-dev \
    libyaml-cpp-dev \
    libgts-dev \
    libpcl-dev \
    ros-humble-pcl-conversions \
    ros-humble-pcl-ros \
    ros-humble-tf-transformations \
    ros-humble-rmw-cyclonedds-cpp \
    ros-humble-xacro \
    ros-humble-rviz2 \
    libxcb-xinerama0 \
    libxkbcommon-x11-0 \
    libwayland-client0 \
    libwayland-cursor0 \
    libwayland-egl1-mesa \
    libegl1-mesa \
    libgl1-mesa-glx \
    libgl1-mesa-dri \
    && rm -rf /var/lib/apt/lists/*

ENV RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
ENV LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH

# Install evo
RUN pip3 install evo
RUN pip install --upgrade "numpy<1.25.0" "scipy<1.11.0"

# Copy workspace and build
WORKDIR /workspace/src
COPY ./workspace/src/ ./src/

WORKDIR /workspace
RUN /bin/bash -c "source /opt/ros/humble/setup.bash && colcon build --symlink-install"

ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/humble/setup.bash && source /workspace/install/setup.bash && exec bash"]

