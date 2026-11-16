# Shared ROS 2 shell environment for this development machine.
if [ -f /opt/ros/jazzy/setup.bash ]; then
  source /opt/ros/jazzy/setup.bash
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
