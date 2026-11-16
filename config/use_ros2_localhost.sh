# Use this profile when every ROS 2 node runs in this WSL distro.
source /opt/ros/jazzy/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export CYCLONEDDS_URI="file://${HOME}/.config/robot_agent/cyclonedds_localhost.xml"
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=Intel
export TURTLEBOT3_MODEL=waffle_pi
