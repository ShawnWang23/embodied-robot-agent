#!/usr/bin/env bash
set -eo pipefail

source "${HOME}/.config/robot_agent/use_ros2_localhost.sh"
set -u

# Headless RGB rendering in WSL requires Mesa software rendering.
export GALLIUM_DRIVER=llvmpipe
export LIBGL_ALWAYS_SOFTWARE=1
export TURTLEBOT3_MODEL=waffle
unset MESA_D3D12_DEFAULT_ADAPTER_NAME

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd -- "${script_dir}/.." && pwd)"
venv_dir="${ROBOT_AGENT_PERCEPTION_VENV:-${HOME}/.venvs/robot-agent-perception}"
test_dir="$(mktemp -d)"
gazebo_pid=""
spawn_pid=""
cmd_bridge_pid=""
state_publisher_pid=""
nav2_pid=""
localizer_pid=""

cleanup() {
  for process_id in \
    "${localizer_pid}" \
    "${nav2_pid}" \
    "${state_publisher_pid}" \
    "${cmd_bridge_pid}" \
    "${spawn_pid}"; do
    if [[ -n "${process_id}" ]]; then
      pkill -TERM -s "${process_id}" 2>/dev/null || true
      wait "${process_id}" 2>/dev/null || true
    fi
  done
  if [[ -n "${gazebo_pid}" ]]; then
    pkill -TERM -s "${gazebo_pid}" 2>/dev/null || true
    sleep 2
    pkill -KILL -s "${gazebo_pid}" 2>/dev/null || true
    wait "${gazebo_pid}" 2>/dev/null || true
  fi
  rm -rf -- "${test_dir}"
}
trap cleanup EXIT

cd "${workspace_dir}"
mkdir -p artifacts/unified

nav2_params="${test_dir}/nav2_params.yaml"
cp /opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml "${nav2_params}"
sed -i \
  -e '/^bt_navigator:/,/^[^ ]/ s/default_server_timeout: 20/default_server_timeout: 2000/' \
  -e '/^collision_monitor:/,/^[^ ]/ s/source_timeout: 1.0/source_timeout: 0.0/' \
  "${nav2_params}"

world_xacro="/opt/ros/jazzy/share/nav2_minimal_tb3_sim/worlds/tb3_sandbox.sdf.xacro"
world_file="${test_dir}/tb3_sandbox.sdf"
map_file="/opt/ros/jazzy/share/nav2_bringup/maps/tb3_sandbox.yaml"
export GZ_SIM_RESOURCE_PATH="/opt/ros/jazzy/share/turtlebot3_gazebo/models:/opt/ros/jazzy/share/nav2_minimal_tb3_sim/models:${GZ_SIM_RESOURCE_PATH:-}"
xacro -o "${world_file}" headless:=True "${world_xacro}"

echo "[1/6] Launch one headless TurtleBot3 world"
setsid timeout --kill-after=5s 270s \
  gz sim -r -s --headless-rendering -v2 "${world_file}" \
  >"${test_dir}/gazebo.log" 2>&1 &
gazebo_pid="$!"

setsid timeout --kill-after=5s 265s \
  ros2 launch turtlebot3_gazebo spawn_turtlebot3.launch.py \
    x_pose:=-2.0 y_pose:=-0.5 \
  >"${test_dir}/spawn.log" 2>&1 &
spawn_pid="$!"

# The camera-enabled TurtleBot3 bridge subscribes to TwistStamped, while this
# Nav2 profile publishes geometry_msgs/Twist. Add the matching ROS -> Gazebo
# bridge explicitly so controller output reaches the same simulated base.
setsid timeout --kill-after=5s 265s \
  ros2 run ros_gz_bridge parameter_bridge \
    /cmd_vel@geometry_msgs/msg/Twist@gz.msgs.Twist \
  >"${test_dir}/cmd_vel_bridge.log" 2>&1 &
cmd_bridge_pid="$!"

setsid timeout --kill-after=5s 265s \
  ros2 launch turtlebot3_gazebo robot_state_publisher.launch.py \
    use_sim_time:=True \
  >"${test_dir}/state_publisher.log" 2>&1 &
state_publisher_pid="$!"

echo "[2/6] Inject Nav2 into the same Gazebo world"
setsid timeout --kill-after=5s 260s \
  ros2 launch nav2_bringup bringup_launch.py \
    map:="${map_file}" params_file:="${nav2_params}" \
    use_sim_time:=True use_composition:=False autostart:=False \
  >"${test_dir}/nav2.log" 2>&1 &
nav2_pid="$!"

# Known-pose localization seam used by the existing controlled Nav2 validation.
setsid timeout --kill-after=5s 255s \
  ros2 run tf2_ros static_transform_publisher \
    --x -2.0 --y -0.5 --z 0.0 --yaw 0.0 --pitch 0.0 --roll 0.0 \
    --frame-id map --child-frame-id odom \
  >"${test_dir}/known_pose.log" 2>&1 &
localizer_pid="$!"

echo "[3/6] Wait for the RGB camera and Nav2 lifecycle managers"
camera_ready=false
managers_ready=false
for _ in $(seq 1 75); do
  topics="$(ros2 topic list 2>/dev/null || true)"
  services="$(ros2 service list 2>/dev/null || true)"
  if grep -qx '/camera/image_raw' <<<"${topics}"; then
    camera_ready=true
  fi
  if grep -qx '/lifecycle_manager_localization/manage_nodes' <<<"${services}" && \
     grep -qx '/lifecycle_manager_navigation/manage_nodes' <<<"${services}"; then
    managers_ready=true
  fi
  if [[ "${camera_ready}" == true && "${managers_ready}" == true ]]; then
    break
  fi
  sleep 1
done
if [[ "${camera_ready}" != true || "${managers_ready}" != true ]]; then
  cat "${test_dir}/spawn.log"
  tail -n 180 "${test_dir}/gazebo.log"
  tail -n 180 "${test_dir}/nav2.log"
  echo "Unified camera or Nav2 lifecycle services did not become ready." >&2
  exit 1
fi

echo "[4/6] Activate localization and navigation"
timeout 45s ros2 service call \
  /lifecycle_manager_localization/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/localization.log" 2>&1
timeout 45s ros2 service call \
  /lifecycle_manager_navigation/manage_nodes \
  nav2_msgs/srv/ManageLifecycleNodes '{command: 0}' \
  >"${test_dir}/navigation.log" 2>&1

action_ready=false
for _ in $(seq 1 45); do
  if ros2 action list 2>/dev/null | grep -qx '/navigate_to_pose'; then
    action_ready=true
    break
  fi
  sleep 1
done
if [[ "${action_ready}" != true ]]; then
  cat "${test_dir}/navigation.log"
  tail -n 180 "${test_dir}/nav2.log"
  echo "NavigateToPose action did not become ready." >&2
  exit 1
fi

echo "[5/6] Verify the camera endpoint from the same robot"
ros2 topic info /camera/image_raw --verbose \
  >"${test_dir}/camera_endpoint.log" 2>&1

echo "[6/6] Run Nav2 + camera + YOLO + bounded replanning"
if ! timeout 190s "${venv_dir}/bin/python" scripts/unified_agent_smoke.py \
  --locations config/locations_unified_sim.json \
  >"${test_dir}/agent.log" 2>&1; then
  cat "${test_dir}/agent.log"
  cat "${test_dir}/spawn.log"
  tail -n 200 "${test_dir}/nav2.log"
  tail -n 120 "${test_dir}/gazebo.log"
  echo "Unified Agent validation failed." >&2
  exit 1
fi

cat "${test_dir}/camera_endpoint.log"
cat "${test_dir}/agent.log"
echo "unified_nav_camera_yolo_agent=passed"

